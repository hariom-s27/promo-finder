"""Load and validate config.yaml, and load the secrets file at run time."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

# src/promo_finder/config.py -> parents[2] is the project folder
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(Exception):
    pass


class PromoCfg(BaseModel):
    min_s: float = 20
    max_s: float = 60
    max_segments: int = 3

    @property
    def min_ms(self) -> int:
        return round(self.min_s * 1000)

    @property
    def max_ms(self) -> int:
        return round(self.max_s * 1000)


class ActiveCfg(BaseModel):
    picker: str
    judge: str


class ModelCfg(BaseModel):
    provider: str
    model: str
    family: str
    params: dict = Field(default_factory=dict)

    @property
    def is_tbd(self) -> bool:
        return self.model.strip().upper() == "TBD"


class ProviderCfg(BaseModel):
    model_config = ConfigDict(extra="allow")

    key_env: str
    base_url: Optional[str] = None
    endpoint_env: Optional[str] = None
    mode: Optional[str] = None
    fallback_api_version: Optional[str] = None
    rpm: Optional[int] = None
    tpm: Optional[int] = None

    @property
    def is_azure(self) -> bool:
        return self.endpoint_env is not None

    def env_names(self) -> list[str]:
        return [n for n in (self.key_env, self.endpoint_env) if n]


class Config(BaseModel):
    data_dir: Path
    secrets_file: str = ".env"
    max_calls_per_run: int = 50
    promo: PromoCfg = Field(default_factory=PromoCfg)
    active: ActiveCfg
    models: dict[str, ModelCfg]
    providers: dict[str, ProviderCfg]

    _root: Path = PrivateAttr(default=PROJECT_ROOT)

    @property
    def root(self) -> Path:
        return self._root

    @model_validator(mode="after")
    def _check(self) -> "Config":
        for name, m in self.models.items():
            if m.provider not in self.providers:
                raise ValueError(f"model '{name}' uses unknown provider '{m.provider}'")
        roles = {"picker": self.active.picker, "judge": self.active.judge}
        for role, key in roles.items():
            if key not in self.models:
                raise ValueError(f"active.{role} = '{key}' is not defined under models")
            if self.models[key].is_tbd:
                raise ValueError(f"active.{role} = '{key}' has model TBD; choose a real model first")
        fp = self.models[self.active.picker].family.strip().lower()
        fj = self.models[self.active.judge].family.strip().lower()
        if fp == fj:
            raise ValueError(
                f"no self-judging: active.picker '{self.active.picker}' and active.judge "
                f"'{self.active.judge}' are both family '{fp}'. Pick a judge from another family."
            )
        return self

    def usable_models(self) -> dict[str, ModelCfg]:
        """Models that are not TBD (TBD models are skipped everywhere)."""
        return {k: m for k, m in self.models.items() if not m.is_tbd}


def load_config(path: Optional[Path | str] = None) -> Config:
    p = Path(path or os.environ.get("KUKU_CONFIG") or (PROJECT_ROOT / "config.yaml"))
    if not p.is_file():
        raise ConfigError(f"config file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"config.yaml is not valid YAML: {e}") from None
    if os.environ.get("KUKU_DATA_DIR"):
        raw["data_dir"] = os.environ["KUKU_DATA_DIR"]
    try:
        cfg = Config.model_validate(raw)
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(str(x) for x in err['loc']) or 'config'}: {err['msg']}" for err in e.errors())
        raise ConfigError(msgs) from None
    root = p.resolve().parent
    cfg._root = root
    if not cfg.data_dir.is_absolute():
        cfg.data_dir = (root / cfg.data_dir).resolve()
    return cfg


def secrets_path(cfg: Config) -> Path:
    env = os.environ.get("KUKU_SECRETS_FILE")
    p = Path(env) if env else Path(cfg.secrets_file)
    return p if p.is_absolute() else cfg.root / p


def required_key_names(cfg: Config) -> list[str]:
    """Env var NAMES needed by every non-TBD model's provider."""
    names: list[str] = []
    for m in cfg.usable_models().values():
        for n in cfg.providers[m.provider].env_names():
            if n not in names:
                names.append(n)
    return names


def load_secrets(cfg: Config) -> Optional[Path]:
    """Load the secrets file into os.environ (override=True). Never prints values.

    If the file does not exist and some required keys are not already in the environment,
    print the missing key NAMES and exit.
    """
    from dotenv import load_dotenv

    p = secrets_path(cfg)
    if p.is_file():
        load_dotenv(p, override=True)
        return p
    missing = [n for n in required_key_names(cfg) if not os.environ.get(n)]
    if missing:
        print(f"Secrets file not found: {p}", file=sys.stderr)
        print("Missing key names: " + ", ".join(missing), file=sys.stderr)
        raise SystemExit(2)
    return None


def secret_values(cfg: Config) -> list[str]:
    """Current values of configured secret env vars (only for scrubbing messages)."""
    vals = []
    for n in required_key_names(cfg):
        v = os.environ.get(n)
        if v and len(v) >= 6:
            vals.append(v)
    return vals
