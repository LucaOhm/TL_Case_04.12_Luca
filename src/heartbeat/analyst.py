"""Optionale KI-Vertiefung mit sicherer Rückfallkette.

Grundsatz: Erkennung, Priorität, Zustellung und Briefing sind deterministisch und hängen NICHT an einem Sprachmodell.
Die KI liefert nur eine zusätzliche, klar gekennzeichnete Einschätzung (Hypothesen, Rückfragen) auf Basis der Belege.

Kette:  Modell 1 -> (Retry mit Pause bei 429/5xx/Timeout) -> Modell 2 -> Regelwerk-Empfehlung.
Schutz: Zeitbudget je Aufruf, Schutzschalter pro Modell nach wiederholten Fehlern, Antwort muss gültiges JSON sein.
Ohne ANTHROPIC_API_KEY wird nichts gesendet; die Oberfläche zeigt dann ehrlich „Regelwerk“.
Hinweis: Der Live-Aufruf ist ohne Schlüssel hier nicht getestet; die Rückfalllogik ist per Test mit simulierten Ausfällen geprüft.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional

SYSTEM = ("Du bist Analyst für Betriebsautomationen. Du bekommst eine bereits erkannte Störung mit Belegen. "
          "Nutze AUSSCHLIESSLICH diese Belege, erfinde keine Fakten, kennzeichne Annahmen. Antworte nur mit JSON: "
          '{"hypothesen":[{"text":"","konfidenz":"niedrig|mittel|hoch","belege":["lauf_id"]}],'
          '"rueckfragen":[""],"plausibilitaet":[{"text":"","staerke":"belegt|hinweis|hypothese"}]}. '
          "Maximal 3 Hypothesen, kurz, auf Deutsch. Du gibst Vorschläge, keine Anweisungen.")


class ProviderError(Exception):
    def __init__(self, msg: str, retryable: bool = False):
        super().__init__(msg)
        self.retryable = retryable


class AnthropicProvider:
    def __init__(self, model: str, api_key: Optional[str] = None, timeout: float = 20.0, base: str = "https://api.anthropic.com"):
        self.model = model
        self.key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.timeout = timeout
        self.base = base
        self.name = "claude:" + model

    @property
    def available(self) -> bool:
        return bool(self.key)

    def complete(self, system: str, user: str) -> str:
        if not self.key:
            raise ProviderError("kein API-Schlüssel", retryable=False)
        body = json.dumps({"model": self.model, "max_tokens": 900, "system": system,
                           "messages": [{"role": "user", "content": user}]}).encode()
        req = urllib.request.Request(self.base + "/v1/messages", body, {
            "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode())
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        except urllib.error.HTTPError as e:
            raise ProviderError("HTTP %d" % e.code, retryable=e.code in (408, 429, 500, 502, 503, 504, 529))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ProviderError("Netz/Timeout: %s" % e, retryable=True)


def evidence_bundle(inc: dict, rows: List[dict]) -> dict:
    """Minimale Beleglage für die KI: nur Protokollzeilen und Befunde, keine Personendaten."""
    return {"titel": inc["titel"], "zusammenfassung": inc["kurz"], "prioritaet": inc["level_name"],
            "automationen": [a["id"] + " " + a["name"] for a in inc["auto_info"]], "wirkung": inc.get("wirkung"),
            "seit": inc["first"], "anzahl": inc["count"], "protokoll": rows[:14],
            "plausibilitaet": [{"titel": p["titel"], "text": p["text"], "staerke": p["staerke"]} for p in inc.get("plausibilitaet", [])],
            "regelwerk_ursachen": inc.get("ursachen", [])}


class Analyst:
    def __init__(self, providers: List, budget_s: float = 45.0, retries: int = 1, pause_s: float = 1.5,
                 breaker_after: int = 2, breaker_cool_s: float = 300.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.providers = providers
        self.budget_s, self.retries, self.pause_s = budget_s, retries, pause_s
        self.breaker_after, self.breaker_cool_s = breaker_after, breaker_cool_s
        self.clock, self.sleep = clock, sleep
        self.fails: Dict[str, int] = {}
        self.open_until: Dict[str, float] = {}

    @classmethod
    def from_env(cls) -> "Analyst":
        models = [m.strip() for m in os.environ.get("HEARTBEAT_MODELS", "claude-sonnet-5-5,claude-haiku-5-5").split(",") if m.strip()]
        return cls([AnthropicProvider(m) for m in models])

    def _fallback(self, why: str, versuche: List[str]) -> dict:
        return {"quelle": "regelwerk", "status": "fallback",
                "body": {"hinweis": "KI-Analyse nicht verfügbar (%s). Es gilt die Empfehlung aus dem Regelwerk – sie ist vollständig." % why, "versuche": versuche,
                         "hypothesen": [], "rueckfragen": [], "plausibilitaet": []}}

    def analyse(self, bundle: dict) -> dict:
        t_start = self.clock()
        versuche: List[str] = []
        user = json.dumps(bundle, ensure_ascii=False)
        for p in self.providers:
            if getattr(p, "available", True) is False:
                versuche.append("%s: kein Schlüssel" % p.name)
                continue
            if self.open_until.get(p.name, 0) > self.clock():
                versuche.append("%s: pausiert (Schutzschalter)" % p.name)
                continue
            for attempt in range(self.retries + 1):
                if self.clock() - t_start > self.budget_s:
                    return self._fallback("Zeitbudget aufgebraucht", versuche)
                try:
                    txt = p.complete(SYSTEM, user)
                    body = self._parse(txt)
                    self.fails[p.name] = 0
                    return {"quelle": p.name, "status": "ok", "body": body}
                except ProviderError as e:
                    versuche.append("%s: %s" % (p.name, e))
                    self._count_fail(p.name)
                    if not e.retryable or attempt == self.retries:
                        break
                    self.sleep(self.pause_s * (attempt + 1))
                except ValueError as e:
                    versuche.append("%s: ungültige Antwort (%s)" % (p.name, e))
                    self._count_fail(p.name)
                    break
        return self._fallback("alle Modelle ausgefallen oder nicht konfiguriert" if versuche else "kein Modell konfiguriert", versuche)

    def _count_fail(self, name: str) -> None:
        self.fails[name] = self.fails.get(name, 0) + 1
        if self.fails[name] >= self.breaker_after:
            self.open_until[name] = self.clock() + self.breaker_cool_s

    @staticmethod
    def _parse(txt: str) -> dict:
        s = txt.strip()
        if s.startswith("```"):
            s = s.strip("`")
            s = s[s.find("{"):]
        a, b = s.find("{"), s.rfind("}")
        if a < 0 or b < a:
            raise ValueError("kein JSON")
        d = json.loads(s[a:b + 1])
        out = {"hypothesen": [], "rueckfragen": [], "plausibilitaet": []}
        for h in d.get("hypothesen", [])[:3]:
            out["hypothesen"].append({"text": str(h.get("text", ""))[:400], "konfidenz": h.get("konfidenz") if h.get("konfidenz") in ("niedrig", "mittel", "hoch") else "niedrig",
                                      "belege": [str(x) for x in h.get("belege", [])][:6]})
        out["rueckfragen"] = [str(x)[:300] for x in d.get("rueckfragen", [])][:4]
        for p in d.get("plausibilitaet", [])[:4]:
            out["plausibilitaet"].append({"text": str(p.get("text", ""))[:400], "staerke": p.get("staerke") if p.get("staerke") in ("belegt", "hinweis", "hypothese") else "hypothese"})
        return out
