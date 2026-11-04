"""Anwendungskern: ein Objekt, das Registry, Speicher, Auswertung, Slack-Zeitlinie, Human-in-the-Loop und KI zusammenhält.
Der HTTP-Server (server.py) ist nur eine dünne Hülle darum."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from . import alerts, analyst, hitl, ingest, insight, slack
from .core import Registry, Run, fmt_day, fmt_dt, from_ts, iso, parse_local
from .store import Store

PUBLIC = ("id", "kind", "titel", "kurz", "level", "level_name", "family", "codes", "lane", "state", "state_label", "assignee",
          "wiederaufgetreten", "delivery", "klasse", "auto_status", "first", "first_iso", "last", "recovered", "recovered_iso",
          "dauer", "count", "wiederkehrend", "owner_namen", "owners", "auto_info", "wirkung", "frozen_notes", "approved", "automations")


class App:
    def __init__(self, store: Store, ai: Optional[analyst.Analyst] = None):
        self.store = store
        self.reg: Registry = store.reg
        self.ai = ai or analyst.Analyst.from_env()
        self._cache: Dict[tuple, dict] = {}
        self.secrets = ingest.load_secrets(self.reg)

    # ---------------------------------------------------------- Modell
    def model(self, as_of: datetime) -> dict:
        key = (iso(as_of), self.store.version)
        if key not in self._cache:
            if len(self._cache) > 60:
                self._cache.clear()
            self._cache[key] = insight.build(self.reg, self.store, as_of)
        return self._cache[key]

    def parse_t(self, t: Optional[str]) -> datetime:
        if t:
            return parse_local(t)
        pts = self.points()
        return parse_local(pts[-1]["iso"]) if pts else parse_local("2026-10-13 07:00")

    def points(self) -> List[dict]:
        out = []
        runs = self.store.runs()
        if not runs:
            return out
        last_end = max(r.end for r in runs)
        for deliver, ev in alerts.morning_points(self.store, last_end.replace(year=last_end.year + 1)):
            out.append({"iso": iso(ev), "deliver": iso(deliver), "label": fmt_dt(deliver), "tag": fmt_day(deliver.date()),
                        "teilweise": ev != deliver, "daten_bis": fmt_dt(last_end) if ev != deliver else ""})
        return out

    # ---------------------------------------------------------- Öffentliche Sicht
    def _public(self, t: dict, pid: str) -> dict:
        d = {k: t.get(k) for k in PUBLIC}
        d["can_act"] = hitl.may_act(self.reg, pid, t)
        if t["kind"] == "gruppe":
            d["children"] = [{"automation": k["automation"], "name": k["name"], "count": k["count"], "first": k["first"], "recovered": k["recovered"],
                              "mine": self.reg.visible_to(pid, k["automation"])} for k in t["children"]]
        return d

    def state(self, t_iso: Optional[str], pid: str) -> dict:
        as_of = self.parse_t(t_iso)
        m = self.model(as_of)
        reg = self.reg
        person = reg.people[pid]
        mine = insight.for_person(reg, m, pid)
        deliver = None
        for pt in self.points():
            if pt["iso"] == iso(as_of):
                deliver = pt
        if deliver:
            tag = parse_local(deliver["deliver"]).date() - timedelta(days=1)
        else:
            tag = (as_of - timedelta(days=1)).date() if as_of.hour < 12 else as_of.date()
        bil = insight.tag_bilanz(reg, m, pid, tag)
        lanes = [t["lane"] for t in mine]
        kpi = {"wartet": sum(1 for t in mine if t["lane"] == "offen"), "in_arbeit": lanes.count("in_arbeit"),
               "erholt": lanes.count("erholt"), "kritisch": sum(1 for t in mine if t["level"] == 1 and t["lane"] in ("offen", "in_arbeit")),
               "info": lanes.count("info"), "erledigt": lanes.count("erledigt")}
        gr = m["grid"]
        grid = {"days": gr["days"], "rows": [r for r in gr["rows"] if reg.visible_to(pid, r["id"])]}
        by_inc: Dict[str, int] = {}
        for t in m["incidents"]:
            if t["lane"] in ("offen", "in_arbeit"):
                for a in t["automations"]:
                    by_inc[a] = min(by_inc.get(a, 9), t["level"])
        autos = []
        for aid, a in reg.autos.items():
            if not reg.visible_to(pid, aid):
                continue
            rs = m["runs_by"].get(aid, [])
            last = rs[-1] if rs else None
            pr = m["profile"].get(aid, {})
            autos.append({"id": aid, "name": a["name"], "werkzeug": a["werkzeug"], "owner": [reg.person_name(o) for o in a["owner"]],
                          "klasse": a["klasse"], "zeitplan": a["zeitplan"], "liefert": a["liefert"],
                          "letzter": fmt_dt(last.start) if last else "–", "letzter_status": last.status if last else "",
                          "median_anzahl": pr.get("median_anzahl"), "median_dauer_s": pr.get("median_dauer_s"), "n": pr.get("n", 0),
                          "level": by_inc.get(aid)})
        tools = {r.tool for rs in m["runs_by"].values() for r in rs}
        rej = self.store.rejects(5)
        sc = {"laeufe": m["n_runs"], "quellen": len(tools), "daten_bis": fmt_dt(from_ts(m["horizon"])) if m["horizon"] else "–",
              "blind": m["blind"], "von": fmt_day(m["first_day"]) if m.get("first_day") else "", "bis": fmt_day(m["last_day"]) if m.get("last_day") else "", "quarantaene": len(self.store.rejects(500)),
              "ki": ("bereit: " + ", ".join(p.name for p in self.ai.providers if getattr(p, "available", False))) if any(getattr(p, "available", False) for p in self.ai.providers) else "Regelwerk (kein API-Schlüssel gesetzt)"}
        brief = alerts.briefing_message(reg, m, pid, parse_local(deliver["deliver"]) if deliver else None)
        return {"as_of": iso(as_of), "label": fmt_dt(as_of), "deliver_label": fmt_dt(parse_local(deliver["deliver"])) if deliver else fmt_dt(as_of), "teilweise": bool(deliver and deliver["teilweise"]), "daten_bis": deliver["daten_bis"] if deliver else "",
                "user": {"id": pid, "name": person["name"], "rolle": person["rolle"], "alle": person["sicht"] == "alle"},
                "users": [{"id": k, "name": v["name"], "rolle": v["rolle"], "alle": v["sicht"] == "alle"} for k, v in reg.people.items()],
                "points": self.points(), "kpi": kpi, "bilanz": bil, "incidents": [self._public(t, pid) for t in mine],
                "grid": grid, "automations": autos, "selfcheck": sc, "briefing": brief, "rejects": rej}

    # ---------------------------------------------------------- Detail
    def _rows(self, m: dict, t: dict) -> List[dict]:
        by_id = {r.id: r for rs in m["runs_by"].values() for r in rs}
        raws = t["children"] if t["kind"] == "gruppe" else [t]
        rows, seen = [], set()
        for r in raws:
            a = r["automation"]
            rs = [x for x in m["runs_by"].get(a, []) if x.id not in m["flagged"] and x.klass == "ok" and x.ts < r["first_ts"]]
            if rs and rs[-1].id not in seen:
                seen.add(rs[-1].id)
                rows.append(dict(rs[-1].row(), markierung="letzter guter Lauf", sort=rs[-1].ts))
            for o in r["occ"]:
                if o["lauf"] and o["lauf"] in by_id:
                    if o["lauf"] not in seen:
                        seen.add(o["lauf"])
                        x = by_id[o["lauf"]]
                        rows.append(dict(x.row(), markierung="betroffen", sort=x.ts))
                else:
                    rows.append({"lauf_id": "–", "automation_id": a, "start": o["slot"] or o["t"], "ende": "", "status": "kein Lauf", "anzahl": None,
                                 "detail": o["detail"], "markierung": "fehlt", "sort": parse_local(o["slot"] or o["t"]).timestamp()})
            if r["recovered_by"] and r["recovered_by"] in by_id and r["recovered_by"] not in seen:
                x = by_id[r["recovered_by"]]
                seen.add(x.id)
                rows.append(dict(x.row(), markierung="wieder normal", sort=x.ts))
        rows.sort(key=lambda x: x["sort"])
        for x in rows:
            x.pop("sort", None)
        return rows

    def detail(self, t_iso: Optional[str], pid: str, inc_id: str) -> Optional[dict]:
        as_of = self.parse_t(t_iso)
        m = self.model(as_of)
        t = m["by_id"].get(inc_id)
        if not t or not insight.visible(self.reg, pid, t):
            return None
        d = self._public(t, pid)
        appr = set(t["approved"])
        d["empfehlung"] = [dict(s, idx=i, freigegeben=i in appr) for i, s in enumerate(t["empfehlung"] or [])]
        d.update({k: t.get(k) for k in ("ursachen", "nacharbeit", "plausibilitaet", "aktionen")})
        d["protokoll"] = self._rows(m, t)
        ver = [{"t": t["first_iso"], "label": t["first"], "text": "Erkannt", "art": "erkannt"}]
        occ = t["occ"]
        if len(occ) >= 3:
            ver.append({"t": occ[2]["t"], "label": fmt_dt(from_ts(occ[2]["ts"])), "text": "3. Vorfall: tritt wiederholt auf", "art": "wdh"})
        for e in alerts.sofort_events(self.reg, m):
            if e["incident"] == inc_id:
                txt = {"alert": "Sofortmeldung an %s", "eskalation": "Eskalation an %s", "entwarnung": "Entwarnung an %s"}[e["typ"]] % self.reg.person_name(e["an"])
                ver.append({"t": iso(from_ts(e["at_ts"])), "label": fmt_dt(from_ts(e["at_ts"])), "text": txt + " (Slack)", "art": "slack"})
        for ac in t["aktionen"]:
            ver.append({"t": ac["at"], "label": fmt_dt(parse_local(ac["at"])), "text": "%s: %s" % (self.reg.person_name(ac["von"]), {
                "ack": "übernommen", "resolve": "als gelöst bestätigt", "false_alarm": "als Fehlalarm markiert", "snooze": "24 h zurückgestellt",
                "reopen": "wieder geöffnet", "approve_step": "Änderung freigegeben", "baseline_reset": "aktuelles Niveau als neues Normal übernommen"}.get(ac["aktion"], ac["aktion"])), "art": "mensch"})
        if t["recovered_iso"]:
            ver.append({"t": t["recovered_iso"], "label": t["recovered"], "text": "Wieder normal", "art": "ok"})
        ver.sort(key=lambda x: x["t"])
        d["verlauf"] = ver
        d["analyse"] = self.store.analysis(inc_id)
        d["ki_bereit"] = any(getattr(p, "available", False) for p in self.ai.providers)
        return d

    # ---------------------------------------------------------- Slack-Mock
    def slack_feed(self, t_iso: Optional[str], pid: str) -> dict:
        as_of = self.parse_t(t_iso)
        msgs = alerts.timeline(self.reg, self.store, as_of, pid, self.model)
        people = [{"id": k, "name": v["name"], "slack": v["slack"], "rolle": v["rolle"]} for k, v in self.reg.people.items()]
        return {"as_of": iso(as_of), "label": fmt_dt(as_of), "user": pid, "people": people,
                "messages": [{"key": e["key"], "typ": e["typ"], "at": e["at"], "label": e["label"], "incident": e["incident"], "slack": e["slack"]} for e in msgs]}

    # ---------------------------------------------------------- Aktionen
    def act(self, t_iso: Optional[str], pid: str, inc_id: str, action: str, note: str = "", step: int = -1) -> Tuple[bool, str]:
        as_of = self.parse_t(t_iso)
        if pid not in self.reg.people:
            return False, "Unbekannte Person"
        m = self.model(as_of)
        return hitl.apply(self.reg, self.store, m, pid, inc_id, action, iso(as_of), note, step)

    def analyse(self, t_iso: Optional[str], pid: str, inc_id: str) -> Tuple[bool, dict]:
        d = self.detail(t_iso, pid, inc_id)
        if not d:
            return False, {"fehler": "nicht gefunden"}
        m = self.model(self.parse_t(t_iso))
        bundle = analyst.evidence_bundle(m["by_id"][inc_id], d["protokoll"])
        res = self.ai.analyse(bundle)
        self.store.save_analysis(inc_id, iso(self.parse_t(t_iso)), res["quelle"], res["status"], res["body"])
        return True, self.store.analysis(inc_id)

    # ---------------------------------------------------------- Einlieferung
    def upload(self, data, filename: str = "") -> dict:
        if isinstance(data, str):
            data = data.encode("utf-8")
        res = ingest.import_bytes(self.store, data, filename, "upload")
        self._cache.clear()
        pts = self.points()
        return dict(res, neuester=pts[-1]["label"] if pts else "")
