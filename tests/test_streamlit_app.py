"""Passcode, upload and temporary-storage checks; no Streamlit server or network."""
import importlib.util
from pathlib import Path

import pytest

from promo_finder import demo

spec = importlib.util.spec_from_file_location("streamlit_demo_app", Path(__file__).resolve().parents[1] / "app/streamlit_app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
UPLOAD = ("episode-023-Episode 23.txt", b"invented fixture")


@pytest.mark.parametrize("provided,expected,ok", [("invented", "invented", True), ("wrong", "invented", False),
                                                  ("", "", False), (None, "invented", False), ("é", "é", True)])
def test_passcode_comparison(provided, expected, ok):
    assert demo.authorized(provided, expected) is ok


class FakeStreamlit:
    def __init__(self, passcode="wrong", configured=True, uploads=None):
        self.secrets = {"APP_PASSCODE": "invented-passcode", "GROQ_API_KEY": "invented-key"} if configured else {}
        self.passcode, self.uploads = passcode, uploads
        self.upload_calls = 0
        self.errors = []
        self.session_state = {}
        self.tab_labels = None

    def set_page_config(self, **kwargs): pass
    def title(self, *args): pass
    def caption(self, *args): pass
    def info(self, *args): pass
    def write(self, *args): pass
    def error(self, text): self.errors.append(text)
    def text_input(self, *args, **kwargs): return self.passcode
    def tabs(self, labels):
        from contextlib import nullcontext
        self.tab_labels = labels
        return [nullcontext(), nullcontext()]
    def file_uploader(self, *args, **kwargs):
        self.upload_calls += 1
        return self.uploads


@pytest.mark.parametrize("configured", [True, False])
def test_gate_blocks_upload_and_processing(configured, monkeypatch):
    st = FakeStreamlit(configured=configured)
    monkeypatch.setattr(app, "run_uploads", lambda *a: pytest.fail("processing before gate"))
    app.main(st)
    assert st.upload_calls == 0


def test_app_rejects_four_before_reading_uploads(monkeypatch):
    st = FakeStreamlit(passcode="invented-passcode", uploads=[object()] * 4)
    monkeypatch.setattr(app, "full_results", lambda st: None)
    monkeypatch.setattr(app, "run_uploads", lambda *a: pytest.fail("processing over cap"))
    app.main(st)
    assert st.errors == ["Upload at most three episodes."]


def test_both_tabs_are_wired_and_saved_results_need_no_groq_key(monkeypatch):
    st = FakeStreamlit(passcode="invented-passcode")
    st.secrets.pop("GROQ_API_KEY")
    seen = []
    monkeypatch.setattr(app, "full_results", lambda st: seen.append("full"))
    monkeypatch.setattr(app, "live_demo", lambda st: seen.append("live"))
    app.main(st)
    assert st.tab_labels == ["Full results (Azure run)", "Try it live (free)"]
    assert seen == ["full", "live"]


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
