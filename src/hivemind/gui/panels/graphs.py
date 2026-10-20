"""STATS > GRAPHS and STATS > COMPARE (ROADMAP U17).

THE OWNER, 2026-10-16: a graphs section to compare data. This is only a VIEWING
LAYER: every number is the benchmark's own
(scripts/benchmark.py, the P1 scorecard), worked out from what the bot
already wrote --

  * var/trips.jsonl, the trip ledger: honey an hour (the HUD balance's rise
    between the bot's own trusted readings, spends left out: benchmark.units),
    pollen a second per field (pollen over gather seconds), walk-home landings
    and trip success;
  * var/night/attempts.log and the run logs beside it: running hours and the
    time split per activity (benchmark.time_account, ROADMAP P10);
  * var/blender.json, var/commando.json: crafts and captures;
  * the deploy history (benchmark.deploys, else var/benchmark.json): the
    "before / after an update" periods.

STATS > TIME (ROADMAP U9, P10's pie): today's and the last 7 days' split of
the running time (benchmark.time_account, the same run logs and trip ledger)
as two donuts of the groups, every slice's share as bars, and the biggest
slice named: P10 says the biggest slice is the next target.

COMPARE BY SETUP (U17b, owner 2026-10-19): each trip row carries the setup it
ran under (world/settings.trip_config); Compare's "Setups" mode sets two of
them side by side with the same verdict, and "Share setup" draws one as a
card for Discord #configs. Trips from before the tagging are one "Untagged"
group: their setup is never guessed.

NOTHING IS INVENTED. A period with too little behind a point leaves the point
out, and a chart with nothing left says "Not enough data yet" instead of
drawing a zero. The work is done off the GUI thread (a week of run logs is a
few seconds) and only when the page is first shown or Refresh is pressed.
No plotting library: none is installed in the venv (pyqtgraph, QtCharts and
matplotlib are all absent), so the charts are QPainter, in the shell's greys
with the amber accent.
"""
from __future__ import annotations

import datetime as dt
import html
import importlib.util
import json
import os
import time
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPoint, QPointF, QRectF, Qt,
                            QThreadPool, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from ...world.settings import macro_pattern_label
from .. import gameicons, theme
from ..widgets import EmptyState, can_animate, fit_pill, human_number

ROOT = Path(__file__).resolve().parents[4]
LOGO = ROOT / "data" / "brand" / "hivemind_logo.png"
UNTAGGED = "untagged"    # trips from before each row carried its setup (U17b)
HOUR, DAY = 3600.0, 86400.0
# What a point needs behind it, or it is left out (never drawn as a guess):
MIN_HONEY_S = {HOUR: 600.0, DAY: 3600.0}   # seconds of balance readings
MIN_JUDGED = 3                              # walk homes judged, for a landing %
MIN_GATHERS = 3                             # gather trips, for a success %
MIN_GATHER_MIN = 5.0                        # minutes gathered, for a field's bar
# A week of run logs is ~5 s and ~1 s a day; past this the split is not worked out.
MAX_TIME_DAYS = 7
GROUP_COLOURS = {"gather": "#f5aa1c", "walking": "#5b8def", "errands": "#3ccf7a",
                 "converting": "#c084fc", "overhead": "#9a9fab",
                 "rejoin/startup": "#e5484d", "paused/idle": "#6b707c", "unknown": "#3d424e"}
SIDE_COLOURS = ("#7c8496", theme.S_AMBER)  # compare: A, B


