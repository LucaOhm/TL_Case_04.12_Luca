"""Kommandozeile:  python -m heartbeat <befehl>   (aus dem Ordner src/ starten)

  serve     Dashboard- und Slack-Mockup starten (liest beim ersten Start data/laeufe*.csv ein)
  import    weitere Lauf-CSVs einspielen (z. B. die Läufe vom 26.10.), idempotent
  briefing  das Morgenbriefing für einen Tag im Terminal ausgeben
  status    kurze Lageübersicht für alle Rollen
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

from . import alerts, ingest
from .app import App
from .core import ROOT, fmt_dt, iso, parse_local
from .store import DB_DEFAULT, Store


EMOJI = {":sunrise:": "☀", ":red_circle:": "(P1)", ":large_orange_circle:": "(P2)", ":large_yellow_circle:": "(P3)", ":white_circle:": "(P4)",
         ":rotating_light:": "!!", ":white_check_mark:": "✓"}


def _plain(s: str) -> str:
    for k, v in EMOJI.items():
        s = s.replace(k, v)
    return s.replace("*", "")


def render(m: dict) -> str:
    out = []
    for b in m["blocks"]:
        t = b["type"]
        if t == "header":
            h = _plain(b["text"]["text"])
            out.append("\n" + h)
            out.append("=" * min(78, len(h)))
        elif t == "section":
            out.append(_plain(b["text"]["text"]))
            for f in b.get("fields", []):
                out.append("  " + _plain(f["text"]).replace("\n", ": "))
        elif t == "context":
            out.append("  (" + " · ".join(e["text"].replace("*", "") for e in b["elements"]) + ")")
        elif t == "divider":
            out.append("-" * 78)
        elif t == "actions":
            out.append("  [" + "] [".join(e["text"]["text"] for e in b["elements"]) + "]")
    return "\n".join(out)


def seed(store: Store) -> None:
    if store.run_count() == 0:
        for f in sorted((ROOT / "data").glob("laeufe*.csv")):
            r = ingest.import_csv(store, f)
            print("Eingelesen: %s -> %s" % (f.name, r))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="heartbeat")
    ap.add_argument("--db", default=str(DB_DEFAULT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--fresh", action="store_true", help="Datenbank leeren und neu einlesen")
    i = sub.add_parser("import")
    i.add_argument("files", nargs="+")
    b = sub.add_parser("briefing")
    b.add_argument("--day", help="Berichtstag, z. B. 2026-10-26 (Briefing kommt am Folgetag 07:00)")
    b.add_argument("--user", default="daniel")
    sub.add_parser("status")
    a = ap.parse_args(argv)

    store = Store(a.db)
    if a.cmd == "serve":
        if a.fresh:
            store.reset_all()
        seed(store)
        from .server import serve
        serve(App(store), a.host, a.port)
        return 0
    if a.cmd == "import":
        for f in a.files:
            print(f, "->", ingest.import_csv(store, Path(f)))
        return 0
    seed(store)
    app = App(store)
    if a.cmd == "briefing":
        pts = app.points()
        if not pts:
            print("Keine Daten.")
            return 1
        pt = pts[-1]
        if a.day:
            want = (parse_local(a.day + " 00:00") + timedelta(days=1)).date().isoformat()
            hits = [p for p in pts if p["deliver"].startswith(want)]
            if not hits:
                print("Für %s liegen keine Daten vor. Verfügbar: %s … %s" % (a.day, pts[0]["tag"], pts[-1]["tag"]))
                return 1
            pt = hits[0]
        m = app.model(parse_local(pt["iso"]))
        users = list(app.reg.people) if a.user == "all" else [a.user]
        for u in users:
            msg = alerts.briefing_message(app.reg, m, u, parse_local(pt["deliver"]))
            print(render(msg))
            print()
        if pt["teilweise"]:
            print("Hinweis: Daten liegen nur bis %s vor, ausgewertet wurde der Tagesabschluss." % pt["daten_bis"])
        return 0
    if a.cmd == "status":
        pt = app.points()[-1]
        st = app.state(pt["iso"], "daniel")
        print("Stand %s · %d Läufe · Daten bis %s" % (st["label"], st["selfcheck"]["laeufe"], st["selfcheck"]["daten_bis"]))
        for t in st["incidents"]:
            if t["lane"] != "erledigt":
                print("  P%d %-9s %-10s %s" % (t["level"], t["delivery"], t["lane"], t["titel"]))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
