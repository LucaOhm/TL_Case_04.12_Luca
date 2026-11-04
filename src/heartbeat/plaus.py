"""Plausibilität: jede Auffälligkeit wird gegen andere Läufe und Automationen gegengeprüft.

Stärken:  belegt (steht so im Protokoll) · hinweis (Muster in den Daten) · hypothese (Schluss/Annahme, nicht belegt)
Alles hier ist lesend und regelbasiert. Die optionale KI-Analyse (analyst.py) bekommt diese Befunde als Belege.
"""
from __future__ import annotations

from typing import Dict, List

from .core import Registry, fmt_dt, from_ts, median


def _g(x) -> str:
    return ("%g" % round(x, 1)).replace(".", ",")


def _item(titel: str, text: str, staerke: str, belege: List[str] = None) -> dict:
    return {"titel": titel, "text": text, "staerke": staerke, "belege": belege or []}


def checks(reg: Registry, inc: dict, ctx: dict) -> List[dict]:
    out: List[dict] = []
    autos = inc["automations"]
    t0 = inc["first_ts"]
    t1 = inc["recovered_ts"] or ctx["as_ts"]
    flagged = ctx["flagged_runs"]
    runs_by = ctx["runs_by"]
    others = [i for i in ctx["raws"] if i["id"] != inc["id"]]

    def ok_runs(aid: str, lo: float, hi: float):
        return [r for r in runs_by.get(aid, []) if lo <= r.ts <= hi and r.id not in flagged and r.klass == "ok"]

    code = inc["codes"][0]
    a = reg.autos.get(autos[0]) if autos and autos[0] in reg.autos else None

    # 1) Umfang eingrenzen: liefen andere Automationen im selben Zeitraum normal?
    if inc["kind"] == "gruppe":
        lo, hi = t0, inc.get("device_back") or t1
        fremd = [r for aid, rs in runs_by.items() if reg.tool_of(aid) != a["werkzeug"] for r in rs
                 if lo <= r.ts <= hi and r.id not in flagged and r.klass == "ok"]
        if fremd:
            out.append(_item("Nur der Laptop betroffen",
                             "Im selben Zeitraum liefen %d Läufe von Make und Cloud-Routinen normal. Der Ausfall ist auf den Laptop begrenzt, nicht auf das Netz oder die Plattformen." % len(fremd),
                             "belegt"))
    elif a and code == "RUN_MISSING":
        lo, hi = t0 - 5400, t0 + 5400
        ps = [(x["id"], ok_runs(x["id"], lo, hi)) for x in reg.autos.values() if x["werkzeug"] == a["werkzeug"] and x["id"] != a["id"]]
        ps = [(i, r) for i, r in ps if r]
        if ps:
            out.append(_item("Plattform lief, nur diese Aufgabe nicht",
                             "Zur selben Zeit liefen %s normal (%s). Das Gerät bzw. die Plattform war verfügbar – %s selbst startet nicht (deaktiviert, gelöscht oder defekt)." %
                             (", ".join(i for i, _ in ps), a["werkzeug"], a["id"]), "belegt", [r[0].id for _, r in ps][:3]))
    elif a and code in ("TEXT_ERROR", "STATUS_ERROR"):
        peers = [x for x in reg.autos.values() if x["werkzeug"] == a["werkzeug"] and x["id"] != a["id"]]
        if a.get("slack_post"):
            ps = [(x["id"], ok_runs(x["id"], t0, t1)) for x in peers if x.get("slack_post")]
            ps = [(i, r) for i, r in ps if r]
            if ps:
                out.append(_item("Andere Kanäle funktionieren",
                                 "Im selben Zeitraum posteten %s erfolgreich in ihre Kanäle. Slack und Make sind erreichbar, das Problem liegt beim Ziel von %s (%s)." %
                                 (", ".join(i for i, _ in ps), a["id"], a.get("ziel", "Ziel")), "belegt", [r[0].id for _, r in ps][:3]))
        else:
            ps = [(x["id"], ok_runs(x["id"], t0, t1)) for x in peers]
            ps = [(i, r) for i, r in ps if r]
            if ps:
                out.append(_item("Andere Szenarien laufen",
                                 "Andere %s-Läufe (%s) liefen im selben Zeitraum fehlerfrei. Das Problem ist auf diese eine Verbindung/Datenquelle begrenzt." %
                                 (a["werkzeug"].split(" ")[0], ", ".join(i for i, _ in ps[:5])), "hinweis"))
        # Anteil betroffener Läufe
        alle = [r for r in runs_by.get(a["id"], []) if t0 - 120 <= r.ts and (r.ts < t1 if inc["recovered_ts"] else r.ts <= t1)]
        bad = [r for r in alle if r.id in flagged]
        if len(alle) >= 3 and bad:
            out.append(_item("Dauerzustand, kein Ausreißer",
                             "%d von %d Läufen im Zeitraum sind betroffen (%d %%). Kein einzelner Aussetzer." % (len(bad), len(alle), round(100.0 * len(bad) / len(alle))), "belegt"))
        if a["art"] == "ereignis":
            tage = {}
            for r in runs_by.get(a["id"], []):
                if r.ts < t0 and r.id not in flagged:
                    tage.setdefault(r.start.date(), 0)
                    tage[r.start.date()] += 1
            if tage:
                out.append(_item("Menge allein hätte nichts gezeigt",
                                 "Pro Tag liefen weiter etwa so viele Läufe wie üblich (Median %s/Tag vorher). Nur die Prüfung des Detailtexts erkennt diesen Fehler." %
                                 (_g(median(list(tage.values())))), "hinweis"))

    # 2) Geschwister-Kennzahlen (z. B. Deal-Zahlen aus A09, A10, A15)
    if a and a.get("gruppe") and code in ("VOLUME_ZERO", "VOLUME_DEVIATION"):
        for m in reg.autos.values():
            if m.get("gruppe") != a["gruppe"] or m["id"] == a["id"]:
                continue
            allv = [r for r in runs_by.get(m["id"], []) if r.id not in flagged and r.count]
            vor = [r.count for r in allv if r.ts < t0][-14:]
            wahr = [r.count for r in allv if t0 <= r.ts <= t1]
            if not vor:
                continue
            base = median(vor)
            if wahr:
                pct = 100.0 * (median(wahr) - base) / base
                if abs(pct) < 5:
                    if code == "VOLUME_ZERO":
                        txt = ("%s %s meldet im selben Zeitraum weiter ≈ %s %s (Median davor %s). Die Deals sind also im CRM vorhanden – die Bewertung durch %s ist falsch, nicht der Bestand." %
                               (m["id"], m["name"], _g(median(wahr)), m["anzahl"].lower(), _g(base), a["id"]))
                    else:
                        txt = ("%s %s liegt im selben Zeitraum unverändert bei ≈ %s (Median davor %s). Der Bestand offener Deals hat sich also nicht um den Sprung von %s verändert. "
                               "Die Ursache liegt wahrscheinlich im Filter oder Datenabruf von %s." % (m["id"], m["name"], _g(median(wahr)), _g(base), a["id"], a["id"]))
                    out.append(_item("Gegenprobe über %s" % m["id"], txt, "hinweis" if code == "VOLUME_DEVIATION" else "belegt"))
                else:
                    out.append(_item("Gegenprobe über %s" % m["id"],
                                     "%s bewegt sich im selben Zeitraum ebenfalls (%+.0f %% gegen Median %s). Eine echte Änderung im CRM wird wahrscheinlicher." % (m["id"], pct, _g(base)), "hinweis"))
            else:
                if ok_runs(m["id"], t0, t1) == [] and any(r.ts >= t0 and r.id in flagged for r in runs_by.get(m["id"], [])):
                    why = "%s ist im Zeitraum selbst auffällig, eine Gegenprobe ist damit nicht möglich." % m["id"]
                else:
                    why = "%s ist im Zeitraum noch nicht gelaufen. Die Gegenprobe steht aus (nächstes Soll: %s)." % (m["id"], m["zeitplan"])
                out.append(_item("Gegenprobe über %s offen" % m["id"], why, "hinweis"))

    # 3) Folgeschäden: was lief während der Störung und baut darauf auf?
    if a and a.get("speist") and code in ("VOLUME_ZERO", "VOLUME_DEVIATION", "TEXT_ERROR", "STATUS_ERROR"):
        for d in a["speist"]:
            hits = [r for r in runs_by.get(d, []) if t0 <= r.ts <= t1]
            for r in hits:
                out.append(_item("Folgebericht prüfen",
                                 "%s %s entstand am %s und damit während der Störung von %s. Annahme: Er nutzt dessen Scores. Inhalt prüfen oder neu erzeugen." %
                                 (d, reg.autos[d]["name"], fmt_dt(r.start), a["id"]), "hypothese", [r.id]))

    # 4) Zeitliche Nähe zu anderen Störungen (mögliche gemeinsame Ursache)
    if inc["kind"] != "gruppe" and inc["level"] <= 3:
        for o in others:
            if o.get("kind") == "gruppe" or o["level"] > 3 or set(o["automations"]) & set(autos):
                continue
            if abs(o["first_ts"] - inc["first_ts"]) <= 3 * 3600:
                out.append(_item("Zeitlich nah an %s" % o["automations"][0],
                                 "%s begann %s, also %d Min. %s. Eine gemeinsame Ursache (Token, Berechtigung, Workspace-Änderung) ist möglich, aber nicht belegt." %
                                 (o["titel"], fmt_dt(from_ts(o["first_ts"])), round(abs(o["first_ts"] - inc["first_ts"]) / 60), "später" if o["first_ts"] > inc["first_ts"] else "früher"),
                                 "hypothese"))

    # 5) Wiederholungsmuster (gleiche Art, gleiche Uhrzeit)
    same = sorted([i for i in ctx["raws"] if i["automations"] == autos and i["family"] == inc["family"] and i["kind"] != "gruppe"], key=lambda i: i["first_ts"])
    if len(same) >= 2:
        stunden = {from_ts(i["first_ts"]).hour for i in same}
        if len(stunden) == 1:
            out.append(_item("Immer zur selben Uhrzeit",
                             "%d Vorfälle in den Daten, alle gegen %02d:00 Uhr (%s). Das spricht für eine zeitgebundene Ursache, z. B. gleichzeitige Last zum Tagesabschluss. Lauf versetzen testen." %
                             (len(same), stunden.pop(), ", ".join(fmt_dt(from_ts(i["first_ts"])) for i in same)), "hinweis"))

    # 6) Normalfall-Einordnung: ist 0 bei dieser Automation üblich?
    if a and code == "STATUS_WARNING":
        rs = runs_by.get(a["id"], [])
        zs = [r for r in rs if r.count == 0]
        o = inc["occ"][0]
        run = next((r for r in rs if r.id == o.get("lauf")), None)
        if run is not None and run.count == 0 and rs:
            out.append(_item("0 ist hier nichts Besonderes",
                             "Bei %s liegen %d von %d Läufen (%d %%) bei 0. Dass beim gedrosselten Lauf nichts zugewiesen wurde, ist deshalb nicht ungewöhnlich. "
                             "Ob der Retry etwas verpasst hat, lässt sich nur über das Ziel-System prüfen." % (a["id"], len(zs), len(rs), round(100.0 * len(zs) / len(rs))), "hinweis"))

    # 7) Nachholung bewerten
    if inc["kompensiert"] and inc.get("recovered_by") and a:
        rr = next((r for r in runs_by.get(a["id"], []) if r.id == inc["recovered_by"]), None)
        if rr is not None and rr.count is not None:
            vals = [r.count for r in runs_by.get(a["id"], []) if r.klass == "ok" and r.id not in flagged and r.start.weekday() < 5 and r.count is not None]
            med = median(vals) if vals else None
            if med is not None:
                out.append(_item("Nachlauf bewertet",
                                 "Der Folgelauf um %s lieferte %d (Median %s). Die Lücke ist damit nach Menge plausibel geschlossen." % (fmt_dt(rr.start), rr.count, _g(med)), "belegt", [rr.id]))
    return out
