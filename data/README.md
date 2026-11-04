# Eingangsdaten

Anonymisierte Testdaten aus dem Case (nach echten Fällen nachgebaut, Namen neutralisiert). Format: UTF-8, Semikolon als Trenner, deutsche Ortszeit.

| Datei | Inhalt |
|---|---|
| [`automationen.csv`](automationen.csv) | Die 22 Automationen: Werkzeug, Zeitplan, was sie liefern, was die Zahl im Protokoll bedeutet, wer sie nutzt (= Owner) |
| [`laeufe_2026-10-12_bis_2026-10-25.csv`](laeufe_2026-10-12_bis_2026-10-25.csv) | 403 protokollierte Läufe aus zwei Wochen (Ausgangsdaten) |
| [`laeufe_2026-10-26.csv`](laeufe_2026-10-26.csv) | 39 Läufe vom Mo 26.10. (Testlauf, während der Session nachgereicht) |

Spalten der Lauf-Dateien: `lauf_id; automation_id; werkzeug; start; ende; status; anzahl; detail`.
Statuswörter je Werkzeug: Make `success/warning/error`, Cloud-Routine `completed/failed`, Laptop `ok/error`.

Beim Start legt das MVP hier eine Datenbank (`*.db`) und ein lokales Geheimnis (`secrets.json`) an. Beide stehen nicht im Repo.
