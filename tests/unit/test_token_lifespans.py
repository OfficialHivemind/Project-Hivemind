"""tools/analysis/token_lifespans.py: the Kaplan-Meier tail behind tokens.yaml
life_s checks and tokenbrain's urgency (ROADMAP AI-N1)."""
from __future__ import annotations

import importlib.util
import pathlib

import hivemind

TOOL = pathlib.Path(hivemind.__file__).resolve().parents[2] / "tools" / "analysis" / "token_lifespans.py"


def tool():
    spec = importlib.util.spec_from_file_location("token_lifespans", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def row(life, censored=""):
    return {"kind": "blue_boost", "life": life, "censored": censored}


def test_km_counts_the_censored_as_at_risk_and_skips_the_unseen_landing():
    t = tool()
    rows = [row(1.0), row(2.0), row(3.0), row(4.0)]
    assert t.km_quantile(rows, 0.5) == 2.0
    # a track still alive at the end keeps the others' share from rising
    # as fast; one never seen landing says nothing about a life
    more = rows + [row(0.5, "alive at the end"), row(9.0, "born at the start")]
    assert t.km_quantile(more, 0.5) == 2.0 and t.km_quantile(more, 1.0) == 4.0
    assert t.km_quantile([row(5.0, "walked out of view")], 0.9) is None
    tab = t.table(rows + [row(9.0, "camera turn")])["blue_boost"]
    assert tab["n"] == 4 and tab["max"] == 4.0 and tab["n_landed"] == 5
