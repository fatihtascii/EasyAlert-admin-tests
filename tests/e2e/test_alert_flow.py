"""Uçtan uca alarm akışı: webhook -> incident -> bildirim -> çözüm (API üzerinden).

Modül başında yalnız bu testlere ait bir düzen kurulur ve sonda silinir:
- Custom tipinde `otomasyon*` entegrasyon (webhook token'ı buradan alınır)
- Tek seviyeli `otomasyon*` escalation policy: hedef YALNIZ EA_NOTIFY_EMAIL kullanıcısı, kanal yalnız e-posta
- Priority 1 (ilk değerlendirilen) `otomasyon*` routing kuralı: tags.automation = <çalışma kimliği> -> bu policy

GÜVENLİK: gerçek kişilere bildirim gitmemesi için, webhook'a herhangi bir olay gönderilmeden önce
escalationRouting/test ucuyla test olayının bu kurala düştüğü doğrulanır; düşmezse modül hiç olay göndermeden durur.
Olayların başlığı "[otomasyon]" ile başlar.
"""
import os
import time
import uuid
from datetime import datetime, timezone

import pytest

from utils.api_client import body, describe
from utils.markers import known_bug
from utils.random_data import unique_name

pytestmark = [pytest.mark.e2e, pytest.mark.data_producing]

NOTIFY_EMAIL = os.getenv("EA_NOTIFY_EMAIL", "").strip().lower()
RUN = uuid.uuid4().hex[:8]  # bu çalışmanın etiketi: routing kuralı yalnız bunu taşıyan olayları yakalar
WH01 = ("WH-01: Webhook ucu dokümanda zorunlu denen alanlar (eventId, title, severity, status, timestamp) eksik olsa da "
        "olayı kabul edip incident açıyor (200 accepted); 4xx doğrulama hatası beklenir")


def _data(r):
    assert r.ok, describe(r)
    return (body(r) or {}).get("data")


def _event(event_id: str, status: str = "problem", severity: str = "critical", **extra) -> dict:
    return {
        "eventId": event_id, "title": f"[otomasyon] e2e {event_id}", "severity": severity, "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(), "host": "otomasyon-host", "service": "otomasyon-service",
        "tags": {"automation": RUN}, **extra,
    }


def _incident(api, incident_id: str, want=None, timeout_s: int = 20) -> dict:
    """Incident'ı getirir; `want(inc)` verilirse sağlanana kadar bekler."""
    inc = {}
    for _ in range(timeout_s * 2):
        inc = _data(api.get(f"incidents/{incident_id}")) or {}
        if want is None or want(inc):
            return inc
        time.sleep(0.5)
    return inc


@pytest.fixture(scope="module")
def setup(api):
    if not NOTIFY_EMAIL:
        pytest.skip(".env'e EA_NOTIFY_EMAIL ekle (bildirim alacak test kullanıcısı)")
    users = _data(api.get("iam/users/lookup", params={"search": NOTIFY_EMAIL})) or []
    user = next((u for u in users if (u.get("email") or "").lower() == NOTIFY_EMAIL), None)
    assert user, f"{NOTIFY_EMAIL} EasyAlert kullanıcıları arasında yok"
    schema = _data(api.get("webhooks/schema")) or body(api.get("webhooks/schema"))
    props = sorted(((schema or {}).get("properties") or {}).keys()) if isinstance(schema, dict) else []
    print(f"\n[e2e] webhook şeması alanları: {props}")
    assert not props or "tags" in props, f"Webhook şemasında 'tags' alanı yok; routing kuralı kurulamaz: {props}"

    name = unique_name()
    created = {}
    try:
        integ = _data(api.post("integrations", data={"name": name, "sourceType": "custom",
                                                    "description": "otomasyon e2e (test sonunda silinir)"}))
        created["integration"] = integ["id"]
        policy = _data(api.post("escalationPolicies", data={
            "name": name, "description": "otomasyon e2e (test sonunda silinir)", "isDefault": False,
            "levels": [{"level": 1, "delayMinutes": 0, "targets": [{"type": "user", "id": user["userId"]}],
                        "channels": ["email"], "callMaxRetries": 0, "sendResolvedNotification": False}]}))
        created["policy"] = policy["id"]
        rule = _data(api.post("escalationRouting", data={
            "name": name, "description": "otomasyon e2e (test sonunda silinir)", "priority": 1, "isActive": True,
            "conditionLogic": "and", "initialDelaySeconds": 0, "escalationPolicyId": policy["id"],
            "conditions": [{"field": "tags.automation", "operator": "equals", "value": RUN}]}))
        created["rule"] = rule["id"]

        # Güvenlik kontrolü: test olayı gerçekten bizim kurala/policy'ye düşüyor mu? (olay gönderilmeden)
        sim = _data(api.post("escalationRouting/test", data={
            "severity": "critical", "title": "[otomasyon] e2e", "host": "otomasyon-host", "service": "otomasyon-service",
            "tags": {"automation": RUN}, "sourceType": "custom"}))
        print(f"[e2e] routing simülasyonu: kural={sim.get('matchedRuleName')} policy={sim.get('escalationPolicyName')} "
              f"varsayılan={sim.get('usedDefault')}")
        assert sim.get("matchedRuleId") == rule["id"] and sim.get("escalationPolicyId") == policy["id"], (
            f"Test olayı otomasyon kuralına düşmüyor ({sim}); gerçek kişilere bildirim gitmemesi için olay gönderilmedi")
        yield {"token": integ["webhookToken"], "integration": integ["id"], "policy": policy["id"], "rule": rule["id"],
               "user": user, "incidents": []}
    finally:
        _cleanup(api, created)


