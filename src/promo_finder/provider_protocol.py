"""Metadata-only provider negotiation and header helpers. No credentials or calls."""

from __future__ import annotations

import math
import re
from urllib.parse import urlsplit, urlunsplit


def rate_headers(headers):
    """Retain rate metadata only, including error responses; never arbitrary headers."""
    return {str(k).lower(): str(v) for k, v in headers.items()
            if str(k).lower() in {"retry-after", "retry-after-ms"} or
            re.fullmatch(r"x-ratelimit-(?:[a-z0-9]+-)*(?:requests|tokens)(?:-[a-z0-9]+)*", str(k).lower())}


def duration_seconds(value):
    if value is None:
        return None
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        pieces = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h)", str(value))
        if not pieces or "".join(a + b for a, b in pieces) != str(value):
            return None
        seconds = sum(float(a) * {"ms": .001, "s": 1, "m": 60, "h": 3600}[b] for a, b in pieces)
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def foundry_base_url(endpoint, path="v1"):
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or
            parsed.query or parsed.fragment):
        raise ValueError("Foundry requires an HTTPS resource endpoint without query or credentials")
    suffix = parsed.path.rstrip("/")
    if suffix not in {"", "/openai", "/openai/v1"}:
        raise ValueError("Foundry requires a resource root or /openai/v1 endpoint")
    host = parsed.netloc
    if path == "foundry_openai":
        host = host.replace(".cognitiveservices.azure.com", ".openai.azure.com")
    elif path == "foundry_cognitive":
        host = host.replace(".openai.azure.com", ".cognitiveservices.azure.com")
    return urlunsplit((parsed.scheme, host, "/openai/v1/", "", ""))


def endpoint_form(endpoint, path):
    host = urlsplit(foundry_base_url(endpoint, path)).hostname or ""
    for suffix in (".cognitiveservices.azure.com", ".openai.azure.com", ".services.ai.azure.com"):
        if host.endswith(suffix):
            return suffix
    return "custom_https_host"


def foundry_paths(endpoint):
    # Hariom's resumed-live instruction permits only the configured endpoint.
    foundry_base_url(endpoint, "v1")
    return ["v1"]


def provider_error_code(exc):
    """Expose a short provider code, never its message or arbitrary body content."""
    body = getattr(exc, "body", None)
    value = getattr(exc, "code", None)
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            value = error.get("code", value)
    value = str(value) if value is not None else ""
    return value if re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value) else None


FILTER_CATEGORIES = frozenset({
    "hate", "sexual", "violence", "self_harm", "jailbreak", "profanity",
    "protected_material_code", "protected_material_text", "indirect_attack",
    "sexual/minors", "self-harm", "violence/graphic", "hate/threatening",
})
FILTER_LABEL = re.compile(r"\bMultiSeverity_(?:Violence|Sexual|Hate|HateUnfairness|SelfHarm)Score\b")
FILTER_ERROR_CODES = frozenset({"content_filter", "contentfilter", "responsibleaipolicyviolation"})


def content_filter_failure(metadata):
    """Recognize explicit filtering; harmless category observations are not failures."""
    return (any(str(metadata.get(key, "")).casefold() in FILTER_ERROR_CODES
                for key in ("provider_error_code", "provider_innererror_code", "content_filter_code")) or
            bool(metadata.get("content_filter_labels")) or
            any(values.get(key) is True for values in metadata.get("content_filter_categories", {}).values()
                for key in ("filtered", "blocked")))


