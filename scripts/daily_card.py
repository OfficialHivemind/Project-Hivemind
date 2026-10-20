#!/usr/bin/env python3
"""The day in one picture: a stats card the owner can post (video sites,
Discord) and that lands on their phone through Telegram.

WHY. Claims about a macro are cheap; Hivemind answers with measured numbers
instead, every day, from what the bot itself recorded (the owner asked for
this on 2026-10-14). Every figure is read from var/ (the trip ledger, the Commando and
Blender books, the purchase log, the run logs); a figure that is not there is
left off the card rather than drawn as zero.

    .venv/bin/python scripts/daily_card.py [--hours 24] [--out card.png] [--send [--now]]

THE SCHEDULE IS THEIRS (settings telegram.stats_cards, the GUI's Telegram tab).
The user timer hivemind-stats-card fires at 09, 13, 17 and 21 whatever it
says; --send then posts only what the schedule wants at this hour and exits
quietly otherwise. --now (the tab's "Send a stats card now") skips the check.

THE HOURLY CARD (telegram.hourly_card, off by default): the alerts service
runs `--hours 1 --send --hourly` at the top of each hour; it is sent when the
switch is on and the timer's own card is not due this hour. Its tiles are the
hour's trips, quests, knock-outs and rejoins (var/hourly_card.png).

A card not sent for the network waits in the outbox (telegram_alerts.OUTBOX).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import telegram_alerts as tg  # noqa: E402  (stdlib only: the token and the switches)
import benchmark  # noqa: E402  (the day's honey/h headline, ROADMAP P4)
from hivemind.stream import show  # noqa: E402  (on the path through telegram_alerts)

VAR = ROOT / "var"
LOGO = ROOT / "data" / "brand" / "hivemind_logo.png"
FONT = "/usr/share/fonts/noto/NotoSans-Black.ttf"
FONT_TEXT = "/usr/share/fonts/noto/NotoSans-Bold.ttf"
W, H = 1080, 1350
GOLD = (40, 190, 255)            # BGR
INK = (245, 240, 235)
DIM = (165, 150, 140)
UP, DOWN = (90, 200, 70), (70, 70, 230)    # BGR: the headline's arrow vs the 7-day
# THE STATS-CARD TIMER's hours (hivemind-stats-card.timer): the hourly card
# stands aside when that one's card is due.
TIMER_HOURS = (9, 13, 17, 21)


def _json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def stats(hours: float = 24.0, now: float | None = None, var: Path = VAR) -> dict:
    """What the bot recorded over the last `hours`. Keys are absent, not zero,
    when nothing measured them."""
    now = time.time() if now is None else now
    since = now - hours * 3600
    rows = []
    try:
        for line in (var / "trips.jsonl").read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if since <= row.get("at", 0) <= now:
                rows.append(row)
    except OSError:
        pass
    out: dict = {"hours": hours}
    # FROM THE RUN LOGS, the window's lines only (show.logged dates them). The
    # rejoins were counted over every line of each log a trip of the window
    # came from, so a 4-hour card counted a run's earlier hours too.
    out["rejoins"] = out["deaths"] = out["quests"] = 0
    last_death = -1e9
    for at, words in show.logged(var / "night", since, now):
        out["rejoins"] += "asking for a rejoin" in words
        out["quests"] += bool(show.HANDED_IN.match(words))
        if words.startswith("died:"):        # 2-4 lines a death (show)
            out["deaths"] += at - last_death > show.DEATH_TOAST_GAP_SECONDS
            last_death = at
    if not rows:
        return out
    # HONEY FROM THE HUD, first read to last: everything the day earned
    # (converts, quests, dispensers, planters), not only the converts.
    reads = [(r["at"], r["context"]["honey"]) for r in rows
             if isinstance((r.get("context") or {}).get("honey"), int)]
    out["series"] = reads
    if len(reads) >= 2 and reads[-1][1] > reads[0][1]:
        out["honey"] = reads[-1][1] - reads[0][1]
        out["honey_per_hour"] = out["honey"] / max(1.0, (reads[-1][0] - reads[0][0]) / 3600)
    out["farming_hours"] = sum(r.get("seconds") or 0 for r in rows) / 3600
    out["trips"] = sum(1 for r in rows if r.get("converted"))
    home = [x.get("outcome") for r in rows for x in r.get("routes") or []
            if x.get("kind") == "home" and x.get("outcome") in ("landed", "elsewhere")]
    if home:
        out["home_landed"] = home.count("landed") / len(home)
    tries = _json(var / "commando.json", {}).get("tries", [])
    out["commando"] = sum(1 for t in tries
                          if t.get("at", 0) >= since and t.get("result") in ("killed", "captured"))
    made = _json(var / "blender.json", {}).get("made", [])
    out["crafted"] = sum(int(m[2]) for m in made if m[0] >= since)
    buys = _json(var / "purchases.json", [])
    out["bought"] = sum(1 for b in buys if b.get("at", 0) >= since and b.get("ok"))
    return out


def short(n: float) -> str:
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= size:
            v = n / size
            places = 2 if abs(v) < 10 else 1 if abs(v) < 100 else 0
            return f"{v:.{places}f}".rstrip("0").rstrip(".") + unit if places else f"{v:.0f}{unit}"
    return f"{n:.0f}"


class _Hershey:
    """OpenCV's built-in font, behind cv2.freetype's FreeType2 calls.

    MEASURED 2026-10-21 on Windows: no pip OpenCV wheel has cv2.freetype
    (contrib included), and the Noto fonts above are Linux paths, so the card
    raised AttributeError there. OpenCV 5 draws its built-in faces with a real
    typeface, so the card looks much the same (rendered and checked by eye on
    Windows, 2026-10-21). ponytail: fontScale px/30 is about the height
    FreeType draws at px, matched by eye, not measured."""
    FACE = cv2.FONT_HERSHEY_DUPLEX

    @staticmethod
    def _scale(px):
        return px / 30.0, max(1, int(round(px / 14)))

    def getTextSize(self, text, px, thickness):
        scale, weight = self._scale(px)
        return cv2.getTextSize(text, self.FACE, scale, weight)

    def putText(self, img, text, org, px, colour, thickness, line_type, bottom_left):
        # `org` is the baseline's left end, as FreeType2 takes it with
        # bottomLeftOrigin=True; cv2.putText's own flag would flip the image.
        scale, weight = self._scale(px)
        cv2.putText(img, text, org, self.FACE, scale, colour, weight, line_type)


def _font(path: str):
    """FreeType2 with `path` (or FONT) when this OpenCV has freetype and the
    file exists; OpenCV's own font otherwise (_Hershey)."""
    file = path if Path(path).exists() else FONT
    if not hasattr(cv2, "freetype") or not Path(file).exists():
        return _Hershey()
    ft = cv2.freetype.createFreeType2()
    ft.loadFontData(file, 0)
    return ft