@lru_cache(maxsize=1)
def bench():
    """scripts/benchmark.py, the P1 scorecard, as a module (as panels/telegram
    loads telegram_alerts): one set of formulas for the card and the graphs."""
    spec = importlib.util.spec_from_file_location("hivemind_benchmark",
                                                  ROOT / "scripts" / "benchmark.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- the numbers -------------------------------------------------------------
def _midnight(t: float) -> float:
    return dt.datetime.fromtimestamp(t).replace(hour=0, minute=0, second=0,
                                                microsecond=0).timestamp()


def _floor(t: float, step: float) -> float:
    """The local clock hour or day `t` falls in (half-hour time zones too)."""
    if step >= DAY:
        return _midnight(t)
    return dt.datetime.fromtimestamp(t).replace(minute=0, second=0, microsecond=0).timestamp()


def load(var: Path, now: float | None = None, work: Path | None = None) -> dict:
    """Everything the pages draw from, read once. Reads, never writes.
    `work`: where the deploy backups and the repo are (benchmark.WORK)."""
    b, now = bench(), time.time() if now is None else now
    trips = b.load_trips(var, 0.0, now)
    deps = []
    try:
        deps = b.deploys(var, work or b.WORK)
    except Exception:                       # no deploy logs, no git: none
        pass
    if not deps:
        try:
            card = json.loads((var / "benchmark.json").read_text())
            deps = [(float(d["at"]), str(d["sha"])) for d in card.get("deploys") or []]
        except (OSError, ValueError, KeyError, TypeError):
            deps = []
    units = b.units(trips)                   # one per trip, in the trips' order
    configs: dict = {}                       # config_id -> its fingerprint, the newest row's
    for u, r in zip(units, trips):
        u["config"] = r.get("config_id") or UNTAGGED
        if r.get("config_id"):
            configs[r["config_id"]] = r.get("config") or {}
    try:
        today = b.today(var, now)            # ROADMAP P4: the day's honey/h headline
    except Exception:
        today = None
    return {"var": var, "now": now, "trips": trips, "units": units, "configs": configs,
            "today": today, "runs": b.runs(var, now), "crafts": b.crafts(var), "captures": b.captures(var),
            "deploys": sorted(deps)}


def periods(data: dict) -> list[tuple[str, float, float]]:
    """(label, since, until), the comparable stretches; the last few updates
    as "before" (the 24 h up to it) and "after" (the 24 h from it)."""
    now = data["now"]
    today = _midnight(now)
    first = data["trips"][0]["at"] if data["trips"] else now - DAY
    out = [("Last 24 hours", now - DAY, now), ("The 24 hours before", now - 2 * DAY, now - DAY),
           ("Today", today, now), ("Yesterday", _midnight(today - 1), today),
           ("Last 7 days", now - 7 * DAY, now), ("The 7 days before", now - 14 * DAY, now - 7 * DAY),
           ("Last 30 days", now - 30 * DAY, now), ("All time", float(first), now)]
    for at, sha in data["deploys"][-5:][::-1]:
        when = time.strftime("%d %b %H:%M", time.localtime(at))
        out.append((f"Before update {sha[:7]} ({when})", at - DAY, at))
        out.append((f"After update {sha[:7]} ({when})", at, min(now, at + DAY)))
    return out


def config_name(fp: dict) -> str:
    """A setup's readable name: its preset's, else e.g. "Macro: Pine Tree,
    Rose · convert at 100%"."""
    if fp.get("preset"):
        return str(fp["preset"])
    if fp.get("mode") == "macro":
        es = fp.get("fields") or []
        conv = "/".join(str(c) for c in sorted({e.get("convert_at") for e in es}))
        text = f"Macro: {', '.join(dict.fromkeys(e.get('field') for e in es))} · convert at {conv}%"
    else:
        field = fp.get("field") or "auto"
        text = f"AI: {'auto field' if field == 'auto' else field} · convert at {fp.get('convert_at')}%"
    return text + (" · boosts" if fp.get("boosts") else "")


def setups(data: dict) -> list[tuple[str, str, int]]:
    """(name, config_id, trips) for each setup seen, most trips first; the
    trips from before tagging are one group, "Untagged", last -- their
    setup was never written down, so none is guessed."""
    counts: dict = {}
    for u in data["units"]:
        counts[u["config"]] = counts.get(u["config"], 0) + 1
    names = {cid: config_name(fp) for cid, fp in data["configs"].items()}
    twins = [n for n in names.values() if list(names.values()).count(n) > 1]
    first = min((u["at"] for u in data["units"] if u["config"] != UNTAGGED), default=None)
    out = []
    for cid, n in sorted(counts.items(), key=lambda kv: (kv[0] == UNTAGGED, -kv[1])):
        if cid == UNTAGGED:
            name = (f"Untagged (before {time.strftime('%d %b', time.localtime(first))})"
                    if first else "Untagged (all trips so far)")
        else:
            name = names.get(cid, cid) + (f" [{cid[:6]}]" if names.get(cid) in twins else "")
        out.append((name, cid, n))
    return out


def _pick(units: list, since: float, until: float) -> list:
    return [u for u in units if since <= u["at"] < until]


def _buckets(units: list, step: float) -> dict:
    out: dict = {}
    for u in units:
        b = out.setdefault(_floor(u["at"], step), {"hgain": 0.0, "hdt": 0.0, "landed": 0,
                                                   "judged": 0, "success": 0, "gather": 0})
        b["hgain"] += u["hgain"]
        b["hdt"] += u["hdt"]
        b["landed"] += u["home_landed"]
        b["judged"] += u["home_judged"]
        b["success"] += u["success"]
        b["gather"] += u["gather"]
    return dict(sorted(out.items()))


def honey_points(units: list, step: float) -> list[tuple[float, float]]:
    """(bucket start, honey an hour) for each clock hour or day with enough
    balance readings behind it."""
    return [(t, b["hgain"] / b["hdt"] * 3600) for t, b in _buckets(units, step).items()
            if b["hdt"] >= MIN_HONEY_S[step]]


def rate_points(units: list, step: float) -> dict:
    """{"landing": [(t, %)], "success": [(t, %)]} per hour or day."""
    out = {"landing": [], "success": []}
    for t, b in _buckets(units, step).items():
        if b["judged"] >= MIN_JUDGED:
            out["landing"].append((t, 100.0 * b["landed"] / b["judged"]))
        if b["gather"] >= MIN_GATHERS:
            out["success"].append((t, 100.0 * b["success"] / b["gather"]))
    return out


def field_rates(units: list) -> list[tuple[str, float, float]]:
    """(field, pollen a second, minutes gathered), best first."""
    sums: dict = {}
    for u in units:
        if u["field"] and u["gather_s"] > 0:
            p, g = sums.get(u["field"], (0.0, 0.0))
            sums[u["field"]] = (p + u["pollen"], g + u["gather_s"])
    rows = [(f, p / g, g / 60) for f, (p, g) in sums.items() if g / 60 >= MIN_GATHER_MIN]
    return sorted(rows, key=lambda r: -r[1])


def time_split(data: dict, since: float, until: float) -> dict | None:
    """benchmark.time_account's groups {name: seconds}, None past MAX_TIME_DAYS."""
    if until - since > MAX_TIME_DAYS * DAY + 60:
        return None
    acc = bench().time_account(data["var"], data["runs"], data["trips"], since, until)
    return {g: c["s"] for g, c in acc["groups"].items() if c["s"] > 0}


def window(data: dict, since: float, until: float, with_time: bool = True,
           config: str | None = None) -> dict:
    """One period, every number the pages draw. With `config`: that setup's
    trips (in the period) only -- its running time and crafts are the
    whole period's, not the setup's, so they are left out (None)."""
    b = bench()
    us = _pick(data["units"], since, until)
    if config is None:
        summary = b.summary(us, since, until, data["runs"], None, data["captures"], data["crafts"])
    else:
        us = [u for u in us if u["config"] == config]
        summary = b.summary(us, since, until) | {"running_hours": None, "crafts": None}
        with_time = False
    step = HOUR if until - since <= 2 * DAY + 60 else DAY
    return {"since": since, "until": until, "units": us, "summary": summary, "step": step,
            "config": config,
            "honey": {HOUR: honey_points(us, HOUR), DAY: honey_points(us, DAY)},
            "rates": {HOUR: rate_points(us, HOUR), DAY: rate_points(us, DAY)},
            "fields": field_rates(us),
            "time": time_split(data, since, until) if with_time else None}


def compare(data: dict, a: tuple[float, float], b: tuple[float, float]) -> dict:
    """Both windows and the benchmark's verdict per metric (95% bootstrap
    over whole clock hours; "too few trips" below its minimum)."""
    wa, wb = window(data, *a), window(data, *b)
    return {"a": wa, "b": wb, "verdict": bench().compare(wa["units"], wb["units"])}


def compare_setups(data: dict, a: str, b: str) -> dict:
    """Two setups (config ids) over all time, the same verdict as compare."""
    span = (0.0, data["now"] + 1)
    wa, wb = window(data, *span, config=a), window(data, *span, config=b)
    return {"a": wa, "b": wb, "verdict": bench().compare(wa["units"], wb["units"])}


def time_windows(data: dict) -> dict:
    """benchmark.time_account for today (since local midnight) and the last
    MAX_TIME_DAYS days: {"today": acc, "week": acc}, each the benchmark's own
    {slices, groups: {name: {s, pct}}, running_h, off_h, biggest_non_gather}."""
    b, now = bench(), data["now"]
    return {name: b.time_account(data["var"], data["runs"], data["trips"], since, now)
            for name, since in (("today", _midnight(now)), ("week", now - MAX_TIME_DAYS * DAY))}


def biggest_line(acc: dict | None) -> str:
    """"Biggest slice: errands 32% (2.1 h)", "" with no running time.
    Gathering is the job, not a target (ROADMAP P10: the biggest slice is the
    next target), so when it is the biggest the next group is named too, and
    the benchmark's biggest single part when it sits in that group."""
    groups = sorted(((g, c) for g, c in ((acc or {}).get("groups") or {}).items()
                     if c.get("s", 0) > 0), key=lambda gc: -gc[1]["s"])
    if not groups:
        return ""

    def say(g: str, c: dict) -> str:
        return f"{g} {c['pct']:.0f}% ({_hours(c['s'] / 3600)})"
    text = "Biggest slice: " + say(*groups[0])
    target = groups[0][0]
    if target == "gather":
        if len(groups) < 2:
            return text
        target = groups[1][0]
        text += " · after gathering: " + say(*groups[1])
    part = acc.get("biggest_non_gather")
    cell = (acc.get("slices") or {}).get(part) or {}
    if part and part != target and bench().SLICES.get(part) == target and cell.get("s", 0) > 0:
        text += f", its biggest part {part} {cell['pct']:.0f}%"
    return text


def slice_rows(today: dict | None, week: dict | None, limit: int = 12) -> list:
    """(slice, % of the week's running, % of today's) for each slice with
    0.5%+ in either, the week's biggest first; None for a window that did
    not run at all (drawn as a dash, never as 0%)."""
    def pct(acc, k):
        if not acc or not acc.get("running_h"):
            return None
        return ((acc.get("slices") or {}).get(k) or {}).get("pct") or 0.0
    keys = dict.fromkeys(list((week or {}).get("slices") or {}) + list((today or {}).get("slices") or {}))
    rows = [(k, pct(week, k), pct(today, k)) for k in keys]
    rows = [r for r in rows if max(r[1] or 0.0, r[2] or 0.0) >= 0.5]
    rows.sort(key=lambda r: (-(r[1] or 0.0), -(r[2] or 0.0)))
    return rows[:limit]


# ---- the charts ----------------------------------------------------------------
def pretty(key: str) -> str:
    return key.replace("_", " ").title()


class Chart(QWidget):
    """A card with a title, a note, and either the drawing or "Not enough
    data yet". It grows in (bars, line, donut) when shown new numbers."""

    def __init__(self, title: str, note: str = "", parent=None):
        super().__init__(parent)
        self.title, self.note = title, note
        self.empty_text = "Not enough data yet"
        self.legend: list[tuple[str, str]] = []
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._t = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(550)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._step)

    def _step(self, value) -> None:
        self._t = float(value)
        self.update()

    def grow(self) -> None:
        self._anim.stop()
        if can_animate(self):
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.start()
        else:
            self._t = 1.0
        self.update()

    def is_empty(self) -> bool:
        return True

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.S_LINE), 1))
        p.setBrush(QColor(theme.S_CARD))
        p.drawRoundedRect(r, 10, 10)
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(theme.S_TEXT))
        p.drawText(QRectF(16, 10, r.width() - 32, 20), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        small = QFont(self.font())
        small.setPixelSize(11)
        p.setFont(small)
        x = r.width() - 16
        for name, colour in reversed(self.legend):          # legend, right to left
            w = p.fontMetrics().horizontalAdvance(name)
            p.setPen(QColor(theme.S_DIM))
            p.drawText(QRectF(x - w, 10, w, 20), Qt.AlignVCenter, name)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(colour))
            p.drawRoundedRect(QRectF(x - w - 14, 16, 9, 9), 2, 2)
            x -= w + 26
        p.setPen(QColor(theme.S_FAINT))
        p.drawText(QRectF(16, 28, r.width() - 32, 16), Qt.AlignLeft | Qt.AlignVCenter, self.note)
        plot = r.adjusted(16, 52, -16, -14)
        if self.is_empty():
            p.setPen(QColor(theme.S_FAINT))
            font.setPixelSize(12)
            font.setBold(False)
            p.setFont(font)
            p.drawText(plot, Qt.AlignCenter | Qt.TextWordWrap, self.empty_text)
        else:
            p.setFont(small)
            self.draw(p, plot)
        p.end()

    def draw(self, p: QPainter, plot: QRectF) -> None:
        raise NotImplementedError