def failed_request_metadata(exc):
    """Whitelist provider codes and filter flags; never retain messages or bodies."""
    def code(value):
        return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/ -]{1,128}", value) else None

    candidates = []
    body = exc if isinstance(exc, dict) else getattr(exc, "body", None)
    if isinstance(body, dict):
        candidates.append(body)
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            body = response.json()
            if isinstance(body, dict):
                candidates.append(body)
        except (ValueError, TypeError):
            pass
    error_code, inner_code, categories = None, None, {}
    nested_codes, labels = [], set()

    def filter_error(container):
        if not isinstance(container, dict):
            return
        error = container.get("error")
        if isinstance(error, dict):
            value = code(error.get("code"))
            if value:
                nested_codes.append(value)
            message = error.get("message")
            if isinstance(message, str):
                labels.update(FILTER_LABEL.findall(message))

    def flags(container):
        if not isinstance(container, dict):
            return
        for category in FILTER_CATEGORIES:
            values = container.get(category)
            if not isinstance(values, dict):
                continue
            kept = {key: values[key] for key in ("filtered", "detected", "blocked") if type(values.get(key)) is bool}
            if isinstance(values.get("severity"), str) and values["severity"] in {"safe", "low", "medium", "high"}:
                kept["severity"] = values["severity"]
            if kept:
                categories.setdefault(category, {}).update(kept)

    def containers(node):
        if not isinstance(node, dict):
            return
        for key in ("content_filter_result", "content_filter_results", "contentFilterResult", "contentFilterResults"):
            flags(node.get(key))
            filter_error(node.get(key))
        prompt_results = node.get("prompt_filter_results")
        if isinstance(prompt_results, list):
            for item in prompt_results:
                if isinstance(item, dict):
                    for key in ("content_filter_result", "content_filter_results"):
                        flags(item.get(key))
                        filter_error(item.get(key))
                    filter_error(item)
        choices = node.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if isinstance(choice, dict):
                    for key in ("content_filter_result", "content_filter_results"):
                        flags(choice.get(key))
                        filter_error(choice.get(key))

    for body in candidates:
        error = body.get("error", body)
        if not isinstance(error, dict):
            error = body
        error_code = error_code or code(error.get("code"))
        containers(body)
        containers(error)
        if isinstance(error.get("message"), str):
            labels.update(FILTER_LABEL.findall(error["message"]))
        inner = error.get("innererror", error.get("innerError", error.get("inner_error")))
        for _ in range(4):
            if not isinstance(inner, dict):
                break
            inner_code = inner_code or code(inner.get("code"))
            containers(inner)
            if isinstance(inner.get("message"), str):
                labels.update(FILTER_LABEL.findall(inner["message"]))
            inner = inner.get("innererror", inner.get("innerError", inner.get("inner_error")))
    result = {"http_status_code": getattr(exc, "status_code", getattr(response, "status_code", None)),
            "provider_error_code": error_code or next(iter(nested_codes), None) or provider_error_code(exc),
            "provider_innererror_code": inner_code, "content_filter_categories": categories}
    filtered_code = next((value for value in nested_codes if value.casefold() in FILTER_ERROR_CODES), None)
    if filtered_code:
        result["content_filter_code"] = filtered_code
    if labels:
        result["content_filter_labels"] = sorted(labels)
    return result


def require_foundry_ping(cfg):
    """Judge stages require a successful explicit ping; dry runs never call this."""
    import json
    from .llm import LLMError
    model = cfg.models[cfg.active.judge]
    if model.provider != "azure_foundry":
        return
    roots = [cfg.output_root]
    if cfg.run_name != "dev":
        roots.append(cfg.root / "outputs/runs/dev")
    for root in roots:
        try:
            ping = json.loads((root / f"judge/ping_{cfg.active.judge}.json").read_text(encoding="utf-8"))
            state = json.loads((root / "logs/foundry_protocol.json").read_text(encoding="utf-8"))[model.provider + "/" + model.model]
            if (ping.get("status") == "ok" and ping.get("deployment") == model.model and
                    ping.get("protocol") == state and state.get("settled") and
                    state.get("response_mode") in {"text", "json_object"} and
                    state.get("token_parameter") in {"max_tokens", "max_completion_tokens"}):
                return
        except (OSError, ValueError, KeyError, TypeError):
            pass
    raise LLMError("successful Foundry judge-shape ping required before judging")
