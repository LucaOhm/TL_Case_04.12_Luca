# TradeLink – Case Study

> Status: Vorbereitung · Repo: https://github.com/LucaOhm/TradeLink_Case_04.12

## Heartbeat (Case-Lösung)

Wächter für 22 Automationen: sagt jeden Morgen, was am Vortag nicht oder falsch gelaufen ist. Dashboard und Slack sind Mockups auf den echten Läufen.

```bash
cd src && python3 -m heartbeat serve      # Dashboard http://127.0.0.1:8765, Slack-Mockup /slack
cd src && python3 -m unittest discover -s ../tests
```

Testlauf mit einem neuen Protokoll (CSV oder Excel): im Dashboard unter „Datenfluss & Testlauf“ ablegen. Details in [docs/betrieb.md](docs/betrieb.md), Übergabenotiz in [docs/uebergabe.md](docs/uebergabe.md), Voranalyse der Daten in [notes/anomalien-analyse.md](notes/anomalien-analyse.md).

## Worum geht es

Gemeinsamer Case mit einem internen Mitarbeitenden von [TradeLink](https://www.tradelink.co). In 90 Minuten wird ein echtes Problem erarbeitet und eine Lösung gebaut: Präsentation, Workflow, Automatisierung oder Webapplikation.

Ziel: meine Fähigkeiten in einem sicheren Datenumfeld anschaulich und überzeugend zeigen.

## Ordnerstruktur

```
TradeLink_Case/
├── README.md
├── data/          Testdaten von TradeLink (vertraulich, nicht in Git)
├── src/           Umsetzung: Webapp, Workflow oder Automatisierung
├── presentation/  Präsentation
└── notes/         Notizen aus dem Termin und Vorbereitung
```

Leere Ordner enthalten eine `.gitkeep`, damit Git sie mitführt. Die `.gitignore` schließt `data/` aus, damit die Testdaten nicht in das Repo gelangen.

## Offen

- [ ] Format und Umfang der Testdaten
- [ ] Ergebnistyp: Präsentation, Workflow, Automatisierung oder Webapplikation
- [ ] Termin: Der Repo-Name nennt 04.12, bitte bestätigen
- [ ] Ansprechperson und erlaubte Tools
