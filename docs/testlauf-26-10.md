# Testlauf: Läufe vom 26.10.2026

**Frage:** Erkennt Heartbeat in neuen, vorher unbekannten Daten die richtigen Dinge, und nur die?
**Vorgehen:** Erst die CSV von Hand durchgesehen und die Erwartung notiert, dann eingespielt und mit dem Briefing für Di 27.10. verglichen.
**Daten:** [`data/laeufe_2026-10-26.csv`](../data/laeufe_2026-10-26.csv), 39 Läufe (L00404–L00442), letzter Lauf Mo 26.10. 20:00.
**Ansehen:** beide Stände über `START.html` (Download siehe [README](../README.md#hier-prüfen)): „MVP: Stand bis 25.10.“ und „MVP: Testlauf 26.10.“

## Ergebnis: Briefing Di 27.10., 07:00

Gestern (Mo 26.10.): **31 von 32** geplanten Läufen gestartet. Ausgewertet wird der Tagesabschluss, weil Läufe vom 27.10. noch nicht vorliegen. Das steht offen im Briefing.

| Prio | Meldung | Owner | Gegenprobe / Beleg |
|---|---|---|---|
| P2 | **A19 Build-Log fehlt zum 2. Mal in Folge** (zwei Wochen ohne Eintrag) | Daniel | A16, A18, A20 liefen zur selben Zeit auf dem Laptop. Die Aufgabe selbst startet nicht. |
| P2 | **A17 Account-Anreicherung liefert 0 statt ≈ 38** (erster Lauf nach der ausgefallenen Woche) | Vertrieb | – |
| P2 | **A08 CRM-Kontaktabgleich: 871 statt ≈ 1.184 (−26 %)** | Vertrieb, Marketing | – |
| P3 | **A01 MQL-Erinnerung doppelt gelaufen** (08:30:02 und 08:30:44): Erinnerungen und CRM-Aufgaben vermutlich doppelt | Vertrieb | zwei erfolgreiche Läufe im selben Zeitfenster |
| P4 | A02 hat Ticket #48404 erneut gepostet (zuerst am 15.10.) | Support | im Ticketsystem prüfen: wiedereröffnet? |

**Weiter offen:** A09 Team-Report-Daten 139 statt ≈ 165, 7. Lauf in Folge. Jetzt ist die Gegenprobe möglich: A15 (211) und A10 (142) sind unverändert, also liegt es am Filter von A09, nicht am Pipeline-Bestand.
**Zur Bestätigung offen** (wieder normal): A02 (die 20 Tickets vom 20./21.10. sind weiterhin nicht nachgetragen), A10 und der Laptop-Ausfall vom 16./19.10.

## Wer bekommt was

| Person / Team | Im Morgenbriefing |
|---|---|
| Daniel (Chief of Staff) | alles oben, dazu die zu bestätigenden Altlasten |
| Geschäftsführung | nur Kritisches: A02, A10 |
| Team Vertrieb | A17, A09, A08, A01, Laptop-Ausfall |
| Team Marketing | A08, Laptop-Ausfall |
| Team Finance | Laptop-Ausfall (A16) |
| Team Support | A02 |
| Account Owner, Team 3 | „Nichts Offenes“ |

## Erwartung gegen Ergebnis

Alle Auffälligkeiten, die ich vorher von Hand in der CSV gefunden hatte, meldet das Tool. Es meldet nichts zusätzlich.

Die Erwartung habe ich vor dem Testlauf von Hand aus der CSV vom 26.10. abgeleitet. Danach lief das Tool:

| Was in den Läufen vom 26.10. steckt | Von Hand erwartet | Version 2 meldet |
|---|---|---|
| A08 CRM-Kontaktabgleich: 871 statt ≈ 1.184 Kontakte | Einbruch | ✅ P2 „−26,4 % gegenüber dem Median“ |
| A17 Account-Anreicherung: 0 statt ≈ 38 Accounts | verdächtige Null | ✅ P2 „liefert 0 statt ≈ 38“ |
| A19 Build-Log fehlt, obwohl der Laptop lief | Ausfall (2. Woche in Folge) | ✅ P2 „fehlt zum 2. Mal in Folge“ |
| A01 MQL-Erinnerung lief um 08:30:02 und 08:30:44 | Doppellauf | ✅ P3 „doppelt gelaufen“ |
| A02 postet Ticket #48404 zum zweiten Mal (erstmals 15.10.) | Hinweis | ✅ Info im Dashboard |
| A09 Team-Report weiter bei 139 statt ≈ 165 | Störung bleibt offen | ✅ P2, 7. Lauf in Folge; Gegenprobe über A15 (211) und A10 (142) |
| Soll-Läufe am Montag | 32, davon 31 gestartet | ✅ „31 von 32“ |
| Alles andere (A04, A05, A07, A10, A12, A13, A15, A16, A18, A20, A21) | normal | ✅ keine Meldung |

## Was der Testlauf am Tool verändert hat

Vor dem Testlauf (Commit 04.11. 14:44) hätte Heartbeat drei Dinge nicht richtig gemeldet. Ich habe sie im Testlauf bis 14:51 ergänzt, also vor dem technischen Freeze um 15:00:

| Lücke | Ohne Ergänzung | Mit Ergänzung |
|---|---|---|
| Doppellauf A01 | nicht erkannt | P3 „doppelt gelaufen“ |
| A19 fehlt, obwohl der Laptop wieder läuft | in der alten Laptop-Meldung versteckt („22 Läufe“) | eigene Meldung „fehlt zum 2. Mal in Folge“ |
| A10 meldet zweimal 142 | Fehlalarm „derselbe Wert wie davor“ | kein Alarm (erst ab 3× gleich) |

Bekannte Schwäche: Der Hinweis „zeitlich nah an …“ verknüpft A01, A17 und A19, weil montags um 08:00 viel gleichzeitig läuft. Das ist als Hypothese markiert, aber Rauschen. Der nächste Schritt wäre, ihn nur bei gemeinsamer Datenquelle zu zeigen.
