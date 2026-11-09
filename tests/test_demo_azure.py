"""D106 a: the live tab runs the official Azure models, keys stay in memory, a hard daily cap applies.

Invented inputs and fake providers only; sockets are blocked.
"""
import datetime as dt
import hashlib
import json
import os
import socket
from pathlib import Path

import openai
import pytest

from promo_finder import builder, demo, llm, pipeline
from promo_finder.config import load_config, required_key_names
from promo_finder.judging import check_family
from test_llm import FakeClock
from test_pipeline import UnifiedProvider

ROOT = Path(__file__).resolve().parents[1]
SECRETS = {"AZURE_OPENAI_API_KEY": "invented-azure-key", "AZURE_OPENAI_ENDPOINT": "https://invented.openai.azure.com/",
           "AZURE_FOUNDRY_API_KEY": "invented-foundry-key", "AZURE_FOUNDRY_ENDPOINT": "https://invented.cognitiveservices.azure.com/"}
UPLOAD_NAME = "episode-023-Episode 9000023.txt"


@pytest.fixture(autouse=True)
def no_network_and_clean_environment(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network forbidden"))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network forbidden"))
    for name in SECRETS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(demo, "DAILY_CAP", demo.DailyCap())


def episode_bytes(lines=8, seconds=5):
    """Invented timestamped episode in the input-pack format."""
    out = ["EPISODE NUMBER: Episode 23", "EPISODE LOGLINE: invented.", "CONTINUITY NOTES: invented.", "",
           "--- SCRIPT START ---", "", "SCENE 01", "Scene heading: INT. TEST ROOM – DAY", "Scene start: 00:00.00",
           f"Scene end: 00:{lines * seconds:02d}.00", "", "Actions and dialogue:", ""]
    for i in range(lines):
        out += ["**TEST SPEAKER (Calm):**", f"Start: (00:{i * seconds:02d}.00) | End: (00:{(i + 1) * seconds:02d}.00)",
                f"invented line {i + 1}", ""]
    out.append("--- SCRIPT END ---")
    return "\n".join(out).encode("utf-8")


@pytest.fixture
def fake_azure(monkeypatch):
    """Both Azure providers resolve to one fake; records the client arguments the factory was given."""
    provider = UnifiedProvider()
    created = []
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: (created.append(kwargs), provider)[1])
    clock = FakeClock()
    monkeypatch.setitem(llm.LLMClient.__init__.__kwdefaults__, "clock", clock)
    monkeypatch.setitem(llm.LLMClient.__init__.__kwdefaults__, "sleep", clock.sleep)
    monkeypatch.setattr(builder, "previous_episode", lambda *a: None)
    return provider, created


# ------------------------------------------------------------------ daily cap
def test_daily_cap_is_thirty_episodes_and_refuses_what_does_not_fit():
    cap = demo.DailyCap()
    assert demo.DAILY_EPISODE_CAP == 30 and cap.limit == 30 and cap.remaining == 30
    assert all(cap.reserve(3) for _ in range(9)) and cap.remaining == 3
    assert not cap.reserve(4) and cap.remaining == 3      # a refusal takes nothing
    assert cap.reserve(3) and cap.remaining == 0
    assert not cap.reserve(1)


def test_daily_cap_resets_at_the_utc_day_boundary():
    now = [dt.datetime(2026, 1, 1, 23, 59, tzinfo=dt.timezone.utc)]
    cap = demo.DailyCap(clock=lambda: now[0])
    assert cap.reserve(30) and not cap.reserve(1)
    now[0] = dt.datetime(2026, 1, 2, 0, 1, tzinfo=dt.timezone.utc)
    assert cap.remaining == 30 and cap.reserve(30)


def test_daily_cap_uses_utc_not_the_local_offset():
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    now = [dt.datetime(2026, 1, 2, 4, 0, tzinfo=ist)]      # still 1 Jan 22:30 UTC
    cap = demo.DailyCap(clock=lambda: now[0])
    assert cap.reserve(30)
    now[0] = dt.datetime(2026, 1, 2, 6, 0, tzinfo=ist)     # 2 Jan 00:30 UTC
    assert cap.remaining == 30


