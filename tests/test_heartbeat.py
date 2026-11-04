"""Tests:  cd src && python3 -m unittest discover -s ../tests -v

Die Rückprobe gegen die echten Läufe (data/ ist vertraulich und nicht im Repo) wird übersprungen, wenn die CSV fehlt.
"""
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from heartbeat import alerts, analyst, hitl, ingest, insight, slack  # noqa: E402
from heartbeat.app import App  # noqa: E402
from heartbeat.core import parse_local, iso  # noqa: E402
from heartbeat.store import Store  # noqa: E402

CSV = ROOT / "data" / "laeufe_2026-10-12_bis_2026-10-25.csv"
HAS_DATA = CSV.exists()


def fresh(with_data=True):
    s = Store(":memory:")
    if with_data:
        ingest.import_csv(s, CSV)
    return s


@unittest.skipUnless(HAS_DATA, "echte Läufe nicht vorhanden")
class Backtest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = fresh()
        cls.reg = cls.s.reg
        cls.m = insight.build(cls.reg, cls.s, parse_local("2026-10-26 00:00"))
        cls.by = {t["id"].split(":")[0] + ":" + t["id"].split(":")[1]: t for t in cls.m["incidents"] if t["kind"] != "gruppe"}
        cls.grp = [t for t in cls.m["incidents"] if t["kind"] == "gruppe"]

    def test_import_vollstaendig_und_idempotent(self):
        self.assertEqual(self.s.run_count(), 403)
        self.assertEqual(ingest.import_csv(self.s, CSV)["neu"], 0)

    def test_a02_stiller_fehler(self):
        t = self.by["A02:fehler"]
        self.assertEqual(t["count"], 20)
        self.assertEqual(t["level"], 1)
        self.assertEqual(t["delivery"], "sofort")
        self.assertEqual(t["recovered"], "Do 22.10. 08:00")
        self.assertEqual(sum(len(o["refs"]) for o in t["occ"]), 20)

    def test_a10_nullen_sind_kritisch_aber_nur_morgens(self):
        t = self.by["A10:wert"]
        self.assertEqual(t["count"], 6)
        self.assertEqual(t["level"], 1)
        self.assertEqual(t["delivery"], "morgen")  # Vorgabe: A10 gehört nicht zu "sofort"

    def test_a09_sprung_bleibt_offen(self):
        t = self.by["A09:wert"]
        self.assertEqual(t["count"], 6)
        self.assertEqual(t["auto_status"], "offen")
        self.assertIn("Gegenprobe über A10", [p["titel"] for p in t["plausibilitaet"]])

    def test_laptop_wird_eine_meldung(self):
        self.assertEqual(len(self.grp), 1)
        g = self.grp[0]
        self.assertEqual(g["automations"], ["A16", "A17", "A18", "A19", "A20", "A21"])
        self.assertEqual(g["count"], 21)
        self.assertEqual(g["auto_status"], "offen")  # A17/A19: Wochenlauf noch nicht nachgeholt

    def test_a04_kompensiert(self):
        t = self.by["A04:fehler"]
        self.assertTrue(t["kompensiert"])
        self.assertEqual(t["level"], 3)

    def test_keine_fehlalarme(self):
        erlaubt = {"A02:fehler", "A10:wert", "A09:wert", "A04:fehler", "A07:warnung", "A08:eingefroren"}
        gefunden = {k for k in self.by}
        self.assertEqual(gefunden - erlaubt, set(), "unerwartete Störungen")
        self.assertEqual(sum(1 for t in self.m["incidents"] if t["id"].startswith("A07:warnung")), 2)

    def test_warnungen_nur_dashboard_bzw_mittel(self):
        for t in self.m["incidents"]:
            if t["family"] == "warnung":
                self.assertNotEqual(t["delivery"], "sofort")

    def test_sofort_kette_a02(self):
        app = App(self.s, analyst.Analyst([]))
        ev = alerts.sofort_events(self.reg, app.model(parse_local("2026-10-23 07:00")), app.model)
        typ = {(e["typ"], e["an"]): e for e in ev}
        self.assertIn(("alert", "support"), typ)
        self.assertIn(("eskalation", "daniel"), typ)
        self.assertIn(("entwarnung", "support"), typ)
        self.assertEqual(iso(__import__("heartbeat.core", fromlist=["x"]).from_ts(typ[("alert", "support")]["at_ts"])), "2026-10-20T07:39:03")
        # Inhalt zum Versandzeitpunkt: 1 Ticket, nicht der Stand von später
        self.assertIn("1 Lauf", typ[("alert", "support")]["slack"]["blocks"][1]["text"]["text"])
        self.assertNotIn("wiederholt auf", typ[("alert", "support")]["slack"]["blocks"][1]["text"]["text"])

    def test_ack_verhindert_eskalation(self):
        s = fresh()
        app = App(s, analyst.Analyst([]))
        m = app.model(parse_local("2026-10-20 07:50"))
        inc = [t for t in m["incidents"] if t["id"].startswith("A02:fehler")][0]
        self.assertTrue(app.act("2026-10-20T07:50:00", "support", inc["id"], "ack")[0])
        ev = alerts.sofort_events(self.reg, app.model(parse_local("2026-10-20 12:00")), app.model)
        self.assertFalse([e for e in ev if e["typ"] == "eskalation"])

    def test_sichtbarkeit(self):
        m = insight.build(self.reg, self.s, parse_local("2026-10-21 07:00"))
        fin = {t["id"].split(":")[0] for t in insight.for_person(self.reg, m, "finance")}
        self.assertNotIn("A02", fin)
        self.assertTrue(any(t["kind"] == "gruppe" for t in insight.for_person(self.reg, m, "finance")))  # A16 liegt im Laptop-Ausfall
        sup = {t["id"].split(":")[0] for t in insight.for_person(self.reg, m, "support")}
        self.assertIn("A02", sup)
        self.assertNotIn("A09", sup)
        self.assertEqual(len(insight.for_person(self.reg, m, "daniel")), len(m["incidents"]))

    def test_gf_briefing_nur_eigenes_und_kritisches(self):
        m = insight.build(self.reg, self.s, parse_local("2026-10-21 07:00"))
        ids = {t["id"].split(":")[0] for t in insight.briefing_items(self.reg, m, "gf")}
        self.assertEqual(ids, {"A10", "A02"})  # A10 eigen, A02 kritisch; A09/Laptop sind P2 und nicht eigen

    def test_briefing_wiederholt_unbearbeitetes(self):
        app = App(self.s, analyst.Analyst([]))
        m = app.model(parse_local("2026-10-21 07:00"))
        titel = [t["titel"] for t in insight.briefing_items(self.reg, m, "support")]
        self.assertTrue(any("Support-Kanal" in x for x in titel))

    def test_neues_normal_beendet_a09_stoerung(self):
        s = fresh()
        app = App(s, analyst.Analyst([]))
        t = "2026-10-26T00:00:00"
        inc = [x for x in app.model(parse_local(t))["incidents"] if x["id"].startswith("A09:wert")][0]
        idx = [i for i, st in enumerate(inc["empfehlung"]) if st.get("aktion") == "baseline_reset"][0]
        ok, _ = app.act(t, "vertrieb", inc["id"], "approve_step", "", idx)
        self.assertTrue(ok)
        m = app.model(parse_local(t))
        a09 = [x for x in m["incidents"] if x["id"].startswith("A09:wert")][0]
        self.assertEqual((a09["state"], a09["lane"]), ("geloest", "erledigt"))
        # und mit den nächsten Läufen (26.10. 06:00: 138) kommt keine neue Störung mehr
        s.add_run(__import__("heartbeat.core", fromlist=["x"]).Run("X1", "A09", "Claude-Routine (Cloud)", parse_local("2026-10-26 06:00:20"), parse_local("2026-10-26 06:04:00"), "completed", 138, "Report aktualisiert, 138 Deals"), "x")
        m2 = app.model(parse_local("2026-10-26 07:00"))
        a09b = [x for x in m2["incidents"] if x["id"].startswith("A09:wert")][0]
        self.assertEqual(a09b["auto_status"], "erholt")
        self.assertEqual(len([x for x in m2["incidents"] if x["id"].startswith("A09:wert")]), 1)

    def test_fremder_darf_nicht_bearbeiten(self):
        s = fresh()
        app = App(s, analyst.Analyst([]))
        m = app.model(parse_local("2026-10-21 07:00"))
        inc = [t for t in m["incidents"] if t["id"].startswith("A02:fehler")][0]
        self.assertFalse(app.act("2026-10-21T07:00:00", "finance", inc["id"], "resolve")[0])
        self.assertTrue(app.act("2026-10-21T07:00:00", "daniel", inc["id"], "ack")[0])

    def test_neuer_tag_per_upload_gibt_briefing_ohne_datenloch(self):
        s = fresh()
        app = App(s, analyst.Analyst([]))
        # synthetischer 26.10. (Montag): nur ein Teil der Läufe reicht, um die Mechanik zu prüfen
        rows = ["lauf_id;automation_id;werkzeug;start;ende;status;anzahl;detail"]
        n = 404
        for a, tool, st, t, c, d in [("A07", "Make", "success", "00:00:03", 0, "0 Übergaben zugewiesen"), ("A09", "Claude-Routine (Cloud)", "completed", "06:00:20", 138, "Report aktualisiert, 138 Deals"),
                                     ("A07", "Make", "success", "20:00:02", 1, "1 Übergaben zugewiesen")]:
            rows.append("L%05d;%s;%s;2026-10-26 %s;2026-10-26 %s;%s;%d;%s" % (n, a, tool, t, t, st, c, d))
            n += 1
        res = app.upload("\n".join(rows) + "\n")
        self.assertEqual(res["neu"], 3)
        last = app.points()[-1]
        self.assertTrue(last["label"].startswith("Di 27.10."))
        st = app.state(last["iso"], "daniel")
        self.assertFalse(st["selfcheck"]["blind"])
        self.assertTrue(st["teilweise"])
        # ohne die fehlenden Läufe nicht als "Datenloch = Ausfall" zu melden: kein Heartbeat-blind-Fall
        self.assertFalse([i for i in st["incidents"] if i["id"].startswith("_heartbeat")])

    def test_rauchtest_alle_rollen_zeitpunkte_meldungen(self):
        """Nichts darf eine Ausnahme werfen: jede Rolle, jeder Briefing-Zeitpunkt, jede Meldung, Slack-Feed, Detail, CLI-Text."""
        import json as _json
        app = App(fresh(), analyst.Analyst([]))
        n = 0
        for p in app.points():
            for pid in app.reg.people:
                st = app.state(p["iso"], pid)
                _json.dumps(st)
                _json.dumps(app.slack_feed(p["iso"], pid))
                for i in st["incidents"]:
                    d = app.detail(p["iso"], pid, i["id"])
                    self.assertIsNotNone(d)
                    _json.dumps(d)
                    n += 1
        self.assertGreater(n, 100)

    def test_upload_falsches_format(self):
        app = App(fresh(False), analyst.Analyst([]))
        res = app.upload("a;b\n1;2\n")
        self.assertIn("Spalten nicht erkannt", res["fehler"])
        self.assertEqual(len(app.store.rejects()), 1)
        self.assertIn("keine gültige Excel", app.upload(b"PK\x03\x04kaputt")["fehler"])


