"""Regelwerk für Beschreibung und Empfehlung (deterministisch, immer verfügbar = Rückfallebene der KI).

Jede Empfehlung ist ein Vorschlag. Schritte vom Typ 'aendern' brauchen die Freigabe eines Menschen,
bevor jemand eine Automation anfasst. Das Tool ändert selbst nie etwas.
"""
from __future__ import annotations

import re
from typing import Dict, List

from .core import fmt_dt, fmt_dur, from_ts, median

# Fehlertyp-Wissen: Muster im Fehlertext -> Ursache/Schritte
PLAYBOOK = [
    {"id": "slack_kanal", "muster": re.compile(r"channel_not_found|HTTP\s*404", re.I)},
    {"id": "auth", "muster": re.compile(r"HTTP\s*40[13]|unauthorized|forbidden|token|abgelaufen", re.I)},
    {"id": "limit", "muster": re.compile(r"rate-?limit|HTTP\s*429|gedrosselt", re.I)},
    {"id": "zeit", "muster": re.compile(r"timeout|zeitüberschreitung|HTTP\s*50\d", re.I)},
]


def step(typ: str, text: str, freigabe: bool = False, aktion: str = "") -> dict:
    return {"typ": typ, "text": text, "freigabe": freigabe, "aktion": aktion}


def match_playbook(detail: str) -> str:
    for p in PLAYBOOK:
        if p["muster"].search(detail):
            return p["id"]
    return "unbekannt"


def _l(n: int) -> str:
    return "1 Lauf" if n == 1 else "%d Läufe" % n


def _n(x) -> str:
    return ("%g" % round(x, 1)).replace(".", ",") if x is not None else "–"


