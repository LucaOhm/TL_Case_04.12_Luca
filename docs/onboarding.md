# Willkommen bei Heartbeat

**In einem Satz:** Heartbeat sagt dir jeden Morgen, ob deine Automationen gestern gelaufen sind, und meldet sich sofort, wenn bei Kunden etwas hängt.

> 🎬 **Lieber schauen als lesen?** [Demo-Video ansehen (2:18 Min.)](../ergebnis/Demo-Video_Mitarbeiter.mp4)
> 👀 **Gleich ausprobieren:** [Online-Vorschau öffnen](https://claude.ai/artifact/Pkpyyp8toprAYnDvhPZfGt) → oben rechts „Geführte Tour“

---

## Was du bekommst

| Wann | Wo | Was |
|---|---|---|
| **Jeden Morgen um 7:00** | Slack, Nachricht von „Heartbeat“ | Dein Briefing: Was ist gestern bei *deinen* Automationen schiefgelaufen? Auch wenn alles gut ist, kommt eine kurze Nachricht. Bleibt sie aus, stimmt etwas mit Heartbeat selbst nicht. |
| **Sofort** | Slack | Nur bei kundennahen Fehlern: Support-Tickets, Kunden-Übergaben, Abo-Freigaben, Newsletter-Aufgaben. |
| **Bei Bedarf** | Dashboard (Link in jeder Nachricht) | Die Details: was passiert ist, warum vermutlich, was zu tun ist, das Rohprotokoll. |

Du siehst nur die Automationen deines Teams. Daniel (Chief of Staff) sieht alle.

## Was du tust, wenn eine Meldung kommt

1. **Übernehmen** klicken. Damit wissen alle, dass du dich kümmerst, und die Eskalation an Daniel stoppt.
2. **Details** öffnen. Unter „Empfehlung“ stehen die konkreten Schritte, unter „Protokoll“ die Rohdaten zum Nachprüfen.
3. Wenn es behoben ist: **Gelöst** klicken. War es keiner: **Fehlalarm**. So bleibt die Liste aktuell, und gehäufte Fehlalarme zeigen, wo die Schwellen nachjustiert werden sollten.

Drei Dinge passieren **nie** automatisch:
- Heartbeat ändert keine Automation. Vorschläge wie „Zeitplan anpassen“ musst du freigeben und selbst umsetzen.
- Heartbeat schließt keine Meldung. Auch wenn wieder alles läuft, bestätigst du die Ursache.
- Heartbeat rät nicht still. Unsichere Schlüsse stehen als **Hypothese** da.

## Was die Farben bedeuten

| | Priorität | Bedeutung | Kommt |
|---|---|---|---|
| 🔴 | **P1 kritisch** | Kunden oder Geld betroffen, oder ein Fehler hält seit Tagen an | sofort bzw. ganz oben im Briefing |
| 🟠 | **P2 hoch** | Ergebnis fehlt oder ist auffällig falsch | Morgenbriefing |
| 🟡 | **P3 mittel** | Ärgerlich, aber begrenzt (z. B. doppelt gelaufen) | Morgenbriefing |
| ⚪ | **P4 Hinweis** | Zur Kenntnis, kein Handlungsbedarf | nur im Dashboard |

Im Dashboard unter **„14-Tage-Raster“** siehst du auf einen Blick, wann was gelaufen ist: grün gelaufen, rot Fehler, orange gestreift Lauf fehlt, gelb Hinweis.

## Häufige Fragen

**Warum meldet Heartbeat einen Fehler, obwohl Make „success“ sagt?**
Weil der Status allein nicht reicht. Ein Lauf kann „erfolgreich“ enden und trotzdem nichts liefern, etwa wenn ein Slack-Kanal fehlt und der Fehler ignoriert wird. Heartbeat prüft deshalb auch den Text und die Zahl.

**Ab wann ist eine Zahl „auffällig“?**
Wenn sie deutlich vom Median der letzten guten Läufe abweicht. Eine 0 ist nur dort ein Fehler, wo sie sonst nie vorkommt. Beim Postfach-Scan ist sie normal, beim Deal-Score nicht.

**Die Zahl ist absichtlich gesunken, z. B. nach einer Bereinigung.**
In der Meldung „Als neues Normal übernehmen“ klicken. Ab dann vergleicht Heartbeat mit dem neuen Niveau.

**Ich bekomme zu viel.**
Sag Bescheid. Schwellen und Zuständigkeiten sind pro Automation einstellbar.

**Wen frage ich?**
Daniel (Chief of Staff) oder Luca (Heartbeat).
