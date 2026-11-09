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
    free_path_judge: Optional[str] = None


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
    reasoning_effort: Optional[str] = None
    max_completion_tokens: Optional[int] = Field(default=None, gt=0)


class GroqDailyCfg(BaseModel):
    daily_safety_factor: float = Field(default=1.2, ge=1, allow_inf_nan=False)


class FoundryQuotaCfg(BaseModel):
    tpm: int = Field(default=20000, gt=0)
    rpm: int = Field(default=20, gt=0)


class RateLimitCfg(BaseModel):
    max_concurrent: int = Field(default=1, ge=1)
    # Old configurations keep their previous pacing; production values live in YAML.
    min_interval_s: float = Field(default=0, ge=0, allow_inf_nan=False)
    honour_retry_after: bool = True
    max_retry_after_s: float = Field(default=60, gt=0, le=60, allow_inf_nan=False)
    groq: GroqDailyCfg = Field(default_factory=GroqDailyCfg)
    azure_foundry: dict[str, FoundryQuotaCfg] = Field(default_factory=dict)


class SpoilerCfg(BaseModel):
    reveal_mode: Literal["block", "flag"] = "flag"
    late_series_start: int = Field(default=46, ge=1)
    resolution_block_confidence: list[Literal["low", "medium", "high"]] = Field(default_factory=lambda: ["medium", "high"])


class PenaltiesCfg(BaseModel):
    possible_recap: float = Field(default=0.5, ge=0, allow_inf_nan=False)
    reaction_cut: float = Field(default=0.25, ge=0, allow_inf_nan=False)
    montage: float = Field(default=0.25, ge=0, allow_inf_nan=False)
    speakers_4: float = Field(default=0.25, ge=0, allow_inf_nan=False)


class BuilderCfg(BaseModel):
    max_per_episode: int = Field(default=8, ge=1)
    max_segments: int = Field(default=2, ge=1, le=2)
    montage_first_min_s: float = Field(default=8, gt=0, allow_inf_nan=False)
    montage_first_max_s: float = Field(default=20, gt=0, allow_inf_nan=False)
    max_speakers: Optional[int] = Field(default=None, ge=1)  # legacy config compatibility
    speakers_soft: int = Field(default=4, ge=1)
    speakers_hard: int = Field(default=5, ge=1)
    j5_at_final_end: bool = False
    dedupe_tiou: float = Field(default=0.7, ge=0, le=1, allow_inf_nan=False)
    recap_scan_lines: int = Field(default=12, ge=1)
    recap_similarity: float = Field(default=0.85, ge=0, le=1, allow_inf_nan=False)
    recap_prev_tail_lines: int = Field(default=15, ge=1)
    recap_fallback_s: float = Field(default=5, ge=0, allow_inf_nan=False)
    penalties: PenaltiesCfg = Field(default_factory=PenaltiesCfg)
    # P08b v2 switches. The defaults are v1 behaviour; only an approved overlay (config/v2.yaml) turns them on.
    too_short_mode: Literal["drop", "extend"] = "drop"                 # F2: extend a too-short clip's end to 20 s
    resolution_mode: Literal["drop", "flag_unless_end"] = "drop"       # F5b: keep, flag and penalise unless at the end

    @model_validator(mode="after")
    def _bounds(self) -> "BuilderCfg":
        if self.montage_first_min_s > self.montage_first_max_s:
            raise ValueError("montage first-piece bounds are inconsistent")
        if self.speakers_soft > self.speakers_hard:
            raise ValueError("speaker thresholds are inconsistent")
        return self


class ModelCfg(BaseModel):
    provider: str
    model: str
    family: str
    structured_output: Literal["strict", "auto", "json_object"] = "strict"
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


class FullRunJudgeCfg(BaseModel):
    top_per_episode: int = Field(default=4, ge=1)
    repeat_top_per_episode: int = Field(default=1, ge=0)
    repeat_runs: Literal[3] = 3
    fidelity_runs: Literal[1] = 1

    @model_validator(mode="after")
    def _selection(self):
        if self.repeat_top_per_episode > self.top_per_episode:
            raise ValueError("repeated selection exceeds judged selection")
        return self