def _cleanup(api, created: dict):
    # Bu çalışmanın açık kalmış incident'larını çöz (ör. beklenmedik şekilde kabul edilen eksik gövdeli olaylar)
    r = api.get("incidents", params={"search": RUN, "size": 50})
    for inc in ((body(r) or {}).get("data") or []) if r.ok else []:
        if inc.get("status") != "resolved" and RUN in (inc.get("title") or ""):
            api.post(f"incidents/{inc['id']}/resolve", data={"resolutionNote": "otomasyon temizlik"})
            print(f"\n[e2e] temizlik: açık kalan incident #{inc.get('incidentNumber')} çözüldü")
    for kind, path in (("rule", "escalationRouting"), ("policy", "escalationPolicies"), ("integration", "integrations")):
        if kind in created:
            r = api.delete(f"{path}/{created[kind]}")
            print(f"\n[e2e] temizlik {kind}: {r.status}")


@pytest.fixture(scope="module")
def send(anon_api, setup):
    """Webhook'a olay gönderir (token URL'de; oturum gerekmez) ve cevabın data kısmını döner."""
    def _send(payload: dict):
        r = anon_api.post(f"webhooks/ingest/{setup['token']}", data=payload)
        b = body(r)
        print(f"[e2e] webhook {payload['status']} {payload['eventId']}: {describe(r)[:250]}")
        assert r.ok, describe(r)
        return (b.get("data") if isinstance(b, dict) and "data" in b else b) or {}
    return _send


@pytest.fixture(scope="module")
def opened(api, setup, send):
    """İlk problem olayı ve açtığı incident (sonraki testler bunu kullanır)."""
    event_id = f"e2e-{RUN}-1"
    res = send(_event(event_id))
    assert res.get("incidentId"), f"Webhook incident döndürmedi: {res}"
    setup["incidents"].append(res["incidentId"])
    return {"event_id": event_id, "response": res, "incident_id": res["incidentId"]}


def test_problem_event_opens_incident(api, setup, opened):
    """Webhook ile gelen kritik problem olayı incident açar ve otomasyon policy'sine bağlanır

    Adımlar:
    1. Webhook'a status=problem, severity=critical bir olay gönder -> 200; cevapta incidentCreated=true ve incidentId
    2. Incident'ı getir -> Durum triggered, severity critical, başlık/host/servis olaydaki gibi, alertCount 1,
       kaynak custom, escalation policy otomasyon policy'si
    """
    res, inc = opened["response"], _incident(api, opened["incident_id"])
    assert res.get("incidentCreated") is True, f"incidentCreated beklenmiyordu: {res}"
    print(f"[e2e] incident #{inc.get('incidentNumber')}: {inc.get('status')} {inc.get('severity')} "
          f"alertCount={inc.get('alertCount')} policy={inc.get('escalationPolicyId') == setup['policy']}")
    assert inc.get("status") == "triggered"
    assert inc.get("severity") == "critical"
    assert inc.get("title", "").startswith("[otomasyon]")
    assert inc.get("host") == "otomasyon-host" and inc.get("service") == "otomasyon-service"
    assert inc.get("alertCount") == 1
    assert inc.get("sourceType") == "custom"
    assert inc.get("escalationPolicyId") == setup["policy"], "Incident otomasyon policy'sine bağlanmadı"


def _notifications(api, incident_id: str, timeout_s: int = 45) -> list:
    logs = []
    for _ in range(timeout_s):
        r = api.get(f"notifications/{incident_id}/logs")
        data = _data(r)
        logs = data if isinstance(data, list) else (data or {}).get("items") or (data or {}).get("logs") or []
        if logs:
            return logs
        time.sleep(1)
    return logs


def test_notification_only_to_automation_target(api, setup, opened):
    """Bildirim yalnız otomasyon policy'sindeki test kullanıcısına, yalnız e-postayla gider

    Adımlar:
    1. Incident'ın bildirim kayıtlarını (notifications/{id}/logs) bekle -> En az bir kayıt oluşur
    2. Kayıtları kontrol et -> Hepsi test kullanıcısına ve email kanalına; gönderim durumu başarısız değil
    """
    notes = _notifications(api, opened["incident_id"])
    print(f"[e2e] bildirimler: {[(n.get('targetName'), n.get('channel'), n.get('status')) for n in notes]}")
    assert notes, "Bildirim kaydı oluşmadı"
    others = [n for n in notes if n.get("targetId") not in (setup["user"]["userId"], None)
              or (n.get("destination") or NOTIFY_EMAIL).lower() != NOTIFY_EMAIL]
    assert not others, f"Test kullanıcısı dışında bildirim gitti: {others}"
    assert {str(n.get("channel")).lower() for n in notes} <= {"email"}, f"E-posta dışı kanal kullanıldı: {notes}"
    assert not [n for n in notes if str(n.get("status")).lower() in ("failed", "error")], f"Başarısız bildirim: {notes}"


