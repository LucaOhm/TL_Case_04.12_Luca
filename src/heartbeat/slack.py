"""Slack: Block-Kit-Nachrichten, Signaturprüfung für den Rückkanal, Transporte.

Slack ist der direkte Draht (kurz, mit Buttons), das Dashboard die Vertiefung (Link in jeder Nachricht).
Der Mock-Transport legt Nachrichten nur ab; die Oberfläche unter /slack rendert exakt dieselben Block-Kit-Objekte,
die ein echter Workspace bekäme. Ein echter Versand ist bewusst noch nicht gebaut (kein Workspace zum Testen).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import List, Optional, Tuple
from urllib.parse import quote

ICON = {1: ":red_circle:", 2: ":large_orange_circle:", 3: ":large_yellow_circle:", 4: ":white_circle:"}


def base_url() -> str:
    return os.environ.get("HEARTBEAT_BASE_URL", "http://127.0.0.1:8765")


def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def short(s: str, n: int = 260) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def first_sentence(s: str, n: int = 220) -> str:
    """Erster Satz (Punkte in Datumsangaben wie „20.10. 07:39“ zählen nicht als Satzende)."""
    import re
    s = " ".join(str(s).split())
    m = re.search(r"(?<=[a-zäöüß\)”“])\. (?=[A-ZÄÖÜ])", s)
    s = s[: m.start() + 1] if m else s
    return short(s, n)


def link(pid: str, as_of: str, incident: str = "") -> str:
    u = "%s/?u=%s&t=%s" % (base_url(), quote(pid), quote(as_of))
    if incident:
        u += "&i=" + quote(incident)
    return u


# ---- Bausteine
def header(t): return {"type": "header", "text": {"type": "plain_text", "text": short(t, 140), "emoji": True}}
def section(md, fields=None):
    b = {"type": "section", "text": {"type": "mrkdwn", "text": md}}
    if fields:
        b["fields"] = [{"type": "mrkdwn", "text": f} for f in fields]
    return b
def context(*md): return {"type": "context", "elements": [{"type": "mrkdwn", "text": m} for m in md]}
def divider(): return {"type": "divider"}
def button(text, action_id, value="", style=None, url=None):
    b = {"type": "button", "text": {"type": "plain_text", "text": text, "emoji": True}, "action_id": action_id}
    if value:
        b["value"] = value
    if style:
        b["style"] = style
    if url:
        b["url"] = url
    return b
def actions(*btns): return {"type": "actions", "elements": list(btns)}


def msg(to_slack: str, text: str, blocks: List[dict]) -> dict:
    return {"channel": to_slack, "text": text, "blocks": blocks}


# ---- Nachrichten
def alert(inc: dict, pid: str, slack: str, as_of: str, count_at: int, refs_at: List[str], eskalation: bool = False, wartezeit_min: int = 0,
          owner_namen: Optional[List[str]] = None) -> dict:
    lv = inc["level"]
    head = ("%s Eskalation · %s" % (":rotating_light:", inc["titel"])) if eskalation else ("%s Sofortmeldung · %s" % (ICON[lv], inc["titel"]))
    lines = [esc(short(inc["kurz"], 420))]
    if eskalation:
        lines.insert(0, "*Nach %d Min. von niemandem übernommen* (Owner: %s)." % (wartezeit_min, esc(", ".join(owner_namen or []))))
    fields = ["*Auswirkung*\n" + esc(short(inc.get("wirkung") or "", 140)),
              "*Bisher betroffen*\n%s%s" % ("1 Lauf" if count_at == 1 else "%d Läufe" % count_at, (" · " + ", ".join("#" + r for r in refs_at[:4]) + (" …" if len(refs_at) > 4 else "")) if refs_at else "")]
    nxt = (inc.get("empfehlung") or [{}])[0].get("text", "")
    blocks = [header(head), section("\n".join(lines), fields)]
    if nxt:
        blocks.append(section("*Als Erstes:* " + esc(short(nxt, 200))))
    blocks.append(context("Heartbeat · Priorität P%d %s · Sofort-Klasse · Protokoll auf Wunsch" % (lv, inc["level_name"])))
    blocks.append(actions(button("Übernehmen", "hb_ack", inc["id"], "primary"), button("Protokoll ansehen", "hb_log", inc["id"]),
                          button("Im Dashboard öffnen", "hb_open", inc["id"], url=link(pid, as_of, inc["id"])),
                          button("24 h zurückstellen", "hb_snooze", inc["id"])))
    return msg(slack, "%s: %s" % ("Eskalation" if eskalation else "Sofortmeldung", inc["titel"]), blocks)


def entwarnung(inc: dict, pid: str, slack: str, as_of: str) -> dict:
    todo = [n["text"] for n in (inc.get("nacharbeit") or [])]
    blocks = [header(":white_check_mark: Wieder normal · " + inc["titel"]),
              section("Seit *%s* laufen wieder korrekte Läufe. Dauer der Störung: %s, %d betroffene Läufe." % (inc["recovered"], inc["dauer"], inc["count"]))]
    if todo:
        blocks.append(section("*Nacharbeit offen*\n" + "\n".join("• " + esc(short(t, 220)) for t in todo[:4])))
    blocks.append(context("Erst nach deiner Bestätigung gilt die Störung als erledigt."))
    blocks.append(actions(button("Ursache bestätigen · Gelöst", "hb_resolve", inc["id"], "primary"),
                          button("Im Dashboard öffnen", "hb_open", inc["id"], url=link(pid, as_of, inc["id"]))))
    return msg(slack, "Wieder normal: " + inc["titel"], blocks)


def briefing(person: dict, pid: str, as_of: str, as_label: str, bilanz: dict, items: List[dict], n_info: int, selfcheck: str) -> dict:
    name = person["name"]
    blocks = [header(":sunrise: Heartbeat · Guten Morgen, %s" % name),
              context("Stand %s · gestern (%s): %d von %d erwarteten Läufen gestartet" % (as_label, bilanz["label"], bilanz["ist"], bilanz["soll"]))]
    if not items:
        blocks.append(section(":white_check_mark: *Nichts Offenes.* Gestern ist alles gelaufen, was laufen sollte."))
    else:
        blocks.append(section("*%s* – sortiert nach Priorität. Was schon sofort gemeldet wurde und noch niemand übernommen hat, steht hier erneut." % ("1 Meldung braucht Aufmerksamkeit" if len(items) == 1 else "%d Meldungen brauchen Aufmerksamkeit" % len(items))))
        for t in items[:6]:
            status = {"offen": "Unbearbeitet", "in_arbeit": "In Arbeit (%s)" % (t.get("assignee") or "–"), "erholt": "Wieder normal seit %s · Bestätigung offen" % t.get("recovered")}.get(t["lane"], t["state_label"])
            sofort = " · *bereits sofort gemeldet*" if t["delivery"] == "sofort" else ""
            blocks.append(divider())
            blocks.append(section("%s *%s*\n%s\n_%s · seit %s · %s%s_" % (ICON[t["level"]], esc(t["titel"]), esc(first_sentence(t["kurz"], 230)), status, t["first"], "1 Lauf" if t["count"] == 1 else "%d Läufe" % t["count"], sofort)))
            btns = []
            if t["lane"] == "erholt":
                btns.append(button("Ursache bestätigen · Gelöst", "hb_resolve", t["id"], "primary"))
            elif t["state"] == "neu":
                btns.append(button("Übernehmen", "hb_ack", t["id"], "primary"))
            btns.append(button("Details im Dashboard", "hb_open", t["id"], url=link(pid, as_of, t["id"])))
            blocks.append(actions(*btns))
        if len(items) > 6:
            blocks.append(context("… und %d weitere im Dashboard" % (len(items) - 6)))
    foot = selfcheck
    if n_info:
        foot += " · %d Hinweise ohne Handlungsbedarf im Dashboard" % n_info
    blocks.append(context(foot))
    blocks.append(actions(button("Gesamtübersicht öffnen", "hb_open", "", url=link(pid, as_of))))
    return msg(person["slack"], "Heartbeat Morgenbriefing für %s" % name, blocks)


def log_reply(inc: dict, rows: List[dict]) -> dict:
    lines = ["`%s` %s %s %s" % (r.get("lauf_id", "–"), r.get("start", "")[11:16], r.get("status", ""), esc(short(r.get("detail", ""), 70))) for r in rows[:8]]
    return msg("", "Protokoll", [section("*Protokoll · %s*\n%s" % (esc(inc["titel"]), "\n".join(lines))),
                                  context("Rohdaten aus dem Lauf-Protokoll. Nichts davon wurde vom Briefing berechnet.")])


# ---- Rückkanal
def verify_signature(signing_secret: str, ts: str, body: bytes, signature: str, now: Optional[float] = None) -> Tuple[bool, str]:
    try:
        t = float(ts)
    except (TypeError, ValueError):
        return False, "Zeitstempel fehlt"
    if abs((now if now is not None else time.time()) - t) > 300:
        return False, "Zeitstempel zu alt"
    mine = "v0=" + hmac.new(signing_secret.encode(), b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mine, signature or ""):
        return False, "Signatur ungültig"
    return True, ""


ACTION_MAP = {"hb_ack": "ack", "hb_resolve": "resolve", "hb_snooze": "snooze", "hb_false": "false_alarm"}


def parse_interaction(payload: dict) -> List[Tuple[str, str, str]]:
    """Slack block_actions -> [(aktion, incident_id, slack_user)]; hb_open/hb_log sind reine Anzeige."""
    out = []
    uid = (payload.get("user") or {}).get("id", "")
    for a in payload.get("actions", []):
        k = ACTION_MAP.get(a.get("action_id"))
        if k and a.get("value"):
            out.append((k, a["value"], uid))
        elif a.get("action_id") == "hb_log" and a.get("value"):
            out.append(("log", a["value"], uid))
    return out


# ---- Transporte
class MockTransport:
    """Legt Nachrichten ab, statt zu senden. Die Oberfläche /slack zeigt sie an."""
    name = "mock"

    def __init__(self):
        self.sent: List[dict] = []

    def send(self, m: dict) -> bool:
        self.sent.append(m)
        return True
