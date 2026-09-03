"""Load and validate the crawl target configuration (``config/orgs.yml``)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_CONFIG_PATH = Path("config/orgs.yml")


class OrgRule(BaseModel):
    """A single org entry. Any unset field falls back to :class:`Defaults`."""

    model_config = ConfigDict(extra="forbid")

    login: str
    min_stars: int | None = None
    include_forks: bool | None = None
    include_archived: bool | None = None

    @field_validator("login")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("org login must not be empty")
        return v


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_stars: int = 0
    include_forks: bool = False
    include_archived: bool = False
    extra_paths: list[str] = Field(default_factory=list)


class ResolvedOrg(BaseModel):
    """An org with every setting concrete (defaults merged in)."""

    login: str
    min_stars: int
    include_forks: bool
    include_archived: bool
    extra_paths: list[str]


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defaults: Defaults = Field(default_factory=Defaults)
    orgs: list[OrgRule]

    @field_validator("orgs")
    @classmethod
    def _unique_non_empty(cls, v: list[OrgRule]) -> list[OrgRule]:
        if not v:
            raise ValueError("config must list at least one org")
        seen: set[str] = set()
        for org in v:
            key = org.login.lower()
            if key in seen:
                raise ValueError(f"duplicate org: {org.login}")
            seen.add(key)
        return v

    def resolved(self) -> list[ResolvedOrg]:
        """Merge ``defaults`` into each org entry."""
        d = self.defaults
        return [
            ResolvedOrg(
                login=o.login,
                min_stars=d.min_stars if o.min_stars is None else o.min_stars,
                include_forks=d.include_forks if o.include_forks is None else o.include_forks,
                include_archived=(
                    d.include_archived if o.include_archived is None else o.include_archived
                ),
                extra_paths=list(d.extra_paths),
            )
            for o in self.orgs
        ]


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Config:
    """Read, parse and validate the YAML config at ``path``."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"config file not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a mapping, got {type(raw).__name__}")
    return Config.model_validate(raw)
