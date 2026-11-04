# Analyse der Läufe 12.10.–25.10.2026 (Stand vor dem Tool-Bau)

Grundlage: `automationen.csv` (22 Automationen), `laeufe_2026-10-12_bis_2026-10-25.csv` (403 Läufe).
Zeitraum: Mo 12.10. bis So 25.10. (14 Tage, 10 Arbeitstage). Alle Zeiten deutsche Ortszeit.

**Methode und Grenze:** Die Dateien liegen auf dem Desktop; die Shell darf dort nicht lesen (macOS-Rechte). Ich habe die Dateien direkt gelesen und von Hand ausgewertet, nicht per Skript. Die Zahlen sind über eine Gegenrechnung abgesichert (siehe Selbstcheck). Sobald die CSVs in `data/` liegen, prüft ein Skript alles noch einmal maschinell.

---

## 1. Befunde, nach Schwere

### F1 – KRITISCH: A02 Support-Ticket-Triage hat 20 Tickets verschluckt, Status zeigt „success"
- Zeitraum: 20.10. 07:38 bis 21.10. 18:30. Davon waren 11 Tickets am 20.10. und 9 am 21.10.
- Jeder Lauf in diesem Fenster hat: `status=success`, `anzahl=1`, Detail „Post fehlgeschlagen, HTTP 404 channel_not_found (Fehler ignoriert)".
- Es gab in dem Fenster **keinen einzigen erfolgreichen** Post. Der Support-Kanal hat diese 20 Tickets nie gesehen.
- Beginn liegt zwischen 19.10. 19:28 (letzter guter Post) und 20.10. 07:38. Ende liegt zwischen 21.10. 18:30 und 22.10. 08:00 (dazwischen kam kein Ticket). Ab 22.10. wieder normal, ohne Hinweis im Log, was geändert wurde.
- Lehre: Status und Anzahl sind hier falsch. Nur der Detailtext verrät den Fehler. Eine reine Statusprüfung hätte das nie gefunden. Auch die Menge (11 und 9 Tickets pro Tag) war normal.
- Offen: Wurden die 20 Tickets nachgetragen?

### F2 – KRITISCH: A10 Deal-Score liefert 6 Arbeitstage lang 0 Deals, Status „completed"
- Läufe mit 0: 14.10., 15.10., 16.10., 19.10., 20.10., 21.10. Normal sind 141–143 (12.10./13.10.). Ab 22.10. wieder 141, 142.
- Laufzeiten (2,5–7,5 Min.) sind wie bei guten Läufen. Das ist also kein schneller Absturz, sondern ein Lauf, der „erfolgreich" nichts bewertet.
- Folge: Grundlage für den Forecast der Geschäftsführung fehlte mindestens 14.–21.10.
- A10 hat sonst immer ≈ 142. Eine 0 ist hier nie plausibel (anders als bei A07, A11, A20 usw., siehe 3.).

