#!/bin/bash
# Startet beide MVP-Versionen nebeneinander zum Vergleich (braucht nur Python 3.9+):
#   http://127.0.0.1:8765  Ausgangsdaten 12.–25.10.
#   http://127.0.0.1:8766  Testlauf mit den Läufen vom 26.10.
# Beenden: Ctrl+C
cd "$(dirname "$0")/src" || exit 1
rm -f ../data/vergleich_bis_25.db ../data/vergleich_mit_26.db
python3 -m heartbeat --db ../data/vergleich_bis_25.db import ../data/laeufe_2026-10-12_bis_2026-10-25.csv > /dev/null
python3 -m heartbeat --db ../data/vergleich_bis_25.db serve --port 8765 &
python3 -m heartbeat --db ../data/vergleich_mit_26.db serve --port 8766 &
sleep 2
echo ""
echo "Bis 25.10.:     http://127.0.0.1:8765   (Slack-Mockup: /slack)"
echo "Mit 26.10.:     http://127.0.0.1:8766   (Slack-Mockup: /slack)"
command -v open > /dev/null && open "http://127.0.0.1:8765" && open "http://127.0.0.1:8766"
trap 'kill $(jobs -p) 2>/dev/null' INT TERM
wait
