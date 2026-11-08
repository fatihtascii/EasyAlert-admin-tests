"""Uçtan uca testlerin ortak düzeni: yalnız bu testlere ait entegrasyon + policy + routing kuralı.

`automation_route(...)` bir bağlam yöneticisidir: kurar, routing simülasyonuyla test olaylarının gerçekten bu
policy'ye düştüğünü doğrular (düşmezse hiç olay göndermeden durur), sonda açık kalan incident'ları çözer ve
kural/policy/entegrasyonu siler. Bildirimler yalnız EA_NOTIFY_EMAIL kullanıcısına, yalnız e-postayla gider.
"""
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from utils.api_client import body, describe
from utils.random_data import unique_name

NOTIFY_EMAIL = os.getenv("EA_NOTIFY_EMAIL", "").strip().lower()
NOTE = "otomasyon e2e (test sonunda silinir)"


def data(r):
    assert r.ok, describe(r)
    return (body(r) or {}).get("data")


def notify_user(api) -> dict:
    if not NOTIFY_EMAIL:
        pytest.skip(".env'e EA_NOTIFY_EMAIL ekle (bildirim alacak test kullanıcısı)")
    users = data(api.get("iam/users/lookup", params={"search": NOTIFY_EMAIL})) or []
    user = next((u for u in users if (u.get("email") or "").lower() == NOTIFY_EMAIL), None)
    assert user, f"{NOTIFY_EMAIL} EasyAlert kullanıcıları arasında yok"
    return user


def level(n: int, user_id: str, delay_minutes: int = 0) -> dict:
    return {"level": n, "delayMinutes": delay_minutes, "targets": [{"type": "user", "id": user_id}],
            "channels": ["email"], "callMaxRetries": 0, "sendResolvedNotification": False}


class Route:
    """Kurulan düzen: olay üretme/gönderme ve incident/bildirim okuma yardımcıları."""

    def __init__(self, api, anon_api, tag: str, token: str, ids: dict, user: dict):
        self.api, self.anon_api, self.tag, self.token, self.ids, self.user = api, anon_api, tag, token, ids, user
        self._n = 0

    def event(self, event_id: str | None = None, status: str = "problem", severity: str = "critical", **extra) -> dict:
        if event_id is None:
            self._n += 1
            event_id = f"e2e-{self.tag}-{self._n}"
        return {"eventId": event_id, "title": f"[otomasyon] e2e {event_id}", "severity": severity, "status": status,
                "timestamp": datetime.now(timezone.utc).isoformat(), "host": "otomasyon-host",
                "service": "otomasyon-service", "tags": {"automation": self.tag}, **extra}

    def send(self, payload: dict) -> dict:
        r = self.anon_api.post(f"webhooks/ingest/{self.token}", data=payload)
        b = body(r)
        print(f"[e2e] webhook {payload.get('status')} {payload.get('eventId')}: {describe(r)[:200]}")
        assert r.ok, describe(r)
        return (b.get("data") if isinstance(b, dict) and "data" in b else b) or {}

    def open_incident(self, **kw) -> tuple[str, str]:
        """Yeni problem olayı gönderir; (eventId, incidentId) döner."""
        payload = self.event(**kw)
        res = self.send(payload)
        assert res.get("incidentId"), f"Webhook incident döndürmedi: {res}"
        return payload["eventId"], res["incidentId"]

    def incident(self, incident_id: str, want=None, timeout_s: int = 20) -> dict:
        inc = {}
        for _ in range(timeout_s * 2):
            inc = data(self.api.get(f"incidents/{incident_id}")) or {}
            if want is None or want(inc):
                return inc
            time.sleep(0.5)
        return inc

    def notifications(self, incident_id: str, want=None, timeout_s: int = 45) -> list:
        logs = []
        for _ in range(timeout_s):
            d = data(self.api.get(f"notifications/{incident_id}/logs"))
            logs = d if isinstance(d, list) else (d or {}).get("items") or (d or {}).get("logs") or []
            if (want(logs) if want else logs):
                return logs
            time.sleep(1)
        return logs


@contextmanager
def automation_route(api, anon_api, levels_fn, initial_delay_s: int = 0):
    """levels_fn(user_id) -> policy seviyeleri. Kurulumu yapar, Route verir, sonunda her şeyi temizler."""
    user = notify_user(api)
    tag = uuid.uuid4().hex[:8]
    name = unique_name()
    ids: dict = {}
    try:
        integ = data(api.post("integrations", data={"name": name, "sourceType": "custom", "description": NOTE}))
        ids["integration"] = integ["id"]
        policy = data(api.post("escalationPolicies", data={
            "name": name, "description": NOTE, "isDefault": False, "repeatLimit": 1,
            "levels": levels_fn(user["userId"])}))
        ids["policy"] = policy["id"]
        rule = data(api.post("escalationRouting", data={
            "name": name, "description": NOTE, "priority": 1, "isActive": True, "conditionLogic": "and",
            "initialDelaySeconds": initial_delay_s, "escalationPolicyId": policy["id"],
            "conditions": [{"field": "tags.automation", "operator": "equals", "value": tag}]}))
        ids["rule"] = rule["id"]
        sim = data(api.post("escalationRouting/test", data={
            "severity": "critical", "title": "[otomasyon] e2e", "host": "otomasyon-host",
            "service": "otomasyon-service", "tags": {"automation": tag}, "sourceType": "custom"}))
        print(f"\n[e2e] routing simülasyonu: kural={sim.get('matchedRuleName')} varsayılan={sim.get('usedDefault')}")
        assert sim.get("matchedRuleId") == rule["id"] and sim.get("escalationPolicyId") == policy["id"], (
            f"Test olayı otomasyon kuralına düşmüyor ({sim}); gerçek kişilere bildirim gitmemesi için olay gönderilmedi")
        yield Route(api, anon_api, tag, integ["webhookToken"], ids, user)
    finally:
        r = api.get("incidents", params={"search": tag, "size": 50})
        for inc in ((body(r) or {}).get("data") or []) if r.ok else []:
            if inc.get("status") != "resolved" and tag in (inc.get("title") or ""):
                api.post(f"incidents/{inc['id']}/resolve", data={"resolutionNote": "otomasyon temizlik"})
                print(f"\n[e2e] temizlik: açık kalan incident #{inc.get('incidentNumber')} çözüldü")
        for kind, path in (("rule", "escalationRouting"), ("policy", "escalationPolicies"), ("integration", "integrations")):
            if kind in ids:
                print(f"[e2e] temizlik {kind}: {api.delete(f'{path}/{ids[kind]}').status}")
