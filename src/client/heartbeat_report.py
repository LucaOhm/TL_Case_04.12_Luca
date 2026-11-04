#!/usr/bin/env python3
"""Meldet EINEN Lauf an den Heartbeat. Nur Standardbibliothek, läuft auf dem Laptop, in Make-Skripten oder in Cloud-Routinen.

Zuverlässigkeit: Jede Meldung wird zuerst lokal abgelegt (~/.heartbeat/outbox) und erst nach Erfolg gelöscht. Ist der Laptop
offline oder der Endpunkt nicht erreichbar, bleibt die Meldung liegen und wird beim nächsten Aufruf (auch beim Aufwachen)
nachgeliefert. Doppelte Zustellung ist unschädlich, der Heartbeat dedupliziert.

Beispiel (Laptop, am Ende der Aufgabe):
  HEARTBEAT_URL=https://heartbeat.example/api/ingest HEARTBEAT_SECRET=... \
  python3 heartbeat_report.py --automation A16 --start "2026-10-27 07:06:12" --end "2026-10-27 07:09:40" \
      --status ok --count 42 --detail "Snapshot geschrieben, 42 Rechnungen"
Das Werkzeug (Laptop/Make/Cloud) ergibt sich aus der Automation, die Quelle aus --source.
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

TOOL = {"laptop": "Geplanter Task (Laptop)", "make": "Make", "cloud": "Claude-Routine (Cloud)"}


def post(url, secret, source, body: bytes, timeout=10):
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json", "X-Heartbeat-Source": source,
                                             "X-Heartbeat-Timestamp": ts, "X-Heartbeat-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError):
        return 0  # offline


def flush(outbox: Path, url, secret, source):
    sent = 0
    for f in sorted(outbox.glob("*.json")):
        code = post(url, secret, source, f.read_bytes())
        if code == 200 or code in (400, 422):  # angekommen oder dauerhaft ungültig (nicht endlos wiederholen)
            f.unlink()
            sent += 1
        elif code in (401, 413):
            print("Abgelehnt (%d): Geheimnis/Größe prüfen: %s" % (code, f.name), file=sys.stderr)
            break
        else:
            break  # offline oder Serverfehler: später wieder
    return sent


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--automation", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--count", type=int)
    p.add_argument("--detail", default="")
    p.add_argument("--source", default=os.environ.get("HEARTBEAT_SOURCE", "laptop"), choices=sorted(TOOL))
    p.add_argument("--outbox", default=str(Path.home() / ".heartbeat" / "outbox"))
    a = p.parse_args()
    url, secret = os.environ.get("HEARTBEAT_URL"), os.environ.get("HEARTBEAT_SECRET")
    if not url or not secret:
        sys.exit("HEARTBEAT_URL und HEARTBEAT_SECRET müssen gesetzt sein")
    box = Path(a.outbox)
    box.mkdir(parents=True, exist_ok=True)
    env = {"automation_id": a.automation, "werkzeug": TOOL[a.source], "start": a.start, "ende": a.end, "status": a.status,
           "anzahl": a.count, "detail": a.detail}
    f = box / ("%s_%s.json" % (a.automation, a.start.replace(" ", "T").replace(":", "")))
    f.write_text(json.dumps(env, ensure_ascii=False), encoding="utf-8")  # erst sichern, dann senden
    n = flush(box, url, secret, a.source)
    left = len(list(box.glob("*.json")))
    print("gesendet: %d, noch in der Warteschlange: %d" % (n, left))
    sys.exit(0)


if __name__ == "__main__":
    main()
