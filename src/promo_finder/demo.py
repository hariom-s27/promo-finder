"""Isolated upload demo. Uploads and generated files live only in a temporary tree."""
from __future__ import annotations

import datetime as dt
import functools
import json
import re
import shutil
import tempfile
import threading
from pathlib import Path

from .config import PROJECT_ROOT, load_config
from .parser import FILENAME_RE

MAX_UPLOADS = 3
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
# D106 a: the live tab runs the official Azure picker and judge, with a hard global daily budget.
DAILY_EPISODE_CAP = 30
SECRET_NAMES = ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_FOUNDRY_API_KEY", "AZURE_FOUNDRY_ENDPOINT")
DAILY_CAP_MESSAGE = "daily demo cap reached; full results are in Tab 1"
UNAVAILABLE_MESSAGE = "live demo is rate-limited or unavailable right now, try later; full results are in Tab 1"
# A judge-shape ping may negotiate two unsupported parameters and validate one retry (same budget as the CLI).
FOUNDRY_PING_CALLS = 5


class DemoError(Exception):
    """Public, content-free error messages safe for the app."""


class DemoNotice(DemoError):
    """Expected condition shown as a friendly note, not as a failure."""


class NotConfigured(DemoNotice):
    """Missing credentials; only secret NAMES are ever mentioned."""


class DailyCapReached(DemoNotice):
    def __init__(self):
        super().__init__(DAILY_CAP_MESSAGE)


class ProviderUnavailable(DemoNotice):
    """Rate limit or quota refusal, without provider details."""

    def __init__(self):
        super().__init__(UNAVAILABLE_MESSAGE)


class DailyCap:
    """Hard in-process budget of episodes per UTC day, shared by every visitor of this server process.

    A restart of the process resets it; that is the documented limit of an in-process counter.
    """

    def __init__(self, limit=DAILY_EPISODE_CAP, clock=None):
        self.limit = limit
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self._lock = threading.Lock()
        self._day, self._used = None, 0

    def _roll(self):
        today = self._clock().astimezone(dt.timezone.utc).date()
        if today != self._day:
            self._day, self._used = today, 0

    @property
    def remaining(self):
        with self._lock:
            self._roll()
            return max(0, self.limit - self._used)

    def reserve(self, episodes):
        """Atomically take `episodes` from today's budget; False (nothing taken) when it would not fit."""
        with self._lock:
            self._roll()
            if self._used + episodes > self.limit:
                return False
            self._used += episodes
            return True


DAILY_CAP = DailyCap()


def missing_secrets(secrets):
    return [name for name in SECRET_NAMES if not str((secrets or {}).get(name) or "").strip()]


