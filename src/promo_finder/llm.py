"""One LLM wrapper for every provider (Groq, Azure OpenAI, Featherless).

- One client type: openai.OpenAI(base_url=..., api_key=...); Azure falls back once to
  openai.AzureOpenAI(api_version=fallback_api_version) if the v1 path fails.
- Strict json_schema response format, plus validation in code (retry once -> SchemaError).
- Empty / truncated replies retry once with doubled max_completion_tokens (cap 16000).
- Disk cache keyed by sha256(provider + model + params + messages + schema).
- Per-provider rpm/tpm limiter, 429 retry-after, 5xx exponential backoff (max 5 tries).
- One JSON line per request in outputs/logs/llm_calls.jsonl (prompt hash only, never text or keys).
- Budget: max_calls_per_run real requests per client; dry_run estimates tokens, makes no calls.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

import openai
from pydantic import BaseModel

from .config import Config, ModelCfg, ProviderCfg, load_config, secret_values

MAX_TOKENS_CAP = 16000
MAX_TRIES = 5
MAX_WAIT_S = 120.0
# Arguments the OpenAI SDK accepts directly; anything else in params goes to extra_body.
CHAT_KWARGS = {
    "max_completion_tokens", "reasoning_effort", "top_p", "seed", "stop",
    "presence_penalty", "frequency_penalty", "temperature", "max_tokens",
}


# ---------------------------------------------------------------- errors
class LLMError(Exception):
    code = "LLM_ERROR"


class SchemaError(LLMError):
    code = "SCHEMA_ERROR"


class EmptyOrTruncated(LLMError):
    code = "EMPTY_OR_TRUNCATED"


class BudgetExceeded(LLMError):
    code = "BUDGET_EXCEEDED"


class MissingKey(LLMError):
    code = "MISSING_KEY"


class ProviderError(LLMError):
    code = "PROVIDER_ERROR"


# ---------------------------------------------------------------- results
class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LLMResult(BaseModel):
    data: Any = None
    raw_text: str = ""
    model_string: str = ""
    usage: Usage = Usage()
    cached: bool = False
    latency_ms: int = 0
    cache_key: str = ""
    api_path: Optional[str] = None  # azure: "v1" or "fallback"
    dry_run: bool = False


# ---------------------------------------------------------------- helpers
def _dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_key(provider: str, model: str, params: dict, messages: list, schema: dict) -> str:
    return sha256_hex(_dumps({"provider": provider, "model": model, "params": params,
                              "messages": messages, "schema": schema}))


_ENC = None
_ENC_FAILED = False


def estimate_tokens(text: str) -> int:
    """tiktoken o200k_base if available, else len/4."""
    global _ENC, _ENC_FAILED
    if _ENC is None and not _ENC_FAILED:
        try:
            os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(__file__).resolve().parents[2] / ".cache" / "tiktoken"))
            import tiktoken

            _ENC = tiktoken.get_encoding("o200k_base")
        except Exception:
            _ENC_FAILED = True
    if _ENC is not None:
        return len(_ENC.encode(text))
    return math.ceil(len(text) / 4)


def _prompt_text(messages: list, schema: dict) -> str:
    parts = []
    for m in messages:
        c = m.get("content", "")
        parts.append(c if isinstance(c, str) else _dumps(c))
    parts.append(_dumps(schema))
    return "\n".join(parts)


def to_strict(schema: dict) -> dict:
    """Make an object schema acceptable for strict json_schema mode:
    every object gets additionalProperties=false and (if absent) all properties required."""
    s = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node.setdefault("additionalProperties", False)
                if "properties" in node:
                    node.setdefault("required", list(node["properties"].keys()))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(s)
    return s


def _is_type(v: Any, t: str) -> bool:
    return {
        "object": isinstance(v, dict),
        "array": isinstance(v, list),
        "string": isinstance(v, str),
        "boolean": isinstance(v, bool),
        "integer": isinstance(v, int) and not isinstance(v, bool),
        "number": isinstance(v, (int, float)) and not isinstance(v, bool),
        "null": v is None,
    }.get(t, True)


def schema_errors(data: Any, schema: dict, path: str = "$") -> list[str]:
    """Small JSON-schema subset validator. Messages contain paths only, never values."""
    errs: list[str] = []
    if "anyOf" in schema:
        if not any(not schema_errors(data, sub, path) for sub in schema["anyOf"]):
            errs.append(f"{path}: matches no anyOf branch")
        return errs
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_is_type(data, x) for x in types):
            return [f"{path}: expected {t}"]
    if "enum" in schema and data not in schema["enum"]:
        errs.append(f"{path}: not one of the allowed values")
    if "const" in schema and data != schema["const"]:
        errs.append(f"{path}: wrong constant")
    if isinstance(data, dict):
        props = schema.get("properties", {})
        for r in schema.get("required", []):
            if r not in data:
                errs.append(f"{path}: missing '{r}'")
        addl = schema.get("additionalProperties", True)
        for k, v in data.items():
            if k in props:
                errs += schema_errors(v, props[k], f"{path}.{k}")
            elif addl is False:
                errs.append(f"{path}: unexpected key")
            elif isinstance(addl, dict):
                errs += schema_errors(v, addl, f"{path}.*")
    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            errs.append(f"{path}: too few items")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errs.append(f"{path}: too many items")
        if isinstance(schema.get("items"), dict):
            for i, v in enumerate(data):
                errs += schema_errors(v, schema["items"], f"{path}[{i}]")
    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errs.append(f"{path}: too short")
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errs.append(f"{path}: too long")
    if _is_type(data, "number"):
        if "minimum" in schema and data < schema["minimum"]:
            errs.append(f"{path}: below minimum")
        if "maximum" in schema and data > schema["maximum"]:
            errs.append(f"{path}: above maximum")
    return errs


def _parse_json(text: str) -> Any:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if m:
        t = m.group(1)
    return json.loads(t)


def _retry_after_s(exc: Exception) -> Optional[float]:
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) or {}
    try:
        if headers.get("retry-after-ms"):
            return float(headers["retry-after-ms"]) / 1000.0
        if headers.get("retry-after"):
            return float(headers["retry-after"])
    except (TypeError, ValueError):
        return None
    return None


# ---------------------------------------------------------------- limiter
class RateLimiter:
    """Sliding 60 s window for requests-per-minute and tokens-per-minute."""

    def __init__(self, rpm: Optional[int] = None, tpm: Optional[int] = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 window: float = 60.0):
        self.rpm, self.tpm, self.window = rpm, tpm, window
        self.clock, self.sleep = clock, sleep
        self.events: deque[list] = deque()  # [timestamp, tokens]

    def _purge(self, now: float) -> None:
        while self.events and self.events[0][0] <= now - self.window:
            self.events.popleft()

    def wait_time(self, tokens: int, now: Optional[float] = None) -> float:
        now = self.clock() if now is None else now
        self._purge(now)
        waits = [0.0]
        ev = list(self.events)
        if self.rpm and len(ev) >= self.rpm:
            waits.append(ev[len(ev) - self.rpm][0] + self.window - now)
        if self.tpm:
            used = sum(e[1] for e in ev)
            if used + tokens > self.tpm and ev:
                acc = used
                for t, tok in ev:
                    acc -= tok
                    if acc + tokens <= self.tpm:
                        waits.append(t + self.window - now)
                        break
                else:  # request alone exceeds tpm: wait for an empty window
                    waits.append(ev[-1][0] + self.window - now)
        return max(waits)

    def acquire(self, tokens: int) -> list:
        while True:
            w = self.wait_time(tokens)
            if w <= 0:
                break
            self.sleep(w)
        entry = [self.clock(), tokens]
        self.events.append(entry)
        return entry

    @staticmethod
    def settle(entry: list, actual_tokens: int) -> None:
        entry[1] = actual_tokens


# ---------------------------------------------------------------- clients
def default_client_factory(provider: str, pcfg: ProviderCfg, mode: Optional[str]):
    key = os.environ.get(pcfg.key_env, "")
    if not key:
        raise MissingKey(f"{pcfg.key_env} not set")
    common = dict(api_key=key, max_retries=0, timeout=120.0)
    if pcfg.is_azure:
        endpoint = os.environ.get(pcfg.endpoint_env or "", "")
        if not endpoint:
            raise MissingKey(f"{pcfg.endpoint_env} not set")
        endpoint = endpoint.rstrip("/") + "/"
        if mode == "fallback":
            base = re.sub(r"openai/v1/?$", "", endpoint)
            return openai.AzureOpenAI(azure_endpoint=base, api_version=pcfg.fallback_api_version, **common)
        base_url = endpoint if endpoint.endswith("openai/v1/") else endpoint + "openai/v1/"
        return openai.OpenAI(base_url=base_url, **common)
    return openai.OpenAI(base_url=pcfg.base_url, **common)


class LLMClient:
    def __init__(self, cfg: Optional[Config] = None, *, client_factory=None,
                 cache_dir: Optional[Path] = None, log_path: Optional[Path] = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 dry_run: bool = False, token_estimator: Callable[[str], int] = estimate_tokens):
        self.cfg = cfg or load_config()
        root = self.cfg.root
        self.cache_dir = Path(cache_dir) if cache_dir else root / ".cache" / "llm"
        self.log_path = Path(log_path) if log_path else root / "outputs" / "logs" / "llm_calls.jsonl"
        self.client_factory = client_factory or default_client_factory
        self.clock, self.sleep = clock, sleep
        self.dry_run = dry_run
        self.estimate = token_estimator
        self.calls_made = 0
        self.limiters = {n: RateLimiter(p.rpm, p.tpm, clock=clock, sleep=sleep)
                         for n, p in self.cfg.providers.items()}
        self._clients: dict[tuple, Any] = {}
        self.azure_path: dict[str, str] = {}  # provider -> path that worked

    # ---------------- public
    def call(self, model_key: str, messages: list, json_schema: dict, *, purpose: str,
             no_cache: bool = False) -> LLMResult:
        m = self.cfg.models.get(model_key)
        if m is None:
            raise LLMError(f"unknown model key '{model_key}'")
        if m.is_tbd:
            raise LLMError(f"model '{model_key}' is TBD")
        p = self.cfg.providers[m.provider]
        schema = to_strict(json_schema)
        params = dict(m.params)
        if m.family.lower() == "openai":
            params.pop("temperature", None)  # gpt-5 rule: never send temperature
        key = cache_key(m.provider, m.model, params, messages, schema)
        est_in = self.estimate(_prompt_text(messages, schema))
        base_log = {"purpose": purpose, "provider": m.provider, "model_key": model_key,
                    "prompt_sha256": sha256_hex(_dumps(messages)), "cache_key": key}

        if not no_cache:
            hit = self._cache_get(key)
            if hit is not None:
                res = LLMResult(data=hit["data"], raw_text=hit["raw_text"], model_string=hit["model_string"],
                                usage=Usage(**hit.get("usage", {})), cached=True, latency_ms=0,
                                cache_key=key, api_path=hit.get("api_path"))
                self._log({**base_log, "model_string": res.model_string, "input_tokens": res.usage.input_tokens,
                           "output_tokens": res.usage.output_tokens, "latency_ms": 0, "cached": True,
                           "error": None, "api_path": res.api_path})
                return res

        if self.dry_run:
            self._log({**base_log, "model_string": None, "input_tokens": est_in, "output_tokens": 0,
                       "latency_ms": 0, "cached": False, "error": None, "api_path": None, "dry_run": True})
            return LLMResult(data=None, raw_text="", model_string="(dry-run)",
                             usage=Usage(input_tokens=est_in, output_tokens=0),
                             cache_key=key, dry_run=True)

        res = self._call_with_retries(m, p, messages, schema, params, est_in, key, base_log)
        self._cache_put(key, res)
        return res

    # ---------------- internals
    def _call_with_retries(self, m: ModelCfg, p: ProviderCfg, messages, schema, params, est_in, key, base_log) -> LLMResult:
        max_tok = params.get("max_completion_tokens")
        empty_retry = schema_retry = False
        while True:
            send = dict(params)
            if max_tok:
                send["max_completion_tokens"] = int(max_tok)
            t0 = self.clock()
            rec = {**base_log, "model_string": None, "input_tokens": None, "output_tokens": None,
                   "cached": False, "error": None, "api_path": None}
            try:
                resp, path = self._send(m, p, messages, schema, send, est_in)
            except LLMError as e:
                self._log({**rec, "latency_ms": int((self.clock() - t0) * 1000), "error": e.code})
                raise
            except openai.APIStatusError as e:
                self._log({**rec, "latency_ms": int((self.clock() - t0) * 1000), "error": f"HTTP_{e.status_code}"})
                raise ProviderError(self._scrub(f"HTTP {e.status_code}: {e.message}")) from None
            except Exception as e:
                self._log({**rec, "latency_ms": int((self.clock() - t0) * 1000), "error": type(e).__name__})
                raise ProviderError(self._scrub(f"{type(e).__name__}: {e}")) from None
            latency = int((self.clock() - t0) * 1000)
            text, finish, model_string, usage = self._extract(resp)
            rec.update(model_string=model_string, input_tokens=usage.input_tokens,
                       output_tokens=usage.output_tokens, latency_ms=latency, api_path=path)

            if not text.strip() or finish == "length":
                rec["error"] = EmptyOrTruncated.code
                self._log(rec)
                if not empty_retry:
                    empty_retry = True
                    max_tok = min(int(max_tok or 4000) * 2, MAX_TOKENS_CAP)
                    continue
                raise EmptyOrTruncated(f"reply empty={not text.strip()} finish_reason={finish}")

            try:
                data = _parse_json(text)
                errs = schema_errors(data, schema)
            except (json.JSONDecodeError, ValueError):
                data, errs = None, ["$: not valid JSON"]
            if errs:
                rec["error"] = SchemaError.code
                self._log(rec)
                if not schema_retry:
                    schema_retry = True
                    continue
                raise SchemaError("; ".join(errs[:5]))

            self._log(rec)
            return LLMResult(data=data, raw_text=text, model_string=model_string, usage=usage,
                             cached=False, latency_ms=latency, cache_key=key, api_path=path)

    def _send(self, m: ModelCfg, p: ProviderCfg, messages, schema, send_params, est_in):
        kwargs: dict[str, Any] = {
            "model": m.model,
            "messages": messages,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "response", "strict": True, "schema": schema}},
        }
        extra = {}
        for k, v in send_params.items():
            (kwargs if k in CHAT_KWARGS else extra)[k] = v
        if extra:
            kwargs["extra_body"] = extra

        if p.is_azure:
            paths = [self.azure_path[m.provider]] if m.provider in self.azure_path else ["v1", "fallback"]
        else:
            paths = [None]
        limiter = self.limiters[m.provider]
        for i, path in enumerate(paths):
            if self.calls_made >= self.cfg.max_calls_per_run:
                raise BudgetExceeded(f"max_calls_per_run={self.cfg.max_calls_per_run} reached")
            self.calls_made += 1
            client = self._client(m.provider, p, path)
            entry = limiter.acquire(est_in)
            try:
                resp = self._with_backoff(lambda: client.chat.completions.create(**kwargs))
            except (openai.APIStatusError, openai.APIConnectionError) as e:
                if i + 1 < len(paths):
                    status = getattr(e, "status_code", type(e).__name__)
                    self._log({"purpose": "azure_path", "provider": m.provider, "model_key": None,
                               "event": f"v1 failed ({status}); trying fallback api_version"})
                    continue
                raise
            u = getattr(resp, "usage", None)
            limiter.settle(entry, int(getattr(u, "prompt_tokens", 0) or 0) + int(getattr(u, "completion_tokens", 0) or 0) or est_in)
            if p.is_azure and m.provider not in self.azure_path:
                self.azure_path[m.provider] = path
                self._log({"purpose": "azure_path", "provider": m.provider, "model_key": None,
                           "event": f"azure path in use: {path}"})
            return resp, path
        raise ProviderError("no API path available")  # pragma: no cover

    def _with_backoff(self, fn):
        for attempt in range(MAX_TRIES):
            try:
                return fn()
            except openai.RateLimitError as e:
                if attempt == MAX_TRIES - 1:
                    raise
                wait = _retry_after_s(e)
                wait = 2.0 ** attempt if wait is None else wait
            except openai.APIStatusError as e:
                if e.status_code < 500 or attempt == MAX_TRIES - 1:
                    raise
                wait = 2.0 ** attempt
            except (openai.APIConnectionError, openai.APITimeoutError):
                if attempt == MAX_TRIES - 1:
                    raise
                wait = 2.0 ** attempt
            self.sleep(min(max(wait, 0.0), MAX_WAIT_S))
        raise ProviderError("retries exhausted")  # pragma: no cover

    def _client(self, provider: str, p: ProviderCfg, path: Optional[str]):
        k = (provider, path)
        if k not in self._clients:
            self._clients[k] = self.client_factory(provider, p, path)
        return self._clients[k]

    @staticmethod
    def _extract(resp) -> tuple[str, Optional[str], str, Usage]:
        choice = resp.choices[0] if getattr(resp, "choices", None) else None
        text = (getattr(getattr(choice, "message", None), "content", None) or "") if choice else ""
        finish = getattr(choice, "finish_reason", None) if choice else None
        u = getattr(resp, "usage", None)
        usage = Usage(input_tokens=int(getattr(u, "prompt_tokens", 0) or 0),
                      output_tokens=int(getattr(u, "completion_tokens", 0) or 0))
        return text, finish, str(getattr(resp, "model", "") or ""), usage

    def _scrub(self, text: str) -> str:
        for v in secret_values(self.cfg):
            text = text.replace(v, "***")
        return text

    def _cache_get(self, key: str) -> Optional[dict]:
        f = self.cache_dir / f"{key}.json"
        if not f.is_file():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _cache_put(self, key: str, res: LLMResult) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        f = self.cache_dir / f"{key}.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(_dumps({"data": res.data, "raw_text": res.raw_text, "model_string": res.model_string,
                               "usage": res.usage.model_dump(), "api_path": res.api_path}), encoding="utf-8")
        os.replace(tmp, f)

    def _log(self, rec: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"time": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **rec}
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(_dumps(rec) + "\n")


_default: Optional[LLMClient] = None


def call(model_key: str, messages: list, json_schema: dict, *, purpose: str, no_cache: bool = False) -> LLMResult:
    """Module-level entry point using a lazily created default client."""
    global _default
    if _default is None:
        _default = LLMClient()
    return _default.call(model_key, messages, json_schema, purpose=purpose, no_cache=no_cache)
