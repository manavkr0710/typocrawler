"""Pluggable LLM back-ends for verification: Groq or Gemini (free tiers), Ollama (local), stub.

Groq is the recommended free option — its daily request quota is far more generous than
Gemini's for this kind of bulk classification.
"""

from __future__ import annotations

import os
import time
from typing import Protocol

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from typocrawler.verify.prompt import VerifyItem, VerifyResult, build_prompt, parse_response

_TRANSIENT_CODES = {429, 500, 502, 503, 504}
_TRANSIENT_NAMES = {"ServerError", "InternalServerError", "RateLimitError", "APITimeoutError"}


def _is_transient(exc: BaseException) -> bool:
    """Retry rate-limit / 5xx / timeout errors from any provider; fail fast on everything else."""
    if isinstance(exc, httpx.TransportError):  # timeouts, connection resets
        return True
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in _TRANSIENT_CODES:
        return True
    return type(exc).__name__ in _TRANSIENT_NAMES


_retry_transient = retry(
    reraise=True,
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception(_is_transient),
)


class Verifier(Protocol):
    name: str

    def verify(self, items: list[VerifyItem]) -> list[VerifyResult]: ...


class _Throttled:
    """Shared throttle + retry wrapper — subclasses implement ``_generate``."""

    name = "?"

    def __init__(self, rpm: float) -> None:
        self._min_gap = 60.0 / rpm if rpm else 0.0
        self._last = 0.0

    def _generate(self, prompt: str) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def verify(self, items: list[VerifyItem]) -> list[VerifyResult]:
        gap = self._min_gap - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)
        text = self._generate(build_prompt(items))
        self._last = time.monotonic()
        return parse_response(text, len(items))


class StubVerifier:
    """Testing / dry-run only — confirms every item using its suggested correction."""

    name = "stub"

    def verify(self, items: list[VerifyItem]) -> list[VerifyResult]:
        return [VerifyResult("typo", it.suggestion) for it in items]


class GroqVerifier(_Throttled):
    """Groq's free tier — generous daily quota. Needs GROQ_API_KEY (console.groq.com/keys)."""

    name = "groq"

    def __init__(
        self,
        *,
        model: str = "llama-3.3-70b-versatile",
        api_key: str | None = None,
        rpm: float = 28,
    ) -> None:
        from groq import Groq

        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError(
                "GROQ_API_KEY not set — get a free key at https://console.groq.com/keys"
            )
        super().__init__(rpm)
        self._client = Groq(api_key=key)
        self._model = model

    @_retry_transient
    def _generate(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return resp.choices[0].message.content or ""


class GeminiVerifier(_Throttled):
    """Google Gemini free tier. Needs GEMINI_API_KEY (aistudio.google.com/apikey).

    Note: recent Gemini free tiers cap daily requests very low (~20/day for some models) —
    prefer Groq for a full run.
    """

    name = "gemini"

    def __init__(
        self,
        *,
        model: str = "gemini-flash-lite-latest",
        api_key: str | None = None,
        rpm: float = 15,
    ) -> None:
        from google import genai
        from google.genai import types

        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY not set — get a free key at https://aistudio.google.com/apikey"
            )
        super().__init__(rpm)
        self._client = genai.Client(api_key=key)
        self._model = model
        self._config = types.GenerateContentConfig(
            response_mime_type="application/json",
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    @_retry_transient
    def _generate(self, prompt: str) -> str:
        resp = self._client.models.generate_content(
            model=self._model, contents=prompt, config=self._config
        )
        return resp.text or ""


_OLLAMA_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"misspelled": {"type": ["boolean", "null"]}},
        "required": ["misspelled"],
    },
}


class OllamaVerifier:
    """A local model served by Ollama — no API key, fully offline.

    Uses Ollama's JSON-schema structured output so even small models return the array shape.
    """

    name = "ollama"

    def __init__(self, *, model: str = "qwen2.5:7b", host: str = "http://localhost:11434") -> None:
        self._model = model
        self._host = host.rstrip("/")
        try:
            httpx.get(f"{self._host}/api/tags", timeout=3.0).raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Ollama not reachable at {self._host} — is `ollama serve` running?"
            ) from exc

    @_retry_transient
    def _generate(self, prompt: str) -> str:
        resp = httpx.post(
            f"{self._host}/api/generate",
            json={
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "format": _OLLAMA_SCHEMA,
                "options": {"temperature": 0},
                "keep_alive": "30m",
            },
            timeout=httpx.Timeout(600.0, connect=10.0),
        )
        resp.raise_for_status()
        return str(resp.json()["response"])

    def verify(self, items: list[VerifyItem]) -> list[VerifyResult]:
        return parse_response(self._generate(build_prompt(items)), len(items))


def get_verifier(provider: str = "", *, model: str | None = None, rpm: float = 0) -> Verifier:
    """Resolve a verifier from ``provider`` / ``LLM_PROVIDER`` / autodetect."""
    provider = (provider or os.environ.get("LLM_PROVIDER") or _autodetect()).lower()
    kw: dict[str, object] = {}
    if model:
        kw["model"] = model
    if rpm and provider in ("groq", "gemini"):
        kw["rpm"] = rpm

    if provider == "groq":
        return GroqVerifier(**kw)
    if provider == "gemini":
        return GeminiVerifier(**kw)
    if provider == "ollama":
        return OllamaVerifier(**kw)
    if provider == "stub":
        return StubVerifier()
    raise RuntimeError(
        f"unknown LLM provider {provider!r} (expected: groq, gemini, ollama, stub)"
    )


def _autodetect() -> str:
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    return "ollama"