def test_repeated_event_is_deduplicated(api, setup, send, opened):
    """Aynı olay kimliğiyle tekrar gelen problem olayı tekrar işlenmez; yeni incident açılmaz

    Adımlar:
    1. Aynı eventId ile problem olayını tekrar gönder -> 200; status "duplicate", incidentCreated=false
    2. Mevcut incident'ı getir -> Hâlâ açık; alertCount değişmemiş (1)
    """
    res = send(_event(opened["event_id"]))
    print(f"[e2e] tekrar: status={res.get('status')} incidentCreated={res.get('incidentCreated')}")
    assert res.get("status") == "duplicate", f"Tekrar eden olay duplicate sayılmadı: {res}"
    assert res.get("incidentCreated") is not True
    inc = _incident(api, opened["incident_id"])
    assert inc.get("status") in ("triggered", "acknowledged")
    assert inc.get("alertCount") == 1, f"alertCount {inc.get('alertCount')}, beklenen 1"


def test_ok_event_resolves_incident(api, setup, send, opened):
    """Kaynaktan gelen 'ok' olayı açık incident'ı otomatik çözer

    Adımlar:
    1. Aynı eventId ile status=ok olayını gönder -> 200; aynı incidentId
    2. Incident'ı getir -> Durum resolved, resolvedAt dolu
    """
    res = send(_event(opened["event_id"], status="ok", severity="ok"))
    assert res.get("incidentId") in (opened["incident_id"], None), f"Farklı incident'a gitti: {res}"
    inc = _incident(api, opened["incident_id"], want=lambda i: i.get("status") == "resolved")
    print(f"[e2e] ok sonrası: {inc.get('status')} resolvedAt={bool(inc.get('resolvedAt'))} action={res.get('incidentAction')}")
    assert inc.get("status") == "resolved"
    assert inc.get("resolvedAt")


def test_manual_acknowledge_then_resolve(api, setup, send):
    """Yeni incident API'den onaylanır ve not ile çözülür; durumlar ve zaman damgaları güncellenir

    Adımlar:
    1. Yeni bir eventId ile problem olayı gönder -> Incident açılır
    2. POST incidents/{id}/acknowledge -> Durum acknowledged, acknowledgedAt ve onaylayan dolu
    3. POST incidents/{id}/resolve (resolutionNote ile) -> Durum resolved, not kaydedilmiş
    """
    res = send(_event(f"e2e-{RUN}-2", severity="high"))
    iid = res.get("incidentId")
    assert iid, res
    setup["incidents"].append(iid)
    r = api.post(f"incidents/{iid}/acknowledge", data={})
    assert r.ok, describe(r)
    inc = _incident(api, iid, want=lambda i: i.get("status") == "acknowledged")
    assert inc.get("status") == "acknowledged" and inc.get("acknowledgedAt"), inc.get("status")
    r = api.post(f"incidents/{iid}/resolve", data={"resolutionNote": "otomasyon e2e"})
    assert r.ok, describe(r)
    inc = _incident(api, iid, want=lambda i: i.get("status") == "resolved")
    print(f"[e2e] elle: acknowledged->resolved, not={inc.get('resolutionNote')!r}")
    assert inc.get("status") == "resolved"
    assert inc.get("resolutionNote") == "otomasyon e2e"


def test_invalid_webhook_token_rejected(anon_api, setup):
    """Geçersiz webhook token'ıyla gelen olay kabul edilmez

    Adımlar:
    1. Token'ın son karakterlerini değiştirip olay gönder -> 4xx; incident açılmaz
    """
    bad = setup["token"][:-4] + ("0000" if not setup["token"].endswith("0000") else "1111")
    r = anon_api.post(f"webhooks/ingest/{bad}", data=_event(f"e2e-{RUN}-bad"))
    print(f"[e2e] geçersiz token: {describe(r)[:200]}")
    assert 400 <= r.status < 500, describe(r)


@known_bug(WH01)
@pytest.mark.parametrize("missing", ["eventId", "title", "severity", "status", "timestamp"])
def test_payload_without_required_field_rejected(anon_api, setup, missing):
    """Zorunlu alanı eksik webhook gövdesi 4xx ile reddedilir, 5xx vermez

    Adımlar:
    1. Zorunlu alanlardan biri (eventId, title, severity, status, timestamp) olmadan olay gönder -> 4xx (ör. 422)
    """
    payload = _event(f"e2e-{RUN}-missing-{missing}")
    payload.pop(missing)
    r = anon_api.post(f"webhooks/ingest/{setup['token']}", data=payload)
    print(f"[e2e] {missing} yok: {describe(r)[:160]}")
    assert r.status < 500, describe(r)
    assert 400 <= r.status < 500, describe(r)
