"""Isolated upload demo. Uploads and generated files live only in a temporary tree."""
from __future__ import annotations

import hmac
import json
import re
import shutil
import tempfile
from pathlib import Path

from .config import PROJECT_ROOT, load_config
from .parser import FILENAME_RE

MAX_UPLOADS = 3
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class DemoError(Exception):
    """Public, content-free error messages safe for the app."""


def authorized(candidate, expected):
    return bool(isinstance(candidate, str) and isinstance(expected, str) and expected
                and hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8")))


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
    for name in ("free.yaml", "score_formula.yaml", "eval_order.yaml", "baseline.yaml", "policy_terms.yaml"):
        shutil.copy2(PROJECT_ROOT / "config" / name, root / "config" / name)
    cfg = load_config(root / "config.yaml", overlay="config/free.yaml")
    cfg.data_dir = data
    cfg._run_name = "upload_demo"
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


def execute(cfg, api_key):
    """Live entry point; called only by an authenticated, explicit app submission."""
    import openai
    from . import pipeline, understanding
    from .llm import LLMClient

    episodes = understanding.load_requested(cfg, sorted(int(FILENAME_RE.fullmatch(p.name).group(1)) for p in cfg.data_dir.iterdir()), True)
    # Original-show held-out numbers have no evaluation meaning for a fresh upload.
    plan = pipeline.dry_run(cfg, episodes, allow_held_out=True)
    cfg.max_calls_per_run = plan["max_calls_per_run"] + 1
    provider = openai.OpenAI(api_key=api_key, base_url=cfg.providers["groq"].base_url,
                             max_retries=0, timeout=120.0)

    class UploadClient(LLMClient):
        def _scrub(self, text):
            return super()._scrub(text).replace(api_key, "***")

    def factory(name, *args):
        if name != "groq":
            raise DemoError("The demo only supports the Groq free path.")
        return provider

    client = UploadClient(cfg, client_factory=factory)
    try:
        # A fresh session has no daily-request evidence. Reserve this initial ping
        # in the request cap; the normal judge-phase refresh remains unchanged.
        pipeline.refresh_groq_budget(cfg, client)
        pipeline.run(cfg, episodes, client=client, allow_held_out=True)
        return table_rows(cfg)
    finally:
        provider.close()


def run_uploads(uploads, api_key, *, runner=None, temp_parent=None):
    validate_uploads(uploads)
    if not isinstance(api_key, str) or not api_key.strip():
        raise DemoError("GROQ_API_KEY is missing.")
    # This owns and cleans only the temporary tree it creates, including on errors.
    with tempfile.TemporaryDirectory(prefix="promo-demo-", dir=temp_parent) as directory:
        cfg = prepare(Path(directory), uploads)
        try:
            return (runner or execute)(cfg, api_key)
        except DemoError:
            raise
        except Exception as exc:
            code = getattr(exc, "code", "DEMO_RUN_FAILED")
            if not isinstance(code, str) or not re.fullmatch(r"[A-Z_]{3,50}", code):
                code = "DEMO_RUN_FAILED"
            raise DemoError(f"Run stopped ({code}). Try fewer episodes or retry after the free-tier reset.") from None
