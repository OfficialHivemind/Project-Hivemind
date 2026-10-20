"""selftest's models check: every .npz model the vision code names ships and
loads, so an installer that leaves one out fails its build (the lead,
2026-10-27: token_types, bufficons, sprinkler)."""
from __future__ import annotations

import pytest

from hivemind import datapaths, selftest


def test_the_models_the_lead_named_are_found_in_the_code():
    assert {"token_types.npz", "bufficons.npz", "sprinkler.npz"} <= set(selftest.model_names())
    assert ("models", selftest._models) in selftest.CHECKS


def test_a_missing_model_fails_the_check(tmp_path, monkeypatch):
    monkeypatch.setattr(datapaths, "data", lambda *parts: tmp_path.joinpath(*parts))
    with pytest.raises(OSError):
        selftest._models()
