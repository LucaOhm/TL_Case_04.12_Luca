# Demo: Heartbeat ohne Installation

| Datei | Was |
|---|---|
| [`heartbeat_bis_25-10.html`](heartbeat_bis_25-10.html) | Version 1: Ausgangsdaten 12.–25.10. ([online](https://claude.ai/artifact/CnsVpL8jFZXvqstir2ygk3)) |
| [`heartbeat_mit_26-10.html`](heartbeat_mit_26-10.html) | Version 2: Testlauf mit den Läufen vom 26.10. ([online](https://claude.ai/artifact/Pkpyyp8toprAYnDvhPZfGt)) |
| [`build_demo.py`](build_demo.py) | Baut beide Dateien aus dem MVP-Code |
| [`vorschau_links.json`](vorschau_links.json) | Adressen der Online-Versionen (für die gegenseitige Verlinkung) |

**Öffnen:** Datei herunterladen (auf GitHub: Datei anklicken → „Download raw file“) und per Doppelklick im Browser öffnen. Es gibt keinen Server und keine Installation, alle Daten stecken in der Datei.

**Wie es gebaut ist:** Das Skript lässt den echten MVP (`src/heartbeat`) einmal alle Antworten vorberechnen, für jede Rolle, jeden Briefing-Zeitpunkt und jede Meldung. Die unveränderten Oberflächen des MVP (Dashboard und Slack-Mockup) bekommen ihre Daten dann aus der Datei statt vom Server. Deshalb sind Aktionen wie „Übernehmen“ hier nur Anzeige. Im lokalen MVP (`./start_lokal.sh`) werden sie gespeichert.

**Neu bauen** (z. B. nach neuen Daten in `data/`): `python3 demo/build_demo.py demo/vorschau_links.json`
