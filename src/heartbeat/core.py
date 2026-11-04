"""Grundbausteine: Zeit (Europe/Berlin), Registry, Normalisierung von Status und Fehlertext."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


# ---------------------------------------------------------------- Zeit
def parse_local(s: str) -> datetime:
    """Lokale deutsche Zeit (ohne Offset) -> aware datetime. Bei Zeitumstellung gilt die erste Stunde."""
    s = s.strip().replace("T", " ")
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(s, f).replace(tzinfo=TZ)
        except ValueError:
            continue
    raise ValueError("Zeitformat nicht erkannt: %r" % s)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def from_ts(t: float) -> datetime:
    return datetime.fromtimestamp(t, TZ)


def day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=TZ)


def fmt_day(d) -> str:
    return "%s %02d.%02d." % (WD[d.weekday()], d.day, d.month)


def fmt_dt(dt: datetime) -> str:
    return "%s %02d.%02d. %02d:%02d" % (WD[dt.weekday()], dt.day, dt.month, dt.hour, dt.minute)


def fmt_dur(sec: float) -> str:
    sec = int(round(sec))
    if sec < 90:
        return "%d Sek." % sec
    m = sec // 60
    if m < 90:
        return "%d Min." % m
    h, mm = divmod(m, 60)
    if h < 48:
        return "%d Std. %02d Min." % (h, mm) if mm else "%d Std." % h
    return "%d Tage" % round(h / 24)


# ---------------------------------------------------------------- Lauf
@dataclass
class Run:
    id: str
    auto: str
    tool: str
    start: datetime
    end: datetime
    status: str
    count: Optional[int]
    detail: str
    source: str = "csv"
    klass: str = "unknown"  # ok | warn | fail | unknown

    @property
    def ts(self) -> float:
        return self.start.timestamp()

    @property
    def manual(self) -> bool:
        return "manuell" in self.detail.lower()

    def row(self) -> dict:
        return {"lauf_id": self.id, "automation_id": self.auto, "start": iso(self.start), "ende": iso(self.end),
                "status": self.status, "anzahl": self.count, "detail": self.detail, "quelle": self.source}


# ---------------------------------------------------------------- Registry
class Registry:
    def __init__(self, path: Path = HERE / "registry.json"):
        self.raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.autos: Dict[str, dict] = self.raw["automationen"]
        for aid, a in self.autos.items():
            a["id"] = aid
        self.people: Dict[str, dict] = self.raw["personen"]
        for pid, p in self.people.items():
            p["id"] = pid
        self.tools: Dict[str, dict] = self.raw["werkzeuge"]
        self.escalate_min: int = self.raw.get("sofort_eskalation_min", 60)

    def tool_of(self, aid: str) -> str:
        return self.autos[aid]["werkzeug"]

    def miss_after(self, aid: str) -> int:
        return self.tools[self.tool_of(aid)]["miss_after_min"]

    def status_class(self, tool: str, status: str) -> str:
        return self.tools.get(tool, {}).get("status", {}).get(status, "unknown")

    def owners(self, aid: str) -> List[str]:
        return list(self.autos[aid]["owner"])

    def visible_to(self, pid: str, aid: str) -> bool:
        p = self.people[pid]
        a = self.autos[aid]
        return p["sicht"] == "alle" or pid in a["owner"] or bool(a.get("sichtbar_fuer_alle"))

    def person_name(self, pid: str) -> str:
        return self.people[pid]["name"]

    def slots(self, aid: str, d: date) -> List[datetime]:
        a = self.autos[aid]
        if a["art"] != "zeit" or d.weekday() not in a["tage"]:
            return []
        out = []
        for t in a["zeiten"]:
            h, m = t.split(":")
            out.append(datetime(d.year, d.month, d.day, int(h), int(m), tzinfo=TZ))
        return out


# ---------------------------------------------------------------- Fehlertext
# Harte Marker: der Lauf hat in Wahrheit nicht geliefert, egal was der Status sagt.
HARD = re.compile(r"fehlgeschlagen|\bHTTP\s*[45]\d\d|unauthorized|forbidden|abgelaufen|timeout|zeitüberschreitung|"
                  r"exception|not_found|\bfehler\b|\berror\b|\bfailed\b", re.I)
# Weiche Marker: Lauf hat sich selbst geholfen, aber etwas ist gedrosselt/wiederholt worden.
SOFT = re.compile(r"rate-?limit|wiederholt|retry|gedrosselt", re.I)


def signature(detail: str) -> str:
    """Fehlertext ohne Ticketnummern/Zahlen, damit gleiche Fehler zusammenfallen."""
    s = re.sub(r"ticket\s*#?\d+:?\s*", "", detail, flags=re.I)
    s = re.sub(r"\(manuell gestartet\)", "", s, flags=re.I)
    s = re.sub(r"(?<!http )\b\d+\b", "#", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip().lower()


def refs(detail: str) -> List[str]:
    return re.findall(r"#(\d{3,})", detail)


def median(xs: List[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if not n:
        raise ValueError("leer")
    return float(s[n // 2]) if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
