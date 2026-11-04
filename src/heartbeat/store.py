"""SQLite-Ablage: Läufe (idempotent), Aktionen (Human in the Loop), Quarantäne, KI-Analysen, Versandprotokoll."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from .core import ROOT, Run, parse_local, iso, Registry

DB_DEFAULT = ROOT / "data" / "heartbeat.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, auto TEXT NOT NULL, tool TEXT NOT NULL, start TEXT NOT NULL, ende TEXT NOT NULL,
  status TEXT NOT NULL, anzahl INTEGER, detail TEXT NOT NULL, source TEXT NOT NULL, received_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS runs_nat ON runs(auto, start);
CREATE TABLE IF NOT EXISTS actions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL, action TEXT NOT NULL, user TEXT NOT NULL,
  at TEXT NOT NULL, note TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS rejects(
  id INTEGER PRIMARY KEY AUTOINCREMENT, received_at TEXT NOT NULL, source TEXT, reason TEXT NOT NULL, raw TEXT);
CREATE TABLE IF NOT EXISTS analysis(
  incident_id TEXT PRIMARY KEY, at TEXT NOT NULL, quelle TEXT NOT NULL, status TEXT NOT NULL, body TEXT);
CREATE TABLE IF NOT EXISTS sent(key TEXT PRIMARY KEY, at TEXT NOT NULL, transport TEXT NOT NULL);
"""


class Store:
    def __init__(self, path=DB_DEFAULT, registry: Optional[Registry] = None):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)
        self.reg = registry or Registry()
        self.version = 0  # steigt bei jeder Änderung -> Cache der Auswertung

    # ---- Läufe
    def add_run(self, r: Run, received_at: str) -> bool:
        with self.lock:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO runs(id,auto,tool,start,ende,status,anzahl,detail,source,received_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (r.id, r.auto, r.tool, iso(r.start), iso(r.end), r.status, r.count, r.detail, r.source, received_at))
            self.db.commit()
            if cur.rowcount:
                self.version += 1
            return bool(cur.rowcount)

    def runs(self, until_iso: Optional[str] = None) -> List[Run]:
        q = "SELECT * FROM runs" + (" WHERE start<=?" if until_iso else "") + " ORDER BY start, id"
        with self.lock:
            rows = self.db.execute(q, (until_iso,) if until_iso else ()).fetchall()
        out = []
        for x in rows:
            run = Run(x["id"], x["auto"], x["tool"], parse_local(x["start"]), parse_local(x["ende"]), x["status"],
                      x["anzahl"], x["detail"], x["source"])
            run.klass = self.reg.status_class(run.tool, run.status)
            out.append(run)
        return out

    def run_count(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"]

    # ---- Quarantäne
    def reject(self, source: str, reason: str, raw: str, at: str) -> None:
        with self.lock:
            self.db.execute("INSERT INTO rejects(received_at,source,reason,raw) VALUES(?,?,?,?)", (at, source, reason, raw[:2000]))
            self.db.commit()
            self.version += 1

    def rejects(self, limit: int = 50) -> List[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM rejects ORDER BY id DESC LIMIT ?", (limit,))]

    # ---- Aktionen (Human in the Loop)
    def add_action(self, incident_id: str, action: str, user: str, at: str, note: str = "", payload: Optional[dict] = None) -> None:
        with self.lock:
            self.db.execute("INSERT INTO actions(incident_id,action,user,at,note,payload) VALUES(?,?,?,?,?,?)",
                            (incident_id, action, user, at, note, json.dumps(payload or {}, ensure_ascii=False)))
            self.db.commit()
            self.version += 1

    def actions(self, until_iso: Optional[str] = None) -> List[dict]:
        q = "SELECT * FROM actions" + (" WHERE at<=?" if until_iso else "") + " ORDER BY at, id"
        with self.lock:
            rows = self.db.execute(q, (until_iso,) if until_iso else ()).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"] or "{}")
            out.append(d)
        return out

    def clear_actions(self) -> None:
        with self.lock:
            self.db.execute("DELETE FROM actions")
            self.db.execute("DELETE FROM analysis")
            self.db.commit()
            self.version += 1

    # ---- KI-Analyse (Cache)
    def save_analysis(self, incident_id: str, at: str, quelle: str, status: str, body: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO analysis(incident_id,at,quelle,status,body) VALUES(?,?,?,?,?)",
                            (incident_id, at, quelle, status, json.dumps(body, ensure_ascii=False)))
            self.db.commit()
            self.version += 1

    def analysis(self, incident_id: str) -> Optional[dict]:
        with self.lock:
            r = self.db.execute("SELECT * FROM analysis WHERE incident_id=?", (incident_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["body"] = json.loads(d["body"] or "{}")
        return d

    # ---- Versandprotokoll (Idempotenz für echte Slack-Zustellung)
    def mark_sent(self, key: str, at: str, transport: str) -> bool:
        with self.lock:
            cur = self.db.execute("INSERT OR IGNORE INTO sent(key,at,transport) VALUES(?,?,?)", (key, at, transport))
            self.db.commit()
            return bool(cur.rowcount)

    def reset_all(self) -> None:
        with self.lock:
            for t in ("runs", "actions", "rejects", "analysis", "sent"):
                self.db.execute("DELETE FROM " + t)
            self.db.commit()
            self.version += 1
