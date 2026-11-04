"""Baut die Online-Vorschau des MVP: eine einzige HTML-Datei pro Datenstand, ohne Server, ohne Installation.

Der MVP-Code (src/heartbeat) wird NICHT verändert, nur gelesen:
  1. Der echte MVP rechnet einmal alle Antworten vor (jede Rolle, jeder Briefing-Zeitpunkt, jede Meldung, jeder Slack-Verlauf).
  2. Dashboard- und Slack-Oberfläche des MVP werden unverändert eingebunden; ein kleiner Adapter beantwortet ihre
     Anfragen aus den vorgerechneten Daten statt vom Server.
  3. Aktionen (Übernehmen, Gelöst, Upload) sind in der Vorschau nur Anzeige. Im lokalen MVP wirken sie.

Aufruf (aus dem Repo-Ordner):  python3 src/demo_build/build_demo.py src/demo_build/vorschau_links.json
Ergebnis:                     ergebnis/MVP_bis_25-10.html, ergebnis/MVP_mit_26-10.html

Hinweis: Dieses Skript gehört nicht zum MVP (src/heartbeat), es verpackt ihn nur für die Vorschau.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ["HEARTBEAT_BASE_URL"] = "HBBASE"   # Links in Slack-Nachrichten werden im Adapter aufgelöst

from heartbeat import analyst, ingest  # noqa: E402
from heartbeat.app import App  # noqa: E402
from heartbeat.store import Store  # noqa: E402

WEB = ROOT / "src" / "heartbeat" / "web"
OUT = ROOT / "ergebnis"
REPO = "https://github.com/LucaOhm/TradeLink_Case_04.12"

VERSIONEN = [
    {"datei": "heartbeat_bis_25-10", "ausgabe": "MVP_bis_25-10", "titel": "Heartbeat bis 25.10.", "csv": ["laeufe_2026-10-12_bis_2026-10-25.csv"],
     "stand": "Läufe 12.–25.10.2026 (Ausgangsdaten)", "neueste": False},
    {"datei": "heartbeat_mit_26-10", "ausgabe": "MVP_mit_26-10", "titel": "Heartbeat Testlauf 26.10.", "csv": ["laeufe_2026-10-12_bis_2026-10-25.csv", "laeufe_2026-10-26.csv"],
     "stand": "Läufe 12.–26.10.2026 (Testlauf mit den Läufen vom 26.10.)", "neueste": True},
]


def vorrechnen(csvs):
    s = Store(":memory:")
    for f in csvs:
        r = ingest.import_csv(s, ROOT / "data" / f)
        assert not r.get("fehler") and r["abgelehnt"] == 0, r
    app = App(s, analyst.Analyst([]))
    pts = app.points()
    state, detail, slack = {}, {}, {}
    for p in pts:
        for u in app.reg.people:
            st = app.state(p["iso"], u)
            state[p["iso"] + "|" + u] = st
            slack[p["iso"] + "|" + u] = app.slack_feed(p["iso"], u)
            for i in st["incidents"]:
                k = p["iso"] + "|" + i["id"]
                if k not in detail:
                    detail[k] = app.detail(p["iso"], "daniel", i["id"])
    return {"state": state, "detail": detail, "slack": slack, "punkte": [p["iso"] for p in pts], "def": pts[-1]["iso"], "laeufe": s.run_count()}


def css():
    a = (WEB / "app.css").read_text(encoding="utf-8")
    m = re.search(r"@media \(prefers-color-scheme: dark\) \{\s*:root \{(.*?)\}\s*\}", a, re.S)
    dunkel = m.group(1).strip()
    a = a.replace(m.group(0), "@media (prefers-color-scheme: dark) {\n  :root:not([data-theme=\"light\"]) {" + dunkel + " color-scheme: dark; }\n}\n"
                  ":root[data-theme=\"dark\"] {" + dunkel + " color-scheme: dark; }")
    extra = """