class JudgeCfg(BaseModel):
    repeat_top_per_episode: int = Field(default=2, ge=0)
    repeat_runs: int = Field(default=3, ge=3)
    temperature: float = Field(default=0.7, ge=0, le=2, allow_inf_nan=False)
    retry_temperature: float = Field(default=0.3, ge=0, le=2, allow_inf_nan=False)
    full_run: FullRunJudgeCfg = Field(default_factory=FullRunJudgeCfg)
    shuffle_seed: int = 52
    fidelity_dependency_allowance_tokens: int = Field(default=512, ge=0)

    @model_validator(mode="after")
    def _odd_runs(self):
        if self.repeat_runs % 2 == 0:
            raise ValueError("repeat_runs must be odd")
        return self


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
    judge: JudgeCfg = Field(default_factory=JudgeCfg)

    _root: Path = PrivateAttr(default=PROJECT_ROOT)
    _config_path: Optional[Path] = PrivateAttr(default=None)
    _overlay_path: Optional[Path] = PrivateAttr(default=None)
    _run_name: str = PrivateAttr(default="dev")
    _free_demo: bool = PrivateAttr(default=False)
    _baseline_skipped: bool = PrivateAttr(default=False)

    @property
    def free_demo(self) -> bool:
        """Only an explicit free-role overlay enables the non-evaluation demo."""
        return self._free_demo

    @property
    def baseline_skipped(self) -> bool:
        """No comparison baseline: the free demo, or the app's upload demo (never an evaluation)."""
        return self._free_demo or self._baseline_skipped

    @property
    def root(self) -> Path:
        return self._root

    @property
    def output_root(self) -> Path:
        return self.root / "outputs" / "runs" / self._run_name

    @property
    def run_name(self) -> str:
        return self._run_name

    @model_validator(mode="after")
    def _check(self) -> "Config":
        if self.builder.montage_first_max_s > self.promo.max_s:
            raise ValueError("montage first-piece maximum exceeds promo maximum")
        for name, m in self.models.items():
            if m.provider not in self.providers:
                raise ValueError(f"model '{name}' uses unknown provider '{m.provider}'")
        roles = {"picker": self.active.picker, "judge": self.active.judge}
        if self.active.free_path_judge is not None:
            roles["free_path_judge"] = self.active.free_path_judge
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
        if self.active.free_path_judge:
            family = self.models[self.active.free_path_judge].family.strip().lower()
            if not family or family in {fp, "tbd"}:
                raise ValueError("free_path_judge must have a distinct known family")
        return self

    def usable_models(self) -> dict[str, ModelCfg]:
        """Models that are not TBD (TBD models are skipped everywhere)."""
        return {k: m for k, m in self.models.items() if not m.is_tbd}


