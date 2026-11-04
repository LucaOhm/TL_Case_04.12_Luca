# Heartbeat für unsere Automationen

*Original-Aufgabenstellung des Case. Die Antworten stehen im [README](../README.md#die-drei-antworten).*

Bei uns laufen 22 Automationen und Agenten: Make-Szenarien, Claude-Routinen in der Cloud und geplante Tasks auf einem Laptop. Keine davon meldet sich, wenn sie nicht läuft.

**Deine Aufgabe:** Bau etwas, das uns jeden Morgen sagt, was am Vortag nicht gelaufen oder falsch gelaufen ist. Es soll laufen, ohne dass einer von uns daran denkt.

## Was du hast

- [`automationen.csv`](../data/automationen.csv): alle 22 Automationen mit Werkzeug, Zeitplan, was sie liefern und was die Zahl in den Protokollen bedeutet.
- [`laeufe_2026-10-12_bis_2026-10-25.csv`](../data/laeufe_2026-10-12_bis_2026-10-25.csv): jeder protokollierte Lauf aus zwei Wochen, eine Zeile pro Lauf.
- [`laeufe_2026-10-26.csv`](../data/laeufe_2026-10-26.csv): die Läufe vom 26.10., nachgereicht während der Session (Testlauf).

## Gut zu wissen

- Alle Zeiten sind deutsche Ortszeit.
- Jedes Werkzeug schreibt seinen Status anders: `success`/`warning`/`error` (Make), `completed`/`failed` (Cloud), `ok`/`error` (Laptop).
- Die Daten sind nach echten Fällen nachgebaut, die Namen sind neutralisiert.
- CSV-Format: UTF-8, Semikolon als Trenner.
- Nimm die Tools, mit denen du am schnellsten bist. Frag alles, was du wissen willst, ich sitze die ganze Zeit neben dir.

## Was ich am Ende sehen will

1. Was dein Ding am Morgen des 27.10. über den 26.10. melden würde. Die Läufe vom 26.10. bekommst du im Lauf der Session.
2. Wo es laufen würde und wer die Meldung bekommt.
3. Eine kurze Übergabenotiz (5 bis 7 Sätze): was es abdeckt, was nicht, und was du als Nächstes bauen würdest.
