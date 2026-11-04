# Heartbeat: Betrieb, Testlauf, Grenzen

## Was heute läuft (MVP)

| Baustein | Stand |
|---|---|
| Protokoll einlesen (CSV, Excel .xlsx) | läuft, getestet |
| Auswertung: Soll-Kalender, Fehlertext, Median-Band, Gegenproben, Bündelung nach Ursache | läuft, an den echten Läufen vom 12.–25.10. geprüft |
| Priorität und Zustellregeln (Sofort / Morgenbriefing / nur Dashboard) | läuft |
| Dashboard (Rollenansicht, 14-Tage-Raster, Detail mit Empfehlung, Plausibilität, Protokoll, Verlauf) | läuft als Mockup auf echten Daten |
| Slack | **Mockup**: fertige Block-Kit-Nachrichten mit Buttons, nur angezeigt, nichts gesendet |
| Human in the Loop | läuft: Übernehmen, Gelöst, Fehlalarm, Zurückstellen, Änderung freigeben, „neues Normal“ |
| Eskalation an Daniel nach 60 Min. ohne Übernahme oder beim 3. Vorfall | läuft |
| KI-Vertiefung mit Rückfallkette | Rückfalllogik getestet; ohne API-Schlüssel gilt immer das Regelwerk. Live-Aufruf nicht getestet |
| Signierter Webhook + Laptop-Client mit Warteschlange | gebaut und getestet, **nirgends eingehängt** |

Bewusst **nicht** gebaut: Anbindung an Make, Cloud-Routinen, Laptop, echtes Slack, Login.

## Starten und Testlauf

```bash
./start_lokal.sh                        # beide Versionen nebeneinander: 8765 = bis 25.10., 8766 = mit 26.10.
cd src && python3 -m heartbeat serve    # nur eine Version; liest beim ersten Start alle data/laeufe*.csv ein
# Dashboard: http://127.0.0.1:8765        Slack-Mockup: http://127.0.0.1:8765/slack
```

Ohne Installation: die Online-Versionen bzw. die HTML-Dateien in `demo/` (siehe README). Sie sind vorberechnet, Aktionen werden dort nur angezeigt.

Neue Läufe einspielen (z. B. das Excel-Protokoll vom 26.10.):
- im Dashboard unter **Datenfluss & Testlauf** die Datei ablegen, oder
- `python3 -m heartbeat import protokoll.xlsx`, danach `python3 -m heartbeat briefing --day 2026-10-26 --user daniel`.

Erkannt werden mindestens die Spalten `automation_id`, `start`, `status` (Schreibweisen wie „Automation“, „Startzeit“, „Details“ gehen auch;
dazu gern `lauf_id`, `werkzeug`, `ende`, `anzahl`, `detail`). Datumswerte als Excel-Zahl oder `26.10.2026 07:30` werden verstanden.
Der Import ist wiederholbar: Bekanntes wird nicht doppelt gezählt. Unlesbares geht mit Grund in die Quarantäne (Dashboard, Reiter Datenfluss).
Liegen nur die Läufe bis 26.10. ~20 Uhr vor, wertet das Briefing für Di 27.10. den Tagesabschluss aus und nennt den Datenstand offen.

Tests: `cd src && python3 -m unittest discover -s ../tests -v`

## Wie es entscheidet

1. **Hat es gelaufen?** Der Soll-Kalender (Zeitplan je Automation, Europe/Berlin) gegen das Protokoll. Nachgeholte Läufe zählen als nachgeholt.
2. **Meldet es Fehler?** Status und Fehlertext. Beispiel A02: Status `success`, Text `HTTP 404 channel_not_found (Fehler ignoriert)` = Fehler.
3. **Ist die Zahl normal?** Median der letzten guten Läufe, Toleranz aus Streuung und fester Untergrenze je Automation.
   Auffällige Werte fließen nicht in die Basis ein, damit ein Fehlerzustand nicht von selbst zum Normal wird. „0“ gilt nur dort als Fehler, wo es nicht üblich ist.
4. **Querchecks:** Liefen andere Automationen im selben Zeitraum normal? Bewegen sich verwandte Kennzahlen (A09/A10/A15) mit? Gibt es zeitlich nahe Störungen?
   Jeder Befund trägt eine Stärke: belegt, Hinweis oder Hypothese.
5. **Bündeln:** Fallen mehrere Laptop-Aufgaben gleichzeitig aus, ist das eine Meldung.

Zustellung: Sofort-Klasse (A02, A03, A07, A22) und Priorität P1/P2 gehen direkt an den Owner, alles andere einmal um 07:00 gebündelt.
Unbearbeitetes steht im Briefing erneut. Auch ein leeres Briefing geht raus, damit sein Ausbleiben auffällt.

## Wo es laufen würde und wer was bekommt

- **Wo:** ein kleiner, dauerhaft laufender Dienst in der Cloud (Webhook-Endpunkt, Briefing 07:00, Dashboard). Nicht auf dem Laptop und nicht in einer der überwachten Routinen.
  Ein externer Wächter erwartet täglich ein Lebenszeichen, damit der Ausfall des Heartbeat selbst auffällt.
- **Owner** = Spalte `genutzt_von` (Vorgabe). Daniel (Chief of Staff) bekommt zusätzlich Eskalationen und sieht alles; die Geschäftsführung sieht alles im Dashboard,
  im Briefing nur Eigenes und Kritisches. „Alle Teams“-Automationen gehören Daniel.
- **Fachbereiche** sehen nur ihre Automationen. Bearbeiten dürfen Owner und Verantwortliche.

## Sicherheit (soweit gebaut)

- Webhook: Signatur je Quelle (HMAC-SHA256 über Zeitstempel und Inhalt), Schutz gegen Wiederholung, eine Quelle darf nur ihr Werkzeug melden, Größenlimit, Quarantäne.
- Excel-Import: Größenlimits, keine XML-Entities, es wird nichts ausgeführt.
- Dashboard: Standard nur lokal (127.0.0.1), Aktionen brauchen einen Anfragekopf, strenge Inhaltsrichtlinie, keine Fremd-Skripte.
- **Mockup-Grenze:** Die Rolle wird im Dashboard gewählt. In Produktion ersetzt „Mit Slack anmelden“ diese Auswahl.
- Daten aus `data/` und Geheimnisse (`data/secrets.json`) bleiben aus Git.

## Annahmen und Grenzen

- Owner = Team, nicht Person (keine Namen in den Daten). Sofort-Klasse und Dateneigentum sind in `src/heartbeat/registry.json` einstellbar.
- A15 nutzt die Scores von A10: Annahme, nicht belegt.
- Nur zwei Wochen Daten: Wochenjobs haben 1–2 Werte, das Band greift bei ihnen erst ab dem zweiten Wert. Schwellen nach vier Wochen nachjustieren.
- Ereignisgesteuerte Läufe (A02, A03): Ein Trigger, der nie ankommt, ist ohne Gegenquelle (Ticketsystem, gewonnene Deals) nicht sichtbar.
- Laufdauer wird nicht bewertet: In den Daten streut sie bei gleichem Ergebnis zu stark.