def day_line(t: float | None = None) -> str:
    """"Tuesday 21 October 2026": the day of the month with no leading zero,
    which strftime's "%-d" only does on glibc (Windows raises ValueError:
    Invalid format string, MEASURED 2026-10-21)."""
    tm = time.localtime(t)
    return f"{time.strftime('%A', tm)} {tm.tm_mday} {time.strftime('%B %Y', tm)}"


def _text(img, text, px, cx, y, colour, font=FONT):
    ft = _font(font)
    (w, _), _ = ft.getTextSize(text, px, -1)
    ft.putText(img, text, (int(cx - w / 2), int(y)), px, colour, -1, cv2.LINE_AA, True)


def _graph(img, series, box) -> None:
    """The HUD's honey over the window as a filled line, with its start and
    end times under it; nothing drawn for fewer than two reads."""
    pts = [(t, h) for t, h in series if h is not None]
    if len(pts) < 2:
        return
    x0, y0, x1, y1 = box
    t0, t1 = pts[0][0], pts[-1][0]
    lo, hi = min(h for _, h in pts), max(h for _, h in pts)
    span_t, span_h = max(1.0, t1 - t0), max(1.0, hi - lo)
    poly = [(int(x0 + (t - t0) / span_t * (x1 - x0)), int(y1 - 24 - (h - lo) / span_h * (y1 - y0 - 34)))
            for t, h in pts]
    fill = img.copy()
    cv2.fillPoly(fill, [np.array(poly + [(poly[-1][0], y1 - 24), (poly[0][0], y1 - 24)], np.int32)], GOLD)
    img[:] = cv2.addWeighted(fill, 0.18, img, 0.82, 0)
    cv2.polylines(img, [np.array(poly, np.int32)], False, GOLD, 4, cv2.LINE_AA)
    for t, x in ((t0, x0 + 40), (t1, x1 - 40)):
        _text(img, time.strftime("%H:%M", time.localtime(t)), 24, x, y1 + 6, DIM, FONT_TEXT)


