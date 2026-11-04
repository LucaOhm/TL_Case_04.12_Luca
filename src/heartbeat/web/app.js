/* Heartbeat-Dashboard (Mockup auf echten Daten). Vanilla JS, kein Build-Schritt. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const E = escH;
const S = {t: null, u: "daniel", d: null, sel: null, det: null, tab: "meldungen", sub: "ueberblick", filter: null, logFor: null, showDone: false, tour: -1};
const LANES = [["offen", "Wartet auf eine Entscheidung"], ["in_arbeit", "In Arbeit"], ["erholt", "Wieder normal · Bestätigung offen"], ["info", "Hinweise ohne Handlungsbedarf"], ["erledigt", "Erledigt"]];
const STEPTYPE = {pruefen: "Prüfen", aendern: "Ändern", nacharbeit: "Nacharbeit", bestaetigen: "Bestätigen"};
const DELIV = {sofort: ["acc", "Sofort per Slack"], morgen: ["", "Morgenbriefing"], dashboard: ["", "Nur Dashboard"]};

// ---------------------------------------------------------------- Daten
async function api(path, body) {
  const o = body === undefined ? {} : {method: "POST", headers: {"X-Requested-With": "heartbeat", "Content-Type": "application/json"}, body: typeof body === "string" ? body : JSON.stringify(body)};
  const r = await fetch(path, o);
  return r.json();
}
const qp = () => "u=" + encodeURIComponent(S.u) + (S.t ? "&t=" + encodeURIComponent(S.t) : "");
function sync() {
  const p = new URLSearchParams({u: S.u, tab: S.tab});
  if (S.t) p.set("t", S.t);
  if (S.sel) p.set("i", S.sel);
  history.replaceState(null, "", "?" + p.toString());
}
function toast(msg) {
  const t = $("#toast"); t.innerHTML = '<div class="toast">' + E(msg) + "</div>";
  clearTimeout(toast.h); toast.h = setTimeout(() => (t.innerHTML = ""), 3800);
}
async function load() {
  let d = await api("/api/state?" + qp());
  if (!S.t) {
    const pref = S.latest ? null : d.points.find(p => p.label.startsWith("Mi 21.10."));
    S.latest = false;
    S.t = pref ? pref.iso : d.as_of;
    if (S.t !== d.as_of) d = await api("/api/state?" + qp());
  }
  S.d = d; S.t = d.as_of;
  if (S.sel && !d.incidents.find(i => i.id === S.sel)) { S.sel = null; S.det = null; }
  if (S.sel) S.det = await api("/api/incident?" + qp() + "&id=" + encodeURIComponent(S.sel));
  render();
}
async function pick(id) {
  S.sel = id; S.sub = "ueberblick"; S.logFor = null;
  S.det = id ? await api("/api/incident?" + qp() + "&id=" + encodeURIComponent(id)) : null;
  renderView(); sync();
}
async function act(action, inc, extra) {
  const r = await api("/api/action?" + qp(), Object.assign({incident: inc, action}, extra || {}));
  toast(r.meldung || r.fehler || "Fertig");
  await load();
}

// ---------------------------------------------------------------- Kopf
function renderTop() {
  const d = S.d, w = $("#when");
  w.innerHTML = d.points.map(p => '<option value="' + E(p.iso) + '"' + (p.iso === d.as_of ? " selected" : "") + ">Briefing " + E(p.label) + (p.teilweise ? " · Teildaten" : "") + "</option>").join("");
  const i = d.points.findIndex(p => p.iso === d.as_of);
  $("#prev").disabled = i <= 0; $("#next").disabled = i < 0 || i >= d.points.length - 1;
  $("#who").innerHTML = d.users.map(u => '<option value="' + u.id + '"' + (u.id === S.u ? " selected" : "") + ">" + E(u.name) + (u.alle ? " (Gesamtübersicht)" : "") + "</option>").join("");
  $("#slacklink").href = "/slack?u=" + encodeURIComponent(S.u) + "&t=" + encodeURIComponent(S.t);
  let b = "";
  if (d.teilweise) b += '<div class="banner warn"><span>⏱</span><div><b>Datenstand bis ' + E(d.daten_bis) + ".</b> Das Briefing wertet den Tagesabschluss aus. Läufe nach diesem Zeitpunkt liegen noch nicht vor und werden nicht als Ausfall gezählt.</div></div>";
  b += '<div class="banner"><span>ℹ</span><div>Replay auf den eingelesenen Läufen (' + E(d.selfcheck.von) + ' bis ' + E(d.selfcheck.bis) + '). Du siehst, <b>was Heartbeat am ' + E(d.deliver_label) + '</b> gemeldet hätte – ' + (d.user.alle ? "mit Gesamtübersicht für Verantwortliche" : "nur mit den Automationen von <b>" + E(d.user.name) + "</b>") + ". Slack ist simuliert.</div></div>";
  $("#banner").innerHTML = b;
}
function renderKpis() {
  const d = S.d, k = d.kpi, b = d.bilanz, q = b.soll ? Math.round(100 * b.ist / b.soll) : 100;
  const T = (id, l, v, s, cls) => '<button class="kpi ' + (cls || "") + (S.filter === id ? " on" : "") + '" data-f="' + id + '"><div class="l">' + l + '</div><div class="v num">' + v + '</div><div class="s">' + s + "</div></button>";
  $("#kpis").innerHTML =
    T("wartet", "Wartet auf eine Entscheidung", k.wartet, k.kritisch ? k.kritisch + " davon kritisch (P1)" : "keine kritischen", k.kritisch ? "alert" : "") +
    T("in_arbeit", "In Arbeit", k.in_arbeit, "von einer Person übernommen") +
    T("erholt", "Wieder normal", k.erholt, "wartet auf Bestätigung der Ursache") +
    '<div class="kpi"><div class="l">Gestern gelaufen (' + E(b.label) + ')</div><div class="v num">' + b.ist + '<span style="font-size:16px;color:var(--faint)"> / ' + b.soll + '</span></div><div class="bar"><i style="width:' + q + '%"></i></div><div class="s">Soll-Läufe, die gestartet sind</div></div>';
  document.querySelectorAll("#kpis [data-f]").forEach(el => el.addEventListener("click", () => { S.filter = S.filter === el.dataset.f ? null : el.dataset.f; S.tab = "meldungen"; renderTabs(); renderView(); renderKpis(); }));
}
function renderTabs() {
  const d = S.d, open = d.kpi.wartet + d.kpi.in_arbeit + d.kpi.erholt;
  const T = [["meldungen", "Meldungen", open], ["raster", "14-Tage-Raster"], ["automationen", "Automationen", d.automations.length], ["einlieferung", "Datenfluss & Testlauf"]];
  $("#tabs").innerHTML = T.map(t => '<button class="tab' + (S.tab === t[0] ? " on" : "") + '" role="tab" data-t="' + t[0] + '">' + t[1] + (t[2] != null ? '<span class="n">' + t[2] + "</span>" : "") + "</button>").join("");
  document.querySelectorAll("#tabs .tab").forEach(el => el.addEventListener("click", () => { S.tab = el.dataset.t; renderTabs(); renderView(); sync(); }));
}

// ---------------------------------------------------------------- Meldungen
function card(i) {
  const lvl = "p" + i.level, dv = DELIV[i.delivery] || ["", ""];
  const autos = i.kind === "gruppe" ? i.children.map(c => '<span class="chip auto" title="' + E(c.name) + '">' + c.automation + " ×" + c.count + "</span>").join("")
    : i.auto_info.map(a => '<span class="chip auto">' + E(a.id) + "</span><span class='chip'>" + E(a.name) + "</span>").join("");
  let btns = "";
  if (i.can_act) {
    if (i.state === "neu" && i.lane !== "erholt") btns += '<button class="btn sm primary" data-act="ack" data-id="' + E(i.id) + '">Übernehmen</button>';
    if (i.lane === "erholt") btns += '<button class="btn sm primary" data-act="resolve" data-id="' + E(i.id) + '">Ursache bestätigen · Gelöst</button>';
  }
  btns += '<button class="btn sm ghost" data-pick="' + E(i.id) + '">Details & Empfehlung →</button>';
  const status = i.lane === "erholt" ? '<span class="chip ok">Wieder normal seit ' + E(i.recovered) + "</span>" : '<span class="chip">' + E(i.state_label) + (i.assignee ? " · " + E(i.assignee) : "") + "</span>";
  return '<article class="card ' + lvl + (i.lane === "erledigt" ? " done" : "") + (S.sel === i.id ? " sel" : "") + '" data-pick="' + E(i.id) + '">' +
    '<div class="chips"><span class="chip ' + lvl + '">P' + i.level + " " + E(i.level_name) + '</span><span class="chip ' + dv[0] + '">' + dv[1] + "</span>" + status +
    (i.wiederkehrend ? '<span class="chip p3">wiederkehrend</span>' : "") + (i.wiederaufgetreten ? '<span class="chip p1">erneut aufgetreten</span>' : "") + "</div>" +
    "<h3>" + E(i.titel) + "</h3><p>" + E(i.kurz) + '</p><div class="chips">' + autos + '</div><div class="meta"><span>Owner: ' + E(i.owner_namen.join(", ")) + "</span><span>seit " + E(i.first) + '</span><span class="num">' + (i.count === 1 ? "1 Lauf" : i.count + " Läufe") + "</span><span>Dauer " + E(i.dauer) + "</span></div>" +
    '<div class="acts">' + btns + "</div></article>";
}
function viewMeldungen() {
  const d = S.d;
  let list = d.incidents.slice();
  if (S.filter === "wartet") list = list.filter(i => i.lane === "offen"); else if (S.filter === "in_arbeit") list = list.filter(i => i.lane === "in_arbeit"); else if (S.filter === "erholt") list = list.filter(i => i.lane === "erholt");
  let html = "";
  LANES.forEach(([lane, label]) => {
    const items = list.filter(i => i.lane === lane);
    if (!items.length) return;
    if (lane === "erledigt" && !S.showDone) { html += '<div class="lane-h"><button class="btn sm" id="showdone">' + items.length + " erledigte anzeigen</button></div>"; return; }
    html += '<div class="lane-h">' + label + '<span class="n">' + items.length + "</span></div>" + items.map(card).join("");
  });
  if (!list.length) html = '<div class="empty"><b>Nichts offen</b>Alles ist gelaufen, was laufen sollte' + (S.filter ? " – oder der Filter ist aktiv. Klick erneut auf die Kachel." : ".") + "</div>";
  return '<div class="cols"><div>' + html + '</div><aside class="side" id="side">' + sideHtml() + "</aside></div>";
}
function sideHtml() {
  if (!S.det) {
    return '<div class="side-h"><h2>Dein Morgenbriefing</h2><div class="meta">So kommt es um 07:00 in Slack bei ' + E(S.d.user.name) + ' an</div></div><div class="side-b" id="prev-brief"></div>' +
      '<div class="side-b" style="padding-top:0"><div class="callout">Die Slack-Nachricht ist kurz und führt zum Handeln. Hier im Dashboard liegt die Vertiefung: Empfehlung, Plausibilität, Protokoll und Verlauf. Klick links auf eine Meldung.</div></div>';
  }
  const i = S.det, lvl = "p" + i.level, dv = DELIV[i.delivery] || ["", ""];
  const tabs = [["ueberblick", "Überblick"], ["empfehlung", "Empfehlung"], ["plausibilitaet", "Plausibilität"], ["protokoll", "Protokoll"], ["verlauf", "Verlauf"]];
  let ab = "";
  if (i.can_act) {
    if (i.lane === "erholt" || i.state === "uebernommen") ab += '<button class="btn sm primary" data-act="resolve" data-id="' + E(i.id) + '">Als gelöst bestätigen</button>';
    if (i.state === "neu" && i.lane !== "erholt") ab += '<button class="btn sm primary" data-act="ack" data-id="' + E(i.id) + '">Übernehmen</button>';
    ab += '<button class="btn sm" data-act="false_alarm" data-id="' + E(i.id) + '">Fehlalarm</button><button class="btn sm" data-act="snooze" data-id="' + E(i.id) + '">24 h zurückstellen</button>';
    if (i.state !== "neu" || i.lane === "erledigt") ab += '<button class="btn sm ghost" data-act="reopen" data-id="' + E(i.id) + '">Wieder öffnen</button>';
  } else ab = '<span class="chip">Nur Ansicht – bearbeiten dürfen Owner und Verantwortliche</span>';
  return '<div class="side-h"><button class="x" id="closeside" aria-label="Schließen">×</button><div class="chips"><span class="chip ' + lvl + '">P' + i.level + " " + E(i.level_name) + '</span><span class="chip ' + dv[0] + '">' + dv[1] + '</span><span class="chip">' + E(i.state_label) + (i.assignee ? " · " + E(i.assignee) : "") + "</span></div><h2>" + E(i.titel) + '</h2><div class="acts" style="margin:8px 0 6px">' + ab + "</div></div>" +
    '<div class="subtabs">' + tabs.map(t => '<button class="tab' + (S.sub === t[0] ? " on" : "") + '" data-sub="' + t[0] + '">' + t[1] + "</button>").join("") + '</div><div class="side-b">' + subHtml(i) + "</div>";
}
function subHtml(i) {
  const li = a => "<ul>" + a.map(x => "<li>" + E(typeof x === "string" ? x : x.text) + "</li>").join("") + "</ul>";
  if (S.sub === "ueberblick") {
    let h = '<div class="sec"><h4>Was ist passiert</h4><p>' + E(i.kurz) + "</p></div>";
    if (i.wirkung) h += '<div class="sec"><h4>Auswirkung</h4><p>' + E(i.wirkung) + "</p></div>";
    if (i.kind === "gruppe") h += '<div class="sec"><h4>Betroffene Automationen</h4><table><tbody>' + i.children.map(c => '<tr><td class="mono">' + c.automation + "</td><td>" + E(c.name) + "</td><td class='num'>" + c.count + " Läufe</td><td>" + (c.recovered ? "wieder ok " + E(c.recovered) : '<b style="color:var(--p2)">noch nicht nachgeholt</b>') + "</td></tr>").join("") + "</tbody></table></div>";
    if (i.ursachen && i.ursachen.length) h += '<div class="sec"><h4>Mögliche Ursachen (nach Wahrscheinlichkeit)</h4>' + li(i.ursachen) + "</div>";
    if (i.nacharbeit && i.nacharbeit.length) h += '<div class="sec"><h4>Nacharbeit</h4>' + li(i.nacharbeit) + "</div>";
    h += '<div class="sec"><h4>Zuständig</h4><p>' + E(i.owner_namen.join(", ")) + "</p></div>";
    return h;
  }
  if (S.sub === "empfehlung") {
    let h = '<div class="callout">Vorschläge aus dem Regelwerk, abgestimmt auf Zweck und Aufbau der Automation. <b>Heartbeat ändert nie selbst etwas.</b> „Freigeben“ ist ein Auftrag an einen Menschen und wird protokolliert.</div>';
    h += (i.empfehlung || []).map(s => '<div class="step"><div class="tp ' + s.typ + '">' + STEPTYPE[s.typ] + "</div><div>" + E(s.text) +
      (s.freigabe ? '<div class="approve">' + (s.freigegeben ? '<span class="chip ok">Freigegeben</span>' : (i.can_act ? '<button class="btn sm" data-approve="' + s.idx + '" data-id="' + E(i.id) + '">' + (s.aktion === "baseline_reset" ? "Als neues Normal übernehmen" : "Änderung freigeben") + "</button>" : "")) + "</div>" : "") + "</div></div>").join("");
    h += '<div class="sec" style="margin-top:16px"><h4>KI-Vertiefung (optional)</h4>';
    if (i.analyse) {
      const a = i.analyse, b = a.body || {};
      h += '<div class="callout ai"><b>' + (a.status === "ok" ? "Einschätzung von " + E(a.quelle) : "Rückfall auf das Regelwerk") + "</b> · Vorschlag, nicht freigegeben</div>";
      if (b.hinweis) h += "<p>" + E(b.hinweis) + "</p>" + ((b.versuche || []).length ? '<p class="meta">Versuche: ' + E(b.versuche.join(" · ")) + "</p>" : "");
      (b.hypothesen || []).forEach(x => (h += '<div class="pl"><b>Hypothese <span class="str hypothese">' + E(x.konfidenz) + "</span></b>" + E(x.text) + "</div>"));
      (b.rueckfragen || []).forEach(x => (h += '<div class="pl"><b>Rückfrage</b>' + E(x) + "</div>"));
    } else h += '<p class="meta">Erkennung, Priorität und Briefing laufen ohne KI. Die KI ergänzt nur Hypothesen. Bei Überlastung fällt sie auf das Regelwerk zurück, das Briefing wartet nie auf sie. Status: ' + E(S.d.selfcheck.ki) + '.</p><div class="acts"><button class="btn sm" id="analyse" data-id="' + E(i.id) + '">KI-Analyse anfordern</button></div>';
    return h + "</div>";
  }
  if (S.sub === "plausibilitaet") {
    const p = i.plausibilitaet || [];
    return '<div class="callout">Jede Auffälligkeit wird gegen andere Läufe und Automationen geprüft. <b>Belegt</b> steht so im Protokoll, <b>Hinweis</b> ist ein Muster, <b>Hypothese</b> ist ein Schluss und muss geprüft werden.</div>' +
      (p.length ? p.map(x => '<div class="pl"><b>' + E(x.titel) + '<span class="str ' + x.staerke + '">' + x.staerke + "</span></b>" + E(x.text) + "</div>").join("") : '<p class="meta">Keine auffälligen Querbezüge gefunden.</p>');
  }
  if (S.sub === "protokoll") {
    if (S.logFor !== i.id) return '<div class="callout">Das Protokoll zeigt die Rohdaten hinter dieser Meldung. So lässt sich nachprüfen, dass das Briefing nichts falsch berechnet hat. Es wird nur auf Wunsch geöffnet.</div><div class="acts"><button class="btn" id="showlog">Protokoll anzeigen (' + i.protokoll.length + " Zeilen)</button></div>";
    return '<div class="callout">Rohdaten aus dem Lauf-Protokoll, unverändert.</div><div class="tbl-wrap" style="box-shadow:none"><table><thead><tr><th>Lauf</th><th>Start</th><th>Status</th><th>Anz.</th><th>Detail</th></tr></thead><tbody>' +
      i.protokoll.map(r => '<tr class="' + (r.markierung === "betroffen" ? "hit" : r.markierung === "fehlt" ? "miss" : r.markierung === "wieder normal" ? "good" : "") + '"><td class="mono">' + E(r.lauf_id) + (r.markierung ? "<br><small>" + E(r.markierung) + "</small>" : "") + '</td><td class="mono">' + E((r.start || "").replace("T", " ")) + '</td><td>' + E(r.status) + '</td><td class="num">' + E(r.anzahl == null ? "–" : r.anzahl) + "</td><td>" + E(r.detail) + "</td></tr>").join("") + "</tbody></table></div>";
  }
  return '<ul class="tl">' + i.verlauf.map(v => '<li class="' + v.art + '"><span class="t">' + E(v.label) + "</span>" + E(v.text) + "</li>").join("") + "</ul>";
}

// ---------------------------------------------------------------- Raster, Automationen, Datenfluss
function viewRaster() {
  const g = S.d.grid, cur = S.d.as_of.slice(0, 10);
  const sym = {ok: "", fail: "×", miss: "–", warn: "!", na: ""};
  let rows = "", last = "";
  g.rows.forEach(r => {
    if (r.werkzeug !== last) { last = r.werkzeug; rows += '<tr class="grp"><td colspan="' + (g.days.length + 1) + '">' + E(r.werkzeug) + "</td></tr>"; }
    rows += '<tr><td class="lab"><b class="mono">' + r.id + "</b> " + E(r.name) + "<small>" + (r.klasse === "sofort" ? "Sofort · " : "") + E(r.owner.join(", ")) + "</small></td>" +
      r.cells.map(c => '<td><' + (c.inc ? "button" : "div") + ' class="cell ' + c.s + (c.d === cur ? " cur" : "") + '" title="' + E(r.id + " " + r.name + " · " + c.d + (c.txt ? " · " + c.txt : "") + (c.s === "fail" ? " · Fehler/Abweichung" : c.s === "miss" ? " · Lauf fehlt" : c.s === "warn" ? " · Warnung" : "")) + '"' + (c.inc ? ' data-pick="' + E(c.inc) + '"' : "") + ">" + sym[c.s] + "</" + (c.inc ? "button" : "div") + "></td>").join("") + "</tr>";
  });
  return '<div class="grid-wrap"><table class="grid"><thead><tr><th></th>' + g.days.map(d => '<th class="' + (d.wd >= 5 ? "we" : "") + (d.iso === cur ? " cur" : "") + '">' + E(d.label.split(" ")[0]) + "<br>" + E(d.label.split(" ")[1]) + "</th>").join("") + "</tr></thead><tbody>" + rows + "</tbody></table>" +
    '<div class="legend"><span><i class="cell ok"></i>gelaufen</span><span><i class="cell fail">×</i>Fehler oder auffälliger Wert</span><span><i class="cell miss">–</i>Lauf fehlt</span><span><i class="cell warn">!</i>Warnung / Hinweis</span><span><i class="cell"></i>nicht geplant</span><span>Klick auf ein farbiges Feld öffnet die Meldung</span></div></div>';
}
function viewAutos() {
  const f = n => (n == null ? "–" : String(Math.round(n * 10) / 10).replace(".", ","));
  return '<div class="tbl-wrap"><table><thead><tr><th>Automation</th><th>Werkzeug</th><th>Owner</th><th>Klasse</th><th>Zeitplan</th><th>Letzter Lauf</th><th>Median Anzahl</th><th>Median Dauer</th><th>Lage</th></tr></thead><tbody>' +
    S.d.automations.map(a => "<tr><td><b class='mono'>" + a.id + "</b> " + E(a.name) + '<br><small style="color:var(--faint)">' + E(a.liefert) + "</small></td><td>" + E(a.werkzeug) + "</td><td>" + E(a.owner.join(", ")) + "</td><td>" + (a.klasse === "sofort" ? '<span class="chip acc">Sofort</span>' : '<span class="chip">Morgen</span>') + "</td><td>" + E(a.zeitplan) + "</td><td>" + E(a.letzter) + " <small>" + E(a.letzter_status) + '</small></td><td class="num">' + f(a.median_anzahl) + '</td><td class="num">' + (a.median_dauer_s != null ? Math.round(a.median_dauer_s) + " s" : "–") + '</td><td><span class="dot ' + (a.level ? "l" + a.level : "") + '"></span>' + (a.level ? "P" + a.level + " offen" : "ok") + "</td></tr>").join("") + "</tbody></table></div>";
}
function viewFlow() {
  const sc = S.d.selfcheck;
  const steps = [["Protokoll einspielen", "Heute im MVP: CSV oder Excel (.xlsx) hochladen oder per Kommando einlesen. Spalten werden erkannt, Bekanntes wird nicht doppelt gezählt, Unbrauchbares geht mit Grund in die Quarantäne."],
    ["Vereinheitlichen", "Die Status der drei Werkzeuge (success/completed/ok …) werden zusammen mit Fehlertext und Anzahl bewertet, nicht allein nach dem Status."],
    ["Auswerten", "Soll-Kalender, Median-Band der letzten guten Läufe, Fehlertext, Gegenproben über andere Automationen. Ursachen werden gebündelt."],
    ["Melden", "Sofort-Fälle gehen direkt an den Owner (Slack-Mockup), alles andere gebündelt ins Morgenbriefing. Das Dashboard ist die Vertiefung."]];
  return '<div class="flow">' + steps.map((s, n) => '<div><span class="no">' + (n + 1) + "</span><b>" + s[0] + "</b><small>" + s[1] + "</small></div>").join("") + "</div>" +
    '<div class="two"><div class="box"><h3>Testlauf: Protokoll einspielen</h3><p style="margin-top:0;color:var(--muted)">Excel oder CSV hierher ziehen, z. B. die Läufe vom 26.10. Erwartet werden mindestens die Spalten <span class="mono">automation_id, start, status</span> (dazu gern <span class="mono">lauf_id, werkzeug, ende, anzahl, detail</span>). Danach springt die Ansicht zum neuesten Briefing.</p><label class="drop" id="drop" for="file">Datei hierher ziehen oder klicken (.xlsx, .csv)<input id="file" type="file" accept=".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" class="sr"></label><div id="upres" class="meta" style="margin-top:8px"></div><div class="acts"><button class="btn sm" id="reset">Demo zurücksetzen (Aktionen löschen)</button></div></div>' +
    '<div class="box"><h3>Selbstcheck</h3><dl class="kv"><dt>Läufe gelesen</dt><dd class="num">' + sc.laeufe + "</dd><dt>Quellen</dt><dd>" + sc.quellen + " von 3 (Make, Cloud, Laptop)</dd><dt>Daten bis</dt><dd>" + E(sc.daten_bis) + "</dd><dt>Quarantäne</dt><dd>" + sc.quarantaene + " abgelehnte Zeilen/Dateien</dd><dt>Datenpfad</dt><dd>" + (sc.blind ? '<b style="color:var(--p1)">still: keine neuen Läufe</b>' : "aktiv") + "</dd><dt>KI-Schicht</dt><dd>" + E(sc.ki) + "</dd></dl>" +
    '<div class="callout" style="margin:12px 0 0">Bleibt das Briefing aus, ist der Heartbeat selbst das Problem. Darum würde auch ein leeres Briefing („nichts offen“) täglich rausgehen.</div></div></div>' +
    '<div class="box" style="margin-top:16px"><h3>Noch nicht angebunden (bewusst nicht Teil des MVP)</h3><ul style="margin:0;padding-left:18px;color:var(--muted)"><li>Automatische Meldung jeder Automation (Make, Cloud-Routine, Laptop). Der signierte Webhook und ein Laptop-Client mit Warteschlange sind gebaut und getestet, aber nirgends eingehängt.</li><li>Echtes Slack. Die Nachrichten sind fertige Block-Kit-Objekte, im Mockup werden sie nur angezeigt.</li><li>KI-Vertiefung. Ohne Schlüssel gilt immer das Regelwerk, die Rückfalllogik ist getestet.</li></ul></div>' +
    (S.d.rejects.length ? '<div class="box" style="margin-top:16px"><h3>Quarantäne (letzte abgelehnte Zeilen)</h3><table><tbody>' + S.d.rejects.map(r => "<tr><td>" + E(r.received_at) + "</td><td>" + E(r.source) + "</td><td>" + E(r.reason) + "</td></tr>").join("") + "</tbody></table></div>" : "");
}

// ---------------------------------------------------------------- Rendern & Ereignisse
function renderView() {
  const v = $("#view");
  v.innerHTML = S.tab === "meldungen" ? viewMeldungen() : S.tab === "raster" ? viewRaster() : S.tab === "automationen" ? viewAutos() : viewFlow();
  const pb = $("#prev-brief");
  if (pb) pb.appendChild(renderBlocks(S.d.briefing, x => { if (x.action_id === "hb_ack" || x.action_id === "hb_resolve") act(x.action_id === "hb_ack" ? "ack" : "resolve", x.value); else if (x.action_id === "hb_open" && x.value) pick(x.value); }));
  v.querySelectorAll("[data-pick]").forEach(el => el.addEventListener("click", e => { e.stopPropagation(); if (el.dataset.pick) { S.tab = "meldungen"; renderTabs(); pick(el.dataset.pick); } }));
  v.querySelectorAll("[data-act]").forEach(el => el.addEventListener("click", e => { e.stopPropagation(); act(el.dataset.act, el.dataset.id); }));
  v.querySelectorAll("[data-sub]").forEach(el => el.addEventListener("click", () => { S.sub = el.dataset.sub; renderView(); }));
  v.querySelectorAll("[data-approve]").forEach(el => el.addEventListener("click", () => act("approve_step", el.dataset.id, {step: +el.dataset.approve})));
  const cs = $("#closeside"); if (cs) cs.addEventListener("click", () => pick(null));
  const sl = $("#showlog"); if (sl) sl.addEventListener("click", () => { S.logFor = S.det.id; renderView(); });
  const sd = $("#showdone"); if (sd) sd.addEventListener("click", () => { S.showDone = true; renderView(); });
  const an = $("#analyse"); if (an) an.addEventListener("click", async () => { an.disabled = true; an.textContent = "Analyse läuft …"; await api("/api/analyse?" + qp(), {incident: an.dataset.id}); S.det = await api("/api/incident?" + qp() + "&id=" + encodeURIComponent(S.sel)); renderView(); });
  const f = $("#file"); if (f) { f.addEventListener("change", () => upload(f.files[0])); const dz = $("#drop"); ["dragover", "dragenter"].forEach(n => dz.addEventListener(n, e => { e.preventDefault(); dz.classList.add("on"); })); ["dragleave", "drop"].forEach(n => dz.addEventListener(n, e => { e.preventDefault(); dz.classList.remove("on"); })); dz.addEventListener("drop", e => upload(e.dataTransfer.files[0])); }
  const rs = $("#reset"); if (rs) rs.addEventListener("click", async () => { await api("/api/reset-demo", {}); toast("Aktionen zurückgesetzt"); await load(); });
}
async function upload(file) {
  if (!file) return;
  const el = $("#upres");
  if (el) el.textContent = "Wird eingelesen …";
  const r = await fetch("/api/upload", {method: "POST", headers: {"X-Requested-With": "heartbeat", "X-Filename": file.name, "Content-Type": "application/octet-stream"}, body: await file.arrayBuffer()});
  const res = await r.json();
  if (res.fehler) { toast("Datei nicht lesbar"); if (el) el.innerHTML = '<b style="color:var(--p1)">Abgelehnt:</b> ' + E(res.fehler); return; }
  const sum = res.art + (res.blatt && res.art === "Excel" ? " · Blatt „" + res.blatt + "“" : "") + ": " + res.zeilen + " Zeilen → " + res.neu + " neu, " + res.doppelt + " bereits bekannt, " + res.abgelehnt + " abgelehnt" + (res.erste ? " · Zeitraum " + res.erste + " bis " + res.letzte : "");
  toast(res.neu + " neue Läufe eingelesen");
  S.latest = true; S.t = null; S.sel = null; S.det = null; S.tab = "meldungen"; S.filter = null;
  await load();
  S.tab = "einlieferung"; renderTabs(); renderView();
  const el2 = $("#upres");
  if (el2) el2.innerHTML = "<b>" + E(sum) + "</b>" + (res.beispiele && res.beispiele.length ? "<br>Abgelehnt, z. B.: " + E(res.beispiele.join(" · ")) : "") + '<br>Neuestes Briefing: <b>' + E(res.neuester) + '</b> – <a href="#" id="tomeld">zu den Meldungen</a>';
  const tm = $("#tomeld"); if (tm) tm.addEventListener("click", e => { e.preventDefault(); S.tab = "meldungen"; renderTabs(); renderView(); sync(); });
}
function render() { renderTop(); renderKpis(); renderTabs(); renderView(); sync(); }

// ---------------------------------------------------------------- Geführte Tour
const TOUR = [
  {t: "Ein Dienstagmorgen, 22 Automationen", x: "Du siehst das Briefing von Mi 21.10. um 07:00 aus Sicht von Daniel (Chief of Staff). Keine Automation hat sich selbst gemeldet. Heartbeat hat gestern jeden Soll-Lauf und jedes Ergebnis geprüft.", go: () => goto({t: "2026-10-21T07:00:00", u: "daniel", tab: "meldungen", sel: null})},
  {t: "Stiller Fehler: Make sagt „success“", x: "Seit gestern 07:39 kommen Support-Tickets nicht im Kanal an. Status: success, Menge: normal. Nur der Fehlertext verrät es. Darum bewertet Heartbeat Status, Text und Zahl gemeinsam.", go: () => goto({sel: "A02:", sub: "ueberblick"})},
  {t: "Sofort statt erst am Morgen", x: "Support-Fälle sind kundennah. Sie gingen um 07:39 direkt an das Support-Team, um 08:39 mit Eskalation an Daniel. Das Slack-Mockup zeigt die Nachrichten mit Buttons. Alles andere kommt gebündelt am Morgen.", link: () => "/slack?u=support&t=" + encodeURIComponent(S.t)},
  {t: "Median statt Bauchgefühl", x: "A10 hat an 6 Arbeitstagen „0 Deals bewertet“ gemeldet, Status completed. Üblich sind etwa 142. Der Vergleichswert ist der Median der letzten guten Läufe. Auffällige Werte fließen nicht in die Basis ein.", go: () => goto({sel: "A10:", sub: "ueberblick"})},
  {t: "Plausibilität: die Gegenprobe", x: "A09 zeigt seit 20.10. 31 Deals weniger. A10 blieb bei etwa 142. Der Bestand hat sich also nicht verändert, wahrscheinlich liegt es am Filter von A09. Das ist eine Hypothese und wird als solche markiert.", go: () => goto({t: "last", sel: "A09:", sub: "plausibilitaet"})},
  {t: "Eine Ursache, eine Meldung", x: "21 ausgefallene Läufe auf dem Laptop werden zu einer Meldung gebündelt. Make und Cloud liefen in dieser Zeit normal. Im Raster sieht man das Muster auf einen Blick.", go: () => goto({t: "2026-10-21T07:00:00", tab: "raster", sel: null})},
  {t: "Der Mensch entscheidet", x: "Empfehlungen sind Vorschläge. Änderungen an einer Automation brauchen eine Freigabe, „neues Normal“ setzt die Vergleichsbasis zurück. Das Protokoll öffnet sich nur auf Wunsch.", go: () => goto({t: "last", tab: "meldungen", sel: "A09:", sub: "empfehlung"})},
  {t: "Jetzt dein Testlauf", x: "Spiel ein neues Protokoll ein (Excel oder CSV), zum Beispiel die Läufe vom 26.10. Heartbeat zeigt dir direkt das Briefing für den 27.10.", go: () => goto({tab: "einlieferung", sel: null})},
];
async function goto(o) {
  if (o.u) S.u = o.u;
  if (o.t === "last") { S.t = S.d.points[S.d.points.length - 1].iso; } else if (o.t) S.t = o.t;
  if (o.tab) S.tab = o.tab;
  if (o.sub) S.sub = o.sub;
  if (o.sel !== undefined) S.sel = null;
  await load();
  if (o.sel) { const i = S.d.incidents.find(x => x.id.startsWith(o.sel)); if (i) { S.tab = "meldungen"; await pick(i.id); if (o.sub) { S.sub = o.sub; renderView(); } renderTabs(); } }
}
function renderTour() {
  const el = $("#tour");
  if (S.tour < 0) { el.innerHTML = ""; return; }
  const s = TOUR[S.tour];
  el.innerHTML = '<div class="tour" role="dialog" aria-label="Geführte Tour"><h4>' + (S.tour + 1) + "/" + TOUR.length + " · " + E(s.t) + "</h4><p>" + E(s.x) + '</p><div class="row"><button class="btn" id="tprev"' + (S.tour === 0 ? " disabled" : "") + '>Zurück</button>' + (s.link ? '<a class="btn" href="' + E(s.link()) + '" target="_blank" rel="noopener">Slack-Mockup öffnen ↗</a>' : "") + '<span class="sp"></span><button class="btn" id="tend">Beenden</button><button class="btn primary" id="tnext">' + (S.tour === TOUR.length - 1 ? "Fertig" : "Weiter") + "</button></div></div>";
  $("#tprev").addEventListener("click", () => step(-1)); $("#tnext").addEventListener("click", () => step(1)); $("#tend").addEventListener("click", () => { S.tour = -1; renderTour(); });
}
async function step(dir) {
  S.tour += dir;
  if (S.tour >= TOUR.length) { S.tour = -1; renderTour(); return; }
  renderTour();
  const s = TOUR[S.tour]; if (s.go) await s.go();
}

// ---------------------------------------------------------------- Start
document.addEventListener("DOMContentLoaded", () => {
  const p = new URLSearchParams(location.search);
  if (p.get("u")) S.u = p.get("u"); if (p.get("t")) S.t = p.get("t"); if (p.get("tab")) S.tab = p.get("tab"); if (p.get("i")) S.sel = p.get("i");
  $("#who").addEventListener("change", e => { S.u = e.target.value; S.sel = null; S.det = null; load(); });
  $("#when").addEventListener("change", e => { S.t = e.target.value; load(); });
  $("#prev").addEventListener("click", () => { const i = S.d.points.findIndex(x => x.iso === S.d.as_of); if (i > 0) { S.t = S.d.points[i - 1].iso; load(); } });
  $("#next").addEventListener("click", () => { const i = S.d.points.findIndex(x => x.iso === S.d.as_of); if (i < S.d.points.length - 1) { S.t = S.d.points[i + 1].iso; load(); } });
  $("#tourbtn").addEventListener("click", () => { S.tour = 0; renderTour(); TOUR[0].go(); });
  document.addEventListener("keydown", e => { if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT") return; if (e.key === "ArrowLeft") $("#prev").click(); if (e.key === "ArrowRight") $("#next").click(); });
  load();
});