def _nice(top: float) -> float:
    """A round axis top above `top`: 1, 2, 2.5 or 5 x 10^n."""
    if top <= 0:
        return 1.0
    exp = 10 ** int(f"{top:e}".split("e")[1])
    for m in (1, 2, 2.5, 5, 10):
        if m * exp >= top:
            return m * exp
    return 10 * exp


class LineChart(Chart):
    """Lines over time: [(name, colour, [(t, y)])]; the first is filled."""

    def __init__(self, title: str, note: str = "", y_fmt=human_number, y_top=None, parent=None):
        super().__init__(title, note, parent)
        self.y_fmt, self.y_top = y_fmt, y_top
        self.series: list = []
        self.step = HOUR

    def set_series(self, series: list, step: float) -> None:
        self.series = [s for s in series if s[2]]
        self.step = step
        self.legend = [(n, c) for n, c, _ in self.series] if len(self.series) > 1 else []
        self.grow()

    def is_empty(self) -> bool:
        return not self.series

    def _x_label(self, t: float, span: float) -> str:
        if self.step >= DAY:
            return time.strftime("%d %b", time.localtime(t))
        return time.strftime("%H:%M" if span <= DAY else "%a %H:%M", time.localtime(t))

    def draw(self, p: QPainter, plot: QRectF) -> None:
        xs = [t for _, _, pts in self.series for t, _ in pts]
        ys = [y for _, _, pts in self.series for _, y in pts]
        x0, x1 = min(xs), max(xs)
        if x1 - x0 < self.step:                    # one point: give it room
            x0, x1 = x0 - self.step / 2, x1 + self.step / 2
        top = self.y_top or _nice(max(ys) * 1.08)
        left = 52.0
        area = QRectF(plot.left() + left, plot.top() + 4, plot.width() - left - 6,
                      plot.height() - 26)
        fx = lambda t: area.left() + (t - x0) / (x1 - x0) * area.width()          # noqa: E731
        fy = lambda y: area.bottom() - max(0.0, min(y, top)) / top * area.height()  # noqa: E731
        for i in range(5):                                   # grid and y labels
            v = top * i / 4
            y = fy(v)
            p.setPen(QPen(QColor(theme.S_LINE), 1))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(QColor(theme.S_FAINT))
            p.drawText(QRectF(plot.left(), y - 8, left - 8, 16),
                       Qt.AlignRight | Qt.AlignVCenter, self.y_fmt(v))
        span = x1 - x0
        n = max(2, min(6, int(area.width() // 110)))
        for i in range(n):                                   # x labels
            t = x0 + span * i / (n - 1)
            x = fx(t)
            p.drawText(QRectF(x - 50, area.bottom() + 6, 100, 16), Qt.AlignCenter,
                       self._x_label(t, span))
        p.save()
        p.setClipRect(QRectF(area.left() - 4, plot.top(), (area.width() + 8) * self._t,
                             plot.height()))
        for k, (_, colour, pts) in enumerate(self.series):
            colour = QColor(colour)
            path = QPainterPath(QPointF(fx(pts[0][0]), fy(pts[0][1])))
            for t, y in pts[1:]:
                path.lineTo(fx(t), fy(y))
            if k == 0 and len(pts) > 1:
                fill = QPainterPath(path)
                fill.lineTo(fx(pts[-1][0]), area.bottom())
                fill.lineTo(fx(pts[0][0]), area.bottom())
                fill.closeSubpath()
                grad = QLinearGradient(0, area.top(), 0, area.bottom())
                c = QColor(colour)
                c.setAlpha(80)
                grad.setColorAt(0, c)
                c.setAlpha(0)
                grad.setColorAt(1, c)
                p.fillPath(fill, grad)
            p.setPen(QPen(colour, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            if len(pts) <= 48:
                p.setPen(Qt.NoPen)
                p.setBrush(colour)
                for t, y in pts:
                    p.drawEllipse(QPointF(fx(t), fy(y)), 2.6, 2.6)
        p.restore()


class BarChart(Chart):
    """Horizontal bars, one row per thing, one bar per series in a row:
    rows = [(label, icon or None, [value per series])]."""

    def __init__(self, title: str, note: str = "", fmt=human_number, parent=None):
        super().__init__(title, note, parent)
        self.fmt = fmt
        self.rows: list = []
        self.colours: list = [theme.S_AMBER]

    def set_rows(self, rows: list, colours: list, names: list | None = None) -> None:
        self.rows, self.colours = rows, colours
        self.legend = list(zip(names, colours)) if names else []
        self.grow()

    def is_empty(self) -> bool:
        return not self.rows

    def draw(self, p: QPainter, plot: QRectF) -> None:
        rows = self.rows
        row_h = min(34.0, plot.height() / len(rows))
        label_w, value_w = 132.0, 62.0
        top = max((v for _, _, vals in rows for v in vals if v is not None), default=0) or 1
        k = len(self.colours)
        bar_h = max(4.0, min(14.0, (row_h - 8) / k))   # 4 px at least (UI panel, low vision)
        for i, (label, icon, values) in enumerate(rows):
            y = plot.top() + i * row_h
            mid = y + row_h / 2
            x = plot.left()
            if icon is not None:
                p.drawPixmap(QRectF(x, mid - 10, 20, 20), icon, QRectF(icon.rect()))
                x += 26
            p.setPen(QColor(theme.S_TEXT))
            p.drawText(QRectF(x, y, plot.left() + label_w - x - 6, row_h),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(label, Qt.ElideRight,
                                                  int(plot.left() + label_w - x - 6)))
            bar_x = plot.left() + label_w
            width = plot.width() - label_w - value_w
            y0 = mid - bar_h * k / 2 - (k - 1)
            for j, value in enumerate(values):
                by = y0 + j * (bar_h + 2)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.S_PANEL))
                p.drawRoundedRect(QRectF(bar_x, by, width, bar_h), 3, 3)
                if value is None:
                    p.setPen(QColor(theme.S_FAINT))
                    p.drawText(QRectF(bar_x + 6, by - 3, width, bar_h + 6), Qt.AlignVCenter, "—")
                    continue
                w = max(2.0, width * value / top * self._t)
                p.setBrush(QColor(self.colours[j % len(self.colours)]))
                p.drawRoundedRect(QRectF(bar_x, by, w, bar_h), 3, 3)
                p.setPen(QColor(theme.S_DIM if j < k - 1 else theme.S_TEXT))
                p.drawText(QRectF(bar_x + width + 6, by - 4, value_w, bar_h + 8),
                           Qt.AlignLeft | Qt.AlignVCenter, self.fmt(value))


class DonutChart(Chart):
    """Shares of a whole: [(label, value, colour)], with a legend."""

    def __init__(self, title: str, note: str = "", parent=None):
        super().__init__(title, note, parent)
        self.slices: list = []
        self.centre = ""

    def set_slices(self, slices: list, centre: str = "") -> None:
        self.slices = [s for s in slices if s[1] > 0]
        self.centre = centre
        self.grow()

    def is_empty(self) -> bool:
        return not self.slices

    def draw(self, p: QPainter, plot: QRectF) -> None:
        total = sum(v for _, v, _ in self.slices)
        d = min(plot.height(), plot.width() * 0.42)
        ring = QRectF(plot.left() + 8, plot.center().y() - d / 2, d, d)
        start = 90 * 16
        for _, value, colour in self.slices:
            span = -int(360 * 16 * value / total * self._t)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(colour))
            p.drawPie(ring, start, span)
            start += span
        p.setBrush(QColor(theme.S_CARD))
        hole = ring.adjusted(d * 0.2, d * 0.2, -d * 0.2, -d * 0.2)
        p.drawEllipse(hole)
        if self.centre:
            big = QFont(p.font())
            big.setPixelSize(15)
            big.setBold(True)
            p.setFont(big)
            p.setPen(QColor(theme.S_TEXT))
            p.drawText(hole, Qt.AlignCenter, self.centre)
            big.setPixelSize(11)
            big.setBold(False)
            p.setFont(big)
        x = ring.right() + 24
        line = min(22.0, plot.height() / max(1, len(self.slices)))
        y = plot.center().y() - line * len(self.slices) / 2
        for label, value, colour in self.slices:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(colour))
            p.drawRoundedRect(QRectF(x, y + line / 2 - 5, 10, 10), 2, 2)
            p.setPen(QColor(theme.S_TEXT))
            p.drawText(QRectF(x + 18, y, 120, line), Qt.AlignVCenter, label)
            p.setPen(QColor(theme.S_DIM))
            p.drawText(QRectF(x + 130, y, plot.right() - x - 130, line), Qt.AlignVCenter,
                       f"{100 * value / total:.0f}%  ·  {value / 3600:.1f} h")
            y += line


# ---- the pages ---------------------------------------------------------------
def _hours(v: float) -> str:
    return f"{v:.1f} h" if v < 100 else f"{v:.0f} h"


def _pct(v: float) -> str:
    return f"{v:.0f}%"


def _per_s(v: float) -> str:
    return human_number(v) + "/s"


def _field_icon(field: str) -> QPixmap | None:
    return gameicons.pixmap("fields", field, 20) if gameicons.has("fields", field) else None


def _time_slices(groups: dict) -> list:
    return [(name, s, GROUP_COLOURS.get(name, theme.S_FAINT))
            for name, s in sorted(groups.items(), key=lambda kv: -kv[1])]


def _button(text: str, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    if primary:
        b.setObjectName("Primary")
    return b


def _combo(width: int = 270) -> QComboBox:
    c = QComboBox()
    c.setMinimumWidth(width)
    c.setFocusPolicy(Qt.StrongFocus)
    return c


def _scrolled(inner: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(inner)
    return area


EMPTY_DEMO = ("This is the demo, so there are no real trips to draw. In the real app "
              "these graphs fill in after the first trip.")
EMPTY_IDLE = ("Press Start. When the bot has gathered and made honey "
              "once, your honey per hour and best fields show here.")
# NOT "Press Start" WHILE THE BAR SAYS RUNNING (UI panel round 2, 2026-10-22)
EMPTY_RUNNING = ("Working… when the bot has gathered and made honey once, your "
                 "honey per hour and best fields show here.")
TIME_DEMO = ("This is the demo, so there is no running time to split. In the real "
             "app this fills in once the bot has run.")
TIME_IDLE = ("Press Start. Once the bot has run, where its time went (gathering, "
             "walking, errands, bosses, getting unstuck) shows here.")
TIME_RUNNING = ("Working… where the bot's time went shows here as it runs "
                "(press Refresh for the latest).")


class StatsGraphs(QObject):
    """Both pages and the one loader behind them. `graphs_page` and
    `compare_page` go on the Stats tab; nothing is read until one is shown
    (or `refresh()` is called)."""

    _done = Signal(object)

    def __init__(self, var: Path | None = None, work: Path | None = None, parent=None):
        super().__init__(parent)
        self.work = work
        if var is None:
            from ...datapaths import VAR_ROOT
            var = VAR_ROOT
        self.var = Path(var)
        self.data: dict | None = None
        self._gen = {"graphs": 0, "compare": 0, "load": 0, "time": 0}
        self._loading = False
        self._time_wanted = False          # the Time page was shown: work its split out
        self._time_result: dict | None = None
        # Qt's pool, not a daemon thread: the app waits for it on exit, so a
        # load still running never emits into a torn-down interpreter
        self._spawn = lambda job: QThreadPool.globalInstance().start(job)
        self._done.connect(self._arrived)
        self.periods: list = []
        self._step_choice: float | None = None     # Hourly / Daily pressed
        self._last_graphs: dict | None = None
        self.graphs_page = self._build_graphs()
        self.compare_page = self._build_compare()
        self.time_page = self._build_time()
        for page in (self.graphs_page, self.compare_page, self.time_page):
            page.installEventFilter(self)

    # ---- building ------------------------------------------------------
    def _header(self, *widgets) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        for w in widgets:
            if w is None:
                row.addStretch(1)
            else:
                row.addWidget(w)
        return row

    def _build_graphs(self) -> QWidget:
        self.period = _combo()
        self.period.currentIndexChanged.connect(lambda _=0: self._compute("graphs"))
        self.hourly, self.daily = QPushButton("Hourly"), QPushButton("Daily")
        steps = QButtonGroup(self)
        for b, step in ((self.hourly, HOUR), (self.daily, DAY)):
            b.setObjectName("Pill")
            fit_pill(b)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=step: self._set_step(s))
            steps.addButton(b)
        self.hourly.setChecked(True)
        self.refresh_button = _button("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button = _button("Export PNG", primary=True)
        self.export_button.setToolTip("Save these graphs as a picture, for Discord")
        self.export_button.clicked.connect(lambda: self.ask_export(self.graphs_sheet))
        label = QLabel("Period")
        label.setObjectName("Dim")
        self.source = QLabel("Reading the bot's records…")
        self.source.setObjectName("Dim")
        self.source.setWordWrap(True)

        sheet = QWidget()
        box = QVBoxLayout(sheet)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        self.today = QLabel()
        self.today.setTextFormat(Qt.RichText)
        self.today.hide()
        box.addWidget(self.today)
        self.kpis = QLabel()
        self.kpis.setTextFormat(Qt.RichText)
        box.addWidget(self.kpis)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.honey_chart = LineChart("Honey per hour",
                                     "the HUD balance's rise between the bot's own readings")
        self.field_chart = BarChart("Pollen per second, by field",
                                    "pollen over gather time, fields gathered 5+ min",
                                    fmt=_per_s)
        self.landing_chart = LineChart("Walk-home landings and trip success", "",
                                       y_fmt=_pct, y_top=100)
        self.time_chart = DonutChart("Time spent", "where the running time went (run logs)")
        for i, chart in enumerate((self.honey_chart, self.field_chart,
                                   self.landing_chart, self.time_chart)):
            grid.addWidget(chart, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.charts = QWidget()
        self.charts.setLayout(grid)
        grid.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.charts, 1)
        # NO EMPTY CHART BOXES before the first trip (UI panel 2026-10-21)
        # A DEMO HAS NO TRIPS OF ITS OWN: the graphs read the bot's records,
        # and a demo keeps its own empty var/ (datapaths.use_demo_dirs), so
        # "Press Start" (off in a demo) would be wrong there.
        demo = bool(os.environ.get("HIVEMIND_DEMO"))
        self.empty = EmptyState(gameicons.pixmap("fields", "Sunflower", 48),
                                "Graphs start after the first trip",
                                EMPTY_DEMO if demo else EMPTY_IDLE)
        self.empty.hide()
        box.addWidget(self.empty)
        self.graphs_sheet = sheet

        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(20, 14, 20, 16)
        outer.setSpacing(10)
        outer.addLayout(self._header(label, self.period, self.hourly, self.daily, None,
                                     self.refresh_button, self.export_button))
        outer.addWidget(self.source)
        outer.addWidget(_scrolled(sheet), 1)
        return page

    def _build_compare(self) -> QWidget:
        self.side_a, self.side_b = _combo(), _combo()
        for c in (self.side_a, self.side_b):
            c.currentIndexChanged.connect(lambda _=0: self._compute("compare"))
        vs = QLabel("vs")
        vs.setObjectName("Dim")
        self.swap_button = _button("Swap")
        self.swap_button.clicked.connect(self.swap)
        self.compare_export = _button("Export PNG", primary=True)
        self.compare_export.setToolTip("Save this comparison as a picture, for Discord")
        self.compare_export.clicked.connect(lambda: self.ask_export(self.compare_sheet))
        # U17b: compare two periods, or two SETUPS (the config each trip ran under)
        self.mode = "periods"
        self.setup_list: list = []
        self.by_periods, self.by_setups = QPushButton("Periods"), QPushButton("Setups")
        modes = QButtonGroup(self)
        for b, mode in ((self.by_periods, "periods"), (self.by_setups, "setups")):
            b.setObjectName("Pill")
            fit_pill(b)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            modes.addButton(b)
        self.by_periods.setChecked(True)
        self.by_setups.setToolTip("Compare two setups (mode, fields, pattern, convert %, "
                                  "boosts): every trip is tagged with the one it ran under")
        self.share_button = _button("Share setup")
        self.share_button.setToolTip("A card of one setup and its measured honey/h, for "
                                     "Discord #configs")
        self.share_menu = QMenu(self.share_button)
        self.share_button.setMenu(self.share_menu)
        self.share_button.hide()

        sheet = QWidget()
        box = QVBoxLayout(sheet)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        table = QFrame()
        table.setObjectName("SettingCard")
        self.table = QGridLayout(table)
        self.table.setContentsMargins(16, 12, 16, 12)
        self.table.setHorizontalSpacing(18)
        self.table.setVerticalSpacing(7)
        self._build_table()
        box.addWidget(table)
        charts = QHBoxLayout()
        charts.setSpacing(10)
        self.cmp_fields = BarChart("Pollen per second, by field", "", fmt=_per_s)
        self.cmp_time = BarChart("Time spent (hours)", "", fmt=_hours)
        charts.addWidget(self.cmp_fields, 1)
        charts.addWidget(self.cmp_time, 1)
        box.addLayout(charts, 1)
        self.compare_sheet = sheet

        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(20, 14, 20, 16)
        outer.setSpacing(10)
        a, b = QLabel("A"), QLabel("B")
        for w, colour in ((a, SIDE_COLOURS[0]), (b, SIDE_COLOURS[1])):
            w.setStyleSheet(f"color: {colour}; font-weight: 800;")
        outer.addLayout(self._header(self.by_periods, self.by_setups, a, self.side_a, vs, b,
                                     self.side_b, self.swap_button, None, self.share_button,
                                     self.compare_export))
        self.compare_note = QLabel("Pick any two periods: before vs after an update, "
                                   "today vs yesterday, this week vs last.")
        self.compare_note.setObjectName("Dim")
        self.compare_note.setWordWrap(True)
        outer.addWidget(self.compare_note)
        outer.addWidget(_scrolled(sheet), 1)
        return page

    def _build_time(self) -> QWidget:
        """Stats > Time (ROADMAP U9): today and the last 7 days, side by side."""
        self.time_refresh = _button("Refresh")
        self.time_refresh.clicked.connect(self.refresh)
        self.time_note = QLabel("Reading the bot's records…")
        self.time_note.setObjectName("Dim")
        self.time_note.setWordWrap(True)

        sheet = QWidget()
        box = QVBoxLayout(sheet)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        self.time_head = QLabel()
        self.time_head.setTextFormat(Qt.RichText)
        self.time_head.setWordWrap(True)
        self.time_head.hide()
        box.addWidget(self.time_head)
        self.today_pie = DonutChart("Today", "share of the running time since midnight")
        self.week_pie = DonutChart(f"Last {MAX_TIME_DAYS} days",
                                   f"share of the running time, the last {MAX_TIME_DAYS} days")
        self.slice_chart = BarChart("Every slice, share of the running time",
                                    "each part of the groups above; a dash: no running time then",
                                    fmt=_pct)
        pies = QHBoxLayout()
        pies.setSpacing(10)
        pies.addWidget(self.today_pie, 1)
        pies.addWidget(self.week_pie, 1)
        self.time_charts = QWidget()
        column = QVBoxLayout(self.time_charts)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        column.addLayout(pies)
        column.addWidget(self.slice_chart)
        column.addStretch(1)                  # the bars at their own height, not stretched
        self.time_charts.hide()
        box.addWidget(self.time_charts, 1)
        demo = bool(os.environ.get("HIVEMIND_DEMO"))
        self.time_empty = EmptyState(gameicons.pixmap("fields", "Sunflower", 48),
                                     "No running time yet", TIME_DEMO if demo else TIME_IDLE)
        self.time_empty.hide()
        box.addWidget(self.time_empty)
        self.time_sheet = sheet

        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(20, 14, 20, 16)
        outer.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(self.time_note, 1)
        head.addWidget(self.time_refresh, 0, Qt.AlignTop)
        outer.addLayout(head)
        outer.addWidget(_scrolled(sheet), 1)
        return page

    # ---- loading -------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Show:
            if obj is getattr(self, "time_page", None):
                self._time_wanted = True
                if self.data is not None and self._gen["time"] == 0:
                    self._compute("time")           # loaded for another page: split it now
            if self.data is None and not self._loading:
                self.refresh()
        return False

    def refresh(self) -> None:
        """Read the files again (in the background) and redraw both pages."""
        self._loading = True
        self._gen["load"] += 1
        gen = self._gen["load"]
        self.source.setText("Reading the bot's records…")
        self.time_note.setText("Reading the bot's records…")

        def job():
            try:
                self._done.emit(("load", gen, load(self.var, work=self.work)))
            except Exception as exc:                     # never break the GUI
                self._done.emit(("load", gen, exc))
        self._spawn(job)

    def _compute(self, kind: str) -> None:
        if kind == "time":
            if self.data is None:
                return
            self._gen[kind] += 1
            gen, data = self._gen[kind], self.data
            self.time_note.setText("Working out where the time went…")

            def job():
                try:
                    self._done.emit(("time", gen, time_windows(data)))
                except Exception as exc:
                    self._done.emit(("time", gen, exc))
            self._spawn(job)
            return
        if self.data is None or not self.periods:
            return
        if kind == "compare" and self.mode == "setups":
            ia, ib = self.side_a.currentIndex(), self.side_b.currentIndex()
            if ia < 0 or ib < 0:
                return
            self._gen[kind] += 1
            gen, data = self._gen[kind], self.data
            a, b = self.setup_list[ia][1], self.setup_list[ib][1]

            def job():
                try:
                    self._done.emit(("compare", gen, compare_setups(data, a, b)))
                except Exception as exc:
                    self._done.emit(("compare", gen, exc))
            self._spawn(job)
            return
        self._gen[kind] += 1
        gen, data = self._gen[kind], self.data
        if kind == "graphs":
            i = self.period.currentIndex()
            if i < 0:
                return
            _, since, until = self.periods[i]
            self.time_chart.empty_text = "Working it out…"
            self.time_chart.set_slices([])

            def job():
                try:
                    self._done.emit(("graphs", gen, window(data, since, until)))
                except Exception as exc:
                    self._done.emit(("graphs", gen, exc))
        else:
            ia, ib = self.side_a.currentIndex(), self.side_b.currentIndex()
            if ia < 0 or ib < 0:
                return
            a, b = self.periods[ia][1:], self.periods[ib][1:]
            self.cmp_time.empty_text = "Working it out…"
            self.cmp_time.set_rows([], [])

            def job():
                try:
                    self._done.emit(("compare", gen, compare(data, a, b)))
                except Exception as exc:
                    self._done.emit(("compare", gen, exc))
        self._spawn(job)

    def _arrived(self, message) -> None:
        kind, gen, result = message
        if gen != self._gen[kind]:
            return                                        # a newer one is coming
        if isinstance(result, Exception):
            if kind == "load":
                self._loading = False
            text = f"Could not read the records: {result}"
            {"compare": self.compare_note, "time": self.time_note}.get(kind, self.source).setText(text)
            if kind == "load":
                self.time_note.setText(text)
            return
        if kind == "load":
            self._loading = False
            self.data = result
            self._show_source()
            self._fill_periods()
            if self._time_wanted:
                self._compute("time")
        elif kind == "time":
            self._show_time(result)
        elif kind == "graphs":
            self._show_graphs(result)
        else:
            self._show_compare(result)

    def set_running(self, on: bool) -> None:
        """The empty state's words follow the run state (the shell's bottom bar)."""
        if hasattr(self, "empty"):
            # a demo starts nothing, so its words never say "Press Start" (the
            # Windows Claude's release check, 2026-10-22: this reset them)
            demo = bool(os.environ.get("HIVEMIND_DEMO"))
            self.empty.line.setText(EMPTY_DEMO if demo else EMPTY_RUNNING if on else EMPTY_IDLE)
            self.time_empty.line.setText(TIME_DEMO if demo else TIME_RUNNING if on else TIME_IDLE)

    def _show_source(self) -> None:
        self._show_today(self.data.get("today"))
        trips = self.data["trips"]
        self.charts.setVisible(bool(trips))
        self.empty.setVisible(not trips)
        self.export_button.setEnabled(bool(trips))
        self.source.setVisible(bool(trips))         # the empty state says it
        if not trips:
            self.kpis.hide()
            self.today.hide()
            # no path here: it shows on stream (UI review 2026-10-21)
            self.source.setText("No trips recorded yet.")
            return
        self.kpis.show()
        span = " – ".join(time.strftime("%d %b", time.localtime(t))
                          for t in (trips[0]["at"], trips[-1]["at"]))
        self.source.setText(
            f"{len(trips):,} trips, {span}. The same numbers as the benchmark "
            "scorecard; a point with too little data behind it is left out.")
        self.source.setToolTip(f"From the bot's own records in {self.var} and the run logs.")

    def _show_today(self, d: dict | None) -> None:
        """benchmark.today_line as the page's headline, the arrow green/red."""
        self.today.setVisible(bool(d))
        if not d:
            return
        words = html.escape(bench().today_line({**d, "vs_week_pct": None}, emoji=False))
        p = d.get("vs_week_pct")
        arrow = "" if p is None else (
            f" <b style='color:{theme.S_GOOD if p >= 0 else theme.S_BAD}'>"
            f"{'▲' if p >= 0 else '▼'} {abs(p):.0f}% vs 7-day</b>")
        self.today.setText(f"<span style='font-size:15px; color:{theme.S_TEXT}'>{words}</span>{arrow}")

    def _fill_periods(self) -> None:
        self.periods = periods(self.data)
        labels = [p[0] for p in self.periods]
        self.setup_list = setups(self.data)
        sides = self.mode == "periods"
        for combo, pick in ((self.period, "Last 24 hours"), (self.side_a, "Yesterday"),
                            (self.side_b, "Today"))[:3 if sides else 1]:
            keep = combo.currentText() or pick
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(labels)
            combo.setCurrentIndex(labels.index(keep) if keep in labels else labels.index(pick))
            combo.blockSignals(False)
        if not sides:
            self._compute("graphs")
            self._fill_setups()
            return
        # the newest update's before / after, when there is one
        if self.data["deploys"] and self.side_a.currentText() == "Yesterday":
            before = next((i for i, l in enumerate(labels) if l.startswith("Before update")), None)
            if before is not None:
                self.side_a.setCurrentIndex(before)
                self.side_b.setCurrentIndex(before + 1)
        self._compute("graphs")
        self._compute("compare")

    def set_mode(self, mode: str) -> None:
        """Periods or Setups: the pickers list those, the table and verdict stay."""
        if mode == self.mode:
            return
        self.mode = mode
        (self.by_setups if mode == "setups" else self.by_periods).setChecked(True)
        self.share_button.setVisible(mode == "setups")
        for combo in (self.side_a, self.side_b):    # a setup's name is longer
            combo.setMinimumWidth(300 if mode == "setups" else 270)
        if self.data is None:
            return
        if mode == "setups":
            self._fill_setups()
        else:
            self._fill_periods()

    def _fill_setups(self) -> None:
        """Each setup seen, with its trips; B the newest trip's, A the next
        most-farmed (the untagged trips when there is no other)."""
        items = [f"{name}  ·  {n:,} trips" for name, _, n in self.setup_list]
        ids = [cid for _, cid, _ in self.setup_list]
        newest = self.data["units"][-1]["config"] if self.data["units"] else None
        ib = ids.index(newest) if newest in ids else 0
        ia = next((i for i in range(len(ids)) if i != ib), ib)
        for combo, i in ((self.side_a, ia), (self.side_b, ib)):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(items)
            combo.setCurrentIndex(i)
            combo.blockSignals(False)
        if not items:
            self.compare_note.setText("No trips recorded yet: setups show once the bot has farmed.")
            return
        self._compute("compare")

    # ---- drawing -------------------------------------------------------
    def _set_step(self, step: float) -> None:
        self._step_choice = step
        if self._last_graphs is not None:
            self._draw_lines(self._last_graphs)

    def _draw_lines(self, w: dict) -> None:
        step = self._step_choice or w["step"]
        (self.hourly if step == HOUR else self.daily).setChecked(True)
        word = "clock hour" if step == HOUR else "day"
        self.honey_chart.note = f"per {word}: the HUD balance's rise between the bot's own readings"
        self.honey_chart.set_series([("Honey/h", theme.S_AMBER, w["honey"][step])], step)
        rates = w["rates"][step]
        self.landing_chart.note = f"per {word}: % of walk homes that landed, % of gather trips that succeeded"
        self.landing_chart.set_series([("Landing %", theme.S_AMBER, rates["landing"]),
                                       ("Success %", theme.S_GOOD, rates["success"])], step)

    def _show_graphs(self, w: dict) -> None:
        self._last_graphs = w
        self._step_choice = None                      # each period starts at its own scale
        s = w["summary"]

        def kpi(name, value):
            return (f"<span style='color:{theme.S_DIM}'>{name}</span> "
                    f"<b style='color:{theme.S_TEXT}'>{value}</b>")
        bits = [kpi("trips", f"{s['trips']:,}")]
        if s.get("honey_per_hour") is not None:
            bits.append(kpi("honey/h", human_number(s["honey_per_hour"])))
        if s.get("landing_pct") is not None:
            bits.append(kpi("landing", f"{s['landing_pct']:.0f}%"))
        if s.get("success_pct") is not None:
            bits.append(kpi("success", f"{s['success_pct']:.0f}%"))
        if s.get("running_hours"):
            bits.append(kpi("running", f"{s['running_hours']:.1f} h"))
        if s.get("crafts"):
            bits.append(kpi("crafts", f"{s['crafts']}"))
        self.kpis.setText("&nbsp;&nbsp;·&nbsp;&nbsp;".join(bits) if s["trips"] else
                          f"<span style='color:{theme.S_DIM}'>No trips in this period.</span>")
        self._draw_lines(w)
        self.field_chart.set_rows([(f"{pretty(f)}", _field_icon(f), [r])
                                   for f, r, _ in w["fields"][:9]], [theme.S_AMBER])
        if w["time"] is None:
            self.time_chart.empty_text = (f"The time split is worked out for periods of up to "
                                          f"{MAX_TIME_DAYS} days. Pick a shorter one.")
            self.time_chart.set_slices([])
        else:
            self.time_chart.empty_text = "Not enough data yet"
            total = sum(w["time"].values())
            self.time_chart.set_slices(_time_slices(w["time"]),
                                       centre=f"{total / 3600:.1f} h" if total else "")

    def _show_time(self, r: dict) -> None:
        """Today's and the week's split (time_windows), or the empty state."""
        self._time_result = r
        today, week = r.get("today"), r.get("week")
        ran = [acc for acc in (today, week) if acc and acc.get("running_h")]
        self.time_charts.setVisible(bool(ran))
        self.time_head.setVisible(bool(ran))
        self.time_empty.setVisible(not ran)
        if not ran:
            # no path here: it shows on stream (UI review 2026-10-21)
            self.time_note.setText("No running time recorded yet.")
            for pie in (self.today_pie, self.week_pie):
                pie.set_slices([])
            self.slice_chart.set_rows([], [])
            return
        heads = []
        for pie, acc, name, nothing in (
                (self.today_pie, today, "Today", "Nothing has run today yet"),
                (self.week_pie, week, f"Last {MAX_TIME_DAYS} days", "Not enough data yet")):
            groups = {g: c["s"] for g, c in ((acc or {}).get("groups") or {}).items() if c["s"] > 0}
            pie.empty_text = nothing
            pie.set_slices(_time_slices(groups),
                           centre=_hours(acc["running_h"]) if groups else "")
            line = biggest_line(acc)
            if line:
                heads.append(f"<span style='color:{theme.S_DIM}'>{name}</span> "
                             f"<b style='color:{theme.S_TEXT}'>{html.escape(line)}</b>")
        self.time_head.setText("<br>".join(heads))
        rows = slice_rows(today, week)
        self.slice_chart.setFixedHeight(max(250, 80 + 34 * len(rows)))   # 34 px a row
        self.slice_chart.set_rows([(k, None, [w, t]) for k, w, t in rows], list(SIDE_COLOURS),
                                  [f"Last {MAX_TIME_DAYS} days", "Today"])
        t_h = (today or {}).get("running_h") or 0.0
        w_h, off = (week or {}).get("running_h") or 0.0, (week or {}).get("off_h") or 0.0
        self.time_note.setText(
            f"Running {_hours(t_h)} today and {_hours(w_h)} in the last {MAX_TIME_DAYS} days "
            f"(not running {_hours(off)} of them). From the run logs and the trip ledger, "
            "the benchmark's own split; a stretch no log line names is 'unknown', never guessed.")

    COMPARE_ROWS = (("Honey per hour", "honey_per_hour", human_number),
                    ("Pollen per hour", "pollen_per_hour", human_number),
                    ("Trip success", "success_pct", _pct),
                    ("Walk-home landings", "landing_pct", _pct),
                    ("Deaths per hour", "deaths_per_hour", lambda v: f"{v:.2f}"),
                    ("Trips", "trips", lambda v: f"{v:,}"),
                    ("Running hours", "running_hours", _hours),
                    ("Blender crafts", "crafts", lambda v: f"{v:,}"))

    def _build_table(self) -> None:
        """The compare table's labels, made once and re-texted per compare."""
        self.cells: list[list[QLabel]] = []
        for r in range(len(self.COMPARE_ROWS) + 1):
            row = []
            for col in range(5):
                label = QLabel(self.COMPARE_ROWS[r - 1][0] if r and not col else "")
                left = col in (0, 4)
                label.setAlignment((Qt.AlignLeft if left else Qt.AlignRight) | Qt.AlignVCenter)
                if r == 0 or col == 0:
                    label.setStyleSheet(f"color: {theme.S_DIM}; font-weight: 700;" if r == 0
                                        else f"color: {theme.S_DIM};")
                self.table.addWidget(label, r, col)
                row.append(label)
            self.cells.append(row)
        self.cells[0][3].setText("change")
        self.cells[0][4].setText("verdict (95%)")
        self.table.setColumnStretch(0, 2)
        for col in (1, 2, 3):
            self.table.setColumnStretch(col, 1)
        self.table.setColumnStretch(4, 2)

    def table_texts(self) -> list[str]:
        return [label.text() for row in self.cells for label in row]

    def _show_compare(self, c: dict) -> None:
        a, b = c["a"]["summary"], c["b"]["summary"]
        verdict = c["verdict"]
        setup = self.mode == "setups"
        for col, combo in ((1, self.side_a), (2, self.side_b)):
            head = self.cells[0][col]
            text = (self.setup_list[combo.currentIndex()][0] if setup
                    and 0 <= combo.currentIndex() < len(self.setup_list) else combo.currentText())
            head.setText(text if len(text) <= 30 else text[:29] + "…")
            head.setToolTip(text)
            head.setStyleSheet(f"color: {SIDE_COLOURS[col - 1]}; font-weight: 700;")
        few = verdict.get("verdict") == "too few trips"
        for r, (_, key, fmt) in enumerate(self.COMPARE_ROWS, 1):
            whole_period = key in ("running_hours", "crafts")   # not a setup's own
            for cell in self.cells[r]:
                cell.setVisible(not (setup and whole_period))
            va, vb = a.get(key), b.get(key)
            cells = self.cells[r]
            cells[1].setText("—" if va is None else fmt(va))
            cells[2].setText("—" if vb is None else fmt(vb))
            cells[2].setStyleSheet("font-weight: 700;")
            change = round(100 * (vb - va) / va) if va and vb is not None else None
            cells[3].setText("" if change is None else f"{change:+d}%" if change else "0%")
            cells[3].setStyleSheet(f"color: {theme.S_DIM};")
            judged = verdict.get(key) if isinstance(verdict.get(key), dict) else None
            if judged:
                word = judged["verdict"]
                colour = {"better": theme.S_GOOD, "worse": theme.S_BAD}.get(word, theme.S_DIM)
            else:
                word = "too few trips" if few and key in bench().METRICS else ""
                colour = theme.S_FAINT
            cells[4].setText(word)
            cells[4].setStyleSheet(f"color: {colour};")
        if few:
            self.compare_note.setText(
                f"Too few trips for a verdict ({verdict.get('n_before', 0)} vs "
                f"{verdict.get('n_after', 0)}; the benchmark wants {bench().MIN_TRIPS}+ "
                f"trips and {bench().MIN_BLOCKS}+ clock hours a side). The numbers are "
                "still the real ones.")
        else:
            self.compare_note.setText(
                "Verdict: the benchmark's 95% bootstrap over whole clock hours. 'no "
                "detectable change' means the gap could be chance.")
        if setup:
            self.compare_note.setText(
                "Each setup's trips from every day it ran. " + self.compare_note.text()
                + (" Untagged trips ran before the bot wrote its setup down: their "
                   "setup is unknown." if UNTAGGED in (c["a"].get("config"),
                                                      c["b"].get("config")) else ""))
            self._fill_share_menu(c)

        fa = {f: r for f, r, _ in c["a"]["fields"]}
        fb = {f: r for f, r, _ in c["b"]["fields"]}
        fields = sorted(set(fa) | set(fb), key=lambda f: -max(fa.get(f, 0), fb.get(f, 0)))[:8]
        legend = ["A", "B"]
        self.cmp_fields.set_rows([(pretty(f), _field_icon(f), [fa.get(f), fb.get(f)])
                                  for f in fields], list(SIDE_COLOURS), legend)
        ta, tb = c["a"]["time"], c["b"]["time"]
        self.cmp_time.setVisible(not setup)          # time is a period's, not a setup's
        if setup:
            return
        if ta is None or tb is None:
            self.cmp_time.empty_text = (f"The time split is worked out for periods of up "
                                        f"to {MAX_TIME_DAYS} days.")
            self.cmp_time.set_rows([], [])
        else:
            self.cmp_time.empty_text = "Not enough data yet"
            groups = sorted(set(ta) | set(tb), key=lambda g: -max(ta.get(g, 0), tb.get(g, 0)))
            self.cmp_time.set_rows([(g, None, [ta.get(g, 0) / 3600, tb.get(g, 0) / 3600])
                                    for g in groups], list(SIDE_COLOURS), legend)

    def swap(self) -> None:
        a, b = self.side_a.currentIndex(), self.side_b.currentIndex()
        self.side_a.blockSignals(True)
        self.side_a.setCurrentIndex(b)
        self.side_a.blockSignals(False)
        self.side_b.setCurrentIndex(a)

    def _fill_share_menu(self, c: dict) -> None:
        self.share_menu.clear()
        for side, w in (("A", c["a"]), ("B", c["b"])):
            cid = w.get("config")
            if cid == UNTAGGED or cid not in (self.data or {}).get("configs", {}):
                act = self.share_menu.addAction(f"Setup {side}: untagged, its setup is unknown")
                act.setEnabled(False)
                continue
            fp = self.data["configs"][cid]
            self.share_menu.addAction(f"Share setup {side}: {config_name(fp)}").triggered.connect(
                lambda _=False, fp=fp, s=w["summary"]: self.ask_share(fp, s))

    def ask_share(self, fp: dict, summary: dict) -> None:
        folder = Path.home() / "Pictures"
        folder = folder if folder.is_dir() else Path.home()
        name = f"hivemind-setup-{time.strftime('%Y-%m-%d-%H%M')}.png"
        path, _ = QFileDialog.getSaveFileName(self.compare_page.window(), "Share setup",
                                              str(folder / name), "PNG image (*.png)")
        if path:
            ok = share_card(fp, summary, Path(path))
            self.compare_note.setText(f"Saved {path}: ready for Discord #configs" if ok
                                      else f"Could not save {path}")

    # ---- export --------------------------------------------------------
    def export_png(self, sheet: QWidget, path: Path) -> bool:
        """The sheet (its charts at their final frame) as a PNG at `path`."""
        for chart in sheet.findChildren(Chart):
            chart._anim.stop()
            chart._t = 1.0
        graphs = sheet is self.graphs_sheet
        what = (self.period.currentText() if graphs else
                f"{self.side_a.currentText()}  vs  {self.side_b.currentText()}")
        head, pad = 46, 16
        shot = sheet.grab()                          # the sheet at the screen's ratio
        ratio = shot.devicePixelRatio() or 1.0
        size = sheet.size()
        picture = QImage(int((size.width() + 2 * pad) * ratio),
                         int((size.height() + head + pad) * ratio), QImage.Format_ARGB32)
        picture.setDevicePixelRatio(ratio)
        picture.fill(QColor(theme.S_BG))            # a dark card, not a transparent one
        p = QPainter(picture)
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont(sheet.font())
        font.setPixelSize(16)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(theme.S_AMBER))
        p.drawText(QRectF(pad, 12, 200, 24), Qt.AlignVCenter, "Hivemind")
        font.setPixelSize(13)
        font.setBold(False)
        p.setFont(font)
        p.setPen(QColor(theme.S_DIM))
        p.drawText(QRectF(pad + 96, 12, size.width() - 96, 24), Qt.AlignVCenter,
                   f"{what}   ·   {time.strftime('%d %b %Y %H:%M')}")
        p.drawPixmap(QPoint(pad, head), shot)
        p.end()
        return not picture.isNull() and picture.save(str(path), "PNG")

    def ask_export(self, sheet: QWidget) -> None:
        folder = Path.home() / "Pictures"
        folder = folder if folder.is_dir() else Path.home()
        name = f"hivemind-{'graphs' if sheet is self.graphs_sheet else 'compare'}-" \
               f"{time.strftime('%Y-%m-%d-%H%M')}.png"
        path, _ = QFileDialog.getSaveFileName(sheet.window(), "Export PNG",
                                              str(folder / name), "PNG image (*.png)")
        if path:
            ok = self.export_png(sheet, Path(path))
            note = self.source if sheet is self.graphs_sheet else self.compare_note
            note.setText(f"Saved {path}" if ok else f"Could not save {path}")


# ---- the share card (U17b) ----------------------------------------------------
def setup_lines(fp: dict) -> list[tuple[str | None, str]]:
    """(field icon name or None, text): the setup's settings, as the card says them."""
    if fp.get("mode") == "macro":
        out = [(None, "Macro mode: your fields, in order")]
        for e in fp.get("fields") or []:
            pattern = "own pattern" if e.get("pattern") == "field" else \
                macro_pattern_label(e.get("pattern")).split(" (")[0]
            minutes = f"{e.get('minutes')} min" if e.get("minutes") else "until full"
            spr = e.get("sprinklers")
            out.append((e.get("field"), f"{e.get('field')}  ·  {pattern}  ·  {minutes}  ·  "
                        f"convert {e.get('convert_at')}%  ·  {spr} sprinkler{'s' * (spr != 1)}"
                        f"  ·  {e.get('return')} home"))
    else:
        field = fp.get("field") or "auto"
        out = [(None, "AI mode: the bot picks " + ("each trip's field" if field == "auto"
                                                    else f"{field}, the preferred field")),
               (None, f"Convert at {fp.get('convert_at')}% backpack")]
    kinds = [k.replace("_", " ") for k in fp.get("boosts") or [] if k != "ai"]
    boosts = "Boost keeper: " + ", ".join(kinds) if kinds else "Boost keeper: off"
    if "ai" in (fp.get("boosts") or []):
        boosts += "  ·  boost AI acting"
    return out + [(None, boosts)]


def share_card(fp: dict, summary: dict, path: Path, scale: float = 2.0) -> bool:
    """One setup and what it measured, as a PNG for Discord #configs. The
    numbers are the benchmark's for that setup's trips; no account name."""
    lines = setup_lines(fp)
    shown = lines[:9] if len(lines) <= 9 else lines[:8] + [(None, f"+{len(lines) - 8} more")]
    w, pad = 760, 28
    h = 196 + 30 * len(shown) + 112
    img = QImage(int(w * scale), int(h * scale), QImage.Format_ARGB32)
    img.setDevicePixelRatio(scale)
    img.fill(QColor(theme.S_BG))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    font = QFont()

    def text(x, y, width, height, words, size, colour, bold=False, align=Qt.AlignLeft):
        font.setPixelSize(size)
        font.setBold(bold)
        p.setFont(font)
        p.setPen(QColor(colour))
        p.drawText(QRectF(x, y, width, height), align | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(words, Qt.ElideRight, int(width)))
    logo = QPixmap(str(LOGO))
    if not logo.isNull():
        p.drawPixmap(QRectF(pad, 22, 44, 44), logo, QRectF(logo.rect()))
    text(pad + 56, 22, 300, 24, "Hivemind", 20, theme.S_AMBER, bold=True)
    text(pad + 56, 44, 300, 20, "setup card", 13, theme.S_DIM)
    text(w - pad - 260, 22, 260, 24, time.strftime("%d %b %Y"), 13, theme.S_DIM,
         align=Qt.AlignRight)
    text(pad, 86, w - 2 * pad, 36, config_name(fp), 24, theme.S_TEXT, bold=True)
    card = QRectF(pad, 136, w - 2 * pad, 30 * len(shown) + 36)
    p.setPen(QPen(QColor(theme.S_LINE), 1))
    p.setBrush(QColor(theme.S_CARD))
    p.drawRoundedRect(card, 12, 12)
    y = card.top() + 18
    for icon, words in shown:
        x = card.left() + 18
        if icon and gameicons.has("fields", icon):
            p.drawPixmap(QRectF(x, y + 4, 22, 22), gameicons.pixmap("fields", icon, 22),
                         QRectF(gameicons.pixmap("fields", icon, 22).rect()))
            x += 30
        text(x, y, card.right() - x - 18, 30, words, 14, theme.S_TEXT if icon else theme.S_DIM)
        y += 30
    stats = [("honey / hour", summary.get("honey_per_hour"), human_number),
             ("trip success", summary.get("success_pct"), _pct),
             ("walk-home landings", summary.get("landing_pct"), _pct),
             ("trips measured", summary.get("trips"), lambda v: f"{v:,}")]
    col = (w - 2 * pad) / len(stats)
    top = card.bottom() + 22
    for i, (label, value, fmt) in enumerate(stats):
        x = pad + i * col
        text(x, top, col - 8, 40, "—" if value is None else fmt(value), 30 if i == 0 else 24,
             theme.S_AMBER if i == 0 else theme.S_TEXT, bold=True)
        text(x, top + 40, col - 8, 18, label, 12, theme.S_DIM)
    text(pad, h - 32, w - 2 * pad, 18, "Measured by Hivemind on its own trips: honey/h is the "
         "HUD balance's rise between readings, spends left out.", 11, theme.S_FAINT)
    p.end()
    return not img.isNull() and img.save(str(path), "PNG")
