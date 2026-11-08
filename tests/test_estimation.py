from __future__ import annotations

import pytest

from promo_finder.budget import observe
from promo_finder.estimation import estimate_50


def saved_pilot():
    rows = {}
    for part, provider, calls in (("characters", "azure", 2), ("header", "azure", 1), ("reveals", "azure", 5),
                                 ("moments", "azure", 5), ("answer_key", "azure", 5), ("baseline", "azure", 5),
                                 ("cold_judge", "groq", 30), ("fidelity", "groq", 20)):
        rows[part+":"+provider] = {"calls": calls, "http_requests": calls, "input_tokens": calls*100,
                                  "output_tokens": calls*20, "request_elapsed_s": calls*2}
    return {"run": "pilot", "status": "complete", "episodes": [9,10,15,16,17],
            "plan": {"parts": {"characters": {"calls": 2}}}, "llm": {"parts": rows}}


def test_fifty_episode_scale_with_chunks_and_late_builder_drop(p07_cfg):
    observe(p07_cfg, {"x-ratelimit-remaining-requests": "1000"})
    result = estimate_50(p07_cfg, saved_pilot(), {"kept": 20})
    assert result["character_chunks"] == 13 and result["builder_eligible_episodes"] == 45
    assert result["builder_kept_estimate"] == 180 and result["groq_calls"] == 450
    assert result["groq_time_s"] == 900 and result["fits_one_day"] is True
    assert result["parts"]["baseline:azure"]["calls"] == 50
    assert result["parts"]["answer_key:azure"]["calls"] == 45
    assert result["parts"]["characters:azure"]["calls"] == 13
    assert result["parts"]["characters:azure"]["input_tokens"] == 2000
    assert result["parts"]["characters:azure"]["output_tokens"] == 260
    assert result["parts"]["header:azure"]["calls"] == 1
    assert result["required_remaining_requests"] == 540 and result["azure_usd"] > 0


def test_estimate_proposes_two_ranges_when_insufficient(p07_cfg):
    observe(p07_cfg, {"x-ratelimit-remaining-requests": "350"})
    result = estimate_50(p07_cfg, saved_pilot(), {"kept": 20})
    assert result["fits_one_day"] is False
    assert [(r["episode_range"], r["groq_calls"]) for r in result["two_day_split_if_needed"]] == [([1,25],250), ([26,50],200)]


def test_estimate_needs_complete_pilot_and_no_claim_without_header(p07_cfg):
    pilot = saved_pilot()
    assert estimate_50(p07_cfg, pilot, {"kept": 0})["fits_one_day"] is None
    pilot["status"] = "failed"
    with pytest.raises(Exception, match="complete"): estimate_50(p07_cfg, pilot, {"kept": 0})