def test_cap_is_enforced_by_run_uploads_with_the_exact_message(tmp_path):
    demo.DAILY_CAP.reserve(28)
    entries = [(f"episode-{n:03d}-Episode {n}.txt", b"invented fixture") for n in (23, 24, 25)]
    with pytest.raises(demo.DailyCapReached) as error:
        demo.run_uploads(entries, SECRETS, runner=lambda *a: pytest.fail("ran over the cap"), temp_parent=tmp_path)
    assert str(error.value) == "daily demo cap reached; full results are in Tab 1"
    assert isinstance(error.value, demo.DemoNotice) and not list(tmp_path.iterdir())
    assert demo.DAILY_CAP.remaining == 2                    # nothing was taken by the refusal
    assert demo.run_uploads(entries[:2], SECRETS, runner=lambda cfg, secrets: ["ok"], temp_parent=tmp_path) == ["ok"]
    assert demo.DAILY_CAP.remaining == 0
    with pytest.raises(demo.DailyCapReached):
        demo.run_uploads(entries[:1], SECRETS, runner=lambda *a: pytest.fail("ran at zero"), temp_parent=tmp_path)


def test_failed_run_still_counts_against_the_cap(tmp_path):
    def runner(cfg, secrets):
        raise RuntimeError("invented-private-error")
    with pytest.raises(demo.DemoError):
        demo.run_uploads([("episode-023-Episode 23.txt", b"invented fixture")], SECRETS, runner=runner, temp_parent=tmp_path)
    assert demo.DAILY_CAP.remaining == 29


def test_app_shows_cap_message_instead_of_the_uploader_when_exhausted():
    from test_streamlit_app import FakeStreamlit, app
    demo.DAILY_CAP.reserve(30)
    st = FakeStreamlit()
    app.live_demo(st)
    assert st.infos == [demo.DAILY_CAP_MESSAGE] and st.upload_calls == 0 and st.errors == []


def test_app_turns_a_cap_refusal_at_click_time_into_a_friendly_note(monkeypatch):
    from test_streamlit_app import FakeStreamlit, Upload, app
    demo.DAILY_CAP.reserve(29)                              # one episode left, two uploaded
    second = type("Second", (), {"name": "episode-024-Episode 24.txt", "getvalue": lambda self: b"invented fixture"})()
    st = FakeStreamlit(uploads=[Upload(), second], submit=True)
    app.live_demo(st)
    assert st.infos == [demo.DAILY_CAP_MESSAGE] and st.errors == []
    assert st.status_updates[-1]["state"] == "error" and "promo_result" not in st.session_state


# ------------------------------------------------------------------ keys
def test_missing_key_names_are_listed_without_values(tmp_path):
    partial = dict(SECRETS, AZURE_FOUNDRY_API_KEY="  ", AZURE_OPENAI_ENDPOINT=None)
    assert demo.missing_secrets(partial) == ["AZURE_OPENAI_ENDPOINT", "AZURE_FOUNDRY_API_KEY"]
    with pytest.raises(demo.NotConfigured) as error:
        demo.run_uploads([("episode-023-Episode 23.txt", b"invented fixture")], partial, runner=lambda *a: pytest.fail("ran"), temp_parent=tmp_path)
    assert str(error.value) == ("live demo is not configured (missing secrets: AZURE_OPENAI_ENDPOINT, AZURE_FOUNDRY_API_KEY); "
                                "full results are in Tab 1")
    assert not any(value in str(error.value) for value in SECRETS.values())


def test_client_factory_reads_the_given_mapping_not_the_process_environment(monkeypatch):
    for name in SECRETS:
        monkeypatch.setenv(name, "environment-value-that-must-not-be-used")
    created = []
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: created.append(kwargs))
    cfg = load_config()
    llm.default_client_factory("azure", cfg.providers["azure"], "v1", env=SECRETS)
    llm.default_client_factory("azure_foundry", cfg.providers["azure_foundry"], "v1", env=SECRETS)
    assert [c["api_key"] for c in created] == ["invented-azure-key", "invented-foundry-key"]
    assert [c["base_url"] for c in created] == ["https://invented.openai.azure.com/openai/v1/",
                                                "https://invented.cognitiveservices.azure.com/openai/v1/"]
    with pytest.raises(llm.MissingKey, match="AZURE_FOUNDRY_ENDPOINT"):
        llm.default_client_factory("azure_foundry", cfg.providers["azure_foundry"], "v1", env={"AZURE_FOUNDRY_API_KEY": "invented-key"})
    # Default behaviour is unchanged: no mapping means the process environment.
    llm.default_client_factory("azure", cfg.providers["azure"], "v1")
    assert created[-1]["api_key"] == "environment-value-that-must-not-be-used"


