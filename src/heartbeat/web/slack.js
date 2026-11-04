/* Slack-Mockup: rendert exakt die Block-Kit-Objekte, die ein echter Workspace bekäme. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const Q = {u: "daniel", t: null, points: []};
const TYP = {alert: ["alert", "Sofortmeldung"], eskalation: ["eskalation", "Eskalation"], entwarnung: ["entwarnung", "Entwarnung"], briefing: ["briefing", "Morgenbriefing"]};

async function api(path, body) {
  const o = body === undefined ? {} : {method: "POST", headers: {"X-Requested-With": "heartbeat", "Content-Type": "application/json"}, body: JSON.stringify(body)};
  return (await fetch(path, o)).json();
}
const qp = () => "u=" + encodeURIComponent(Q.u) + (Q.t ? "&t=" + encodeURIComponent(Q.t) : "");
function toast(m) { const t = $("#toast"); t.innerHTML = '<div class="toast">' + escH(m) + "</div>"; clearTimeout(toast.h); toast.h = setTimeout(() => (t.innerHTML = ""), 3500); }

async function load() {
  const st = await api("/api/state?" + qp());               // liefert auch die Zeitpunkte
  Q.points = st.points; Q.t = st.as_of;
  const f = await api("/api/slack?" + qp());
  $("#who").innerHTML = f.people.map(p => '<option value="' + p.id + '"' + (p.id === Q.u ? " selected" : "") + ">" + escH(p.name) + " (" + escH(p.slack) + ")</option>").join("");
  $("#when").innerHTML = Q.points.map(p => '<option value="' + escH(p.iso) + '"' + (p.iso === Q.t ? " selected" : "") + ">Stand " + escH(p.label) + (p.teilweise ? " · Teildaten" : "") + "</option>").join("");
  const i = Q.points.findIndex(p => p.iso === Q.t);
  $("#prev").disabled = i <= 0; $("#next").disabled = i < 0 || i >= Q.points.length - 1;
  $("#todash").href = "/?u=" + encodeURIComponent(Q.u) + "&t=" + encodeURIComponent(Q.t);
  history.replaceState(null, "", "?" + qp());
  draw(f);
}
function draw(f) {
  const feed = $("#feed"); feed.innerHTML = "";
  if (!f.messages.length) { feed.innerHTML = '<p class="meta" style="padding:20px">Noch keine Nachrichten für diesen Zeitpunkt.</p>'; return; }
  let day = "";
  f.messages.forEach(m => {
    const d = m.label.slice(0, 9);
    if (d !== day) { day = d; const h = document.createElement("div"); h.className = "slk-day"; h.innerHTML = "<span>" + escH(d) + "</span>"; feed.appendChild(h); }
    const w = document.createElement("div"); w.className = "slk-msg";
    w.innerHTML = '<div class="slk-av"><svg viewBox="0 0 32 32"><path d="M4 17h6l3-8 5 15 3-7h7" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg></div><div><div class="slk-who">Heartbeat<span class="app">APP</span><small>' + escH(m.label.slice(10)) + " · " + (TYP[m.typ] || ["", m.typ])[1] + '</small></div><div class="slk-body ' + m.typ + '"></div></div>';
    const body = w.querySelector(".slk-body");
    const out = document.createElement("div");
    body.appendChild(renderBlocks(m.slack, x => onAction(x, m, out)));
    body.appendChild(out);
    const tools = document.createElement("div"); tools.className = "slk-tools";
    const jb = document.createElement("button"); jb.textContent = "Block-Kit-JSON anzeigen"; jb.type = "button";
    const pre = document.createElement("pre"); pre.className = "code slk-json"; pre.hidden = true; pre.textContent = JSON.stringify(m.slack, null, 2);
    jb.addEventListener("click", () => { pre.hidden = !pre.hidden; jb.textContent = pre.hidden ? "Block-Kit-JSON anzeigen" : "JSON ausblenden"; });
    tools.appendChild(jb); body.appendChild(tools); body.appendChild(pre);
    feed.appendChild(w);
  });
  feed.scrollTop = feed.scrollHeight;
}
async function onAction(x, m, out) {
  const map = {hb_ack: "ack", hb_resolve: "resolve", hb_snooze: "snooze", hb_false: "false_alarm"};
  if (x.action_id === "hb_open") { window.open(x.url || "/", "_blank", "noopener"); return; }
  if (x.action_id === "hb_log") {
    const d = await api("/api/incident?" + qp() + "&id=" + encodeURIComponent(x.value));
    if (!d || !d.protokoll) { out.textContent = "Nicht gefunden."; return; }
    const rows = d.protokoll.slice(0, 8).map(r => "`" + r.lauf_id + "` " + (r.start || "").slice(11, 16) + " " + r.status + " " + (r.detail || "").slice(0, 70)).join("\n");
    const box = document.createElement("div");
    box.appendChild(renderBlocks({blocks: [{type: "section", text: {type: "mrkdwn", text: "*Protokoll · " + d.titel + "*\n" + rows}}, {type: "context", elements: [{type: "mrkdwn", text: "Rohdaten aus dem Lauf-Protokoll. Nichts davon wurde vom Briefing berechnet."}]}]}));
    out.innerHTML = ""; out.appendChild(box);
    return;
  }
  const a = map[x.action_id];
  if (!a) return;
  const r = await api("/api/action?" + qp(), {incident: x.value, action: a});
  toast(r.meldung || r.fehler || "Fertig");
  await load();
}
document.addEventListener("DOMContentLoaded", () => {
  const p = new URLSearchParams(location.search);
  if (p.get("u")) Q.u = p.get("u"); if (p.get("t")) Q.t = p.get("t");
  $("#who").addEventListener("change", e => { Q.u = e.target.value; load(); });
  $("#when").addEventListener("change", e => { Q.t = e.target.value; load(); });
  $("#prev").addEventListener("click", () => { const i = Q.points.findIndex(x => x.iso === Q.t); if (i > 0) { Q.t = Q.points[i - 1].iso; load(); } });
  $("#next").addEventListener("click", () => { const i = Q.points.findIndex(x => x.iso === Q.t); if (i < Q.points.length - 1) { Q.t = Q.points[i + 1].iso; load(); } });
  load();
});
