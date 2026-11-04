"""Zustellung: Sofortmeldungen (nur kritische Kunden-/Geld-Fälle, direkt an den Owner), Eskalation, Entwarnung und das Morgenbriefing.

Regeln
  • Sofort-Klasse (A02, A03, A07, A22) und Priorität P1/P2 -> sofort an den Owner, nicht erst morgens.
  • Niemand übernimmt innerhalb von 60 Min. oder der Fehler tritt zum 3. Mal auf -> Eskalation an Daniel (Chief of Staff).
  • Alles andere: einmal am Morgen, je Person gebündelt. Unbearbeitetes (auch schon sofort Gemeldetes) steht dort erneut.
  • Auch ein leeres Briefing wird gesendet: bleibt es aus, ist der Heartbeat selbst das Problem.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from . import insight, slack
from .core import Registry, day_start, fmt_dt, from_ts, iso, parse_local
from .engine import BLIND_AFTER_S


def _ack_ts(model: dict, inc_id: str):
    for ac in model["actions"]:
        if ac["incident_id"] == inc_id and ac["action"] in ("ack", "resolve", "false_alarm"):
            return parse_local(ac["at"]).timestamp()
    return None


def sofort_events(reg: Registry, model: dict, get_model: Optional[Callable[[datetime], dict]] = None) -> List[dict]:
    """Nachrichten, die bis zum Auswertungszeitpunkt hätten rausgehen müssen. Inhalt = Stand zum Versandzeitpunkt
    (die Meldung um 07:39 nennt 1 Ticket, nicht den Stand von morgen)."""
    out = []
    as_ts, as_iso = model["as_ts"], model["as_of"]

    def at(t_inc: dict, ts: float) -> dict:
        if get_model is None:
            return t_inc
        return get_model(from_ts(ts + 1))["by_id"].get(t_inc["id"], t_inc)

    for t in model["incidents"]:
        if t["kind"] == "gruppe" or t["delivery"] != "sofort":
            continue
        occ = t["occ"]
        t0 = occ[0]["ts"]

        def upto(ts):
            return [o for o in occ if o["ts"] <= ts]

        s0 = at(t, t0)
        for pid in t["owners"]:
            o = upto(t0)
            out.append({"key": "alert:%s:%s" % (t["id"], pid), "typ": "alert", "at_ts": t0, "an": pid, "incident": t["id"],
                        "slack": slack.alert(s0, pid, reg.people[pid]["slack"], as_iso, len(o), [r for x in o for r in x.get("refs", [])])})
        third = occ[2]["ts"] if len(occ) >= 3 else None
        e = min([t0 + reg.escalate_min * 60] + ([third] if third else []))
        ack = _ack_ts(model, t["id"])
        if as_ts >= e and not (ack is not None and ack <= e) and "daniel" not in t["owners"]:
            o = upto(e)
            out.append({"key": "esk:%s:daniel" % t["id"], "typ": "eskalation", "at_ts": e, "an": "daniel", "incident": t["id"],
                        "slack": slack.alert(at(t, e), "daniel", reg.people["daniel"]["slack"], as_iso, len(o), [r for x in o for r in x.get("refs", [])],
                                             True, int(round((e - t0) / 60)), t["owner_namen"])})
        if t["recovered_ts"] and as_ts >= t["recovered_ts"] and t["level"] <= 2:
            for pid in t["owners"]:
                out.append({"key": "ok:%s:%s" % (t["id"], pid), "typ": "entwarnung", "at_ts": t["recovered_ts"], "an": pid, "incident": t["id"],
                            "slack": slack.entwarnung(t, pid, reg.people[pid]["slack"], as_iso)})
    return out


def briefing_message(reg: Registry, model: dict, pid: str, deliver: Optional[datetime] = None) -> dict:
    as_of = from_ts(model["as_ts"])
    if deliver is None:
        deliver = as_of
    tag = (deliver - timedelta(days=1)).date() if deliver.hour < 12 else deliver.date()
    items = insight.briefing_items(reg, model, pid)
    n_info = sum(1 for t in insight.for_person(reg, model, pid) if t["lane"] == "info")
    tools = {r.tool for rs in model["runs_by"].values() for r in rs}
    last = max((r.end for rs in model["runs_by"].values() for r in rs), default=as_of)
    sc = "Prüfung lief %s · %d Läufe aus %d Quellen gelesen · Datenstand bis %s" % (fmt_dt(deliver), model["n_runs"], len(tools), fmt_dt(last))
    return slack.briefing(reg.people[pid], pid, model["as_of"], fmt_dt(deliver), insight.tag_bilanz(reg, model, pid, tag), items, n_info, sc)


def morning_points(store, until: datetime) -> List[tuple]:
    """Briefing-Punkte (Zustellung 07:00, Auswertungszeitpunkt).

    Normalfall: Auswertung = 07:00 des Folgetags. Liegen die Daten nur bis in den Vortag (z. B. nur die Läufe vom 26.10.),
    wird der Tagesabschluss 00:00 ausgewertet und der Datenstand im Briefing offen genannt. Liegt auch das mehr als
    5 Std. hinter dem letzten Lauf, gibt es keinen Punkt (sonst würde ein Datenloch als Ausfall erscheinen)."""
    runs = store.runs()
    if not runs:
        return []
    first = runs[0].start.date()
    last_end = max(r.end for r in runs)
    pts = []
    d = first + timedelta(days=1)
    while True:
        deliver = day_start(d).replace(hour=7)
        if day_start(d).timestamp() - last_end.timestamp() > BLIND_AFTER_S:
            break
        ev = deliver if last_end.timestamp() + BLIND_AFTER_S >= deliver.timestamp() else day_start(d)
        if ev <= until:
            pts.append((deliver, ev))
        d += timedelta(days=1)
    return pts


def timeline(reg: Registry, store, as_of: datetime, pid: str, get_model: Callable[[datetime], dict], tage: int = 3) -> List[dict]:
    """Alles, was pid bis as_of in Slack bekommen hätte (für die Mock-Oberfläche und die echte Zustellung)."""
    out = []
    cur = get_model(as_of)
    for e in sofort_events(reg, cur, get_model):
        if e["an"] == pid and e["at_ts"] <= cur["as_ts"]:
            out.append(e)
    for deliver, ev in morning_points(store, as_of):
        if (as_of - ev) > timedelta(days=tage):
            continue
        m = get_model(ev)
        out.append({"key": "brief:%s:%s" % (iso(deliver), pid), "typ": "briefing", "at_ts": deliver.timestamp(), "an": pid, "incident": "",
                    "slack": briefing_message(reg, m, pid, deliver)})
    for e in out:
        e["at"] = iso(from_ts(e["at_ts"]))
        e["label"] = fmt_dt(from_ts(e["at_ts"]))
    out.sort(key=lambda e: (e["at_ts"], 0 if e["typ"] != "briefing" else 1))
    return out


def deliver(reg: Registry, store, transport, as_of: datetime, get_model: Callable[[datetime], dict]) -> int:
    """Echte Zustellung (idempotent): sendet jede Nachricht genau einmal, auch bei wiederholtem Aufruf."""
    n = 0
    for pid in reg.people:
        for e in timeline(reg, store, as_of, pid, get_model, tage=0):
            if store.mark_sent(e["key"], iso(as_of), transport.name):
                if transport.send(e["slack"]):
                    n += 1
    return n