def describe(inc: dict, a: dict, ctx: dict) -> dict:
    """Liefert titel, kurz, ursachen, empfehlung, nacharbeit für eine EINZELNE Störung (Gruppen: describe_group)."""
    code = inc["codes"][0]
    for c in ("TEXT_ERROR", "STATUS_ERROR", "VOLUME_ZERO", "VOLUME_DEVIATION", "RUN_MISSING"):
        if c in inc["codes"]:
            code = c
            break
    name = "%s %s" % (a["id"], a["name"])
    occ = inc["occ"]
    n = len(occ)
    first, last = from_ts(occ[0]["ts"]), from_ts(occ[-1]["ts"])
    zeitraum = fmt_dt(first) if n == 1 else "%s bis %s" % (fmt_dt(first), fmt_dt(last))
    refs = [r for o in occ for r in o.get("refs", [])]
    out = {"ursachen": [], "empfehlung": [], "nacharbeit": []}

    if code in ("TEXT_ERROR", "STATUS_ERROR"):
        det = occ[0]["detail"]
        kind = match_playbook(det)
        stat = "meldet „success“, " if code == "TEXT_ERROR" else ""
        if kind == "slack_kanal":
            out["titel"] = "Tickets erreichen den Support-Kanal nicht" if a["id"] == "A02" else "%s: Ziel-Kanal nicht erreichbar" % a["name"]
            out["kurz"] = ("%s %sschreibt aber nichts in den Kanal: %s mit „HTTP 404 channel_not_found“ (%s). "
                           "Das Szenario ignoriert den Fehler, deshalb sieht es von außen gesund aus." % (name, stat, _l(n), zeitraum))
            out["ursachen"] = ["Kanal gelöscht, archiviert oder umbenannt (Zugriff ins Leere)",
                               "App/Bot aus dem Kanal entfernt oder Kanal auf privat gestellt",
                               "Kanal-ID nach einer Workspace-Änderung nicht mehr gültig"]
            out["empfehlung"] = [
                step("pruefen", "In Slack prüfen, ob %s noch existiert, nicht archiviert ist und die App Mitglied ist." % a.get("ziel", "der Ziel-Kanal")),
                step("aendern", "Im Make-Szenario %s das Slack-Modul auf die Kanal-ID umstellen und die App neu in den Kanal einladen." % a["id"], True),
                step("aendern", "Fehlerbehandlung am Slack-Modul von „Fehler ignorieren“ auf „Abbrechen“ stellen und einen Aufruf an den Heartbeat-Webhook anhängen. Dann steht ein solcher Lauf auf error statt success.", True),
            ]
            if refs:
                out["nacharbeit"] = [step("nacharbeit", "Nicht gepostete Tickets im Support-Kanal nachtragen (%d): %s" % (len(refs), ", ".join("#" + r for r in refs)))]
        elif kind == "auth":
            out["titel"] = "%s: Zugang abgelaufen (401)" % a["name"]
            out["kurz"] = "%s ist am %s mit „%s“ fehlgeschlagen." % (name, fmt_dt(first), det)
            out["ursachen"] = ["Zugangs-Token der Verbindung abgelaufen", "Passwort/Berechtigung des Dienstkontos geändert"]
            out["empfehlung"] = [
                step("pruefen", "In Make die Verbindung von %s öffnen und den Status prüfen." % a["id"]),
                step("aendern", "Verbindung neu autorisieren (oder auf einen dauerhaften Token/Dienstkonto umstellen).", True),
                step("aendern", "Ablaufdatum des Tokens ins Heartbeat-Register eintragen, 7 Tage vorher erinnern lassen.", True),
            ]
        elif kind == "limit":
            out["titel"] = "%s: Rate-Limit" % a["name"]
            out["kurz"] = "%s wurde vom Zielsystem gedrosselt (%s)." % (name, zeitraum)
            out["ursachen"] = ["Zu viele Aufrufe in kurzer Zeit"]
            out["empfehlung"] = [step("pruefen", "Wiederholung prüfen: Ist der Retry durchgelaufen?")]
        else:
            out["titel"] = "%s: Lauf mit Fehler" % a["name"]
            out["kurz"] = "%s meldet in %s: „%s“ (%s)." % (name, _l(n), det, zeitraum)
            out["ursachen"] = ["Neuer, noch unbekannter Fehlertyp"]
            out["empfehlung"] = [step("pruefen", "Protokoll öffnen und Fehlermeldung im Zielsystem nachvollziehen."),
                                 step("pruefen", "Fehlertext in das Regelwerk aufnehmen, damit künftig eine Empfehlung kommt.")]
        if n >= 3:
            out["kurz"] += " Der Fehler tritt wiederholt auf – das ist ein Dauerzustand, kein Ausreißer."
    elif code == "VOLUME_ZERO":
        o = occ[0]
        med = o.get("median")
        out["titel"] = "%s: liefert 0 statt ≈ %s" % (a["name"], _n(med)) if med else "%s: liefert 0" % a["name"]
        out["kurz"] = ("%s meldet „0“ bei „%s“ (Status ok), üblich sind ≈ %s. Das ist %s passiert (%s). "
                       "Der Lauf endet normal, liefert aber nichts." % (name, a["anzahl"], _n(med), ("im letzten Lauf" if n == 1 else "in %d Läufen in Folge" % n), zeitraum))
        out["ursachen"] = ["Verbindung/Connector zur Datenquelle liefert leere Antwort (Berechtigung, Token)",
                           "Filter oder Abfrage der Routine trifft keine Datensätze",
                           "Routine endet bei leerem Ergebnis ohne Fehler (fehlende Plausibilitätsprüfung)"]
        out["empfehlung"] = [step("pruefen", "Lauf-Transkript des ersten Nulllaufs (%s) öffnen und die Datenabfrage prüfen." % fmt_dt(first)),
                             step("pruefen", "Prüfen, ob dieselbe Verbindung/dasselbe Token wie bei einer gleichzeitigen Fehlermeldung betroffen ist (siehe Plausibilität).")]
        if a["id"] == "A10":
            out["empfehlung"].append(step("aendern", "In der Routine eine Schutzregel ergänzen: Bei 0 bewerteten Deals mit Fehler abbrechen und den Heartbeat-Webhook auslösen.", True))
            out["nacharbeit"] = [step("nacharbeit", "Forecast-Grundlage der Geschäftsführung für den Zeitraum neu berechnen (manueller Lauf) und prüfen, ob Berichte mit leeren Scores entstanden sind.")]
        else:
            out["empfehlung"].append(step("aendern", "Schutzregel ergänzen: Bei 0 als Ergebnis mit Fehler abbrechen statt „erfolgreich“ zu melden.", True))
            out["nacharbeit"] = [step("nacharbeit", "Lauf manuell wiederholen, sobald die Ursache behoben ist.")]
    elif code == "VOLUME_DEVIATION":
        o = occ[-1]
        pct = o.get("abweichung_pct")
        out["titel"] = "%s: %s" % (a["name"], ("%s %% gegenüber dem Median" % _n(pct)) if pct is not None else "Wert außerhalb der Norm")
        out["kurz"] = ("%s meldet „%s“ = %d. Median der letzten Läufe: %s (Band %s bis %s). %s (%s)." %
                       (name, a["anzahl"], o["wert"], _n(o.get("median")), _n(o.get("unten")), _n(o.get("oben")),
                        "Erstmals außerhalb" if n == 1 else "%s in Folge außerhalb" % _l(n), zeitraum))
        if inc.get("frozen_notes"):
            out["kurz"] += " Der Wert ist danach praktisch eingefroren (%d× identisch), vorher schwankte er täglich." % (inc["frozen_notes"] + 1)
        out["ursachen"] = ["Gewollte Änderung (Pipeline bereinigt, Deals geschlossen, neue Stage-Definition)",
                           "Geänderter Filter oder Zeitraum in der Abfrage",
                           "Neue/entzogene Berechtigung auf Datensätze (nur ein Teil der Daten sichtbar)",
                           "Datenquelle liefert einen zwischengespeicherten Stand (Wert bewegt sich nicht mehr)"]
        out["empfehlung"] = [step("pruefen", "Beim Fachbereich klären: Gab es kurz vor %s eine bewusste Änderung an Pipeline, Filtern oder Rechten?" % fmt_dt(first)),
                             step("pruefen", "Abfrage/Filter der Routine mit dem CRM abgleichen (Anzahl offener Deals manuell zählen)."),
                             step("bestaetigen", "Falls gewollt: als neues Normal übernehmen. Die Vergleichsbasis wird ab dem ersten abweichenden Lauf neu gesetzt.", True, "baseline_reset")]
    elif code == "RUN_MISSING":
        weekly = len(a.get("tage", [])) == 1
        out["titel"] = "%s: %d geplante%s Lauf%s ausgefallen" % (a["name"], n, "r" if n == 1 else "", "" if n == 1 else "e")
        out["kurz"] = "%s ist zum Soll nicht gestartet (%s)." % (name, zeitraum)
        if weekly:
            out["kurz"] += " Es ist ein Wochenjob: bis zum nächsten Soll vergeht eine Woche."
        out["ursachen"] = ["Szenario/Routine pausiert oder deaktiviert", "Kontingent/Abo-Limit erreicht", "Zeitplan geändert"]
        out["empfehlung"] = [step("pruefen", "Zeitplan und Aktiv-Schalter von %s prüfen." % a["id"]),
                             step("pruefen", "Lauf einmal manuell starten und Protokoll prüfen.")]
        out["nacharbeit"] = [step("nacharbeit", "Ausgefallenen Lauf nachholen.")]
    elif code == "RUN_DUPLICATE":
        o = occ[-1]
        out["titel"] = "%s: doppelt gelaufen" % a["name"]
        out["kurz"] = ("%s lief zum selben Soll zweimal, um %s und um %s (im Abstand von %d Sekunden), beide erfolgreich. Das Ergebnis („%s“) ist damit vermutlich doppelt angekommen." %
                       (name, o.get("vorher_t", "")[11:19], o.get("dieser_t", "")[11:19], o.get("abstand_s", 0), a["liefert"]))
        out["ursachen"] = ["Szenario zweimal geplant oder zusätzlich manuell gestartet", "Trigger feuert doppelt (z. B. zwei aktive Kopien des Szenarios)",
                           "Zeitumstellung am Wochenende hat einen Zeitplan verschoben"]
        out["empfehlung"] = [step("pruefen", "Im Ziel nachsehen, ob Posts und Aufgaben doppelt angelegt wurden."),
                             step("pruefen", "In Make prüfen, ob es zwei aktive Szenarien oder zwei Zeitpläne für %s gibt." % a["id"]),
                             step("aendern", "Szenario auf „sequenzielle Verarbeitung“ stellen und doppelte Zeitpläne entfernen.", True)]
        out["nacharbeit"] = [step("nacharbeit", "Doppelte Einträge entfernen (%s)." % a["liefert"])]
    elif code == "REF_DUPLICATE":
        o = occ[-1]
        out["titel"] = "%s: Ticket #%s erneut gepostet" % (a["name"], o.get("ref"))
        out["kurz"] = "Ticket #%s wurde bereits am %s gepostet und kam am %s noch einmal. Wiedereröffnet oder doppelt?" % (
            o.get("ref"), fmt_dt(from_ts(__import__("heartbeat.core", fromlist=["x"]).parse_local(o["vorher_t"]).timestamp())), fmt_dt(first))
        out["ursachen"] = ["Ticket wurde wiedereröffnet (dann korrekt)", "Trigger hat dasselbe Ticket zweimal geliefert"]
        out["empfehlung"] = [step("pruefen", "Im Ticketsystem prüfen, ob #%s wiedereröffnet wurde." % o.get("ref"))]
    elif code == "STATUS_WARNING":
        out["titel"] = "%s: Rate-Limit, automatisch wiederholt" % a["name"] if "limit" in occ[0]["detail"].lower() else "%s: Warnung" % a["name"]
        out["kurz"] = "%s meldet eine Warnung: „%s“ (%s)." % (name, occ[0]["detail"], zeitraum)
        out["ursachen"] = ["Zielsystem hat kurz gedrosselt, Retry hat geholfen"]
        out["empfehlung"] = [step("pruefen", "Nur beobachten. Bei Wiederholung zur selben Uhrzeit: Lauf zeitlich entzerren.")]
    elif code == "VOLUME_FROZEN":
        out["titel"] = "%s: Wert bewegt sich nicht mehr" % a["name"]
        out["kurz"] = "%s meldet %d× in Folge exakt %d (%s)." % (name, occ[-1].get("mal", 3), occ[0].get("wert", 0), zeitraum)
        out["ursachen"] = ["Zufall bei stabilem Bestand", "Abgleich hat nichts Neues verarbeitet (Quelle nicht aktualisiert)"]
        out["empfehlung"] = [step("pruefen", "Quelle auf Aktualität prüfen: Bekommt der Lauf neue Daten oder einen zwischengespeicherten Stand?")]
    elif code == "SILENCE":
        out["titel"] = "%s: ungewöhnlich lange keine Läufe" % a["name"]
        out["kurz"] = "%s: %s." % (name, occ[-1]["detail"])
        out["ursachen"] = ["Trigger kommt nicht mehr an (Webhook, Filter)", "Wirklich kein Ereignis"]
        out["empfehlung"] = [step("pruefen", "Quelle des Triggers (z. B. Ticketsystem) mit dem Szenario vergleichen.")]
    elif code == "STATUS_UNBEKANNT":
        out["titel"] = "%s: unbekannter Status" % a["name"]
        out["kurz"] = "%s meldet einen Status, der im Register nicht bekannt ist: „%s“." % (name, occ[-1].get("detail", ""))
        out["ursachen"] = ["Werkzeug hat sein Statusvokabular geändert (Schema-Änderung)"]
        out["empfehlung"] = [step("aendern", "Statuszuordnung des Werkzeugs im Register ergänzen.", True)]
    else:
        out["titel"] = "%s: Auffälligkeit" % a["name"]
        out["kurz"] = "%s: %s" % (name, occ[-1].get("detail", ""))
    out["wirkung"] = a.get("wirkung", "")
    return out


