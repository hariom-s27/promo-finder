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
import threading
from collections import deque
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Optional

import openai
from pydantic import BaseModel

from .config import Config, ModelCfg, ProviderCfg, load_config, model_quota, secret_values
from .provider_protocol import content_filter_failure, duration_seconds, endpoint_form, foundry_base_url, foundry_paths, failed_request_metadata, rate_headers

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


class RateLimited(LLMError):
    code = "RATE_LIMITED"


class MissingKey(LLMError):
    code = "MISSING_KEY"

    def __init__(self, variable_name):
        self.variable_name = variable_name
        super().__init__(f"{variable_name} not set")


class ProviderError(LLMError):
    code = "PROVIDER_ERROR"


class ContentFiltered(ProviderError):
    code = "CONTENT_FILTERED"

    def __init__(self, metadata=None):
        self.provider_metadata = metadata
        super().__init__("provider content filter blocked response")


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
    response_mode: str = "json_schema"
    validation_retry_used: bool = False
    final_temperature: Optional[float] = None
    reasoning_tokens: Optional[int] = None
    token_parameter: Optional[str] = None
    endpoint_form: Optional[str] = None
    rate_limit_headers: dict[str, str] = {}
    thinking_method: Optional[str] = None


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
    """Offline estimate: an already-loaded encoding, otherwise ceil(len/4).

    Never initialize an encoding here: tiktoken may download its vocabulary.
    Dry runs must be independent of network and credentials.
    """
    global _ENC, _ENC_FAILED
    if _ENC is None and not _ENC_FAILED:
        try:
            from tiktoken.registry import ENCODINGS
            _ENC = ENCODINGS.get("o200k_base")
            _ENC_FAILED = _ENC is None
        except Exception:
            _ENC_FAILED = True
    if _ENC is not None:
        return len(_ENC.encode(text))
    return math.ceil(len(text) / 4)


def json_messages(messages, schema):
    payload = copy.deepcopy(messages)
    instruction = "Return only JSON matching this schema: " + _dumps(schema)
    if payload and payload[0]["role"] == "system":
        content = payload[0]["content"]
        marker = "\n\nQuestions:\n"
        if marker in content:
            fixed, questions = content.split(marker, 1)
            payload[0]["content"] = fixed + "\n\n" + instruction + marker + questions
        else:
            payload[0]["content"] = content + "\n\n" + instruction
    else:
        payload.insert(0, {"role": "system", "content": instruction})
    return payload


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
            for unsupported in ("pattern", "minLength", "maxLength", "minItems", "maxItems"):
                node.pop(unsupported, None)
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
        "number": isinstance(v, (int, float)) and not isinstance(v, bool) and (not isinstance(v, float) or math.isfinite(v)),
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


def _parse_json(text: str, *, first_object=False) -> Any:
    t = re.sub(r"<think\b[^>]*>.*?</think\s*>", "", text, flags=re.S | re.I).strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if m:
        t = m.group(1)
    def invalid_constant(_):
        raise ValueError("nonfinite JSON number")
    if not first_object:
        return json.loads(t, parse_constant=invalid_constant)
    decoder = json.JSONDecoder(parse_constant=invalid_constant)
    # Skip prose/code fences; validation still applies to the first JSON object.
    for pos, char in enumerate(t):
        if char == "{":
            try:
                data, _ = decoder.raw_decode(t, pos)
                return data
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON object")


def _retry_after_s(exc: Exception) -> Optional[float]:
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) or {}
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        value = headers.get(name)
        if value is None:
            continue
        try:
            return float(value) * scale
        except (TypeError, ValueError):
            if name == "retry-after":
                try:
                    return parsedate_to_datetime(value).timestamp() - time.time()
                except (TypeError, ValueError, OverflowError):
                    pass
    return None