### F3 – HOCH: A09 Team-Report-Daten fällt am 20.10. sprunghaft ab und bleibt dort
- 12.–19.10.: 163–168 Deals. Ab 20.10.: 137, 138, 138, 138, 138, 137 (−31, etwa −18 %).
- Auffällig: Vorher streut die Zahl um ±3, nachher fast gar nicht mehr. Das kann ein echter Pipeline-Effekt sein (Deals geschlossen, Filter geändert) oder ein Fehler (Quelle, Berechtigung, Filter).
- Zeitlich fällt das mit F1 (ab 20.10.) zusammen. Eine gemeinsame Ursache (z. B. Umbau im Workspace am 19./20.10.) ist nur eine Vermutung.
- Gegenprobe: A15 (Pipeline-Wochenreport, „alle offenen Deals") meldete 214 und 213. Läuft Mo 26.10. und zeigt, ob der Sprung dort auch auftaucht.
- Auch ohne Sprung: Die Deal-Zahlen der drei Läufe passen nicht zusammen (A15 ≈ 214, A09 ≈ 165, A10 ≈ 142). Die Definitionen sind mir unklar (Frage 3).

### F4 – HOCH: Laptop war am Fr 16.10. komplett und am Mo 19.10. teilweise aus
- **Fr 16.10.: 0 von 14 Läufen.** A16, A18, A21 und alle 11 Stundenläufe von A20 fehlen. Die Cloud- und Make-Läufe dieses Tages sind da.
- **Mo 19.10.:** Der Laptop war offenbar bis ca. 10:06 aus. Es fehlen A16 (07:06), A17 (08:00), A19 (07:45) und die A20-Läufe 08, 09, 10 Uhr. A18 lief erst um 10:06 statt 07:30 (2 h 36 min zu spät). Ab 11:00 normal.
- Gesamt: 20 verpasste Läufe, 1 verspätet.
- Folgen: Rechnungs-Snapshot für Finance fehlt für 16.10. und 19.10., der Stand vom 15.10. war am 20.10. fünf Tage alt. A17 (Account-Anreicherung) und A19 (Build-Log) sind **Wochenläufe, die eine ganze Woche ausgefallen sind** (nächster Versuch 26.10.). Ein Wochenjob, der ausfällt, fällt sonst erst nach 7 Tagen auf.
- A18 wurde nachgeholt, A16/A17/A19 nicht. Warum, ist offen (Frage 6).

### F5 – MITTEL: A04 Transkript-Import 14.10. mit HTTP 401 „Token abgelaufen"
- Fehler um 06:00, um 09:12 manuell nachgeholt („manuell gestartet", 9 Transkripte). Die Lücke ist also geschlossen.
- Trotzdem melden: Das Token läuft ab und kann wieder ablaufen. Der manuelle Lauf darf nicht wie ein regulärer zählen und nicht den Fehler „löschen", aber er muss ihn als „behoben" herabstufen.

### F6 – NIEDRIG: A07 Warnungen wegen Rate-Limit
- 14.10. 20:00: 3 Übergaben zugewiesen, Rate-Limit, automatisch wiederholt. Ausgang plausibel gut.
- 22.10. 20:00: **0** zugewiesen, Rate-Limit, wiederholt. Hier ist unklar, ob der Retry wirklich etwas zugewiesen hätte. Der nächste Lauf (23.10. 00:00) hat ebenfalls 0, das klärt nichts.

### F7 – NIEDRIG, UNSICHER: A08 CRM-Kontaktabgleich zweimal identisch
- 15.10. und 16.10.: beide 1163, Laufzeit 6 s und 4 s (sonst oft 20–37 s). Sonst schwankt die Zahl 1159–1212.
- Kann Zufall sein. Weil Laufzeit allein nichts belegt (19.10. ebenfalls 6 s bei 1212), nur als Hinweis führen.

### F8 – NIEDRIG: Ticket #48586 kommt zweimal vor
- 13.10. 18:49 und 22.10. 19:20 in A02. Entweder ein wiedereröffnetes Ticket oder ein Duplikat. Kein anderes doppelt.

### F9 – INFO: Zeitumstellung am So 25.10.2026
- Am 25.10. endet die Sommerzeit: 25-Stunden-Tag, 02:00–03:00 gibt es doppelt. A08 hat nur einen Lauf um 02:00, kein Fehler.
- Für das Tool: Tage und „Vortag" in Europe/Berlin rechnen, nicht mit festem UTC-Versatz. Der 26.10. selbst ist ein normaler 24-Stunden-Tag.

---

## 2. Abdeckung: Soll gegen Ist (nur zeitgesteuerte Läufe)

| Automation | Soll | Ist | Bemerkung |
|---|---|---|---|
| A01 | 10 | 10 | 0 = „keine neuen MQLs", normal |
| A04 | 14 | 14 + 1 manuell | 14.10. Fehler, siehe F5 |
| A05, A06, A12, A13, A14, A15, A22 | je 2 | je 2 | vollständig |
| A07 | 84 | 84 | 2 Warnungen (F6) |
| A08 | 14 | 14 | F7 |
| A09 | 14 | 14 | F3 |
| A10 | 10 | 10 | 6 davon mit 0 (F2) |
| A11 | 14 | 14 | |
| A16 | 10 | 8 | fehlt 16.10., 19.10. |
| A17 | 2 | 1 | fehlt 19.10. |
| A18 | 10 | 9 | fehlt 16.10.; 19.10. 2 h 36 min zu spät |
| A19 | 2 | 1 | fehlt 19.10. |
| A20 | 110 | 96 | fehlt 16.10. (11), 19.10. (3) |
| A21 | 10 | 9 | fehlt 16.10. |
| **Summe** | **318** | **298** (+1 manuell) | 20 Läufe fehlen |

Ereignisgesteuert: A02 hat 99 Läufe (davon 20 mit verschlucktem Fehler), A03 hat 5 Läufe (13.10. ×2, 20.10. ×2, 22.10. ×1).

---

## 3. Was „0" bedeutet, je Automation

Eine 0 ist nicht überall ein Fehler. Das Tool braucht pro Automation eine Regel. Mein Vorschlag, bitte bestätigen:

| 0 ist normal | 0 ist verdächtig |
|---|---|
| A01 (keine neuen MQLs), A04 am Wochenende, A07, A11 (meist 0), A20, A21 | **A10** (immer ≈ 142), **A09** (immer ≈ 140–170), A08 (immer ≈ 1200), A16 (≈ 41–47), A18 (immer 6–12), A15 (≈ 214), A12 (3), A05 (5), A14/A06/A13/A19 (1) |

Offen: A04 an Werktagen (liegt 7–19, eine 0 wäre auffällig), A22/A17/A03 (kaum Daten).

---

## 4. Grenzen der Daten (was das Tool nicht erkennen kann)

1. **Das Log enthält nur gestartete Läufe.** „Nicht gelaufen" ist nur aus dem Zeitplan ableitbar. Das gilt besonders für den Laptop, wenn dessen Logs verspätet ankommen (Frage 1).
2. **Ereignisgesteuerte Automationen (A02, A03)** haben keinen Zeitplan. Ein Ausfall (Trigger kommt nicht an) ist ohne Gegenquelle (Ticketsystem, gewonnene Deals) nicht sichtbar. Nur Fehlertexte und ungewöhnlich lange Pausen sind prüfbar.
3. **Status ist unzuverlässig** (F1, F2). Man braucht Regeln auf Detailtext und Zahlen.
4. **Zahlenvergleich braucht eine Basis.** Nach nur zwei Wochen gibt es kaum Wochenläufe zum Vergleichen (A05/A12/A14: je 2 Werte).
5. **Der Heartbeat kann selbst ausfallen.** Es braucht eine Meldung „Heartbeat selbst lief", sonst ist Stille nicht von „alles gut" zu unterscheiden.

---

## 5. Selbstcheck

- Gegenrechnung: 298 geplante Läufe + 1 manueller + 5 A03 + 99 A02 = **403** = Anzahl Zeilen. Das passt exakt, meine Zählung je Automation stimmt damit sehr wahrscheinlich.
- Alle 22 IDs in beiden Dateien vorhanden, Werkzeug je Lauf passt zur Automationenliste, Statuswörter passen zum jeweiligen Werkzeug.
- Beim Durchlesen keine Läufe mit Ende vor Start, keine unplanmäßigen Läufe außer A04 (manuell) und A18 (verspätet), Anzahl in `anzahl` passt zur Zahl im Detail.
- **Nicht** per Skript geprüft: lückenlose `lauf_id`, exakte Laufzeitverteilung. Das folgt, sobald die Dateien in `data/` liegen.
- Kalender geprüft: 12.10.2026 ist ein Montag, 25.10.2026 ein Sonntag, Zeitumstellung am 25.10.
- Zwischenentscheidungen, die ich getroffen habe: „0 bei A10 ist falsch", „Laptop-Ausfall = Gerät aus, nicht Aufgabenfehler", „identische 1163 ist nur ein Hinweis".

---

## 6. Offene Fragen an dich

1. **Datenquelle im Betrieb:** Wie kommen die Läufe zum Heartbeat? Make-API, Log der Cloud-Routinen, Datei auf dem Laptop? Und kommen Laptop-Logs sofort oder erst, wenn der Laptop wieder online ist?
2. **A10:** Stimmt es, dass 0 Deals bewertet nie korrekt sein kann?
3. **Deal-Zahlen:** A15 ≈ 214, A09 ≈ 165, A10 ≈ 142. Sind das bewusst verschiedene Mengen? Gab es um den 19./20.10. eine Änderung an der Pipeline (Bereinigung, neuer Filter, Berechtigung), die den Sprung auf 138 erklärt?
4. **A02:** Wurde am 19./20.10. ein Kanal gelöscht, umbenannt oder archiviert? Wurden die 20 Tickets nachgetragen? Ist #48586 ein Duplikat?
5. **A07 22.10. 20:00:** Gilt „Rate-Limit, wiederholt, 0" als erledigt oder als prüfen?
6. **Laptop:** War er am 16.10. und Vormittag des 19.10. aus (frei, unterwegs)? Warum wurde nur A18 nachgeholt?
7. **Zeitpunkt der Meldung:** Soll die Meldung vor 07:00 kommen? Dann ist A16 (07:06) für den heutigen Tag noch nicht gelaufen, die Meldung betrifft aber nur den Vortag. Passt das?
8. **Feiertage:** Sollen Mo–Fr-Automationen an Feiertagen als „sollte laufen" gelten?