/* Vorschau-Anpassungen (nur in der Online-Fassung) */
.top { top: env(safe-area-inset-top, 0px); }
body::before { content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px); z-index: 10; background: var(--surface); }
.top-in, .wrap, .ribbon-in { padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
.wrap { padding-block: 20px 80px; }
.ribbon { background: var(--accent-bg); color: var(--accent-text); border-bottom: 1px solid var(--line); font-size: 13px; }
.ribbon-in { max-width: 1280px; margin: 0 auto; padding-block: 8px; display: flex; gap: 6px 16px; flex-wrap: wrap; align-items: center; }
.ribbon b { font-weight: 650; } .ribbon a { color: var(--accent-text); font-weight: 600; }
#hb-slack .slk { height: 100vh; }
"""
    return a + "\n" + (WEB / "slack.css").read_text(encoding="utf-8") + extra


def body_of(html):
    return re.search(r"<body>(.*)</body>", html, re.S).group(1)


def ohne_skripte(html):
    return re.sub(r"<script[^>]*></script>\s*", "", html)


SAFE_REPLACE = "(function(s,t,u){try{history.replaceState(s,t,u+location.hash)}catch(e){}})("  # Sprungpunkt (#slack-…) bleibt erhalten


def app_js(neueste):
    j = (WEB / "app.js").read_text(encoding="utf-8")
    ersatz = [
        ('$("#slacklink").href = "/slack?u=" + encodeURIComponent(S.u) + "&t=" + encodeURIComponent(S.t);', '$("#slacklink").href = "#slack-" + S.u;'),
        ('link: () => "/slack?u=support&t=" + encodeURIComponent(S.t)', 'link: () => "#slack-support"'),
        ('\'" target="_blank" rel="noopener">Slack-Mockup öffnen ↗</a>\'', '\'">Slack-Mockup öffnen →</a>\''),
        ("history.replaceState(", SAFE_REPLACE),
    ]
    if neueste:
        ersatz.append(('const S = {t: null, u: "daniel"', 'const S = {t: null, latest: true, u: "daniel"'))
    for alt, neu in ersatz:
        assert alt in j, alt
        j = j.replace(alt, neu)
    return "(function(){\n" + j + "\nwindow.__dash = {S: S, load: load};\n})();"


SLACK_IDS = ["who", "when", "prev", "next", "feed", "toast", "todash", "navhb"]


def slack_teile():
    h = body_of((WEB / "slack.html").read_text(encoding="utf-8"))
    h = ohne_skripte(h)
    for i in SLACK_IDS:
        h = h.replace('id="%s"' % i, 'id="s-%s"' % i).replace('for="%s"' % i, 'for="s-%s"' % i)
    h = h.replace('<a id="s-todash" href="/">Dashboard öffnen ↗</a>', '<a id="s-todash" href="#dashboard">← Zurück zum Dashboard</a>')
    h = h.replace("<h1>TradeLink <span", "<h1>Case-Workspace <span")
    j = (WEB / "slack.js").read_text(encoding="utf-8")
    for i in SLACK_IDS:
        j = j.replace('"#%s"' % i, '"#s-%s"' % i)
    ersatz = [
        ('$("#s-todash").href = "/?u=" + encodeURIComponent(Q.u) + "&t=" + encodeURIComponent(Q.t);', '$("#s-todash").href = "#dashboard";'),
        ('window.open(x.url || "/", "_blank", "noopener"); return;', 'window.__hbOpen(x.url || ""); return;'),
        ("history.replaceState(", SAFE_REPLACE),
    ]
    for alt, neu in ersatz:
        assert alt in j, alt
        j = j.replace(alt, neu)
    return h, "(function(){\n" + j + "\nwindow.__slack = {Q: Q, load: load};\n})();"


ADAPTER = r"""
(function () {
  var D = window.HB_DATA, analysiert = {};
  var tset = {}; D.punkte.forEach(function (p) { tset[p] = 1; });
  function zeit(t) {
    if (!t) return D.def;
    if (tset[t]) return t;
    var vor = D.punkte.filter(function (p) { return p <= t; });
    return vor.length ? vor[vor.length - 1] : D.def;
  }
  function antwort(obj, code) {
    return Promise.resolve(new Response(JSON.stringify(obj), {status: code || 200, headers: {"Content-Type": "application/json"}}));
  }
  var echt = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : input.url;
    if (url.indexOf("/api/") !== 0) return echt(input, init);
    var pfad = url.split("?")[0], q = new URLSearchParams(url.split("?")[1] || "");
    var t = zeit(q.get("t")), u = q.get("u") || "daniel";
    if (pfad === "/api/state") return antwort(D.state[t + "|" + u]);
    if (pfad === "/api/slack") return antwort(D.slack[t + "|" + u]);
    if (pfad === "/api/incident") {
      var id = q.get("id"), d = D.detail[t + "|" + id];
      if (!d) return antwort({fehler: "nicht gefunden"}, 404);
      if (analysiert[id]) d = Object.assign({}, d, {analyse: analysiert[id]});
      return antwort(d);
    }
    if (pfad === "/api/analyse") {
      var b = {}; try { b = JSON.parse(init && init.body || "{}"); } catch (e) {}
      analysiert[b.incident] = {quelle: "regelwerk", status: "fallback", body: {hinweis: "In der Online-Vorschau ist keine KI angebunden. Es gilt die Empfehlung aus dem Regelwerk, sie ist vollständig.", versuche: [], hypothesen: [], rueckfragen: [], plausibilitaet: []}};
      return antwort(analysiert[b.incident]);
    }
    if (pfad === "/api/upload") return antwort({fehler: "Die Online-Vorschau liest keine Dateien ein. Im lokalen MVP geht das, siehe README."}, 400);
    return antwort({ok: false, meldung: "Online-Vorschau: nur ansehen. Im lokalen MVP wird diese Aktion gespeichert."});
  };
})();
"""

GLUE = r"""
(function () {
  function zeige(ansicht) {
    document.getElementById("hb-dash").hidden = ansicht !== "dash";
    document.getElementById("hb-slack").hidden = ansicht !== "slack";
    window.scrollTo(0, 0);
  }
  function route() {
    var h = (location.hash || "").slice(1);
    if (h.indexOf("slack") === 0) {
      var u = h.split("-")[1] || (window.__dash && window.__dash.S.u) || "daniel";
      if (window.__slack && window.__dash) { window.__slack.Q.u = u; window.__slack.Q.t = window.__dash.S.t; window.__slack.load(); }
      zeige("slack");
    } else {
      if (window.__dash && window.__slack && window.__kamVonSlack) {
        window.__dash.S.u = window.__slack.Q.u; window.__dash.S.t = window.__slack.Q.t; window.__dash.load();
      }
      zeige("dash");
    }
    window.__kamVonSlack = h.indexOf("slack") === 0;
  }
  window.__hbOpen = function (url) {
    var p = new URLSearchParams((url.split("?")[1]) || "");
    var d = window.__dash;
    if (d) { d.S.u = p.get("u") || d.S.u; d.S.t = p.get("t") || d.S.t; d.S.sel = p.get("i") || null; d.S.tab = "meldungen"; }
    window.__kamVonSlack = false;
    location.hash = "dashboard";
    zeige("dash");
    if (d) d.load();
  };
  window.addEventListener("hashchange", route);
  document.addEventListener("DOMContentLoaded", function () { setTimeout(route, 0); });
})();
"""


def seite(v, daten, andere_url, artefakt):
    dash = body_of((WEB / "index.html").read_text(encoding="utf-8"))
    dash = ohne_skripte(dash)
    dash = dash.replace('<a class="btn" id="slacklink" href="/slack" target="_blank" rel="noopener">Slack-Mockup ↗</a>',
                        '<a class="btn" id="slacklink" href="#slack-daniel">Slack-Mockup →</a>')
    assert 'href="#slack-daniel"' in dash
    slack_html, slack_js = slack_teile()
    ribbon = ('<div class="ribbon"><div class="ribbon-in"><span><b>Online-Vorschau</b> · %s · %d Läufe</span>'
              '<span>Alles ist klickbar, Aktionen wie „Übernehmen“ werden hier nur angezeigt.</span>'
              '%s<a href="%s" target="_blank" rel="noopener">Code und Anleitung auf GitHub ↗</a></div></div>') % (
        v["stand"], daten["laeufe"],
        ('<a href="%s" target="_blank" rel="noopener">%s ↗</a>' % (andere_url[0], andere_url[1])) if andere_url else "", REPO)
    payload = json.dumps(daten, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    blocks = (WEB / "blocks.js").read_text(encoding="utf-8")
    inhalt = (
        '<div id="hb-dash">' + ribbon + dash + '</div>\n<div id="hb-slack" hidden>' + slack_html + '</div>\n'
        "<script>window.HB_DATA = " + payload + ";</script>\n"
        "<script>" + ADAPTER + "</script>\n<script>" + blocks + "</script>\n"
        "<script>" + app_js(v["neueste"]) + "</script>\n<script>" + slack_js + "</script>\n<script>" + GLUE + "</script>\n")
    kopf = ('<title>%s</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n<style>\n%s\n</style>\n' % (v["titel"], css()))
    if artefakt:
        return kopf + inhalt
    return ('<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + kopf + '</head>\n<body>\n' + inhalt + '</body>\n</html>\n')


def main(argv):
    links = {}
    if len(argv) > 1 and argv[1]:  # optional: URLs der veröffentlichten Vorschauen, um sie gegenseitig zu verlinken
        links = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    artefakt_dir = Path(argv[2]) if len(argv) > 2 else None
    for i, v in enumerate(VERSIONEN):
        daten = vorrechnen(v["csv"])
        other = VERSIONEN[1 - i]
        andere = (links[other["datei"]], "Zur anderen Version: " + other["titel"]) if other["datei"] in links else None
        (OUT / (v["ausgabe"] + ".html")).write_text(seite(v, daten, andere, False), encoding="utf-8")
        if artefakt_dir:
            artefakt_dir.mkdir(parents=True, exist_ok=True)
            (artefakt_dir / (v["datei"] + ".html")).write_text(seite(v, daten, andere, True), encoding="utf-8")
        print("%-24s %5.1f MB  %d Briefing-Zeitpunkte, %d Läufe" % (v["datei"], (OUT / (v["ausgabe"] + ".html")).stat().st_size / 1e6, len(daten["punkte"]), daten["laeufe"]))


if __name__ == "__main__":
    main(sys.argv)