# ---------------------------------------------------------------- limiter
class RateLimiter:
    """Sliding 60 s window for requests-per-minute and tokens-per-minute."""

    def __init__(self, rpm: Optional[int] = None, tpm: Optional[int] = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 window: float = 60.0, min_interval_s: float = 0.0):
        self.rpm, self.tpm, self.window = rpm, tpm, window
        self.clock, self.sleep = clock, sleep
        self.events: deque[list] = deque()  # [timestamp, tokens]
        self.min_interval_s = min_interval_s
        self.last_start: Optional[float] = None
        self.lock = threading.Lock()
        self.not_before = 0.0
        self.remaining_tokens: Optional[int] = None
        self.tokens_reset_at = 0.0
        self.quota_margin = 0

    def observe(self, headers):
        """Provider metadata may delay admission, never relax the local quota."""
        now = self.clock()
        delay = duration_seconds(headers.get("retry-after-ms"))
        if delay is not None:
            delay /= 1000
        else:
            delay = duration_seconds(headers.get("retry-after"))
            if delay is None and headers.get("retry-after"):
                try:
                    delay = max(0, parsedate_to_datetime(headers["retry-after"]).timestamp() - time.time())
                except (TypeError, ValueError, OverflowError):
                    pass
        if delay is not None:
            self.not_before = max(self.not_before, now + delay)
        try:
            remaining = int(headers["x-ratelimit-remaining-tokens"])
        except (KeyError, ValueError, TypeError):
            return
        self.remaining_tokens = max(0, remaining - self.quota_margin)
        reset = duration_seconds(headers.get("x-ratelimit-reset-tokens"))
        self.tokens_reset_at = now + (reset if reset is not None else self.window)

    def _purge(self, now: float) -> None:
        while self.events and self.events[0][0] <= now - self.window:
            self.events.popleft()

    def wait_time(self, tokens: int, now: Optional[float] = None) -> float:
        now = self.clock() if now is None else now
        self._purge(now)
        if self.tpm and tokens > self.tpm:
            raise LLMError("single request token reservation exceeds effective TPM")
        waits = [0.0, self.not_before - now]
        if self.remaining_tokens is not None:
            if now >= self.tokens_reset_at:
                self.remaining_tokens = None
            elif tokens > self.remaining_tokens:
                waits.append(self.tokens_reset_at - now)
        if self.last_start is not None:
            waits.append(self.last_start + self.min_interval_s - now)
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
        with self.lock:
            while True:
                w = self.wait_time(tokens)
                if w <= 0:
                    break
                self.sleep(min(w, 60.0))
            entry = [self.clock(), tokens]
            self.last_start = entry[0]
            self.events.append(entry)
            if self.remaining_tokens is not None:
                self.remaining_tokens = max(0, self.remaining_tokens - tokens)
            return entry

    @staticmethod
    def settle(entry: list, actual_tokens: int) -> None:
        entry[1] = actual_tokens


