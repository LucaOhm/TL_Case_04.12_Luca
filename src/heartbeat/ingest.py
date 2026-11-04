"""Einheitliche, abgesicherte Einlieferung aller Läufe (Make, Cloud-Routinen, Laptop).

Meldekette (siehe docs/betrieb.md):
  1. Jede Automation meldet am Ende genau einen Lauf als JSON-Umschlag (Push, at-least-once).
  2. Der Umschlag ist mit einem Geheimnis je Quelle signiert (HMAC-SHA256 über Zeitstempel + Body).
  3. Doppelte Meldungen sind unschädlich (Idempotenz über Automation + Startzeit).
  4. Ungültiges wandert in Quarantäne und wird im Dashboard als Datenqualitätsproblem sichtbar.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import tabular
from .core import ROOT, Registry, Run, parse_local, iso
from .store import Store

SECRETS_FILE = ROOT / "data" / "secrets.json"
MAX_SKEW_S = 300
MAX_BODY = 64 * 1024


def load_secrets(reg: Registry, path: Path = SECRETS_FILE) -> Dict[str, str]:
    """Env hat Vorrang (HEARTBEAT_SECRET_MAKE ...). Fehlt beides, wird lokal ein Demo-Geheimnis erzeugt."""
    names = [t["quelle"] for t in reg.tools.values()]
    out: Dict[str, str] = {}
    file_vals: Dict[str, str] = {}
    if path.exists():
        file_vals = json.loads(path.read_text(encoding="utf-8"))
    changed = False
    for n in names:
        v = os.environ.get("HEARTBEAT_SECRET_" + n.upper()) or file_vals.get(n)
        if not v:
            v = secrets.token_hex(24)
            file_vals[n] = v
            changed = True
        out[n] = v
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(file_vals, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return out


def sign(secret: str, ts: str, body: bytes) -> str:
    return hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify(secret: str, ts: str, body: bytes, signature: str, now: Optional[float] = None) -> Tuple[bool, str]:
    try:
        t = float(ts)
    except (TypeError, ValueError):
        return False, "Zeitstempel fehlt oder ungültig"
    if abs((now if now is not None else time.time()) - t) > MAX_SKEW_S:
        return False, "Zeitstempel zu alt oder zu neu (Replay-Schutz)"
    if not hmac.compare_digest(sign(secret, ts, body), signature or ""):
        return False, "Signatur ungültig"
    return True, ""


def parse_envelope(d: dict, reg: Registry, source: str) -> Tuple[Optional[Run], str]:
    """Prüft einen Umschlag. Gibt (Lauf, '') oder (None, Grund) zurück."""
    if not isinstance(d, dict):
        return None, "Umschlag ist kein Objekt"
    for k in ("automation_id", "werkzeug", "start", "ende", "status"):
        if not d.get(k):
            return None, "Pflichtfeld fehlt: " + k
    aid, tool = str(d["automation_id"]), str(d["werkzeug"])
    if aid not in reg.autos:
        return None, "Unbekannte Automation: " + aid
    if reg.tool_of(aid) != tool:
        return None, "Werkzeug %r passt nicht zu %s (erwartet %r)" % (tool, aid, reg.tool_of(aid))
    if source and reg.tools[tool]["quelle"] != source:
        return None, "Quelle %r darf kein Werkzeug %r melden" % (source, tool)
    try:
        start, end = parse_local(str(d["start"])), parse_local(str(d["ende"]))
    except ValueError as e:
        return None, str(e)
    if end < start:
        return None, "Ende liegt vor Start"
    cnt = d.get("anzahl")
    if cnt is not None:
        try:
            cnt = int(cnt)
        except (TypeError, ValueError):
            return None, "anzahl ist keine Zahl"
        if cnt < 0:
            return None, "anzahl negativ"
    detail = str(d.get("detail") or "")[:1000]
    rid = str(d.get("lauf_id") or "%s-%s" % (aid, iso(start)))
    r = Run(rid, aid, tool, start, end, str(d["status"]), cnt, detail, source or "webhook")
    r.klass = reg.status_class(tool, r.status)
    return r, ""


def receive(store: Store, body: bytes, headers: dict, secrets_map: Dict[str, str], now: Optional[float] = None) -> Tuple[int, dict]:
    """HTTP-unabhängige Annahme eines Webhooks. Gibt (Statuscode, Antwort) zurück."""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
    source = (headers.get("X-Heartbeat-Source") or "").lower()
    if len(body) > MAX_BODY:
        return 413, {"fehler": "Nachricht zu groß"}
    if source not in secrets_map:
        return 401, {"fehler": "Unbekannte Quelle"}
    ok, why = verify(secrets_map[source], headers.get("X-Heartbeat-Timestamp", ""), body, headers.get("X-Heartbeat-Signature", ""), now)
    if not ok:
        store.reject(source, "Auth: " + why, body.decode("utf-8", "replace"), stamp)
        return 401, {"fehler": why}
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError:
        store.reject(source, "Kein gültiges JSON", body.decode("utf-8", "replace"), stamp)
        return 400, {"fehler": "Kein gültiges JSON"}
    run, why = parse_envelope(data, store.reg, source)
    if run is None:
        store.reject(source, why, body.decode("utf-8", "replace"), stamp)
        return 422, {"fehler": why}
    if run.klass == "unknown":
        # wird gespeichert (kein Datenverlust), die Auswertung meldet das Schema-Drift sichtbar
        pass
    neu = store.add_run(run, stamp)
    return 200, {"ok": True, "neu": neu, "lauf_id": run.id}


def _tool_from_text(reg: Registry, v) -> str:
    s = str(v or "").strip()
    if s in reg.tools:
        return s
    low = s.lower()
    for key, name in (("laptop", "Geplanter Task (Laptop)"), ("cloud", "Claude-Routine (Cloud)"), ("routine", "Claude-Routine (Cloud)"), ("make", "Make")):
        if key in low:
            return name
    return s


def _int(v) -> Optional[int]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v)
    m = re.match(r"\s*(\d+)", str(v))
    return int(m.group(1)) if m else None


def row_to_envelope(reg: Registry, row: dict) -> Tuple[Optional[dict], str]:
    """Eine Tabellenzeile (CSV/Excel) in den Standard-Umschlag übersetzen. Tolerant bei Schreibweisen, streng bei Wesentlichem."""
    raw = str(row.get("automation_id") or "").strip()
    aid = raw.upper() if raw.upper() in reg.autos else next((k for k, a in reg.autos.items() if a["name"].lower() == raw.lower()), "")
    if not aid:
        return None, "Unbekannte Automation: %r" % raw
    start = row.get("start")
    if start in (None, ""):
        return None, "Startzeit fehlt"
    ende = row.get("ende") if row.get("ende") not in (None, "") else start
    status = str(row.get("status") or "").strip().lower()
    if not status:
        return None, "Status fehlt"
    env = {"lauf_id": str(row.get("lauf_id") or "").strip() or None, "automation_id": aid,
           "werkzeug": _tool_from_text(reg, row.get("werkzeug")) if row.get("werkzeug") else reg.tool_of(aid),
           "start": str(start), "ende": str(ende), "status": status, "anzahl": _int(row.get("anzahl")),
           "detail": str(row.get("detail") or "").strip()}
    return env, ""


def import_csv(store: Store, path: Path, source: str = "csv") -> Dict[str, int]:
    return import_bytes(store, Path(path).read_bytes(), Path(path).name, source)


def import_bytes(store: Store, data: bytes, filename: str = "", source: str = "datei") -> dict:
    """Protokoll-Datei einlesen (CSV oder Excel). Idempotent: bereits bekannte Läufe zählen als 'doppelt'.
    Unbrauchbare Zeilen kommen mit Grund in die Quarantäne und werden im Dashboard sichtbar."""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        rows, info = tabular.read_table(data, filename)
    except tabular.TableError as e:
        store.reject(source, str(e), filename, stamp)
        return {"fehler": str(e), "neu": 0, "doppelt": 0, "abgelehnt": 0}
    res = {"neu": 0, "doppelt": 0, "abgelehnt": 0, "beispiele": [], "zeilen": info["zeilen"], "art": info["art"], "blatt": info["blatt"], "erste": None, "letzte": None}
    for row in rows:
        env, why = row_to_envelope(store.reg, row)
        run = None
        if env:
            run, why = parse_envelope(env, store.reg, "")
        if run is None:
            store.reject(source, why, json.dumps(row, ensure_ascii=False, default=str), stamp)
            res["abgelehnt"] += 1
            if len(res["beispiele"]) < 5:
                res["beispiele"].append(why)
            continue
        run.source = source
        res["neu" if store.add_run(run, iso(run.end)) else "doppelt"] += 1
        d = iso(run.start)[:10]
        res["erste"] = min(res["erste"] or d, d)
        res["letzte"] = max(res["letzte"] or d, d)
    return res
