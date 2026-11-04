"""Aus den rohen Störungen der Engine wird das Lagebild: Gruppierung nach Ursache, Priorität, Zustand (Human in the Loop),
Auswirkung, Empfehlung, Plausibilität und das 14-Tage-Raster.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from . import plaus, texts
from .core import Registry, Run, day_start, fmt_day, fmt_dt, fmt_dur, from_ts, iso, median, parse_local, WD
from .engine import evaluate, profile
from .store import Store

LEVEL_NAME = {1: "kritisch", 2: "hoch", 3: "mittel", 4: "info"}
STATE_LABEL = {"neu": "Unbearbeitet", "uebernommen": "In Arbeit", "geloest": "Gelöst", "fehlalarm": "Fehlalarm", "ruhend": "Zurückgestellt"}
FAM_LABEL = {"doppelt": "Doppellauf", "referenz": "Doppelte Referenz", "fehler": "Fehler", "warnung": "Warnung", "wert": "Wert", "eingefroren": "Wert", "ausfall": "Ausfall", "stille": "Ruhe", "daten": "Daten"}
SERIOUS = ("TEXT_ERROR", "STATUS_ERROR", "RUN_MISSING", "VOLUME_ZERO", "STATUS_UNBEKANNT")


def _code_level(code: str, a: Optional[dict]) -> int:
    sofort = bool(a) and a["klasse"] == "sofort"
    if code in ("TEXT_ERROR", "STATUS_ERROR"):
        return 1 if sofort else 2
    if code == "RUN_MISSING":
        if sofort:
            return 1
        return 2 if len(a.get("tage", [])) == 1 else 3
    if code == "VOLUME_ZERO":
        return 1 if sofort else 2
    if code == "RUN_DUPLICATE":
        return 2 if sofort else 3
    if code in ("VOLUME_DEVIATION", "SILENCE", "STATUS_UNBEKANNT"):
        return 2
    if code == "KEINE_EINLIEFERUNG":
        return 1
    return 4  # STATUS_WARNING, VOLUME_FROZEN


def _level(raw: dict, a: Optional[dict], prior: int) -> int:
    lv = min(_code_level(c, a) for c in raw["codes"])
    if len(raw["occ"]) >= 3 and any(c in SERIOUS for c in raw["codes"]):
        lv -= 1
    if raw["kompensiert"]:
        lv += 1
    if prior and lv >= 4 and raw["family"] in ("warnung", "eingefroren"):
        lv = 3
    return max(1, min(4, lv))


def _hitl(actions: List[dict], inc_id: str, last_ts: float, as_ts: float) -> dict:
    st = {"state": "neu", "assignee": None, "state_at": None, "approved": [], "aktionen": [], "wiederaufgetreten": False}
    for ac in actions:
        if ac["incident_id"] != inc_id:
            continue
        at = parse_local(ac["at"]).timestamp()
        st["aktionen"].append({"aktion": ac["action"], "von": ac["user"], "at": ac["at"], "notiz": ac.get("note") or ""})
        k = ac["action"]
        if k == "ack":
            st.update(state="uebernommen", assignee=ac["user"], state_at=at)
        elif k == "resolve":
            st.update(state="geloest", state_at=at)
        elif k == "false_alarm":
            st.update(state="fehlalarm", state_at=at)
        elif k == "snooze":
            st.update(state="ruhend", state_at=at, snooze_until=at + 24 * 3600)
        elif k == "reopen":
            st.update(state="neu", state_at=at)
        elif k == "approve_step":
            st["approved"].append(int(ac["payload"].get("step", -1)))
    if st["state"] in ("geloest", "fehlalarm") and st["state_at"] is not None and last_ts > st["state_at"]:
        st.update(state="neu", wiederaufgetreten=True)
    if st["state"] == "ruhend" and st.get("snooze_until", 0) <= as_ts:
        st.update(state="neu")
    return st


def build(reg: Registry, store: Store, as_of: datetime) -> dict:
    as_iso = iso(as_of)
    all_runs = store.runs()
    actions = store.actions(as_iso)
    resets = {}
    for ac in actions:
        if ac["action"] == "baseline_reset":
            resets[ac["payload"].get("automation")] = parse_local(ac["at"]).timestamp()
    ev = evaluate(reg, all_runs, as_of, resets)
    as_ts = ev["as_ts"]
    runs = ev["runs"]
    runs_by: Dict[str, List[Run]] = defaultdict(list)
    for r in runs:
        runs_by[r.auto].append(r)
    raws = ev["incidents"]
    flagged = {o["lauf"] for r in raws for o in r["occ"] if o["lauf"]}

    # --- Wiederholung: gleiche Automation + Familie schon früher aufgetreten?
    raws.sort(key=lambda r: r["first_ts"])
    seen = defaultdict(int)
    for r in raws:
        r["prior"] = seen[(r["automation"], r["family"])]
        seen[(r["automation"], r["family"])] += 1

    # --- Ausfälle auf dem Laptop nach gemeinsamer Ursache bündeln (ein Gerät, eine Meldung)
    first_run_by_tool = defaultdict(list)
    for r in runs:
        first_run_by_tool[r.tool].append(r.ts)
    groups: Dict[tuple, List[dict]] = defaultdict(list)
    singles: List[dict] = []
    for r in raws:
        a = reg.autos.get(r["automation"])
        if a and r["family"] == "ausfall" and a["werkzeug"].startswith("Geplanter Task"):
            nxt = [t for t in first_run_by_tool[a["werkzeug"]] if t > r["first_ts"]]
            back = nxt[0] if nxt else None
            # Läufe der Kinder, die erst nach der Rückkehr fehlen, gehören nicht dazu
            groups[(a["werkzeug"], back)].append(r)
        else:
            singles.append(r)
    top: List[dict] = []
    for (tool, back), kids in groups.items():
        if len(kids) < 2:
            singles += kids
            continue
        for k in kids:
            def soll(o):  # maßgeblich ist der Soll-Zeitpunkt, nicht der Erkennungszeitpunkt
                return parse_local(o["slot"]).timestamp() if o.get("slot") else o["ts"]
            later = [o for o in k["occ"] if back and soll(o) > back]
            if later:
                n = dict(k)
                n.update({"occ": later, "first_ts": later[0]["ts"], "last_ts": later[-1]["ts"], "prior": k["prior"] + 1,
                          "id": "%s:ausfall:%s" % (k["automation"], iso(from_ts(later[0]["ts"]))), "kompensiert": k["kompensiert"]})
                singles.append(n)
                k["occ"] = [o for o in k["occ"] if soll(o) <= back]
                k["last_ts"] = k["occ"][-1]["ts"]
                k["recovered_ts"], k["recovered_by"], k["kompensiert"], k["weiter_als"] = None, None, False, n["id"]
        kids.sort(key=lambda k: k["first_ts"])
        first = min(k["first_ts"] for k in kids)
        g = {"id": "GRP:%s:%s" % (reg.tools[tool]["kurz"], iso(from_ts(first))), "kind": "gruppe", "family": "ausfall",
             "codes": ["RUN_MISSING"], "first_ts": first, "last_ts": max(k["last_ts"] for k in kids),
             "automations": sorted({k["automation"] for k in kids}), "children": kids, "device_back": back,
             "occ": [o for k in kids for o in k["occ"]], "prior": 0, "kompensiert": False, "frozen_notes": 0,
             "recovered_by": None}
        g["recovered_ts"] = (max((k["recovered_ts"] or back or 0) for k in kids)
                             if all(k["recovered_ts"] or k.get("weiter_als") for k in kids) else None)
        top.append(g)
    for r in singles:
        r["kind"] = "einzel"
        r["automations"] = [r["automation"]] if r["automation"] in reg.autos else []
        top.append(r)

    # --- Priorität, Titel, Texte
    for t in top:
        if t["kind"] == "gruppe":
            for k in t["children"]:
                k["kind"] = "einzel"
                k["automations"] = [k["automation"]]
                k["level"] = _level(k, reg.autos[k["automation"]], k["prior"])
            t["level"] = min(k["level"] for k in t["children"])
            d = texts.describe_group(t["children"], {"device_back": t["device_back"]})
            t["owners"] = sorted({o for k in t["children"] for o in reg.owners(k["automation"])})
            t["klasse"] = "morgen"
        elif t["automation"] == "_heartbeat":
            t["level"] = 1
            d = {"titel": "Heartbeat bekommt keine Daten", "ursachen": ["Einlieferung (Webhook/Import) unterbrochen", "Alle Quellen gleichzeitig still"],
                 "kurz": "Seit %s ist kein Lauf eingegangen. Fehlende Läufe in dieser Zeit werden bewusst NICHT einzeln gemeldet, weil nicht erkennbar ist, ob sie ausgefallen oder nur nicht angekommen sind." % fmt_dt(from_ts(t["first_ts"])),
                 "empfehlung": [texts.step("pruefen", "Einlieferung prüfen: Endpunkt erreichbar? Geheimnisse gültig? Quarantäne-Liste ansehen.")],
                 "nacharbeit": [], "wirkung": "Der Heartbeat ist blind, bis wieder Läufe eintreffen."}
            t["owners"] = ["daniel"]
            t["klasse"] = "sofort"
        else:
            a = reg.autos[t["automation"]]
            t["level"] = _level(t, a, t["prior"])
            d = texts.describe(t, a, {})
            t["owners"] = list(a["owner"])
            t["klasse"] = a["klasse"]
        t.update({k: d.get(k) for k in ("titel", "kurz", "ursachen", "empfehlung", "nacharbeit", "wirkung")})
        if t.get("prior") and t["family"] == "ausfall" and t["kind"] != "gruppe":
            a_ = reg.autos[t["automation"]]
            weekly = len(a_.get("tage", [])) == 1
            t["titel"] = ("%s: fehlt zum %d. Mal in Folge" % (a_["name"], t["prior"] + 1)) if weekly else ("%s: fällt erneut aus" % a_["name"])
            t["kurz"] = ("%s %s ist am %s wieder nicht gestartet. Der Lauf fehlte schon zuvor und ist seitdem kein einziges Mal gelaufen%s." %
                         (a_["id"], a_["name"], fmt_dt(from_ts(t["first_ts"])), " – bei einem Wochenjob sind das zwei Wochen ohne Ergebnis" if weekly else ""))
        t["level_name"] = LEVEL_NAME[t["level"]]
        t["count"] = len(t["occ"])
        t["wiederkehrend"] = t.get("prior", 0) > 0
        t["auto_status"] = "offen" if (t["recovered_ts"] is None) else "erholt"
        t["delivery"] = ("sofort" if t["klasse"] == "sofort" and t["level"] <= 2 and t["family"] != "warnung"
                         else ("morgen" if t["level"] <= 3 else "dashboard"))

    # --- Plausibilität (braucht Level/Titel der anderen)
    ctx = {"as_ts": as_ts, "flagged_runs": flagged, "runs_by": runs_by, "raws": top}
    for t in top:
        t["plausibilitaet"] = plaus.checks(reg, t, ctx)

    # --- Zustand (Human in the Loop), Spur, Anzeige
    for t in top:
        h = _hitl(actions, t["id"], t["last_ts"], as_ts)
        t.update(h)
        if t["assignee"] in reg.people:
            t["assignee"] = reg.person_name(t["assignee"])
        t["state_label"] = STATE_LABEL[t["state"]]
        rec = t["recovered_ts"]
        age_d = (as_ts - rec) / 86400.0 if rec else 0
        if t["state"] in ("geloest", "fehlalarm", "ruhend"):
            lane = "erledigt"
        elif t["level"] >= 4:
            lane = "info"
        elif t["auto_status"] == "erholt":
            lane = "erholt" if age_d <= (7 if t["level"] <= 2 else 2) or t["state"] == "uebernommen" else "erledigt"
        else:
            lane = "in_arbeit" if t["state"] == "uebernommen" else "offen"
        t["lane"] = lane
        t["im_briefing"] = lane in ("offen", "in_arbeit", "erholt") and t["level"] <= 3
        t["first"] = fmt_dt(from_ts(t["first_ts"]))
        t["first_iso"] = iso(from_ts(t["first_ts"]))
        t["last"] = fmt_dt(from_ts(t["last_ts"]))
        t["recovered"] = fmt_dt(from_ts(rec)) if rec else None
        t["recovered_iso"] = iso(from_ts(rec)) if rec else None
        end = rec if rec else as_ts
        t["dauer"] = fmt_dur(max(0, end - t["first_ts"]))
        t["owner_namen"] = [reg.person_name(o) for o in t["owners"]]
        # Beteiligte Automationen mit Namen
        t["auto_info"] = [{"id": i, "name": reg.autos[i]["name"], "werkzeug": reg.autos[i]["werkzeug"]} for i in t["automations"] if i in reg.autos] or [{"id": "_heartbeat", "name": "Heartbeat", "werkzeug": ""}]
        if t["kind"] == "gruppe":
            for k in t["children"]:
                k["recovered"] = fmt_dt(from_ts(k["recovered_ts"])) if k["recovered_ts"] else None
                k["name"] = reg.autos[k["automation"]]["name"]
                k["first"] = fmt_dt(from_ts(k["first_ts"]))
                k["count"] = len(k["occ"])
                k["owners"] = reg.owners(k["automation"])
    top.sort(key=lambda t: (0 if t["lane"] in ("offen",) else 1 if t["lane"] == "in_arbeit" else 2 if t["lane"] == "erholt" else 3 if t["lane"] == "info" else 4,
                            t["level"], 0 if t["delivery"] == "sofort" else 1, -t["last_ts"]))
    model = {"as_of": as_iso, "as_ts": as_ts, "as_label": fmt_dt(as_of), "incidents": top, "by_id": {t["id"]: t for t in top},
             "horizon": ev["horizon"], "blind": ev["blind"], "runs_by": runs_by, "flagged": flagged,
             "first_day": min((r.start.date() for r in all_runs), default=None), "last_day": max((r.end.date() for r in all_runs), default=None), "soll_ist": ev["soll_ist"], "day_runs": ev["day_runs"], "profile": profile(runs), "n_runs": len(runs), "actions": actions}
    model["grid"] = grid(reg, model, all_runs)
    return model


# ------------------------------------------------------------------ Sichten
def visible(reg: Registry, pid: str, inc: dict) -> bool:
    if inc["automations"] == ["_heartbeat"] or not inc["automations"]:
        return reg.people[pid]["sicht"] == "alle"
    return any(reg.visible_to(pid, a) for a in inc["automations"])


def for_person(reg: Registry, model: dict, pid: str) -> List[dict]:
    out = []
    for t in model["incidents"]:
        if visible(reg, pid, t):
            out.append(t)
    return out


def briefing_items(reg: Registry, model: dict, pid: str) -> List[dict]:
    """Was im Morgenbriefing von pid steht: alles Unbearbeitete, das ihn betrifft (Sofort-Meldungen wiederholen sich hier)."""
    p = reg.people[pid]
    items = []
    for t in for_person(reg, model, pid):
        if not t["im_briefing"]:
            continue
        if p["briefing"] == "eigene" and not any(pid in reg.owners(a) for a in t["automations"] if a in reg.autos) and not any(reg.visible_to(pid, a) for a in t["automations"] if a in reg.autos and reg.autos[a].get("sichtbar_fuer_alle")):
            continue
        if p["briefing"] == "eigene_und_kritisch" and not (pid in t["owners"] or t["level"] == 1):
            continue
        items.append(t)
    return items


# ------------------------------------------------------------------ Raster
def grid(reg: Registry, model: dict, all_runs: List[Run]) -> dict:
    if not all_runs:
        return {"days": [], "rows": []}
    d0 = min(r.start.date() for r in all_runs)
    last = from_ts(model["as_ts"]).date()
    days = []
    d = d0
    while d <= last:
        days.append(d)
        d += timedelta(days=1)
    days = days[-14:]
    flags: Dict[tuple, str] = {}
    ids: Dict[tuple, str] = {}
    rank = {"fail": 3, "miss": 2, "warn": 1}
    child_to_top = {}
    for t in model["incidents"]:
        if t["kind"] == "gruppe":
            for k in t["children"]:
                child_to_top[k["id"]] = t["id"]
    raws = []
    for t in model["incidents"]:
        raws += t["children"] if t["kind"] == "gruppe" else [t]
    for r in raws:
        if r["automations"] == ["_heartbeat"]:
            continue
        fam = r["family"]
        st = "fail" if fam in ("fehler", "wert", "daten") else "miss" if fam == "ausfall" else "warn"
        for o in r["occ"]:
            day = from_ts(o["ts"]).date().isoformat()
            k = (r["automation"], day)
            if rank[st] > rank.get(flags.get(k, ""), 0):
                flags[k] = st
                ids[k] = child_to_top.get(r["id"], r["id"])
    rows = []
    for aid, a in reg.autos.items():
        cells = []
        for d in days:
            ds = d.isoformat()
            soll, ist = model["soll_ist"].get(aid, {}).get(ds, (0, 0))
            n = model["day_runs"].get(aid, {}).get(ds, 0)
            st = flags.get((aid, ds))
            if st is None:
                if n:
                    st = "ok"
                elif a["art"] == "zeit" and soll == 0 and not reg.slots(aid, d):
                    st = "na"
                else:
                    st = "na"
            txt = ("%d von %d Soll-Läufen" % (ist, soll)) if a["art"] == "zeit" and soll else ("%d Läufe" % n if n else "")
            cells.append({"d": ds, "s": st, "soll": soll, "ist": ist, "n": n, "txt": txt, "inc": ids.get((aid, ds))})
        rows.append({"id": aid, "name": a["name"], "werkzeug": a["werkzeug"], "owner": [reg.person_name(o) for o in a["owner"]],
                     "klasse": a["klasse"], "cells": cells})
    return {"days": [{"iso": d.isoformat(), "label": fmt_day(d), "wd": d.weekday()} for d in days], "rows": rows}


def tag_bilanz(reg: Registry, model: dict, pid: str, tag) -> dict:
    """Soll/Ist für einen Tag, nur Automationen, die pid sehen darf."""
    soll = ist = 0
    ds = tag.isoformat()
    for aid in reg.autos:
        if not reg.visible_to(pid, aid):
            continue
        s, i = model["soll_ist"].get(aid, {}).get(ds, (0, 0))
        soll += s
        ist += i
    return {"label": fmt_day(tag), "soll": soll, "ist": ist}