# ---------------------------------------------------------------- clients
def default_client_factory(provider: str, pcfg: ProviderCfg, mode: Optional[str], env=None):
    """Build a provider client. `env` defaults to the process environment; the app passes its own mapping."""
    env = os.environ if env is None else env
    key = env.get(pcfg.key_env, "")
    if not key:
        raise MissingKey(pcfg.key_env)
    common = dict(api_key=key, max_retries=0, timeout=120.0)
    if provider == "azure_foundry":
        endpoint = env.get(pcfg.endpoint_env or "", "")
        if not endpoint:
            raise MissingKey(pcfg.endpoint_env)
        try:
            base_url = foundry_base_url(endpoint, mode or "v1")
        except ValueError:
            raise LLMError("invalid Foundry resource endpoint form") from None
        return openai.OpenAI(base_url=base_url, **common)
    if pcfg.is_azure:
        endpoint = env.get(pcfg.endpoint_env or "", "")
        if not endpoint:
            raise MissingKey(pcfg.endpoint_env)
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
        self.cache_dir = Path(cache_dir) if cache_dir else self.cfg.output_root / ".llm_cache"
        self.log_path = Path(log_path) if log_path else self.cfg.output_root / "logs/llm_calls.jsonl"
        self.client_factory = client_factory or default_client_factory
        self.clock, self.sleep = clock, sleep
        self.dry_run = dry_run
        self.estimate = token_estimator
        self.calls_made = 0
        self.logical_calls = 0
        self.records: list[dict] = []  # metadata only, for per-run accounting
        self.limiters = {n: RateLimiter(p.rpm, p.tpm, clock=clock, sleep=sleep,
                                      min_interval_s=self.cfg.rate_limit.min_interval_s)
                         for n, p in self.cfg.providers.items()}
        self._slots = {n: threading.BoundedSemaphore(self.cfg.rate_limit.max_concurrent)
                       for n in self.cfg.providers}
        if "azure_foundry" in self._slots:
            self._slots["azure_foundry"] = threading.BoundedSemaphore(1)
        self.deployment_limiters = {}
        for key, model in self.cfg.models.items():
            if model.provider == "azure_foundry":
                quota = model_quota(self.cfg, key)
                limiter = RateLimiter(quota["effective_rpm"], quota["effective_tpm"], clock=clock, sleep=sleep,
                                      min_interval_s=self.cfg.rate_limit.min_interval_s)
                limiter.quota_margin = quota["tpm"] - quota["effective_tpm"]
                self.deployment_limiters[key] = limiter
        self._budget_lock = threading.Lock()
        self._clients: dict[tuple, Any] = {}
        self.azure_path: dict[str, str] = {}  # provider -> path that worked
        self.mode_path = self.cfg.output_root / "logs/structured_output_modes.json"
        try:
            self.output_modes = json.loads(self.mode_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.output_modes = {}
        self.protocol_path = self.cfg.output_root / "logs/foundry_protocol.json"
        try:
            self.foundry_protocols = json.loads(self.protocol_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.foundry_protocols = {}
            if self.cfg.run_name != "dev":
                try:
                    self.foundry_protocols = json.loads((self.cfg.root / "outputs/runs/dev/logs/foundry_protocol.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
        self.consecutive_429s = 0
        self.phase_rate_limited = False
        self.response_metadata = {}

    def begin_phase(self):
        self.consecutive_429s = 0
        self.phase_rate_limited = False

    def _save_protocols(self):
        self.protocol_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.protocol_path.with_suffix(".json.tmp")
        temporary.write_text(_dumps(self.foundry_protocols), encoding="utf-8")
        temporary.replace(self.protocol_path)

    def protocol(self, model_key):
        model = self.cfg.models[model_key]
        return copy.deepcopy(self.foundry_protocols.get(model.provider + "/" + model.model, {}))

    # ---------------- public
    def call(self, model_key: str, messages: list, json_schema: dict, *, purpose: str,
             no_cache: bool = False, reasoning_effort: Optional[str] = None,
             temperature: Optional[float] = None, max_completion_tokens: Optional[int] = None,
             cache_namespace: str = "", response_validator=None,
             retry_temperature: Optional[float] = None, cache_only: bool = False) -> LLMResult:
        m = self.cfg.models.get(model_key)
        if m is None:
            raise LLMError(f"unknown model key '{model_key}'")
        if m.is_tbd:
            raise LLMError(f"model '{model_key}' is TBD")
        p = self.cfg.providers[m.provider]
        if self.phase_rate_limited:
            raise RateLimited("phase stopped after five consecutive HTTP 429s")
        schema = to_strict(json_schema)
        params = dict(m.params)
        if reasoning_effort is not None:
            params["reasoning_effort"] = reasoning_effort
        if temperature is not None:
            params["temperature"] = temperature
        if max_completion_tokens is not None:
            params["max_completion_tokens"] = max_completion_tokens
        if m.family.lower() == "openai":
            params.pop("temperature", None)  # gpt-5 rule: never send temperature
        identity = dict(params)
        if cache_namespace:
            identity["_namespace"] = cache_namespace
        if m.structured_output != "strict":
            identity["_structured_output"] = m.structured_output
        if retry_temperature is not None:
            identity["_retry_temperature"] = retry_temperature
        if m.provider == "azure_foundry":
            identity["_foundry_protocol"] = 1
        key = cache_key(m.provider, m.model, identity, messages, schema)
        est_in = self.estimate(_prompt_text(json_messages(messages, schema) if m.structured_output == "json_object" else messages,
                                           {} if m.structured_output == "json_object" else schema))
        self.logical_calls += 1
        base_log = {"purpose": purpose, "provider": m.provider, "model_key": model_key,
                    "credential_set": "azure_openai" if m.provider == "azure" else m.provider,
                    "credential_variable_names": p.env_names(),
                    "prompt_sha256": sha256_hex(_dumps(messages)), "cache_key": key,
                    "logical_call_id": self.logical_calls}

        if not no_cache:
            hit = self._cache_get(key)
            validate_hit = bool(cache_namespace) or m.structured_output in {"auto", "json_object"}
            if hit is not None and (not validate_hit or (not schema_errors(hit.get("data"), schema) and not (
                    response_validator and response_validator(hit.get("data"))))):
                res = LLMResult(data=hit["data"], raw_text=hit["raw_text"], model_string=hit["model_string"],
                                usage=Usage(**hit.get("usage", {})), cached=True, latency_ms=0,
                                cache_key=key, api_path=hit.get("api_path"),
                                response_mode=hit.get("response_mode", "json_schema"),
                                validation_retry_used=hit.get("validation_retry_used", False),
                                final_temperature=hit.get("final_temperature"),
                                **{k: hit[k] for k in ("reasoning_tokens", "token_parameter", "endpoint_form", "rate_limit_headers", "thinking_method") if k in hit})
                self._log({**base_log, "model_string": res.model_string, "input_tokens": res.usage.input_tokens,
                           "output_tokens": res.usage.output_tokens, "latency_ms": 0, "cached": True,
                           "error": None, "api_path": res.api_path, "response_mode": res.response_mode,
                           "validation_retry_used": res.validation_retry_used, "final_temperature": res.final_temperature,
                           "reasoning_tokens": res.reasoning_tokens, "token_parameter": res.token_parameter,
                           "endpoint_form": res.endpoint_form, "response_headers": res.rate_limit_headers})
                return res

        if cache_only:
            raise LLMError("required cache hit missing or invalid; refusing a live request")
        if self.dry_run:
            self._log({**base_log, "model_string": None, "input_tokens": est_in, "output_tokens": 0,
                       "latency_ms": 0, "cached": False, "error": None, "api_path": None, "dry_run": True})
            return LLMResult(data=None, raw_text="", model_string="(dry-run)",
                             usage=Usage(input_tokens=est_in, output_tokens=0),
                             cache_key=key, dry_run=True)

        res = self._call_with_retries(m, p, messages, schema, params, est_in, key, base_log, response_validator, retry_temperature)
        self._cache_put(key, res)
        return res

    # ---------------- internals
    def _call_with_retries(self, m: ModelCfg, p: ProviderCfg, messages, schema, params, est_in, key, base_log, response_validator=None, retry_temperature=None) -> LLMResult:
        max_tok = params.get("max_completion_tokens", params.get("max_tokens"))
        invalid_retry = False
        while True:
            send = dict(params)
            if invalid_retry and retry_temperature is not None and m.family.lower() != "openai":
                send["temperature"] = retry_temperature
            if max_tok:
                send["max_completion_tokens"] = int(max_tok)
            t0 = self.clock()
            rec = {**base_log, "model_string": None, "input_tokens": None, "output_tokens": None,
                   "cached": False, "error": None, "api_path": None}
            try:
                resp, path, request_number = self._send(m, p, messages, schema, send, est_in, base_log)
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
            rec.update(request_number=request_number, model_string=model_string, input_tokens=usage.input_tokens,
                       output_tokens=usage.output_tokens, latency_ms=latency, api_path=path,
                       response_mode=self.output_modes.get(m.provider + "/" + m.model, "json_schema") if m.structured_output == "auto" else "json_object" if m.structured_output == "json_object" else "json_schema",
                       validation_retry_used=invalid_retry, final_temperature=send.get("temperature"))
            extra_metadata = self.response_metadata.pop(request_number, {})
            rec.update(extra_metadata)
            details = getattr(getattr(resp, "usage", None), "completion_tokens_details", None)
            reasoning = getattr(details, "reasoning_tokens", None)
            if reasoning is not None:
                rec["reasoning_tokens"] = reasoning
            result_metadata = {"reasoning_tokens": reasoning,
                               "token_parameter": rec.get("token_parameter"),
                               "endpoint_form": rec.get("endpoint_form"),
                               "rate_limit_headers": rec.get("response_headers", {}),
                               "thinking_method": "not_applicable" if m.provider == "azure_foundry" and m.family.lower() == "meta" else None}

            if not text.strip() or finish == "length":
                rec["error"] = EmptyOrTruncated.code
                self._log(rec)
                if not invalid_retry:
                    invalid_retry = True
                    self._log({**base_log, "event": "response_retry", "reason": EmptyOrTruncated.code,
                               "retry_temperature": retry_temperature})
                    if m.provider != "azure_foundry":
                        max_tok = min(int(max_tok or 4000) * 2, MAX_TOKENS_CAP)
                    continue
                raise EmptyOrTruncated(f"reply empty={not text.strip()} finish_reason={finish}")

            try:
                data = _parse_json(text, first_object=rec["response_mode"] == "text")
                errs = schema_errors(data, schema)
                if not errs and response_validator:
                    errs = response_validator(data)
            except (json.JSONDecodeError, ValueError):
                data, errs = None, ["$: not valid JSON"]
            if errs:
                rec["error"] = SchemaError.code
                self._log(rec)
                if not invalid_retry:
                    invalid_retry = True
                    self._log({**base_log, "event": "response_retry", "reason": SchemaError.code,
                               "retry_temperature": retry_temperature})
                    continue
                exc = SchemaError("; ".join(errs[:5]))
                exc.result = LLMResult(data=data, raw_text=text, model_string=model_string, usage=usage,
                                       cache_key=key, api_path=path, response_mode=rec["response_mode"],
                                       validation_retry_used=invalid_retry, final_temperature=send.get("temperature"), **result_metadata)
                raise exc

            self._log(rec)
            return LLMResult(data=data, raw_text=text, model_string=model_string, usage=usage,
                             cached=False, latency_ms=latency, cache_key=key, api_path=path,
                             response_mode=rec["response_mode"], validation_retry_used=invalid_retry,
                             final_temperature=send.get("temperature"), **result_metadata)

    def _send(self, m: ModelCfg, p: ProviderCfg, messages, schema, send_params, est_in, base_log):
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

        is_foundry = m.provider == "azure_foundry"
        mode_key = m.provider + "/" + m.model
        endpoint = os.environ.get(p.endpoint_env or "", "")
        protocol = self.foundry_protocols.setdefault(mode_key, {"response_mode": "json_object",
                      "token_parameter": "max_completion_tokens", "settled": False}) if is_foundry else {}
        if is_foundry:
            paths = foundry_paths(endpoint) if endpoint else ["v1"]
        elif p.is_azure:
            paths = [self.azure_path[m.provider]] if m.provider in self.azure_path else ["v1", "fallback"]
        else:
            paths = [None]
        limiter = self.deployment_limiters[base_log["model_key"]] if is_foundry else self.limiters[m.provider]
        for i, path in enumerate(paths):
            client = self._client(m.provider, p, path)

            def physical_request():
                if self.phase_rate_limited:
                    raise RateLimited("phase stopped after five consecutive HTTP 429s")
                with self._budget_lock:
                    if self.calls_made >= self.cfg.max_calls_per_run:
                        raise BudgetExceeded(f"max_calls_per_run={self.cfg.max_calls_per_run} reached")
                output_cap = int(send_params.get("max_completion_tokens", send_params.get("max_tokens", 0)))
                reservation = est_in + output_cap if m.provider == "groq" or is_foundry else est_in
                if m.provider == "groq" and p.tpm and reservation > p.tpm:
                    raise LLMError("single request token reservation exceeds provider TPM")
                entry = limiter.acquire(reservation)
                with self._budget_lock:
                    if self.calls_made >= self.cfg.max_calls_per_run:
                        raise BudgetExceeded(f"max_calls_per_run={self.cfg.max_calls_per_run} reached")
                    self.calls_made += 1
                    number = self.calls_made
                self._log({**base_log, "event": "http_attempt_started", "api_path": path,
                           "request_number": number, "cached": False, "reserved_tokens": reservation,
                           "endpoint_form": endpoint_form(endpoint, path) if is_foundry and endpoint else None})
                headers = {}
                try:
                    mode = protocol["response_mode"] if is_foundry else self.output_modes.get(mode_key, "json_schema") if m.structured_output == "auto" else "json_object" if m.structured_output == "json_object" else "json_schema"
                    payload = copy.deepcopy(kwargs)
                    if mode in {"json_object", "text"}:
                        payload["messages"] = json_messages(messages, schema)
                        if mode == "text":
                            payload.pop("response_format", None)
                        else:
                            payload["response_format"] = {"type": "json_object"}
                    if is_foundry:
                        payload.pop("max_completion_tokens", None)
                        payload.pop("max_tokens", None)
                        payload[protocol["token_parameter"]] = output_cap
                    completions = client.chat.completions
                    if hasattr(completions, "with_raw_response"):
                        raw_response = completions.with_raw_response.create(**payload)
                        headers = rate_headers(raw_response.headers)
                        if m.provider == "groq":
                            from .budget import observe
                            observe(self.cfg, raw_response.headers)
                        response = raw_response.parse()
                    else:
                        response = completions.create(**payload)
                    body = response.model_dump() if hasattr(response, "model_dump") else vars(response)
                    filter_metadata = failed_request_metadata(body)
                    if content_filter_failure(filter_metadata):
                        filter_metadata["http_status_code"] = 200
                        raise ContentFiltered(filter_metadata)
                except Exception as exc:
                    raw_headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
                    headers = rate_headers(raw_headers)
                    if is_foundry:
                        limiter.observe(headers)
                    if m.provider == "groq" and getattr(exc, "response", None) is not None:
                        from .budget import observe
                        observe(self.cfg, exc.response.headers)
                    metadata = getattr(exc, "provider_metadata", None) or failed_request_metadata(exc)
                    status = metadata["http_status_code"]
                    filtered = content_filter_failure(metadata)
                    self._log({**base_log, "event": "http_attempt_failed", "api_path": path,
                               "request_number": number, "cached": False,
                               "error": f"HTTP_{status}" if status and status != 200 else ContentFiltered.code if filtered else type(exc).__name__,
                               **metadata,
                               **({"error_code": ContentFiltered.code} if filtered else {}),
                               "endpoint_form": endpoint_form(endpoint, path) if is_foundry and endpoint else None,
                               "response_headers": headers})
                    if filtered:
                        self.consecutive_429s = 0
                        raise ContentFiltered(metadata) from None
                    if status == 429:
                        self.consecutive_429s += 1
                        if self.consecutive_429s >= 5:
                            self.phase_rate_limited = True
                            raise RateLimited("phase stopped after five consecutive HTTP 429s") from None
                    elif status is not None:
                        self.consecutive_429s = 0
                    message = str(getattr(exc, "message", "")).lower()
                    if is_foundry and status == 400 and not protocol.get("settled"):
                        if "response_format" in message and mode == "json_object":
                            protocol["response_mode"] = "text"
                            self._save_protocols()
                            self._log({**base_log, "event": "json_mode_fallback", "response_mode": "text"})
                            return physical_request()
                        if "max_completion_tokens" in message and protocol["token_parameter"] == "max_completion_tokens":
                            protocol["token_parameter"] = "max_tokens"
                            self._save_protocols()
                            self._log({**base_log, "event": "token_parameter_fallback", "token_parameter": "max_tokens"})
                            return physical_request()
                    if (m.structured_output == "auto" and mode == "json_schema" and status in (400, 422)
                            and any(term in message for term in ("json_schema", "response_format", "structured output"))
                            and any(term in message for term in ("not support", "unsupported", "not available", "not permitted"))):
                        self.output_modes[mode_key] = "json_object"
                        self.mode_path.parent.mkdir(parents=True, exist_ok=True)
                        self.mode_path.write_text(_dumps(self.output_modes), encoding="utf-8")
                        self._log({**base_log, "event": "json_mode_fallback", "response_mode": "json_object"})
                        return physical_request()
                    raise
                self.consecutive_429s = 0
                if is_foundry:
                    limiter.observe(headers)
                    protocol.update(settled=True, api_path=path,
                                    endpoint_form=endpoint_form(endpoint, path) if endpoint else None,
                                    model_string=str(getattr(response, "model", "") or ""))
                    self._save_protocols()
                metadata = {"response_mode": mode, "response_headers": headers}
                if is_foundry:
                    metadata.update(token_parameter=protocol["token_parameter"], endpoint_form=protocol["endpoint_form"])
                self.response_metadata[number] = metadata
                usage = getattr(response, "usage", None)
                actual = int(getattr(usage, "prompt_tokens", 0) or 0) + int(getattr(usage, "completion_tokens", 0) or 0)
                if is_foundry:
                    entry[1] = max(reservation, actual)
                else:
                    limiter.settle(entry, actual or est_in)
                return response, number

            def request():
                with self._slots[m.provider]:
                    return physical_request()

            def retry(attempt, wait):
                self._log({**base_log, "event": "transport_retry", "api_path": path,
                           "request_number": self.calls_made, "retry_index": attempt,
                           "wait_s": wait})

            try:
                resp, number = self._with_backoff(request, on_retry=retry, honour_long_retry_after=is_foundry)
            except (openai.APIStatusError, openai.APIConnectionError) as e:
                route_error = (getattr(e, "status_code", None) == 404 and
                               not any(word in str(getattr(e, "message", "")).lower()
                                       for word in ("deployment", "model", "marketplace", "subscription")))
                if i + 1 < len(paths) and (not is_foundry or route_error):
                    status = getattr(e, "status_code", type(e).__name__)
                    self._log({"purpose": "azure_path", "provider": m.provider, "model_key": None,
                               "event": f"routing failed ({status}); trying same-resource endpoint form" if is_foundry else f"v1 failed ({status}); trying fallback api_version"})
                    continue
                raise
            if p.is_azure and m.provider not in self.azure_path:
                self.azure_path[m.provider] = path
                self._log({"purpose": "azure_path", "provider": m.provider, "model_key": None,
                           "event": f"azure path in use: {path}"})
            return resp, path, number
        raise ProviderError("no API path available")  # pragma: no cover

    def _with_backoff(self, fn, on_retry=None, honour_long_retry_after=False):
        for attempt in range(MAX_TRIES):
            try:
                return fn()
            except openai.RateLimitError as e:
                if attempt == MAX_TRIES - 1:
                    raise
                wait = _retry_after_s(e) if self.cfg.rate_limit.honour_retry_after else None
                if wait is None or not math.isfinite(wait) or wait <= 0 or (not honour_long_retry_after and wait > self.cfg.rate_limit.max_retry_after_s):
                    wait = 2.0 ** attempt
            except openai.APIStatusError as e:
                if e.status_code < 500 or attempt == MAX_TRIES - 1:
                    raise
                wait = 2.0 ** attempt
            except (openai.APIConnectionError, openai.APITimeoutError):
                if attempt == MAX_TRIES - 1:
                    raise
                wait = 2.0 ** attempt
            wait = max(wait, 0.0) if honour_long_retry_after else min(max(wait, 0.0), MAX_WAIT_S)
            if on_retry is not None:
                on_retry(attempt + 1, wait)
            remaining = wait
            while remaining > 0:
                chunk = min(remaining, 60.0)
                self.sleep(chunk)
                remaining -= chunk
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
                               "usage": res.usage.model_dump(), "api_path": res.api_path,
                               "response_mode": res.response_mode, "validation_retry_used": res.validation_retry_used,
                               "final_temperature": res.final_temperature,
                               "reasoning_tokens": res.reasoning_tokens, "token_parameter": res.token_parameter,
                               "endpoint_form": res.endpoint_form, "rate_limit_headers": res.rate_limit_headers,
                               "thinking_method": res.thinking_method}), encoding="utf-8")
        os.replace(tmp, f)

    def _log(self, rec: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"time": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **rec}
        self.records.append(rec)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(_dumps(rec) + "\n")


_default: Optional[LLMClient] = None


def call(model_key: str, messages: list, json_schema: dict, *, purpose: str, no_cache: bool = False,
         reasoning_effort: Optional[str] = None) -> LLMResult:
    """Module-level entry point using a lazily created default client."""
    global _default
    if _default is None:
        _default = LLMClient()
    return _default.call(model_key, messages, json_schema, purpose=purpose, no_cache=no_cache,
                         reasoning_effort=reasoning_effort)
