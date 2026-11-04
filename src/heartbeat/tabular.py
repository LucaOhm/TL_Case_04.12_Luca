"""Tabellen einlesen: CSV (Trenner ; , Tab, UTF-8 oder Windows-1252) und Excel (.xlsx) – nur Standardbibliothek.

Excel ist ein ZIP mit XML. Schutz: Größenlimits, keine DOCTYPE/ENTITY (Entity-Expansion), nur Lesen, nie Makros/Formeln ausführen.
Die Spaltenköpfe werden tolerant erkannt (siehe ALIASES). Fehlt etwas Wesentliches, gibt es eine klare Fehlermeldung statt Raten.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

MAX_UNPACKED = 40 * 1024 * 1024
MAX_ROWS = 200_000
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}

ALIASES = {
    "lauf_id": {"lauf_id", "laufid", "run_id", "runid", "lauf", "id"},
    "automation_id": {"automation_id", "automation", "automationid", "auto_id", "automations_id", "id_automation"},
    "werkzeug": {"werkzeug", "tool", "plattform", "system"},
    "start": {"start", "startzeit", "start_zeit", "gestartet", "beginn", "start_zeitpunkt"},
    "ende": {"ende", "endzeit", "ende_zeit", "end", "beendet", "ende_zeitpunkt"},
    "status": {"status", "lauf_status", "ergebnis_status"},
    "anzahl": {"anzahl", "count", "menge", "ergebnis", "anzahl_ergebnis"},
    "detail": {"detail", "details", "meldung", "nachricht", "protokoll", "bemerkung", "log"},
}
REQUIRED = ("automation_id", "start", "status")


class TableError(ValueError):
    pass


def norm_header(h) -> str:
    s = str(h or "").strip().lower()
    s = re.sub(r"[\s\-\.]+", "_", s)
    return s.strip("_")


def map_headers(headers: List) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for i, h in enumerate(headers):
        n = norm_header(h)
        for key, al in ALIASES.items():
            if n in al and key not in out.values():
                out[i] = key
                break
    return out


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def excel_dt(v: float) -> str:
    dt = datetime(1899, 12, 30) + timedelta(days=float(v))
    dt = (dt + timedelta(milliseconds=500)).replace(microsecond=0)  # auf Sekunden runden
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _safe_xml(z: zipfile.ZipFile, name: str) -> ET.Element:
    raw = z.read(name)
    if b"<!DOCTYPE" in raw[:4096].upper() or b"<!ENTITY" in raw[:65536].upper():
        raise TableError("Excel-Datei abgelehnt (unzulässige XML-Deklaration)")
    return ET.fromstring(raw)


def _xlsx_sheets(data: bytes) -> List[Tuple[str, List[List]]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise TableError("Die Datei ist keine gültige Excel-Datei (.xlsx)")
    if sum(i.file_size for i in z.infolist()) > MAX_UNPACKED:
        raise TableError("Excel-Datei ist entpackt zu groß")
    names = set(z.namelist())
    shared: List[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in _safe_xml(z, "xl/sharedStrings.xml").findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = _safe_xml(z, "xl/workbook.xml")
    rels = {r.get("Id"): r.get("Target") for r in _safe_xml(z, "xl/_rels/workbook.xml.rels").findall("pr:Relationship", NS)}
    sheets = []
    for s in wb.find("m:sheets", NS).findall("m:sheet", NS):
        tgt = rels.get(s.get("{%s}id" % NS["r"]), "")
        path = ("xl/" + tgt.lstrip("/")) if not tgt.startswith("/xl/") else tgt.lstrip("/")
        path = path.replace("xl/xl/", "xl/")
        if path not in names:
            continue
        rows: List[List] = []
        root = _safe_xml(z, path)
        for row in root.iter("{%s}row" % NS["m"]):
            cells: Dict[int, object] = {}
            for c in row.findall("m:c", NS):
                t = c.get("t", "n")
                v = c.find("m:v", NS)
                if t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
                elif v is None or v.text is None:
                    continue
                elif t == "s":
                    val = shared[int(v.text)]
                elif t in ("str", "e"):
                    val = v.text
                elif t == "b":
                    val = bool(int(v.text))
                else:
                    f = float(v.text)
                    val = int(f) if f.is_integer() and abs(f) < 1e15 else f
                cells[_col(c.get("r", "A1"))] = val
            if cells:
                rows.append([cells.get(i) for i in range(max(cells) + 1)])
            if len(rows) > MAX_ROWS:
                raise TableError("Zu viele Zeilen (mehr als %d)" % MAX_ROWS)
        sheets.append((s.get("name", ""), rows))
    return sheets


def _csv_rows(data: bytes) -> List[List]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    first = text.split("\n", 1)[0]
    delim = max(";,\t", key=lambda d: first.count(d))
    return [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(x.strip() for x in r)]


def read_table(data: bytes, filename: str = "") -> Tuple[List[dict], dict]:
    """Gibt (Zeilen als Dicts mit Standard-Spaltennamen, Info) zurück. Wirft TableError bei unbrauchbarem Format."""
    if data[:2] == b"PK":
        sheets = _xlsx_sheets(data)
        kind = "Excel"
    else:
        sheets = [("CSV", _csv_rows(data))]
        kind = "CSV"
    if not sheets:
        raise TableError("Keine Tabelle gefunden")
    best = None
    for name, rows in sheets:
        for hi, hdr in enumerate(rows[:20]):
            m = map_headers(hdr)
            if all(k in m.values() for k in REQUIRED):
                best = (name, rows, hi, m)
                break
        if best:
            break
    if not best:
        first = sheets[0][1][0] if sheets[0][1] else []
        raise TableError("Spalten nicht erkannt. Erwartet mindestens: automation_id, start, status (optional lauf_id, werkzeug, ende, anzahl, detail). Gefunden: %s"
                         % ", ".join(str(x) for x in first[:12] if x is not None))
    name, rows, hi, m = best
    out = []
    for r in rows[hi + 1:]:
        d = {}
        for i, key in m.items():
            v = r[i] if i < len(r) else None
            if key in ("start", "ende") and isinstance(v, (int, float)) and not isinstance(v, bool):
                v = excel_dt(v)
            d[key] = v
        if any(x not in (None, "") for x in d.values()):
            out.append(d)
    return out, {"art": kind, "blatt": name, "zeilen": len(out), "spalten": sorted(set(m.values()))}