# ------------------------------------------------------------------ configuration
def test_demo_uses_the_official_config_and_roles_unchanged(tmp_path):
    before = hashlib.sha256((ROOT / "config.yaml").read_bytes()).hexdigest()
    official = load_config()
    cfg = demo.prepare(tmp_path, [(UPLOAD_NAME, episode_bytes())])
    check_family(cfg)
    assert (cfg.active.picker, cfg.active.judge) == ("azure_mini", "azure_llama") == (official.active.picker, official.active.judge)
    assert (cfg.models[cfg.active.picker].family, cfg.models[cfg.active.judge].family) == ("openai", "meta")
    assert cfg._overlay_path is None and not cfg.free_demo and cfg.baseline_skipped
    a, b = official.model_dump(), cfg.model_dump()
    a.pop("data_dir"), b.pop("data_dir")
    assert a == b                                           # only the data folder differs from the official config
    assert not official.baseline_skipped and not official.free_demo
    assert pipeline.stage_order(official) == pipeline.ORDER and "baseline" not in pipeline.stage_order(cfg)
    assert hashlib.sha256((ROOT / "config.yaml").read_bytes()).hexdigest() == before
    assert not (tmp_path / "config/free.yaml").exists() and not (tmp_path / ".env").exists()


def test_free_config_and_cli_path_are_untouched():
    free = load_config(overlay="config/free.yaml")
    assert free.free_demo and free.baseline_skipped
    assert (free.active.picker, free.active.judge) == ("groq_oss", "groq_qwen")
    assert required_key_names(free) == ["GROQ_API_KEY"]


def test_dry_run_plans_azure_calls_only_and_skips_the_baseline(tmp_path):
    from conftest import make_episode
    cfg = demo.prepare(tmp_path, [(f"episode-{n:03d}-Episode {n}.txt", b"invented fixture") for n in (23, 24)])
    plan = pipeline.dry_run(cfg, [make_episode(n, [(i * 5000, (i + 1) * 5000) for i in range(8)]) for n in (23, 24)], allow_held_out=True)
    assert "baseline" not in plan["parts"] and "baseline" not in plan["order"]
    assert set(plan["providers"]) <= {"azure", "azure_foundry", "code"} and "groq" not in plan["providers"]
    assert plan["planned_calls"] > 0 and plan["max_calls_per_run"] >= plan["planned_calls"]
    assert not cfg.output_root.exists()


# ------------------------------------------------------------------ end to end, fake providers
def test_execute_runs_the_whole_pipeline_on_azure_with_keys_from_the_mapping(tmp_path, fake_azure):
    provider, created = fake_azure
    cfg = demo.prepare(tmp_path, [(UPLOAD_NAME, episode_bytes())])
    rows = demo.execute(cfg, SECRETS)
    assert rows and rows[0]["episode"] == 23 and {"start–end", "hook_type", "cliff_type", "why", "lane", "score"} <= rows[0].keys()
    # Client arguments came from the mapping; the process environment was never touched.
    assert {c["api_key"] for c in created} == {"invented-azure-key", "invented-foundry-key"}
    assert not any(name in os.environ for name in SECRETS)
    models = [c["model"] for c in provider.calls]
    assert models[0] == "llama70" and "mini" in models      # judge-shape ping first, then the picker
    assert not any('"promos"' in json.dumps(c["response_format"]) for c in provider.calls)   # no baseline call
    manifest = json.loads((cfg.output_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete" and "baseline" not in manifest["stages"]
    assert (cfg.output_root / "judge/ping_azure_llama.json").is_file()
    assert manifest["max_calls_per_run"] > 0 and not list((cfg.output_root / "baseline").glob("baseline_E*.json"))


def test_run_uploads_end_to_end_cleans_up_and_spends_the_cap(tmp_path, fake_azure):
    rows = demo.run_uploads([(UPLOAD_NAME, episode_bytes())], SECRETS, temp_parent=tmp_path)
    assert rows and rows[0]["episode"] == 23
    assert not list(tmp_path.iterdir())                      # input, outputs, cache and logs are gone
    assert demo.DAILY_CAP.remaining == demo.DAILY_EPISODE_CAP - 1


def test_a_rate_limited_azure_run_becomes_the_friendly_note_and_leaves_nothing(tmp_path, monkeypatch, fake_azure):
    import httpx
    provider, _ = fake_azure
    request = httpx.Request("POST", "https://invented.invalid/openai/v1/chat/completions")
    def refuse(**kwargs):
        raise openai.RateLimitError("invented-private-detail", response=httpx.Response(429, request=request), body=None)
    monkeypatch.setattr(provider.chat.completions, "create", refuse)
    with pytest.raises(demo.ProviderUnavailable) as error:
        demo.run_uploads([(UPLOAD_NAME, episode_bytes())], SECRETS, temp_parent=tmp_path)
    assert str(error.value) == demo.UNAVAILABLE_MESSAGE and not list(tmp_path.iterdir())
