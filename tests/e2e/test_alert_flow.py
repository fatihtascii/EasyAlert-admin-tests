"""Uçtan uca alarm akışı: webhook -> incident -> bildirim -> çözüm (API üzerinden).

Düzen (entegrasyon + tek seviyeli policy + priority 1 routing kuralı) tests/e2e/helpers.py'deki automation_route
ile kurulur ve sonda silinir; olay göndermeden önce routing simülasyonuyla doğru policy'ye düştüğü doğrulanır.
"""
import pytest

from tests.e2e.helpers import automation_route, level
from utils.api_client import describe
from utils.markers import known_bug

pytestmark = [pytest.mark.e2e, pytest.mark.data_producing]

WH01 = ("WH-01: Webhook ucu dokümanda zorunlu denen alanlar (eventId, title, severity, status, timestamp) eksik olsa da "
        "olayı kabul edip incident açıyor (200 accepted); 4xx doğrulama hatası beklenir")


@pytest.fixture(scope="module")
def route(api, anon_api):
    with automation_route(api, anon_api, lambda uid: [level(1, uid)]) as r:
        yield r


@pytest.fixture(scope="module")
def opened(route):
    """İlk problem olayı ve açtığı incident (sonraki testler bunu kullanır)."""
    payload = route.event()
    res = route.send(payload)
    assert res.get("incidentId"), f"Webhook incident döndürmedi: {res}"
    return {"event_id": payload["eventId"], "response": res, "incident_id": res["incidentId"]}


def test_problem_event_opens_incident(route, opened):
    """Webhook ile gelen kritik problem olayı incident açar ve otomasyon policy'sine bağlanır

    Adımlar:
    1. Webhook'a status=problem, severity=critical bir olay gönder -> 200; cevapta incidentCreated=true ve incidentId
    2. Incident'ı getir -> Durum triggered, severity critical, başlık/host/servis olaydaki gibi, alertCount 1,
       kaynak custom, escalation policy otomasyon policy'si
    """
    res, inc = opened["response"], route.incident(opened["incident_id"])
    assert res.get("incidentCreated") is True, f"incidentCreated beklenmiyordu: {res}"
    print(f"[e2e] incident #{inc.get('incidentNumber')}: {inc.get('status')} {inc.get('severity')} "
          f"alertCount={inc.get('alertCount')} policy={inc.get('escalationPolicyId') == route.ids['policy']}")
    assert inc.get("status") == "triggered"
    assert inc.get("severity") == "critical"
    assert inc.get("title", "").startswith("[otomasyon]")
    assert inc.get("host") == "otomasyon-host" and inc.get("service") == "otomasyon-service"
    assert inc.get("alertCount") == 1
    assert inc.get("sourceType") == "custom"
    assert inc.get("escalationPolicyId") == route.ids["policy"], "Incident otomasyon policy'sine bağlanmadı"


def test_notification_only_to_automation_target(route, opened):
    """Bildirim yalnız otomasyon policy'sindeki test kullanıcısına, yalnız e-postayla gider

    Adımlar:
    1. Incident'ın bildirim kayıtlarını (notifications/{id}/logs) bekle -> En az bir kayıt oluşur
    2. Kayıtları kontrol et -> Hepsi test kullanıcısına ve email kanalına; gönderim durumu başarısız değil
    """
    notes = route.notifications(opened["incident_id"])
    print(f"[e2e] bildirimler: {[(n.get('targetName'), n.get('channel'), n.get('status')) for n in notes]}")
    assert notes, "Bildirim kaydı oluşmadı"
    email = route.user["email"].lower()
    others = [n for n in notes if n.get("targetId") not in (route.user["userId"], None)
              or (n.get("destination") or email).lower() != email]
    assert not others, f"Test kullanıcısı dışında bildirim gitti: {others}"
    assert {str(n.get("channel")).lower() for n in notes} <= {"email"}, f"E-posta dışı kanal kullanıldı: {notes}"
    assert not [n for n in notes if str(n.get("status")).lower() in ("failed", "error")], f"Başarısız bildirim: {notes}"


