"""Which token a coin is: the typed head, as an A/B against the honey head.

OFF UNLESS SWITCHED ON. vision/coins.kinds_of names a coin "honey" or
"unknown" with its honey head (today's model). With the setting
`gather.token_types` on AND data/models/token_types.npz loading, this
module names it instead: one of the kinds the model was trained on
(`Model.classes`), or "unknown" where its best guess is under `tau`, is
"other" (a kind too rare to learn), or is "background" (the coin network
called it a coin, this one does not agree -- the coin decision stays the
coin network's either way). A missing or broken file leaves the honey head
in charge and `error()` says why.

THE NETWORK is vision/coinnet's own forward pass with one output per class,
on the same 32 px crop vision/coins cuts for a sighting. What it is, how it
was trained and what it measured against the honey head on the same held-out
crops: scripts/train_token_types.py and docs/pending/ai-tokens-typed.md.
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from ..datapaths import data
from . import coinnet

MODEL = data("models", "token_types.npz")
SETTING = "gather.token_types"

_lock = threading.Lock()
_model = None
_error = ""
_on = False


class Model:
    def __init__(self, params: dict, classes, tau: float):
        self.params = {k: np.asarray(v, np.float32) for k, v in params.items()}
        self.classes = [str(c) for c in classes]
        self.tau = float(tau)

    @classmethod
    def load(cls, path: Path = MODEL) -> "Model":
        with np.load(path, allow_pickle=False) as z:
            return cls({k: z[k] for k in coinnet.PARAM_NAMES}, list(z["classes"]),
                       float(z["tau"]))

    def save(self, path: Path, **notes) -> None:
        np.savez_compressed(path, classes=np.array(self.classes), tau=np.float32(self.tau),
                            **self.params, **notes)

    def name(self, batch: np.ndarray) -> list[str]:
        """Kinds for a batch of crops (N x 32 x 32 x 3 floats in 0..1)."""
        z = coinnet.logits(self.params, batch)
        z = z - z.max(1, keepdims=True)
        p = np.exp(z)
        p /= p.sum(1, keepdims=True)
        out = []
        for row in p:
            j = int(row.argmax())
            c = self.classes[j]
            out.append("unknown" if c in ("background", "other") or row[j] < self.tau else c)
        return out


def switch(on: bool) -> None:
    """The setting's value; run_farm sets it each time it reads settings."""
    global _on
    _on = bool(on)


def model() -> Model | None:
    """The typed model while switched on and loadable, else None."""
    global _model, _error
    if not _on:
        return None
    if _model is None and not _error:
        with _lock:
            if _model is None and not _error:
                try:
                    _model = Model.load(MODEL)
                except (OSError, KeyError, ValueError) as err:
                    _error = f"no token-type model ({MODEL.name}): {err}"
    return _model


def error() -> str:
    return _error


def kinds(path: Path = MODEL) -> list[str]:
    """The kinds the typed head can name (its classes but background and
    other), switched on or not; [] when the file does not load. Only the
    names are read (the Token priority table lists them)."""
    try:
        with np.load(path, allow_pickle=False) as z:
            return [str(c) for c in z["classes"] if str(c) not in ("background", "other")]
    except (OSError, KeyError, ValueError):
        return []
