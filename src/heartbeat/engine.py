"""Auswertung: Soll-Kalender, Bewertung jedes Laufs auf drei Ebenen, Bildung von Störungen.

Ebene 1  Hat es gelaufen?        Soll-Kalender gegen Protokoll (fehlt / nachgeholt).
Ebene 2  Meldet es Fehler?       Status des Werkzeugs UND Fehlertext im Detail (A02: Status 'success', Text 'fehlgeschlagen').
Ebene 3  Ist das Ergebnis normal? Anzahl gegen den Median der letzten vertrauenswürdigen Läufe.

Eine Störung ("Incident") fasst aufeinanderfolgende schlechte Beobachtungen derselben Art zusammen
und endet beim ersten wieder guten Lauf. Auffällige Werte fließen NICHT in die Vergleichsbasis ein,
damit sich ein Fehlerzustand nicht nach ein paar Tagen selbst zum "Normal" erklärt.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .core import HARD, SOFT, Registry, Run, day_start, from_ts, iso, median, refs

EARLY_S = 300            # ein Lauf darf bis 5 Min. VOR dem Soll zählen
LATE_CAP_S = 12 * 3600   # nachgeholte Läufe bis 12 Std. nach Soll gehören noch zum Slot
BLIND_AFTER_S = 5 * 3600  # keine Einlieferung seit 5 Std. (länger als der 4-Std.-Takt von A07) -> Datenpfad selbst ist das Problem
BASE_WINDOW = 14         # Median über die letzten 14 vertrauenswürdigen Werte
K_MAD = 4.0

RUN_FAMILIES = ("fehler", "warnung", "wert", "eingefroren", "daten")


def _band(vals: List[float], cfg: dict):
    med = median(vals)
    mad = median([abs(x - med) for x in vals])
    tol = max(K_MAD * 1.4826 * mad, cfg.get("rel", 0) * med, cfg.get("abs", 0), 0.5)
    if cfg.get("zaehlend"):  # Ereigniszählung (z. B. Transkripte pro Tag): natürliche Streuung ≈ Wurzel des Mittels
        tol = max(tol, 3.0 * med ** 0.5)
    return med, tol


def _work_hours(t0: float, t1: float) -> float:
    """Stunden Mo–Fr 07:00–20:00 zwischen zwei Zeitpunkten (für die Ruhe-Prüfung ereignisgesteuerter Läufe)."""
    if t1 <= t0:
        return 0.0
    a, b = from_ts(t0), from_ts(t1)
    d, total = a.date(), 0.0
    while d <= b.date():
        if d.weekday() < 5:
            lo = max(t0, day_start(d).replace(hour=7).timestamp())
            hi = min(t1, day_start(d).replace(hour=20).timestamp())
            if hi > lo:
                total += (hi - lo) / 3600.0
        d += timedelta(days=1)
    return total


def evaluate(reg: Registry, all_runs: List[Run], as_of: datetime, resets: Optional[Dict[str, float]] = None) -> dict:
    resets = resets or {}
    as_ts = as_of.timestamp()
    runs = [r for r in all_runs if r.ts <= as_ts]
    horizon = max((r.end.timestamp() for r in runs), default=None)
    blind = horizon is not None and as_ts - horizon > BLIND_AFTER_S
    blind_from = horizon if blind else None
    data_start = day_start(min(r.start.date() for r in all_runs)) if all_runs else None

    by_auto: Dict[str, List[Run]] = defaultdict(list)
    for r in runs:
        by_auto[r.auto].append(r)

    incidents: List[dict] = []
    soll_ist: Dict[str, Dict[str, list]] = {}
    day_runs: Dict[str, Dict[str, int]] = {}

    for aid, a in reg.autos.items():
        ra = sorted(by_auto.get(aid, []), key=lambda r: r.ts)
        events = []  # (ts, prio, kind, payload)
        si: Dict[str, list] = defaultdict(lambda: [0, 0])
        dr: Dict[str, int] = defaultdict(int)
        for r in ra:
            dr[r.start.date().isoformat()] += 1

        if a["art"] == "zeit" and data_start is not None:
            slots = []
            d = data_start.date()
            while d <= as_of.date():
                slots += reg.slots(aid, d)
                d += timedelta(days=1)
            sts = [s.timestamp() for s in slots]
            starts = [t - EARLY_S for t in sts]
            assigned: List[List[Run]] = [[] for _ in slots]
            slot_of: Dict[str, Optional[float]] = {}
            for r in ra:
                i = bisect.bisect_right(starts, r.ts) - 1
                ok = False
                if i >= 0:
                    end_i = min(starts[i + 1] if i + 1 < len(starts) else 1e18, sts[i] + LATE_CAP_S)
                    ok = r.ts < end_i
                if ok:
                    assigned[i].append(r)
                    slot_of[r.id] = sts[i]
                else:
                    slot_of[r.id] = None
            miss_s = reg.miss_after(aid) * 60
            for i, st in enumerate(sts):
                due = st + miss_s <= as_ts
                day = slots[i].date().isoformat()
                if due:
                    si[day][0] += 1
                    if assigned[i]:
                        si[day][1] += 1
                first = min((r.ts for r in assigned[i]), default=None)
                if due and (first is None or first - st > miss_s):
                    if blind_from is not None and st >= blind_from:
                        si[day][0] -= 1  # nicht bewertbar: Datenpfad ist still
                        continue
                    events.append((st + miss_s, 0, "miss", {"slot": st}))
            for r in ra:
                events.append((r.ts, 1, "run", {"run": r, "slot": slot_of.get(r.id)}))
        else:
            for r in ra:
                events.append((r.ts, 1, "run", {"run": r, "slot": None}))
        events.sort(key=lambda e: (e[0], e[1]))
        soll_ist[aid] = {k: tuple(v) for k, v in si.items()}
        day_runs[aid] = dict(dr)
        incidents += _process(reg, a, events, resets.get(aid), as_ts, ra)
    if blind:
        incidents.append({
            "id": "_heartbeat:daten:%s" % iso(from_ts(horizon)), "automation": "_heartbeat", "family": "daten",
            "codes": ["KEINE_EINLIEFERUNG"], "first_ts": horizon, "last_ts": as_ts, "recovered_ts": None,
            "recovered_by": None, "kompensiert": False, "frozen_notes": 0, "last_slot": None,
            "occ": [{"ts": as_ts, "t": iso(as_of), "lauf": None, "slot": None, "code": "KEINE_EINLIEFERUNG",
                     "detail": "Letzter eingelieferter Lauf endete %s" % iso(from_ts(horizon)), "refs": []}]})
    return {"incidents": incidents, "soll_ist": soll_ist, "day_runs": day_runs, "horizon": horizon, "blind": blind,
            "as_ts": as_ts, "runs": runs}


def _new(aid: str, fam: str, code: str, ts: float) -> dict:
    return {"id": "%s:%s:%s" % (aid, fam, iso(from_ts(ts))), "automation": aid, "family": fam, "codes": [code],
            "first_ts": ts, "last_ts": ts, "occ": [], "recovered_ts": None, "recovered_by": None,
            "kompensiert": False, "frozen_notes": 0, "last_slot": None}


def _process(reg: Registry, a: dict, events: list, reset_ts: Optional[float], as_ts: float, ra: List[Run]) -> List[dict]:
    aid = a["id"]
    cfg = a["wert"]
    trusted: Dict[str, List] = defaultdict(list)
    open_: Dict[str, dict] = {}
    out: List[dict] = []
    prev_val: Optional[int] = None

    def occur(fam, code, ts, run, slot, detail, extra=None):
        inc = open_.get(fam)
        if inc is None:
            inc = _new(aid, fam, code, ts)
            open_[fam] = inc
            out.append(inc)
        if code not in inc["codes"]:
            inc["codes"].append(code)
        o = {"ts": ts, "t": iso(from_ts(ts)), "lauf": run.id if run else None, "slot": iso(from_ts(slot)) if slot else None,
             "code": code, "detail": detail, "refs": refs(detail) if run else []}
        if extra:
            o.update(extra)
        inc["occ"].append(o)
        inc["last_ts"] = ts
        inc["last_slot"] = slot
        return inc

    def close(fam, ts, run, slot):
        inc = open_.pop(fam, None)
        if inc is None:
            return
        inc["recovered_ts"] = ts
        inc["recovered_by"] = run.id if run else None
        inc["recovered_manual"] = bool(run and run.manual)
        inc["kompensiert"] = slot is not None and inc.get("last_slot") == slot

    for ts, _prio, kind, p in events:
        if kind == "miss":
            occur("ausfall", "RUN_MISSING", ts, None, p["slot"], "Kein Protokolleintrag zum Soll %s" % iso(from_ts(p["slot"])))
            continue
        run: Run = p["run"]
        slot = p["slot"]
        end_ts = run.end.timestamp()
        flags: Dict[str, tuple] = {}
        if run.klass == "unknown":
            flags["daten"] = ("STATUS_UNBEKANNT", {})
        elif run.klass == "fail":
            flags["fehler"] = ("STATUS_ERROR", {})
        elif HARD.search(run.detail):
            flags["fehler"] = ("TEXT_ERROR", {})
        elif run.klass == "warn" or SOFT.search(run.detail):
            flags["warnung"] = ("STATUS_WARNING", {})

        reliable = "fehler" not in flags and "daten" not in flags and run.count is not None
        v = run.count
        key = "we" if cfg.get("wochenende_getrennt") and run.start.weekday() >= 5 else "all"
        wert_flagged = False
        if reliable and (cfg["modus"] != "aus" or cfg.get("null", "ok") != "ok"):
            zero_rule = cfg.get("null", "ok")
            zero_bad = zero_rule == "schlecht" or (zero_rule == "schlecht_werktags" and run.start.weekday() < 5)
            vals = [x for (t, x) in trusted[key] if reset_ts is None or run.ts < reset_ts or t >= reset_ts][-BASE_WINDOW:]  # Reset gilt nur für Läufe danach
            info = {"wert": v}
            if len(vals) >= 1:
                m, tol = _band(vals, cfg)
                info.update({"median": m, "unten": m - tol, "oben": m + tol, "n": len(vals)})
            if v == 0 and zero_bad:
                flags["wert"] = ("VOLUME_ZERO", info)
            elif cfg["modus"] == "band" and len(vals) >= cfg.get("min_n", 3):
                m, tol = _band(vals, cfg)
                if abs(v - m) > tol:
                    info.update({"abweichung_pct": round(100.0 * (v - m) / m, 1) if m else None})
                    flags["wert"] = ("VOLUME_DEVIATION", info)
            wert_flagged = "wert" in flags
            if not wert_flagged:
                trusted[key].append((run.ts, v))
            # eingefroren: gleicher großer Wert wie im Lauf davor
            if cfg["modus"] == "band" and v is not None and v >= 100 and prev_val == v:
                if wert_flagged:
                    flags["_frozen_note"] = ("NOTE", {})
                else:
                    flags["eingefroren"] = ("VOLUME_FROZEN", {"wert": v})
        if reliable:
            prev_val = v

        if "fehler" in flags or "daten" in flags:
            evaluated = {"fehler", "daten"}            # Zahl eines fehlerhaften Laufs sagt nichts über den Wert
        elif not reliable:
            evaluated = {"fehler", "daten", "warnung"}  # Lauf ohne Zahl
        else:
            evaluated = set(RUN_FAMILIES)
        for fam in RUN_FAMILIES:
            if fam not in evaluated:
                continue
            f = flags.get(fam)
            if f:
                occur(fam, f[0], end_ts, run, slot, run.detail, f[1])
            else:
                close(fam, run.ts, run, slot)
        if "_frozen_note" in flags and open_.get("wert") is not None:
            open_["wert"]["frozen_notes"] += 1
        close("ausfall", run.ts, run, slot)

    # Ruhe-Prüfung (nur ereignisgesteuerte Automationen mit Schwellwert)
    thr = a.get("stille_werktag_std")
    if a["art"] == "ereignis" and thr and ra:
        marks = [r.end.timestamp() for r in ra]
        for i, t0 in enumerate(marks):
            t1 = marks[i + 1] if i + 1 < len(marks) else as_ts
            if _work_hours(t0, t1) > thr:
                inc = _new(aid, "stille", "SILENCE", t1)
                inc["occ"].append({"ts": t1, "t": iso(from_ts(t1)), "lauf": None, "slot": None, "code": "SILENCE",
                                   "detail": "%.1f Arbeitsstunden ohne Lauf" % _work_hours(t0, t1), "refs": []})
                if i + 1 < len(marks):
                    inc["recovered_ts"] = t1
                out.append(inc)
    return out


def profile(runs: List[Run]) -> dict:
    """Median-Profil je Automation (Transparenz für die Registerkarte 'Automationen')."""
    out = {}
    by = defaultdict(list)
    for r in runs:
        by[r.auto].append(r)
    for aid, rs in by.items():
        ok = [r for r in rs if r.klass != "fail" and r.count is not None]
        out[aid] = {
            "n": len(rs),
            "median_anzahl": median([r.count for r in ok]) if ok else None,
            "median_dauer_s": median([(r.end - r.start).total_seconds() for r in rs]),
        }
    return out
