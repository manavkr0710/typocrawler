from __future__ import annotations

import httpx
import pytest
import respx

from typocrawler.verify.llm import (
    GeminiVerifier,
    GroqVerifier,
    OllamaVerifier,
    StubVerifier,
    _is_transient,
    get_verifier,
)
from typocrawler.verify.prompt import VerifyItem

_ITEMS = [VerifyItem("recieve", "receive", "you recieve it", "acme/foo")]


def test_stub_confirms_everything():
    [result] = StubVerifier().verify(_ITEMS)
    assert result.verdict == "typo" and result.correction == "receive"


def test_get_verifier_explicit_and_unknown():
    assert isinstance(get_verifier("stub"), StubVerifier)
    with pytest.raises(RuntimeError, match="unknown LLM provider"):
        get_verifier("banana")


def test_get_verifier_autodetect_prefers_groq_then_gemini(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert isinstance(get_verifier(), GroqVerifier)

    monkeypatch.delenv("GROQ_API_KEY")
    assert isinstance(get_verifier(), GeminiVerifier)


def test_api_verifiers_require_a_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiVerifier()
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        GroqVerifier()


def test_is_transient_classifies_by_code_and_name():
    assert _is_transient(type("E", (Exception,), {"status_code": 429})())
    assert _is_transient(type("RateLimitError", (Exception,), {})())
    assert not _is_transient(type("E", (Exception,), {"status_code": 400})())
    assert not _is_transient(ValueError("nope"))


@respx.mock
def test_ollama_verifier_end_to_end():
    respx.get("http://localhost:11434/api/tags").mock(return_value=httpx.Response(200, json={}))
    respx.post("http://localhost:11434/api/generate").mock(
        return_value=httpx.Response(200, json={"response": '[{"misspelled": true}]'})
    )
    [result] = OllamaVerifier().verify(_ITEMS)
    assert result.verdict == "typo"


@respx.mock
def test_ollama_verifier_fails_fast_when_server_down():
    respx.get("http://localhost:11434/api/tags").mock(side_effect=httpx.ConnectError("nope"))
    with pytest.raises(RuntimeError, match="Ollama not reachable"):
        OllamaVerifier()
