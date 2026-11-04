"""HTTP-Hülle (nur Standardbibliothek): Dashboard-Mockup, Slack-Mockup, Datei-Upload, signierter Webhook (vorbereitet).

Standard ist 127.0.0.1. Die Demo-Endpunkte (Aktionen, Upload, Zurücksetzen) sind als Mockup gedacht: Die Identität kommt
dort aus dem Rollenwähler. In Produktion ersetzt „Mit Slack anmelden“ diesen Wähler (siehe docs/betrieb.md).
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import hitl, ingest, slack
from .app import App

WEB = Path(__file__).resolve().parent / "web"
MAX_UPLOAD = 5 * 1024 * 1024
T_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$")


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        server_version = "Heartbeat"

        def log_message(self, fmt, *a):  # ruhig
            if os.environ.get("HEARTBEAT_LOG"):
                super().log_message(fmt, *a)

        # ---- Hilfen
        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            if ctype.startswith("text/html"):
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _body(self, limit=MAX_UPLOAD):
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                return None
            return self.rfile.read(n)

        def _q(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            t = q.get("t")
            if t and not T_RE.match(t):
                t = None
            u_id = q.get("u") if q.get("u") in app.reg.people else "daniel"
            return u.path, q, t, u_id

        # ---- GET
        def do_GET(self):
            path, q, t, uid = self._q()
            try:
                if path in ("/", "/index.html"):
                    return self._send(200, (WEB / "index.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")
                if path == "/slack":
                    return self._send(200, (WEB / "slack.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")
                if path.startswith("/static/"):
                    f = (WEB / path[len("/static/"):]).resolve()
                    if WEB.resolve() not in f.parents or not f.is_file():
                        return self._send(404, {"fehler": "nicht gefunden"})
                    return self._send(200, f.read_bytes(), mimetypes.guess_type(str(f))[0] or "application/octet-stream")
                if path == "/healthz":
                    return self._send(200, {"ok": True, "laeufe": app.store.run_count()})
                if path == "/api/state":
                    return self._send(200, app.state(t, uid))
                if path == "/api/incident":
                    d = app.detail(t, uid, q.get("id", ""))
                    return self._send(200 if d else 404, d or {"fehler": "nicht gefunden"})
                if path == "/api/slack":
                    return self._send(200, app.slack_feed(t, uid))
                return self._send(404, {"fehler": "nicht gefunden"})
            except Exception as e:  # nie mit Stacktrace antworten
                if os.environ.get("HEARTBEAT_LOG"):
                    raise
                return self._send(500, {"fehler": "Interner Fehler: %s" % type(e).__name__})

        # ---- POST
        def do_POST(self):
            path, q, t, uid = self._q()
            body = self._body()
            if body is None:
                return self._send(413, {"fehler": "zu groß"})
            try:
                if path == "/api/ingest":  # signierter Webhook (Make, Cloud-Routinen, Laptop)
                    code, res = ingest.receive(app.store, body, dict(self.headers), app.secrets)
                    if code == 200:
                        app._cache.clear()
                    return self._send(code, res)
                # --- Demo-Endpunkte (Mockup)
                if self.headers.get("X-Requested-With") != "heartbeat":
                    return self._send(403, {"fehler": "fehlender Kopf"})
                if path == "/api/action":
                    d = json.loads(body or b"{}")
                    ok, msg = app.act(t, uid, str(d.get("incident", "")), str(d.get("action", "")), str(d.get("note", ""))[:300], int(d.get("step", -1)))
                    return self._send(200 if ok else 400, {"ok": ok, "meldung": msg})
                if path == "/api/analyse":
                    d = json.loads(body or b"{}")
                    ok, res = app.analyse(t, uid, str(d.get("incident", "")))
                    return self._send(200 if ok else 404, res)
                if path == "/api/upload":
                    res = app.upload(body, self.headers.get("X-Filename", "")[:200])
                    return self._send(200 if "fehler" not in res else 400, res)
                if path == "/api/reset-demo":
                    app.store.clear_actions()
                    app._cache.clear()
                    return self._send(200, {"ok": True})
                return self._send(404, {"fehler": "nicht gefunden"})
            except (ValueError, KeyError) as e:
                return self._send(400, {"fehler": "Ungültige Anfrage"})
            except Exception as e:
                if os.environ.get("HEARTBEAT_LOG"):
                    raise
                return self._send(500, {"fehler": "Interner Fehler: %s" % type(e).__name__})

    return H


def serve(app: App, host: str = "127.0.0.1", port: int = 8765) -> None:
    srv = ThreadingHTTPServer((host, port), make_handler(app))
    print("Heartbeat läuft auf http://%s:%d   (Dashboard: /   Slack-Mockup: /slack)" % (host, port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