def model_quota(cfg: Config, model_key: str) -> dict:
    """The same effective limits drive live reservations and offline simulation."""
    model = cfg.models[model_key]
    provider = cfg.providers[model.provider]
    if model.provider == "azure_foundry":
        limits = cfg.rate_limit.azure_foundry.get(model_key, FoundryQuotaCfg())
        return {"tpm": limits.tpm, "rpm": limits.rpm, "utilization": .85,
                "effective_tpm": max(1, limits.tpm * 85 // 100),
                "effective_rpm": max(1, limits.rpm * 85 // 100)}
    return {"tpm": provider.tpm, "rpm": provider.rpm, "utilization": 1.0,
            "effective_tpm": provider.tpm, "effective_rpm": provider.rpm}


# Role selection may change; model definitions, prompts, temperatures and scoring may not.
OVERLAY_TOP_KEYS = ("version", "builder", "active", "understanding", "purposes")
OVERLAY_BUILDER_KEYS = ("too_short_mode", "resolution_mode")
OVERLAY_ACTIVE_KEYS = ("picker", "judge")
FREE_ROLES = {"picker": "groq_oss", "judge": "groq_qwen"}


def read_overlay(path: Path) -> dict:
    """Read and whitelist-check a config overlay (e.g. config/v2.yaml). Never prints its contents."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        raise ConfigError("overlay file is unreadable or not valid YAML") from None
    if not isinstance(raw, dict):
        raise ConfigError("overlay must be a mapping")
    extra = sorted(str(k) for k in set(raw) - set(OVERLAY_TOP_KEYS))
    if extra:
        raise ConfigError("overlay key not allowed: " + ", ".join(extra))
    builder = raw.get("builder", {})
    if not isinstance(builder, dict):
        raise ConfigError("overlay builder section must be a mapping")
    bad = sorted(str(k) for k in set(builder) - set(OVERLAY_BUILDER_KEYS))
    if bad:
        raise ConfigError("overlay builder key not allowed: " + ", ".join(bad))
    active = raw.get("active", {})
    if not isinstance(active, dict):
        raise ConfigError("overlay active section must be a mapping")
    bad = sorted(str(k) for k in set(active) - set(OVERLAY_ACTIVE_KEYS))
    if bad:
        raise ConfigError("overlay active key not allowed: " + ", ".join(bad))
    if any(not isinstance(v, str) for v in active.values()):
        raise ConfigError("overlay active values must be model keys")
    if "understanding" in raw:
        section = raw["understanding"]
        if (active != FREE_ROLES or not isinstance(section, dict)
                or set(section) != {"character_chunk_episodes"}
                or type(section["character_chunk_episodes"]) is not int
                or section["character_chunk_episodes"] != 1):
            raise ConfigError("only the free-role overlay may set singleton character batching")
    if "purposes" in raw:
        section = raw["purposes"]
        if (active != FREE_ROLES or not isinstance(section, dict) or set(section) != {"answer_key"}
                or not isinstance(section["answer_key"], dict)
                or set(section["answer_key"]) != {"max_completion_tokens"}
                or type(section["answer_key"]["max_completion_tokens"]) is not int
                or section["answer_key"]["max_completion_tokens"] != 4500):
            raise ConfigError("only the free-role overlay may set the approved answer-key cap")
    if "version" in raw and (isinstance(raw["version"], bool) or not isinstance(raw["version"], int)):
        raise ConfigError("overlay version must be an integer")
    return raw


def load_config(path: Optional[Path | str] = None, overlay: Optional[Path | str] = None) -> Config:
    p = Path(path or os.environ.get("KUKU_CONFIG") or (PROJECT_ROOT / "config.yaml"))
    if not p.is_file():
        raise ConfigError(f"config file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"config.yaml is not valid YAML: {e}") from None
    if os.environ.get("KUKU_DATA_DIR"):
        raw["data_dir"] = os.environ["KUKU_DATA_DIR"]
    overlay_path = None
    if overlay:
        overlay_path = Path(overlay)
        if not overlay_path.is_absolute():
            overlay_path = p.resolve().parent / overlay_path
        try:
            overlay_path = overlay_path.resolve()
            overlay_path.relative_to(p.resolve().parent)
        except ValueError:
            raise ConfigError("overlay must be inside the project folder") from None
        if not overlay_path.is_file():
            raise ConfigError("overlay file not found")
        patch = read_overlay(overlay_path)
        base = raw.get("builder") or {}
        if not isinstance(base, dict):
            raise ConfigError("config builder section must be a mapping")
        raw["builder"] = {**base, **patch.get("builder", {})}
        if "active" in patch:
            raw["active"] = {**raw.get("active", {}), **patch["active"]}
        if "understanding" in patch:
            raw["understanding"] = {**raw.get("understanding", {}), **patch["understanding"]}
        if "purposes" in patch:
            purposes = dict(raw.get("purposes", {}))
            purposes["answer_key"] = {**purposes.get("answer_key", {}), **patch["purposes"]["answer_key"]}
            raw["purposes"] = purposes
    try:
        cfg = Config.model_validate(raw)
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(str(x) for x in err['loc']) or 'config'}: {err['msg']}" for err in e.errors())
        raise ConfigError(msgs) from None
    root = p.resolve().parent
    cfg._root = root
    cfg._config_path = p.resolve()
    cfg._overlay_path = overlay_path
    cfg._free_demo = bool(overlay_path and patch.get("active") == FREE_ROLES
                          and all(cfg.models[k].provider == "groq" for k in FREE_ROLES.values()))
    if overlay_path and ("understanding" in patch or "purposes" in patch) and not cfg.free_demo:
        raise ConfigError("free-only settings require the Groq free path")
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
    models = ([cfg.models[key] for key in (cfg.active.picker, cfg.active.judge)]
              if cfg.free_demo else cfg.usable_models().values())
    for m in models:
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