def test_repeated_event_is_deduplicated(route, opened):
    """Aynı olay kimliğiyle tekrar gelen problem olayı tekrar işlenmez; yeni incident açılmaz

    Adımlar:
    1. Aynı eventId ile problem olayını tekrar gönder -> 200; status "duplicate", incidentCreated=false
    2. Mevcut incident'ı getir -> Hâlâ açık; alertCount değişmemiş (1)
    """
    res = route.send(route.event(opened["event_id"]))
    print(f"[e2e] tekrar: status={res.get('status')} incidentCreated={res.get('incidentCreated')}")
    assert res.get("status") == "duplicate", f"Tekrar eden olay duplicate sayılmadı: {res}"
    assert res.get("incidentCreated") is not True
    inc = route.incident(opened["incident_id"])
    assert inc.get("status") in ("triggered", "acknowledged")
    assert inc.get("alertCount") == 1, f"alertCount {inc.get('alertCount')}, beklenen 1"


def test_ok_event_resolves_incident(route, opened):
    """Kaynaktan gelen 'ok' olayı açık incident'ı otomatik çözer

    Adımlar:
    1. Aynı eventId ile status=ok olayını gönder -> 200; aynı incidentId
    2. Incident'ı getir -> Durum resolved, resolvedAt dolu
    """
    res = route.send(route.event(opened["event_id"], status="ok", severity="ok"))
    assert res.get("incidentId") in (opened["incident_id"], None), f"Farklı incident'a gitti: {res}"
    inc = route.incident(opened["incident_id"], want=lambda i: i.get("status") == "resolved")
    print(f"[e2e] ok sonrası: {inc.get('status')} resolvedAt={bool(inc.get('resolvedAt'))} action={res.get('incidentAction')}")
    assert inc.get("status") == "resolved"
    assert inc.get("resolvedAt")


def test_manual_acknowledge_then_resolve(api, route):
    """Yeni incident API'den onaylanır ve not ile çözülür; durumlar ve zaman damgaları güncellenir

    Adımlar:
    1. Yeni bir eventId ile problem olayı gönder -> Incident açılır
    2. POST incidents/{id}/acknowledge -> Durum acknowledged, acknowledgedAt ve onaylayan dolu
    3. POST incidents/{id}/resolve (resolutionNote ile) -> Durum resolved, not kaydedilmiş
    """
    _, iid = route.open_incident(severity="high")
    r = api.post(f"incidents/{iid}/acknowledge", data={})
    assert r.ok, describe(r)
    inc = route.incident(iid, want=lambda i: i.get("status") == "acknowledged")
    assert inc.get("status") == "acknowledged" and inc.get("acknowledgedAt"), inc.get("status")
    r = api.post(f"incidents/{iid}/resolve", data={"resolutionNote": "otomasyon e2e"})
    assert r.ok, describe(r)
    inc = route.incident(iid, want=lambda i: i.get("status") == "resolved")
    print(f"[e2e] elle: acknowledged->resolved, not={inc.get('resolutionNote')!r}")
    assert inc.get("status") == "resolved"
    assert inc.get("resolutionNote") == "otomasyon e2e"


def test_invalid_webhook_token_rejected(anon_api, route):
    """Geçersiz webhook token'ıyla gelen olay kabul edilmez

    Adımlar:
    1. Token'ın son karakterlerini değiştirip olay gönder -> 4xx; incident açılmaz
    """
    bad = route.token[:-4] + ("0000" if not route.token.endswith("0000") else "1111")
    r = anon_api.post(f"webhooks/ingest/{bad}", data=route.event(f"e2e-{route.tag}-bad"))
    print(f"[e2e] geçersiz token: {describe(r)[:200]}")
    assert 400 <= r.status < 500, describe(r)


@known_bug(WH01)
@pytest.mark.parametrize("missing", ["eventId", "title", "severity", "status", "timestamp"])
def test_payload_without_required_field_rejected(anon_api, route, missing):
    """Zorunlu alanı eksik webhook gövdesi 4xx ile reddedilir, 5xx vermez

    Adımlar:
    1. Zorunlu alanlardan biri (eventId, title, severity, status, timestamp) olmadan olay gönder -> 4xx (ör. 422)
    """
    payload = route.event(f"e2e-{route.tag}-missing-{missing}")
    payload.pop(missing)
    r = anon_api.post(f"webhooks/ingest/{route.token}", data=payload)
    print(f"[e2e] {missing} yok: {describe(r)[:160]}")
    assert r.status < 500, describe(r)
    assert 400 <= r.status < 500, describe(r)
