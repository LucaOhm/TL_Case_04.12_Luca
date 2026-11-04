/* Gemeinsam genutzt: Block-Kit -> HTML (Dashboard-Vorschau und Slack-Mockup). Alles wird escaped, bevor Markup ersetzt wird. */
const EMOJI = {red_circle: "🔴", large_orange_circle: "🟠", large_yellow_circle: "🟡", white_circle: "⚪", rotating_light: "🚨", white_check_mark: "✅", sunrise: "🌅"};
function escH(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c])); }
function mrkdwn(t) {
  t = String(t == null ? "" : t).replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&"); // Slack-Entities zurück, dann sicher escapen
  t = escH(t);
  t = t.replace(/:([a-z_]+):/g, (m, k) => EMOJI[k] || m);
  t = t.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*([^*\n]+)\*/g, "<b>$1</b>").replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,]|$)/g, "$1<i>$2</i>");
  return t.replace(/\n/g, "<br>");
}
function renderBlocks(msg, onAction) {
  const el = document.createElement("div");
  el.className = "sb";
  (msg.blocks || []).forEach(b => {
    if (b.type === "header") { const h = document.createElement("div"); h.className = "sb-h"; h.innerHTML = mrkdwn(b.text.text); el.appendChild(h); }
    else if (b.type === "section") {
      const s = document.createElement("div"); s.className = "sb-s"; s.innerHTML = mrkdwn(b.text.text);
      if (b.fields) { const f = document.createElement("div"); f.className = "sb-f"; b.fields.forEach(x => { const c = document.createElement("div"); c.innerHTML = mrkdwn(x.text); f.appendChild(c); }); s.appendChild(f); }
      el.appendChild(s);
    } else if (b.type === "context") { const c = document.createElement("div"); c.className = "sb-c"; c.innerHTML = b.elements.map(e => mrkdwn(e.text)).join(" · "); el.appendChild(c); }
    else if (b.type === "divider") { el.appendChild(document.createElement("hr")); }
    else if (b.type === "actions") {
      const a = document.createElement("div"); a.className = "sb-a";
      b.elements.forEach(x => {
        const bt = document.createElement("button");
        bt.type = "button"; bt.className = "sb-b" + (x.style === "primary" ? " pri" : ""); bt.textContent = x.text.text;
        bt.addEventListener("click", () => onAction && onAction(x));
        a.appendChild(bt);
      });
      el.appendChild(a);
    }
  });
  return el;
}
