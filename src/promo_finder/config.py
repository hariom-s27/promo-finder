"""Load and validate config.yaml, and load the secrets file at run time."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal, Optional

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


class IntensityCfg(BaseModel):
    weights: dict[str, float] = Field(default_factory=lambda: {
        "exclamations": 1.0, "questions": 0.5, "all_caps_words": 0.5,
        "strong_emotion": 2.0, "sfx": 1.5, "action_violence_shock": 2.0,
        "speaker_change": 0.5, "short_dialogue": 1.0,
    })
    strong_emotions: list[str] = Field(default_factory=lambda: [
        "angry", "furious", "screaming", "shocked", "terrified", "crying", "desperate",
    ])
    action_terms: list[str] = Field(default_factory=lambda: [
        "slap", "punch", "kick", "stab", "shoot", "strangle", "choke", "beat",
        "drag by hair", "shove", "throw acid", "set on fire", "burn", "run over",
        "falling", "scream", "screaming",
    ])

    @model_validator(mode="after")
    def _weights(self) -> "IntensityCfg":
        expected = set(type(self).model_fields["weights"].default_factory())
        if set(self.weights) != expected or any(v < 0 for v in self.weights.values()):
            raise ValueError("intensity weights must include each feature and be nonnegative")
        return self


class UnderstandingCfg(BaseModel):
    character_chunk_episodes: int = Field(default=4, ge=1)


class PricingCfg(BaseModel):
    input_per_million_usd: float = Field(ge=0)
    output_per_million_usd: float = Field(ge=0)
    source: str = "RESEARCH"
    description: str = "list price, Global Standard"


class PurposeCfg(BaseModel):
    reasoning_effort: str


class RateLimitCfg(BaseModel):
    max_concurrent: int = Field(default=1, ge=1)
    # Old configurations keep their previous pacing; production values live in YAML.
    min_interval_s: float = Field(default=0, ge=0, allow_inf_nan=False)
    honour_retry_after: bool = True
    max_retry_after_s: float = Field(default=60, gt=0, le=60, allow_inf_nan=False)


class SpoilerCfg(BaseModel):
    reveal_mode: Literal["block", "flag"] = "block"
    late_series_start: int = Field(default=46, ge=1)


class PenaltiesCfg(BaseModel):
    possible_recap: float = Field(default=0.5, ge=0, allow_inf_nan=False)
    reaction_cut: float = Field(default=0.25, ge=0, allow_inf_nan=False)
    montage: float = Field(default=0.25, ge=0, allow_inf_nan=False)


class BuilderCfg(BaseModel):
    max_per_episode: int = Field(default=8, ge=1)
    max_segments: int = Field(default=2, ge=1, le=2)
    montage_first_min_s: float = Field(default=8, gt=0, allow_inf_nan=False)
    montage_first_max_s: float = Field(default=20, gt=0, allow_inf_nan=False)
    max_speakers: int = Field(default=3, ge=1)
    dedupe_tiou: float = Field(default=0.7, ge=0, le=1, allow_inf_nan=False)
    recap_scan_lines: int = Field(default=12, ge=1)
    recap_similarity: float = Field(default=0.85, ge=0, le=1, allow_inf_nan=False)
    recap_prev_tail_lines: int = Field(default=15, ge=1)
    recap_fallback_s: float = Field(default=5, ge=0, allow_inf_nan=False)
    penalties: PenaltiesCfg = Field(default_factory=PenaltiesCfg)

    @model_validator(mode="after")
    def _bounds(self) -> "BuilderCfg":
        if self.montage_first_min_s > self.montage_first_max_s:
            raise ValueError("montage first-piece bounds are inconsistent")
        return self


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
    intensity: IntensityCfg = Field(default_factory=IntensityCfg)
    understanding: UnderstandingCfg = Field(default_factory=UnderstandingCfg)
    pricing: dict[str, PricingCfg] = Field(default_factory=dict)
    purposes: dict[str, PurposeCfg] = Field(default_factory=dict)
    rate_limit: RateLimitCfg = Field(default_factory=RateLimitCfg)
    spoiler: SpoilerCfg = Field(default_factory=SpoilerCfg)
    builder: BuilderCfg = Field(default_factory=BuilderCfg)

    _root: Path = PrivateAttr(default=PROJECT_ROOT)

    @property
    def root(self) -> Path:
        return self._root

    @model_validator(mode="after")
    def _check(self) -> "Config":
        if self.builder.montage_first_max_s > self.promo.max_s:
            raise ValueError("montage first-piece maximum exceeds promo maximum")
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
