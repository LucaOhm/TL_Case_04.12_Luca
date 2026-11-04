"""Human in the Loop: nur Menschen ändern Zustände. Heartbeat selbst verändert nie eine Automation.

Aktionen: ack (Übernehmen) · resolve (Gelöst) · false_alarm · snooze (24 h) · reopen
          approve_step (Änderung freigeben: nur Freigabe + Protokoll, Umsetzung macht der Mensch)
          baseline_reset (aktuelles Niveau als neues Normal übernehmen)
"""
from __future__ import annotations

from typing import Tuple

from . import insight
from .core import Registry

ACTIONS = {"ack", "resolve", "false_alarm", "snooze", "reopen", "approve_step", "baseline_reset"}


def may_act(reg: Registry, pid: str, inc: dict) -> bool:
    p = reg.people.get(pid)
    return bool(p) and (p["sicht"] == "alle" or pid in inc["owners"])


def apply(reg: Registry, store, model: dict, pid: str, incident_id: str, action: str, as_of_iso: str,
          note: str = "", step: int = -1) -> Tuple[bool, str]:
    if action not in ACTIONS:
        return False, "Unbekannte Aktion"
    inc = model["by_id"].get(incident_id)
    if not inc or not insight.visible(reg, pid, inc):
        return False, "Meldung nicht gefunden oder nicht sichtbar"
    if not may_act(reg, pid, inc):
        return False, "Nur Owner oder Verantwortliche dürfen diese Meldung bearbeiten"
    if action == "approve_step":
        steps = inc.get("empfehlung") or []
        if not 0 <= step < len(steps) or not steps[step].get("freigabe"):
            return False, "Dieser Schritt braucht keine Freigabe"
        store.add_action(incident_id, "approve_step", pid, as_of_iso, note, {"step": step, "text": steps[step]["text"]})
        if steps[step].get("aktion") == "baseline_reset":
            return apply(reg, store, model, pid, incident_id, "baseline_reset", as_of_iso, note)
        return True, "Freigegeben. Die Umsetzung bleibt bei dir, Heartbeat ändert nichts."
    if action == "baseline_reset":
        if inc["family"] != "wert":
            return False, "Neues Normal gibt es nur bei Wert-Abweichungen"
        store.add_action(incident_id, "baseline_reset", pid, as_of_iso, note, {"automation": inc["automations"][0]})
        store.add_action(incident_id, "resolve", pid, as_of_iso, "Neues Normal übernommen", {})
        return True, "Neues Normal übernommen. Ab jetzt gilt das aktuelle Niveau als Vergleichsbasis, die Störung bleibt als erledigt im Verlauf."
    store.add_action(incident_id, action, pid, as_of_iso, note, {})
    return True, {"ack": "Übernommen. Du bist jetzt zuständig, Eskalationen stoppen.", "resolve": "Als gelöst bestätigt. Die Meldung verschwindet aus dem Briefing.",
                  "false_alarm": "Als Fehlalarm markiert. Tritt es erneut auf, öffnet sich die Meldung wieder.", "snooze": "24 Stunden zurückgestellt.",
                  "reopen": "Wieder geöffnet."}[action]