def is_rate_limit(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if getattr(exc, "code", None) in {"RATE_LIMITED", "MISSING_KEY"}:
            return True
        if getattr(exc, "status_code", None) == 429 or getattr(getattr(exc, "response", None), "status_code", None) == 429:
            return True
        # Some wrapper errors retain only a scrubbed SDK message. Inspect it in
        # memory to choose a fixed public message; never print or persist it.
        text = str(exc).lower()
        if any(token in text for token in ("http 429", "rate limit", "rate_limit", "quota", "tokens per day",
                                            "daily limit", "exceeds provider tpm", "exceeds judge tpm")):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def validate_uploads(uploads):
    if not 1 <= len(uploads) <= MAX_UPLOADS:
        raise DemoError("Upload one to three episode .txt files.")
    numbers = set()
    for name, raw in uploads:
        match = FILENAME_RE.fullmatch(name)
        if not match or "/" in name or "\\" in name:
            raise DemoError("Use episode-001-Episode 1.txt style filenames.")
        number = int(match.group(1))
        # The second filename number is a source ID, not the episode number.
        if number < 1 or number in numbers:
            raise DemoError("Episode numbers must be positive and unique.")
        numbers.add(number)
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_UPLOAD_BYTES:
            raise DemoError("Each episode must be nonempty and at most 5 MiB.")
        try:
            raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise DemoError("Episode files must use UTF-8 text.") from None


def prepare(root, uploads):
    validate_uploads(uploads)
    data = root / "inputs"
    data.mkdir()
    for name, raw in uploads:
        (data / name).write_bytes(raw)
    # Public config assets only: never copy a local secret file or earlier show output.
    (root / "config").mkdir()
    shutil.copy2(PROJECT_ROOT / "config.yaml", root / "config.yaml")
    for name in ("score_formula.yaml", "eval_order.yaml", "baseline.yaml", "policy_terms.yaml"):
        shutil.copy2(PROJECT_ROOT / "config" / name, root / "config" / name)
    # D106 a: the official config and roles (azure_mini picker, azure_llama judge), no overlay.
    cfg = load_config(root / "config.yaml")
    cfg.data_dir = data
    cfg._run_name = "upload_demo"
    cfg._baseline_skipped = True  # a demo, not an evaluation: no comparison baseline
    return cfg


def timestamp(ms):
    seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def table_rows(cfg):
    path = cfg.output_root / "ranked/promos_dev.json"
    promos = json.loads(path.read_text(encoding="utf-8"))["promos"]
    moments = {}
    for ep in {p["segments"][0]["episode"] for p in promos}:
        data = json.loads((cfg.output_root / f"moments/moments_E{ep:02d}.json").read_text(encoding="utf-8"))
        moments[ep] = {key: {row["line_id"]: row["why"] for row in data[key]}
                       for key in ("hook_starts", "cliff_ends")}
    rows = []
    for promo in promos:
        episode = promo["segments"][0]["episode"]
        hook = moments[episode]["hook_starts"].get(promo["line_ids"][0], "Hook at the clip start.")
        cliff = moments[episode]["cliff_ends"].get(promo["line_ids"][-1], "Cliff at the clip end.")
        reasons = promo.get("needs_human_reasons", [])
        why = f"Hook: {hook} Cliff: {cliff}"
        if reasons:
            why += " Review: " + ", ".join(reason.replace("_", " ") for reason in reasons) + "."
        rows.append({"episode": promo["segments"][0]["episode"],
                     "start–end": " + ".join(f"{timestamp(s['start_ms'])}–{timestamp(s['end_ms'])}" for s in promo["segments"]),
                     "hook_type": promo["hook_type"], "cliff_type": promo["cliff_type"],
                     "why": why, "lane": promo["lane"], "score": promo["S"], "promo_id": promo["promo_id"]})
    return rows


def foundry_ping(cfg, client):
    """The judge-shape ping the pipeline requires before an Azure Foundry judge runs (same record as the CLI)."""
    from . import judging, pipeline
    from .understanding_common import metadata, write_json

    key = cfg.active.judge
    model = cfg.models[key]
    if model.provider != "azure_foundry":
        return None
    options = judging.purpose_options(cfg, "cold_judge")
    options.update(temperature=cfg.judge.temperature, retry_temperature=cfg.judge.retry_temperature)
    result = client.call(key, pipeline.GUARD_PING_MESSAGES, pipeline.guard_ping_schema(),
                         purpose=f"p07.ping.{key}", no_cache=True,
                         response_validator=lambda data: [] if data.get("ok") is True else ["$.ok: expected true"],
                         **options)
    row = {"model_key": key, "provider": model.provider, "deployment": model.model,
           "credential_set": model.provider, "credential_variable_names": cfg.providers[model.provider].env_names(),
           "status": "ok", **metadata(result, response_mode=result.response_mode), "protocol": client.protocol(key)}
    write_json(cfg.output_root / f"judge/ping_{key}.json", row)
    return row


def execute(cfg, secrets):
    """Live entry point; called only by an explicit app submission. Secrets are used from memory only."""
    from . import pipeline, understanding
    from .llm import LLMClient, default_client_factory

    episodes = understanding.load_requested(cfg, sorted(int(FILENAME_RE.fullmatch(p.name).group(1)) for p in cfg.data_dir.iterdir()), True)
    # Original-show held-out numbers have no evaluation meaning for a fresh upload.
    plan = pipeline.dry_run(cfg, episodes, allow_held_out=True)
    cfg.max_calls_per_run = plan["max_calls_per_run"] + FOUNDRY_PING_CALLS
    values = [str(secrets[name]) for name in SECRET_NAMES if len(str(secrets[name])) >= 6]

    class UploadClient(LLMClient):
        def _scrub(self, text):
            text = super()._scrub(text)
            for value in values:
                text = text.replace(value, "***")
            return text

    # The mapping is handed to the factory directly: nothing is written to the process environment.
    client = UploadClient(cfg, client_factory=functools.partial(default_client_factory, env={name: secrets[name] for name in SECRET_NAMES}))
    foundry_ping(cfg, client)
    pipeline.run(cfg, episodes, client=client, allow_held_out=True)
    return table_rows(cfg)


def run_uploads(uploads, secrets, *, runner=None, temp_parent=None, cap=None):
    """Validate, check credentials, spend from the daily cap, then run in an owned temporary tree."""
    validate_uploads(uploads)
    missing = missing_secrets(secrets)
    if missing:
        raise NotConfigured("live demo is not configured (missing secrets: " + ", ".join(missing)
                            + "); full results are in Tab 1")
    # Counted before any provider call and never refunded: the cap bounds spend, not successes.
    if not (cap or DAILY_CAP).reserve(len(uploads)):
        raise DailyCapReached()
    # This owns and cleans only the temporary tree it creates, including on errors.
    with tempfile.TemporaryDirectory(prefix="promo-demo-", dir=temp_parent) as directory:
        cfg = prepare(Path(directory), uploads)
        try:
            return (runner or execute)(cfg, secrets)
        except DemoError:
            raise
        except Exception as exc:
            if is_rate_limit(exc):
                raise ProviderUnavailable() from None
            code = getattr(exc, "code", "DEMO_RUN_FAILED")
            if not isinstance(code, str) or not re.fullmatch(r"[A-Z_]{3,50}", code):
                code = "DEMO_RUN_FAILED"
            raise DemoError(f"Run stopped ({code}). Try fewer episodes or retry later.") from None
