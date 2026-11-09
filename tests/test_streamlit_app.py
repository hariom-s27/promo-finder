"""Open tabs, Azure live tab, daily cap, upload and temp-storage checks; no network."""
import importlib.util
import socket
from pathlib import Path

import pytest

from promo_finder import demo

spec = importlib.util.spec_from_file_location("streamlit_demo_app", Path(__file__).resolve().parents[1] / "app/streamlit_app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
REAL_RUN_UPLOADS = demo.run_uploads  # captured before any test patches the module attribute
UPLOAD = ("episode-023-Episode 23.txt", b"invented fixture")
SECRETS = {name: "invented-" + name.lower() for name in demo.SECRET_NAMES}
TABS = ["Full results (Azure run)", "Try it live"]


@pytest.fixture(autouse=True)
def no_network_and_fresh_cap(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network forbidden"))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network forbidden"))
    for name in demo.SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(demo, "DAILY_CAP", demo.DailyCap())


class FakeStreamlit:
    def __init__(self, configured=True, uploads=None, submit=False):
        self.secrets = dict(SECRETS) if configured else {}
        self.uploads, self.submit = uploads, submit
        self.upload_calls = 0
        self.errors = []
        self.infos = []
        self.status_updates = []
        self.session_state = {}
        self.tab_labels = None

    def set_page_config(self, **kwargs): pass
    def title(self, *args): pass
    def caption(self, *args): pass
    def info(self, message): self.infos.append(message)
    def write(self, *args): pass
    def error(self, text): self.errors.append(text)
    def text_input(self, *args, **kwargs):
        pytest.fail("unexpected authentication widget")
    def tabs(self, labels):
        from contextlib import nullcontext
        self.tab_labels = labels
        return [nullcontext(), nullcontext()]
    def file_uploader(self, *args, **kwargs):
        self.upload_calls += 1
        return self.uploads
    def button(self, *args, **kwargs): return self.submit
    def status(self, *args, **kwargs): return self
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def update(self, **kwargs): self.status_updates.append(kwargs)


class Upload:
    name = UPLOAD[0]
    def getvalue(self): return UPLOAD[1]


@pytest.mark.parametrize("configured", [True, False])
def test_both_tabs_open_without_authentication(configured, monkeypatch):
    st = FakeStreamlit(configured=configured)
    rendered = []
    monkeypatch.setattr(app, "full_results", lambda st: rendered.append("full"))
    monkeypatch.setattr(demo, "run_uploads", lambda *a, **k: pytest.fail("processing without submission"))
    app.main(st)
    assert rendered == ["full"] and st.upload_calls == (1 if configured else 0)
    assert st.tab_labels == TABS
    if not configured:
        # Friendly note naming the missing secret NAMES only; never an error box.
        assert len(st.infos) == 1 and st.errors == []
        assert all(name in st.infos[0] for name in demo.SECRET_NAMES) and "Tab 1" in st.infos[0]


@pytest.mark.parametrize("missing", demo.SECRET_NAMES)
def test_any_missing_key_gives_friendly_message_and_no_upload_widget(missing, monkeypatch):
    st = FakeStreamlit()
    st.secrets.pop(missing)
    monkeypatch.setattr(app, "full_results", lambda st: None)
    monkeypatch.setattr(demo, "run_uploads", lambda *a, **k: pytest.fail("processing without keys"))
    app.main(st)
    assert st.upload_calls == 0 and st.errors == []
    assert st.infos == [f"live demo is not configured (missing secrets: {missing}); full results are in Tab 1"]
    assert not any(value in st.infos[0] for value in SECRETS.values())


def test_keys_may_come_from_the_environment(monkeypatch):
    st = FakeStreamlit(configured=False)
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(app, "full_results", lambda st: None)
    app.main(st)
    assert st.upload_calls == 1 and st.infos == []


def test_app_rejects_four_before_reading_uploads(monkeypatch):
    st = FakeStreamlit(uploads=[object()] * 4)
    monkeypatch.setattr(app, "full_results", lambda st: None)
    monkeypatch.setattr(demo, "run_uploads", lambda *a, **k: pytest.fail("processing over cap"))
    app.main(st)
    assert st.errors == ["Upload at most three episodes."]


def test_both_tabs_are_wired_and_saved_results_need_no_keys(monkeypatch):
    st = FakeStreamlit(configured=False)
    seen = []
    monkeypatch.setattr(app, "full_results", lambda st: seen.append("full"))
    monkeypatch.setattr(app, "live_demo", lambda st: seen.append("live"))
    app.main(st)
    assert st.tab_labels == TABS and seen == ["full", "live"]


@pytest.mark.parametrize("kind", ["rate_limited", "wrapped_429", "sdk_429", "provider_quota", "azure_tpm"])
def test_quota_failure_shows_friendly_message_and_cleans_temp(kind, monkeypatch, tmp_path):
    import httpx
    import openai
    from promo_finder.llm import ProviderError, RateLimited
    failures = {"rate_limited": RateLimited("invented-private-detail"),
                "wrapped_429": ProviderError("HTTP 429: invented-private-detail"),
                "sdk_429": openai.RateLimitError("invented-private-detail", body=None,
                    response=httpx.Response(429, request=httpx.Request("POST", "https://invented.invalid"))),
                "provider_quota": ProviderError("quota exhausted: invented-private-detail"),
                "azure_tpm": ProviderError("request exceeds judge TPM: invented-private-detail")}

    roots = []
    def runner(cfg, secrets):
        roots.append(cfg.root)
        raise failures[kind]

    monkeypatch.setattr(app, "full_results", lambda st: None)
    monkeypatch.setattr(demo, "run_uploads", lambda entries, secrets:
                        REAL_RUN_UPLOADS(entries, secrets, runner=runner, temp_parent=tmp_path))
    st = FakeStreamlit(uploads=[Upload()], submit=True)
    app.main(st)
    assert st.infos == [demo.UNAVAILABLE_MESSAGE] and st.errors == []
    assert st.status_updates[-1]["state"] == "error"
    assert roots and not roots[0].exists() and not list(tmp_path.iterdir())
    assert "promo_result" not in st.session_state


