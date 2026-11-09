"""Open tabs, quota fallback, upload and temp-storage checks; no network."""
import importlib.util
from pathlib import Path

import pytest

from promo_finder import demo

spec = importlib.util.spec_from_file_location("streamlit_demo_app", Path(__file__).resolve().parents[1] / "app/streamlit_app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
UPLOAD = ("episode-023-Episode 23.txt", b"invented fixture")


class FakeStreamlit:
    def __init__(self, configured=True, uploads=None, submit=False):
        self.secrets = {"GROQ_API_KEY": "invented-key"} if configured else {}
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


@pytest.mark.parametrize("configured", [True, False])
def test_both_tabs_open_without_authentication(configured, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    st = FakeStreamlit(configured=configured)
    rendered = []
    monkeypatch.setattr(app, "full_results", lambda st: rendered.append("full"))
    monkeypatch.setattr(app, "run_uploads", lambda *a: pytest.fail("processing without submission"))
    app.main(st)
    assert rendered == ["full"] and st.upload_calls == (1 if configured else 0)
    assert st.tab_labels == ["Full results (Azure run)", "Try it live (free)"]
    if not configured:
        assert st.infos == [demo.FREE_TIER_MESSAGE] and st.errors == []


def test_app_rejects_four_before_reading_uploads(monkeypatch):
    st = FakeStreamlit(uploads=[object()] * 4)
    monkeypatch.setattr(app, "full_results", lambda st: None)
    monkeypatch.setattr(app, "run_uploads", lambda *a: pytest.fail("processing over cap"))
    app.main(st)
    assert st.errors == ["Upload at most three episodes."]


def test_both_tabs_are_wired_and_saved_results_need_no_groq_key(monkeypatch):
    st = FakeStreamlit()
    st.secrets.pop("GROQ_API_KEY")
    seen = []
    monkeypatch.setattr(app, "full_results", lambda st: seen.append("full"))
    monkeypatch.setattr(app, "live_demo", lambda st: seen.append("live"))
    app.main(st)
    assert st.tab_labels == ["Full results (Azure run)", "Try it live (free)"]
    assert seen == ["full", "live"]


@pytest.mark.parametrize("kind", ["rate_limited", "daily_limit", "wrapped_429", "sdk_429", "provider_quota"])
def test_quota_failure_shows_friendly_message_and_cleans_temp(kind, monkeypatch, tmp_path):
    import httpx
    import openai
    from promo_finder.budget import DailyBudgetRefused
    from promo_finder.llm import ProviderError, RateLimited
    failures = {"rate_limited": RateLimited("invented-private-detail"),
                "daily_limit": DailyBudgetRefused("invented-private-detail"),
                "wrapped_429": ProviderError("HTTP 429: invented-private-detail"),
                "sdk_429": openai.RateLimitError("invented-private-detail", body=None,
                    response=httpx.Response(429, request=httpx.Request("POST", "https://invented.invalid"))),
                "provider_quota": ProviderError("quota exhausted: invented-private-detail")}

    class Upload:
        name = UPLOAD[0]
        def getvalue(self): return UPLOAD[1]

    roots = []
    def runner(cfg, key):
        roots.append(cfg.root)
        raise failures[kind]

    monkeypatch.setattr(app, "full_results", lambda st: None)
    monkeypatch.setattr(app, "run_uploads", lambda entries, key:
                        demo.run_uploads(entries, key, runner=runner, temp_parent=tmp_path))
    st = FakeStreamlit(uploads=[Upload()], submit=True)
    app.main(st)
    assert st.infos == [demo.FREE_TIER_MESSAGE] and st.errors == []
    assert st.status_updates[-1]["state"] == "error"
    assert roots and not roots[0].exists() and not list(tmp_path.iterdir())
    assert "promo_result" not in st.session_state


def test_missing_key_helper_returns_friendly_message_without_temp_files(tmp_path):
    with pytest.raises(demo.FreeTierUnavailable) as error:
        demo.run_uploads([UPLOAD], "", runner=lambda *a: pytest.fail("missing-key request"), temp_parent=tmp_path)
    assert str(error.value) == demo.FREE_TIER_MESSAGE
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("uploads", [[], [UPLOAD] * 4, [("../episode-023-Episode 23.txt", b"invented")],
                                    [UPLOAD, UPLOAD], [("episode-000-Episode 24.txt", b"invented")],
                                    [(UPLOAD[0], b"\xff")], [(UPLOAD[0], b"")]])
def test_invalid_uploads_never_invoke_pipeline(uploads, tmp_path):
    with pytest.raises(demo.DemoError):
        demo.run_uploads(uploads, "invented-key", runner=lambda *a: pytest.fail("pipeline"), temp_parent=tmp_path)
    assert not list(tmp_path.iterdir())


def test_input_pack_source_id_can_differ_from_episode_number():
    demo.validate_uploads([("episode-023-Episode 9000023.txt", b"invented fixture")])


@pytest.mark.parametrize("fails", [False, True])
def test_temporary_tree_cleanup_and_secret_isolation(tmp_path, monkeypatch, fails):
    roots = []
    monkeypatch.setattr("promo_finder.config.load_secrets", lambda *a: pytest.fail("dotenv"))

    def runner(cfg, key):
        roots.append(cfg.root)
        assert cfg.root.parent == tmp_path and cfg.data_dir.parent == cfg.root
        assert cfg.free_demo and key == "invented-key"
        assert cfg.understanding.character_chunk_episodes == 1
        assert cfg.purposes["answer_key"].max_completion_tokens == 4500
        assert not (cfg.root / ".env").exists()
        cache = cfg.output_root / ".llm_cache"
        cache.mkdir(parents=True)
        (cache / "invented.json").write_text("invented transient")
        if fails:
            raise RuntimeError("invented-private-error")
        return [{"episode": 23, "score": 1}]

    if fails:
        with pytest.raises(demo.DemoError) as error:
            demo.run_uploads([UPLOAD], "invented-key", runner=runner, temp_parent=tmp_path)
        assert "invented-private-error" not in str(error.value)
    else:
        assert demo.run_uploads([UPLOAD], "invented-key", runner=runner, temp_parent=tmp_path)[0]["episode"] == 23
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