def make_xlsx(rows, shared=False, extra_first_sheet=True):
    """Minimaler .xlsx-Schreiber nur für Tests (openpyxl ist nicht installiert)."""
    import io, zipfile
    from xml.sax.saxutils import escape
    strings = []

    def cell(r, c, v):
        ref = "%s%d" % (chr(65 + c), r + 1)
        if v is None:
            return ""
        if isinstance(v, (int, float)):
            return '<c r="%s"><v>%s</v></c>' % (ref, v)
        if shared:
            if v not in strings:
                strings.append(v)
            return '<c r="%s" t="s"><v>%d</v></c>' % (ref, strings.index(v))
        return '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, escape(v))

    def sheet(rs):
        return ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' +
                "".join('<row r="%d">%s</row>' % (i + 1, "".join(cell(i, j, v) for j, v in enumerate(r))) for i, r in enumerate(rs)) + "</sheetData></worksheet>")
    sheets = ([("Deckblatt", [["Läufe-Export"], ["Stand 27.10."]])] if extra_first_sheet else []) + [("Protokoll", rows)]
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' +
                   "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (n, i + 1, i + 1) for i, (n, _) in enumerate(sheets)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
                   "".join('<Relationship Id="rId%d" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1) for i in range(len(sheets))) + "</Relationships>")
        for i, (_, rs) in enumerate(sheets):
            z.writestr("xl/worksheets/sheet%d.xml" % (i + 1), sheet(rs))
        if shared:
            z.writestr("xl/sharedStrings.xml", '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
                       "".join("<si><t>%s</t></si>" % escape(s) for s in strings) + "</sst>")
    return bio.getvalue()


def serial(s):
    from datetime import datetime
    return (datetime.strptime(s, "%Y-%m-%d %H:%M:%S") - datetime(1899, 12, 30)).total_seconds() / 86400.0


class ExcelImport(unittest.TestCase):
    def rows(self):
        return [["Lauf-ID", "Automation", "Werkzeug", "Startzeit", "Endzeit", "Status", "Anzahl", "Details"],
                ["L1", "A07", "Make", serial("2026-10-26 00:00:03"), serial("2026-10-26 00:00:20"), "Success", 2, "2 Übergaben zugewiesen"],
                [None, "Kunden-Agent-Übergabe", None, "26.10.2026 04:00:05", "26.10.2026 04:00:30", "success", "1", "1 Übergaben zugewiesen"],
                ["L3", "A09", "Claude-Routine (Cloud)", serial("2026-10-26 06:00:40"), serial("2026-10-26 06:05:00"), "completed", 138.0, "Report aktualisiert, 138 Deals"],
                ["L4", "A99", "Make", "2026-10-26 07:00:00", "2026-10-26 07:00:05", "success", 1, "unbekannt"]]

    def test_excel_mit_deutschen_spalten_serien_und_namen(self):
        for shared in (False, True):
            s = fresh(False)
            res = ingest.import_bytes(s, make_xlsx(self.rows(), shared=shared), "x.xlsx", "upload")
            self.assertEqual((res["neu"], res["abgelehnt"], res["art"], res["blatt"]), (3, 1, "Excel", "Protokoll"))
            runs = s.runs()
            self.assertEqual(iso(runs[0].start), "2026-10-26T00:00:03")
            self.assertEqual(runs[0].status, "success")  # „Success“ -> success
            self.assertEqual(runs[1].auto, "A07")        # per Name erkannt
            self.assertEqual(runs[2].count, 138)
            self.assertIn("Unbekannte Automation", s.rejects()[0]["reason"])

    def test_excel_zweimal_einspielen_ist_idempotent(self):
        s = fresh(False)
        data = make_xlsx(self.rows())
        ingest.import_bytes(s, data, "x.xlsx")
        self.assertEqual(ingest.import_bytes(s, data, "x.xlsx")["doppelt"], 3)
        self.assertEqual(s.run_count(), 3)

    def test_csv_mit_komma_und_windows_kodierung(self):
        s = fresh(False)
        txt = "lauf_id,automation_id,start,ende,status,anzahl,detail\nL1,A07,2026-10-26 00:00:03,2026-10-26 00:00:20,success,1,1 Übergaben zugewiesen\n"
        self.assertEqual(ingest.import_bytes(s, txt.encode("cp1252"), "a.csv")["neu"], 1)

    def test_excel_ohne_pflichtspalten(self):
        res = ingest.import_bytes(fresh(False), make_xlsx([["Foo", "Bar"], [1, 2]]), "x.xlsx")
        self.assertIn("Spalten nicht erkannt", res["fehler"])

    def test_xml_entity_wird_abgelehnt(self):
        import io, zipfile
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as z:
            z.writestr("xl/workbook.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets/></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels", "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'/>")
        self.assertIn("abgelehnt", ingest.import_bytes(fresh(False), bio.getvalue(), "x.xlsx")["fehler"])


class Einlieferung(unittest.TestCase):
    def setUp(self):
        self.s = fresh(False)
        self.sec = ingest.load_secrets(self.s.reg, Path(self.id() + ".json"))
        self.addCleanup(lambda: Path(self.id() + ".json").unlink(missing_ok=True) if sys.version_info >= (3, 8) else None)

    def post(self, body, source="make", secret=None, ts=None, sig=None):
        now = time.time()
        ts = str(int(now)) if ts is None else ts
        raw = json.dumps(body).encode() if not isinstance(body, bytes) else body
        sig = ingest.sign(secret or self.sec[source], ts, raw) if sig is None else sig
        return ingest.receive(self.s, raw, {"X-Heartbeat-Source": source, "X-Heartbeat-Timestamp": ts, "X-Heartbeat-Signature": sig}, self.sec, now)

    ENV = {"automation_id": "A07", "werkzeug": "Make", "start": "2026-10-27 00:00:03", "ende": "2026-10-27 00:00:09", "status": "success", "anzahl": 1, "detail": "1 Übergaben zugewiesen"}

    def test_gueltig_und_idempotent(self):
        self.assertEqual(self.post(self.ENV)[0], 200)
        code, res = self.post(self.ENV)
        self.assertEqual(code, 200)
        self.assertFalse(res["neu"])
        self.assertEqual(self.s.run_count(), 1)

    def test_falsche_signatur(self):
        self.assertEqual(self.post(self.ENV, sig="00")[0], 401)
        self.assertEqual(self.s.run_count(), 0)

    def test_manipulierter_body(self):
        raw = json.dumps(self.ENV).encode()
        ts = str(int(time.time()))
        sig = ingest.sign(self.sec["make"], ts, raw)
        code, _ = self.post(raw.replace(b'"anzahl": 1', b'"anzahl": 9'), sig=sig, ts=ts)
        self.assertEqual(code, 401)

    def test_replay_zu_alter_zeitstempel(self):
        self.assertEqual(self.post(self.ENV, ts=str(int(time.time()) - 3600))[0], 401)

    def test_quelle_darf_fremdes_werkzeug_nicht_melden(self):
        self.assertEqual(self.post(self.ENV, source="laptop")[0], 422)  # Laptop-Geheimnis, aber Make-Automation

    def test_unbekannte_automation_und_quarantaene(self):
        code, _ = self.post(dict(self.ENV, automation_id="A99"))
        self.assertEqual(code, 422)
        self.assertEqual(len(self.s.rejects()), 1)

    def test_unbekannter_status_wird_gespeichert_und_gemeldet(self):
        self.assertEqual(self.post(dict(self.ENV, status="kaputt"))[0], 200)
        m = insight.build(self.s.reg, self.s, parse_local("2026-10-27 01:00"))
        self.assertTrue([t for t in m["incidents"] if "STATUS_UNBEKANNT" in t["codes"]])

    def test_zu_gross(self):
        self.assertEqual(ingest.receive(self.s, b"x" * 70000, {"X-Heartbeat-Source": "make"}, self.sec)[0], 413)


class KiRueckfall(unittest.TestCase):
    class P:
        def __init__(self, name, *res):
            self.name, self.res, self.calls = name, list(res), 0

        def complete(self, system, user):
            self.calls += 1
            r = self.res.pop(0) if self.res else self.res_last
            if isinstance(r, Exception):
                raise r
            return r

    GOOD = '{"hypothesen":[{"text":"Kanal archiviert","konfidenz":"mittel","belege":["L1"]}],"rueckfragen":["Wer hat den Kanal geändert?"],"plausibilitaet":[]}'

    def mk(self, *ps):
        return analyst.Analyst(list(ps), pause_s=0, sleep=lambda s: None)

    def test_erstes_modell_ok(self):
        p = self.P("a", self.GOOD)
        r = self.mk(p).analyse({})
        self.assertEqual((r["status"], r["quelle"]), ("ok", "a"))
        self.assertEqual(r["body"]["hypothesen"][0]["konfidenz"], "mittel")

    def test_ueberlast_dann_zweites_modell(self):
        a = self.P("a", analyst.ProviderError("HTTP 529", True), analyst.ProviderError("HTTP 529", True))
        b = self.P("b", self.GOOD)
        r = self.mk(a, b).analyse({})
        self.assertEqual(r["quelle"], "b")
        self.assertEqual(a.calls, 2)  # ein Retry

    def test_alle_aus_dann_regelwerk(self):
        a = self.P("a", analyst.ProviderError("Timeout", True), analyst.ProviderError("Timeout", True))
        b = self.P("b", analyst.ProviderError("HTTP 500", True), analyst.ProviderError("HTTP 500", True))
        r = self.mk(a, b).analyse({})
        self.assertEqual((r["status"], r["quelle"]), ("fallback", "regelwerk"))
        self.assertIn("Regelwerk", r["body"]["hinweis"])

    def test_kein_schluessel_kein_netzaufruf(self):
        p = analyst.AnthropicProvider("x", api_key=None)
        p.key = None
        self.assertEqual(self.mk(p).analyse({})["status"], "fallback")

    def test_ungueltige_antwort_naechstes_modell(self):
        a = self.P("a", "kein json")
        b = self.P("b", self.GOOD)
        self.assertEqual(self.mk(a, b).analyse({})["quelle"], "b")

    def test_schutzschalter_pausiert_defektes_modell(self):
        a = self.P("a", *([analyst.ProviderError("HTTP 400", False)] * 5))
        ai = self.mk(a)
        ai.analyse({}); ai.analyse({})
        n = a.calls
        ai.analyse({})
        self.assertEqual(a.calls, n)  # pausiert

    def test_zeitbudget(self):
        t = [0.0]
        a = self.P("a", analyst.ProviderError("Timeout", True), analyst.ProviderError("Timeout", True))
        ai = analyst.Analyst([a], budget_s=5, pause_s=0, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + 10))
        r = ai.analyse({})
        self.assertEqual(r["status"], "fallback")


class SlackSicherheit(unittest.TestCase):
    def test_signatur(self):
        import hashlib, hmac
        body, ts = b"payload=%7B%7D", str(int(time.time()))
        sig = "v0=" + hmac.new(b"s3cret", b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
        self.assertTrue(slack.verify_signature("s3cret", ts, body, sig)[0])
        self.assertFalse(slack.verify_signature("andere", ts, body, sig)[0])
        self.assertFalse(slack.verify_signature("s3cret", str(int(ts) - 4000), body, sig)[0])

    def test_interaktion_parsen(self):
        p = {"user": {"id": "U1"}, "actions": [{"action_id": "hb_ack", "value": "A02:x"}, {"action_id": "hb_open", "value": "A02:x"}]}
        self.assertEqual(slack.parse_interaction(p), [("ack", "A02:x", "U1")])

    def test_erster_satz_zerreisst_keine_datumsangabe(self):
        s = "A02 meldet Fehler (Di 20.10. 07:39 bis Di 20.10. 19:05). Das Szenario ignoriert alles."
        self.assertTrue(slack.first_sentence(s).endswith("19:05)."))


if __name__ == "__main__":
    unittest.main()