def _headline(img, d: dict, y: int) -> None:
    """benchmark.today_line's first part, centred (smaller until it fits),
    then a green/red triangle and the % against the 7-day average. A drawn
    triangle: Noto Sans has no arrow glyph."""
    words = benchmark.today_line({**d, "vs_week_pct": None, "running_hours": None})
    p = d.get("vs_week_pct")
    pct = "" if p is None else f"{abs(p):.0f}%"
    ft, px = _font(FONT_TEXT), 32
    while True:
        (w1, _), _ = ft.getTextSize(words, px, -1)
        (w2, _), _ = ft.getTextSize(pct, px, -1) if pct else ((0, 0), 0)
        tri = int(px * 0.7) if pct else 0
        total = w1 + (tri + w2 + px if pct else 0)
        if total <= W - 60 or px <= 18:
            break
        px -= 2
    x = int((W - total) / 2)
    ft.putText(img, words, (x, y), px, INK, -1, cv2.LINE_AA, True)
    if pct:
        colour, tx = (UP if p >= 0 else DOWN), x + w1 + px // 2
        top, bot = y - int(px * 0.62), y - int(px * 0.08)
        pts = ([(tx, bot), (tx + tri, bot), (tx + tri // 2, top)] if p >= 0 else
               [(tx, top), (tx + tri, top), (tx + tri // 2, bot)])
        cv2.fillPoly(img, [np.array(pts, np.int32)], colour, cv2.LINE_AA)
        ft.putText(img, pct, (tx + tri + px // 4, y), px, colour, -1, cv2.LINE_AA, True)


def render(s: dict, out: Path, day: str) -> Path:
    y = np.linspace(0, 1, H)[:, None, None]
    img = ((1 - y) * np.array([26, 15, 11]) + y * np.array([43, 26, 20])).astype(np.uint8)
    img = np.repeat(img, W, axis=1)
    # A faint honeycomb behind everything.
    glow = np.zeros_like(img)
    r = 60
    for row in range(-1, H // int(r * 1.5) + 2):
        for col in range(-1, W // int(r * 1.73) + 2):
            cx = col * r * 1.732 + (row % 2) * r * 0.866
            cy = row * r * 1.5
            pts = np.array([(cx + r * np.cos(np.radians(a)), cy + r * np.sin(np.radians(a)))
                            for a in range(30, 390, 60)], np.int32)
            cv2.polylines(glow, [pts], True, GOLD, 2, cv2.LINE_AA)
    img = cv2.addWeighted(img, 1.0, glow, 0.07, 0)

    logo = cv2.imread(str(LOGO), cv2.IMREAD_UNCHANGED)
    if logo is not None:
        logo = cv2.resize(logo, (200, 200), interpolation=cv2.INTER_AREA)
        a = logo[:, :, 3:4] / 255.0
        x0, y0 = (W - 200) // 2, 30
        roi = img[y0:y0 + 200, x0:x0 + 200]
        img[y0:y0 + 200, x0:x0 + 200] = (roi * (1 - a) + logo[:, :, :3] * a).astype(np.uint8)

    hourly = s["hours"] <= 1
    _text(img, "DAILY REPORT" if s["hours"] >= 24 else "LAST HOUR" if hourly else
          f"LAST {s['hours']:.0f} HOURS", 34, W / 2, 272, GOLD)
    _text(img, day, 30, W / 2, 316, DIM, FONT_TEXT)
    if s.get("today"):                        # ROADMAP P4: the day's honey/h headline
        _headline(img, s["today"], 366)
    if "honey" in s:
        _text(img, "+" + short(s["honey"]), 140, W / 2, 490, GOLD)
        _text(img, "honey this hour" if hourly else f"honey in {s['hours']:.0f} hours",
              36, W / 2, 542, INK, FONT_TEXT)
    _graph(img, s.get("series") or [], (60, 572, W - 60, 745))

    tiles = []
    if "honey_per_hour" in s:
        tiles.append((short(s["honey_per_hour"]), "honey / hour"))
    # "3.8h" alone read as a rate (the owner asked "3.8 what?", 2026-10-15):
    # say it is hours OUT OF the card's window (ROADMAP TG10)
    tiles.append((f"{s.get('farming_hours', 0):.1f} of {s['hours']:.0f}h", "spent farming"))
    tiles.append((str(s.get("trips", 0)), "trips banked"))
    if "home_landed" in s:
        tiles.append((f"{s['home_landed'] * 100:.0f}%", "walks home landed"))
    if hourly:                                # the hour's own story: six tiles fit
        tiles = [t for t in tiles if t[1] != "walks home landed"]
        tiles += [(str(s.get("quests", 0)), "quests handed in"),
                  (str(s.get("deaths", 0)), "knock-outs"), (str(s.get("rejoins", 0)), "rejoins")]
    tiles.append((str(s.get("crafted", 0)), "items crafted"))
    tiles.append((str(s.get("commando", 0)), "Commando Chicks"))
    tw, th, gap, top = 470, 150, 30, 780
    for i, (value, label) in enumerate(tiles[:6]):
        x = (W - 2 * tw - gap) // 2 + (i % 2) * (tw + gap)
        yy = top + (i // 2) * (th + gap)
        over = img.copy()
        cv2.rectangle(over, (x, yy), (x + tw, yy + th), (60, 40, 30), -1, cv2.LINE_AA)
        img = cv2.addWeighted(over, 0.75, img, 0.25, 0)
        cv2.rectangle(img, (x, yy), (x + tw, yy + th), GOLD, 2, cv2.LINE_AA)
        _text(img, value, 64, x + tw / 2, yy + 82, INK)
        _text(img, label, 28, x + tw / 2, yy + 128, DIM, FONT_TEXT)

    _text(img, "no hands on the keyboard · Hivemind plays Bee Swarm by itself", 28,
          W / 2, H - 28, DIM, FONT_TEXT)
    cv2.imwrite(str(out), img)
    return out


def due(schedule: str, hour: int) -> bool:
    """Does telegram.stats_cards want a card at this hour of the timer's
    09/13/17/21? 'daily at 21:00' only the 21:00 one (the 24-hour report)."""
    if schedule == "off":
        return False
    if schedule == "every 4 hours + daily":
        return True
    return hour == 21


def hourly_due(switches: dict, hour: int) -> bool:
    """The hourly card: its switch on, and not at an hour the timer's card
    is due (one card an hour is enough)."""
    return bool(switches.get("telegram.hourly_card")) and not (
        hour in TIMER_HOURS and due(switches.get("telegram.stats_cards", "off"), hour))


def demo() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        var = Path(d)
        (var / "night").mkdir()
        # the log's last write at 12:30 local, the card at 12:40
        stamp = time.mktime(time.strptime("1970-01-12 12:30", "%Y-%m-%d %H:%M"))
        t = stamp + 600
        rows =[{"at": t - 7200, "attempt": 1, "seconds": 600, "converted": True,
                 "context": {"honey": 1_000}, "routes": [{"kind": "home", "outcome": "landed"}]},
                {"at": t - 3600, "attempt": 1, "seconds": 600, "converted": True,
                 "context": {"honey": 5_000}, "routes": [{"kind": "home", "outcome": "elsewhere"}]},
                {"at": t - 200_000, "attempt": 0, "context": {"honey": 1}}]
        (var / "trips.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        (var / "night" / "run-1.log").write_text(
            "    12:00:00  x asking for a rejoin\n"
            "    12:01:00  died: pollen fell 9 -> 1 (8 lost)\n    12:01:20  died: 8 pollen lost\n"
            "    12:02:00  a dialogue was read at the Brown Bear, so it leaves the hand-in queue\n")
        os.utime(var / "night" / "run-1.log", (stamp, stamp))
        (var / "blender.json").write_text(json.dumps({"made": [[t - 10, "glue", 3], [t - 1e6, "oil", 9]]}))
        s = stats(24, now=t, var=var)
        assert s["honey"] == 4_000 and s["honey_per_hour"] == 4_000, s
        assert s["trips"] == 2 and s["home_landed"] == 0.5 and s["rejoins"] == 1, s
        assert s["deaths"] == 1 and s["quests"] == 1, s
        assert stats(0.1, now=t, var=var)["rejoins"] == 0       # 12:00 is out of 12:34-12:40
        assert s["crafted"] == 3 and s["commando"] == 0 and s["bought"] == 0, s
        assert "honey" not in stats(24, now=t + 1e7, var=var)
    assert short(1_495_716_851) == "1.5B" and short(72_600_000) == "72.6M"
    assert short(65_070_000) == "65.1M" and short(365_000_000) == "365M"
    assert [h for h in (9, 13, 17, 21) if due("daily at 21:00", h)] == [21]
    assert all(due("every 4 hours + daily", h) for h in (9, 13, 17, 21))
    assert not any(due("off", h) for h in (9, 13, 17, 21))
    on = {"telegram.hourly_card": True, "telegram.stats_cards": "daily at 21:00"}
    assert [h for h in range(24) if not hourly_due(on, h)] == [21]
    assert not hourly_due({"telegram.hourly_card": False}, 10)
    print("daily_card demo: ok")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=float, default=24.0)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--send", action="store_true")
    p.add_argument("--demo", action="store_true")
    p.add_argument("--now", action="store_true", help="send whatever the schedule says")
    p.add_argument("--hourly", action="store_true", help="send if telegram.hourly_card wants it")
    a = p.parse_args()
    if a.demo:
        return demo()
    hour = time.localtime().tm_hour
    if a.send and not a.now and not (hourly_due(tg.toggles(), hour) if a.hourly else
                                     due(tg.toggles()["telegram.stats_cards"], hour)):
        return                                # not wanted at this hour: quietly
    a.out = a.out or VAR / ("hourly_card.png" if a.hourly else "daily_card.png")
    s = stats(a.hours)
    try:
        s["today"] = benchmark.today(VAR)
    except Exception as exc:                  # a broken ledger never stops the card
        print(f"no honey/h today: {exc}", file=sys.stderr)
    path = render(s, a.out, day_line())
    print(json.dumps({k: v for k, v in s.items() if k != "series"}), path)
    if a.send:
        head = benchmark.today_line(s["today"]) + "\n" if s.get("today") else ""
        # A6: the day's walks home from the run logs (scripts/landing_rate)
        try:
            import landing_rate
            head += landing_rate.today(VAR) + "\n"
        except Exception as exc:              # the card still goes
            print(f"no walk-home line: {exc}", file=sys.stderr)
        try:
            tg.post_photo(path, head + (
                f"🐝 Hivemind's last hour — quests: {s.get('quests', 0)}, knock-outs: "
                f"{s.get('deaths', 0)}, rejoins: {s.get('rejoins', 0)}" if a.hourly else
                f"🐝 Hivemind's last {a.hours:.0f} hours — rejoins: "
                f"{s.get('rejoins', 0)}, ticket buys: {s.get('bought', 0)}"))
        except (KeyError, RuntimeError) as exc:   # never the token: see post_photo
            sys.exit(f"stats card not sent: {'Telegram is not set up' if isinstance(exc, KeyError) else exc}")
        # THE DAILY PROGRESS REPORT with the evening card (the owner asked
        # for real stats of improvement, 2026-10-20): what it bought, quests handed in,
        # honey/h against the week, what it would buy next (scripts/progress_report).
        if time.localtime().tm_hour == 21 and not a.hourly:
            try:
                import progress_report
                try:
                    from hivemind.brain import roi
                    ranking = roi.from_files(VAR)
                except Exception:             # the report says "no ranking" then
                    ranking = None
                tg.send(progress_report.text(
                    progress_report.report(VAR, time.time(), a.hours, ranking), telegram=True))
            except Exception as exc:          # the card already went: never fatal
                print(f"progress report not sent: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