def test_missing_keys_helper_returns_friendly_message_without_temp_files_or_cap_use(tmp_path):
    with pytest.raises(demo.NotConfigured) as error:
        demo.run_uploads([UPLOAD], {}, runner=lambda *a: pytest.fail("missing-key request"), temp_parent=tmp_path)
    assert "missing secrets: " + ", ".join(demo.SECRET_NAMES) in str(error.value) and "Tab 1" in str(error.value)
    assert not list(tmp_path.iterdir()) and demo.DAILY_CAP.remaining == demo.DAILY_EPISODE_CAP


@pytest.mark.parametrize("uploads", [[], [UPLOAD] * 4, [("../episode-023-Episode 23.txt", b"invented")],
                                    [UPLOAD, UPLOAD], [("episode-000-Episode 24.txt", b"invented")],
                                    [(UPLOAD[0], b"\xff")], [(UPLOAD[0], b"")]])
def test_invalid_uploads_never_invoke_pipeline_or_spend_cap(uploads, tmp_path):
    with pytest.raises(demo.DemoError):
        demo.run_uploads(uploads, SECRETS, runner=lambda *a: pytest.fail("pipeline"), temp_parent=tmp_path)
    assert not list(tmp_path.iterdir()) and demo.DAILY_CAP.remaining == demo.DAILY_EPISODE_CAP


def test_input_pack_source_id_can_differ_from_episode_number():
    demo.validate_uploads([("episode-023-Episode 9000023.txt", b"invented fixture")])


@pytest.mark.parametrize("fails", [False, True])
def test_temporary_tree_cleanup_and_secret_isolation(tmp_path, monkeypatch, fails):
    roots = []
    monkeypatch.setattr("promo_finder.config.load_secrets", lambda *a: pytest.fail("dotenv"))

    def runner(cfg, secrets):
        roots.append(cfg.root)
        assert cfg.root.parent == tmp_path and cfg.data_dir.parent == cfg.root
        # D106 a: official Azure roles, official settings, baseline skipped, no free overlay.
        assert (cfg.active.picker, cfg.active.judge) == ("azure_mini", "azure_llama")
        assert cfg.baseline_skipped and not cfg.free_demo and cfg._overlay_path is None
        assert cfg.understanding.character_chunk_episodes == 4
        assert cfg.purposes["answer_key"].max_completion_tokens == 6000
        assert secrets == SECRETS
        assert not (cfg.root / ".env").exists()
        cache = cfg.output_root / ".llm_cache"
        cache.mkdir(parents=True)
        (cache / "invented.json").write_text("invented transient")
        if fails:
            raise RuntimeError("invented-private-error")
        return [{"episode": 23, "score": 1}]

    if fails:
        with pytest.raises(demo.DemoError) as error:
            demo.run_uploads([UPLOAD], SECRETS, runner=runner, temp_parent=tmp_path)
        assert "invented-private-error" not in str(error.value)
        assert not isinstance(error.value, demo.DemoNotice)
    else:
        assert demo.run_uploads([UPLOAD], SECRETS, runner=runner, temp_parent=tmp_path)[0]["episode"] == 23
    assert roots and not roots[0].exists() and not list(tmp_path.iterdir())


def test_guard_blocks_real_streamlit_secrets_without_opening(tmp_path, monkeypatch, capsys):
    from test_guard import guard
    data = tmp_path / "input"
    data.mkdir()
    monkeypatch.setattr(guard, "in_git_repo", lambda *a: True)
    monkeypatch.setattr(guard, "staged_files", lambda *a: [".streamlit/secrets.toml"])
    monkeypatch.setattr(guard, "read_staged", lambda *a: pytest.fail("opened secrets"))
    assert guard.main(["--root", str(tmp_path), "--data-dir", str(data)]) == 1
    assert ".streamlit/secrets.toml" in capsys.readouterr().out
    assert guard.path_problems([".streamlit/secrets.toml.example"]) == []


def test_all_file_guard_skips_streamlit_secrets(tmp_path, monkeypatch):
    from test_guard import guard
    data = tmp_path / "input"
    data.mkdir()
    monkeypatch.setattr(guard, "walk_files", lambda *a: [".streamlit/secrets.toml"])
    assert guard.main(["--all", "--root", str(tmp_path), "--data-dir", str(data)]) == 0


def test_secrets_example_lists_only_the_four_azure_names():
    text = (Path(__file__).resolve().parents[1] / ".streamlit/secrets.toml.example").read_text(encoding="utf-8")
    body = [line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("# ") and line.lstrip("# ").strip() in demo.SECRET_NAMES]
    assert body == list(demo.SECRET_NAMES)
    assert "=" not in text and "GROQ" not in text
