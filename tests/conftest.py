from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from promo_finder.models import Episode, Line, Scene, line_id

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def pytest_configure(config):
    # keep every temp file inside the project (git-ignored .cache/)
    if not config.option.basetemp:
        config.option.basetemp = str(ROOT / ".cache" / "pytest-tmp")


@pytest.fixture(autouse=True)
def _no_real_secrets(monkeypatch, tmp_path):
    """Unit tests must never load the real secrets file."""
    monkeypatch.setenv("KUKU_SECRETS_FILE", str(tmp_path / "no-such-secrets.env"))


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


def make_episode(ep: int, spans: list[tuple[int, int]], kind: str = "dialogue") -> Episode:
    """Build an in-memory episode with lines at exact millisecond times (invented)."""
    lines = [
        Line(id=line_id(ep, i), ep=ep, idx=i, scene=1, kind=kind,
             speaker="TEST SPEAKER" if kind == "dialogue" else None,
             text=f"invented line {i}", start_ms=s, end_ms=e, src_line=i)
        for i, (s, e) in enumerate(spans, 1)
    ]
    sc = Scene(number=1, heading="TEST", start_ms=0, end_ms=max(e for _, e in spans),
               line_ids=[x.id for x in lines])
    return Episode(ep=ep, source_file=f"episode-{ep:03d}-Episode 0.txt", source_id="0",
                   header_ep=ep, scenes=[sc], lines=lines, duration_ms=sc.end_ms)


@pytest.fixture
def episode_factory():
    return make_episode


CONFIG_TEMPLATE = textwrap.dedent(
    """
    data_dir: "data"
    secrets_file: ".env"
    max_calls_per_run: {max_calls}
    promo: {{ min_s: 20, max_s: 60, max_segments: 3 }}
    active: {{ picker: {picker}, judge: {judge} }}
    models:
      fake_a: {{ provider: fakeprov, model: "fake-a", family: openai,
                 params: {{ reasoning_effort: minimal, max_completion_tokens: 1000, include_reasoning: false, temperature: 0.5 }} }}
      fake_b: {{ provider: fakeprov, model: "fake-b", family: alibaba, params: {{ max_completion_tokens: 10000 }} }}
      fake_az: {{ provider: fakeazure, model: "mini", family: openai, params: {{ max_completion_tokens: 500 }} }}
      fake_tbd: {{ provider: fakeprov, model: "TBD", family: "TBD", params: {{}} }}
    providers:
      fakeprov:  {{ base_url: "https://fake.invalid/v1", key_env: FAKE_API_KEY, rpm: 1000 }}
      fakeazure: {{ endpoint_env: FAKE_AZURE_ENDPOINT, key_env: FAKE_AZURE_KEY, mode: v1,
                    fallback_api_version: "2025-04-01-preview" }}
    """
)


@pytest.fixture
def write_config(tmp_path):
    def _write(picker="fake_a", judge="fake_b", max_calls=50) -> Path:
        p = tmp_path / "config.yaml"
        p.write_text(CONFIG_TEMPLATE.format(picker=picker, judge=judge, max_calls=max_calls), encoding="utf-8")
        return p

    return _write