def describe_group(children: List[dict], ctx: dict) -> dict:
    n = sum(len(c["occ"]) for c in children)
    names = ", ".join("%s" % c["automation"] for c in sorted(children, key=lambda c: c["automation"]))
    back = ctx.get("device_back")
    first = from_ts(min(c["first_ts"] for c in children))
    offen = [c for c in children if c["recovered_ts"] is None and not c.get("weiter_als")]
    weiter = [c for c in children if c.get("weiter_als")]
    out = {"titel": "Laptop war offline: %d geplante Läufe ausgefallen" % n}
    out["kurz"] = ("Ab %s lief auf dem Laptop nichts mehr (%s). %s" %
                   (fmt_dt(first), names,
                    ("Er war erst am %s wieder erreichbar (Ausfall %s)." % (fmt_dt(from_ts(back)), fmt_dur(back - min(c["first_ts"] for c in children)))) if back
                    else "Er ist noch nicht wieder erreichbar."))
    if back and offen:
        out["kurz"] += " Noch nicht nachgeholt: " + ", ".join(c["automation"] for c in offen) + " (Wochenjobs, nächstes Soll abwarten oder manuell starten)."
    if back and weiter:
        out["kurz"] += " " + ", ".join(c["automation"] for c in weiter) + " fehlt auch danach, obwohl der Laptop wieder lief – siehe eigene Meldung."
    out["ursachen"] = ["Laptop ausgeschaltet, zugeklappt oder im Ruhezustand (Make und Cloud liefen im selben Zeitraum normal)",
                       "Nicht angemeldet / gesperrt, geplante Aufgaben starten nicht",
                       "Energiesparen verhindert das Aufwachen zur Soll-Zeit"]
    out["empfehlung"] = [
        step("pruefen", "Klären, warum der Laptop am Ausfalltag aus war (geplant oder Zufall?) und ob es ein Muster gibt (Freitag/Montag)."),
        step("aendern", "Aufwachen zu den Startzeiten einplanen (macOS: „Einschalten oder Aufwachen planen“, Netzteil, Anmeldung automatisch).", True),
        step("aendern", "Finance-relevante Aufgabe A16 (Rechnungs-Snapshot) in die Cloud verlagern. Sie hängt sonst an einem Gerät, das ausfallen darf.", True),
        step("aendern", "Laptop-Aufgaben um den Heartbeat-Client ergänzen, der beim Aufwachen verpasste Meldungen nachliefert.", True),
    ]
    out["nacharbeit"] = []
    for c in children:
        if c["automation"] == "A16":
            out["nacharbeit"].append(step("nacharbeit", "Rechnungs-Snapshot für Finance neu erzeugen: letzter Stand war vor dem Ausfall."))
        if c["automation"] in ("A17", "A19") and c["recovered_ts"] is None:
            out["nacharbeit"].append(step("nacharbeit", "%s manuell nachholen (Wochenlauf ausgefallen)." % c["automation"]))
    out["wirkung"] = "Finance-Dashboard ohne aktuellen Snapshot, Wochenjobs fehlen, Tagesplan und Postfach-Scan fehlen."
    return out
