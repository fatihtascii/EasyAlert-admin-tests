"""Uçtan uca eskalasyon: seviye geçişi, onayla durma, elle eskalasyon ve routing başlangıç gecikmesi.

İki seviyeli policy (L1 hemen, L2 1 dk sonra); iki seviyenin hedefi de EA_NOTIFY_EMAIL kullanıcısı, kanal e-posta.
Seviye, bildirim kaydındaki escalationLevel ve incident'ın currentLevel alanından okunur. Testler gerçek süre
bekler (her biri ~1-2 dk). Düzen tests/e2e/helpers.py'deki automation_route ile kurulur ve sonda silinir.
"""
import time

import pytest

from tests.e2e.helpers import automation_route, level
from utils.markers import known_bug

pytestmark = [pytest.mark.e2e, pytest.mark.data_producing]

L2_DELAY_MIN = 1
WAIT_L2_S = 150  # L2 gecikmesi (60 sn) + zamanlayıcı aralığı payı
INITIAL_DELAY_S = 30
ESC01 = ("EE-5 (ESC-01): Elle Escalate işlemi incident'ı 2. seviyeye taşıyor (currentLevel=2) ama 2. seviye hedeflerine "
         "bildirim göndermiyor; otomatik eskalasyonda aynı hedefe L2 bildirimi gidiyor")


def _levels(logs: list) -> set:
    return {n.get("escalationLevel") for n in logs}


@pytest.fixture(scope="module")
def two_levels(api, anon_api):
    with automation_route(api, anon_api, lambda uid: [level(1, uid), level(2, uid, L2_DELAY_MIN)]) as r:
        yield r


@pytest.fixture(scope="module")
def delayed(api, anon_api):
    with automation_route(api, anon_api, lambda uid: [level(1, uid)], initial_delay_s=INITIAL_DELAY_S) as r:
        yield r


def test_unacknowledged_incident_escalates_to_level_2(two_levels):
    """Onaylanmayan incident, seviye gecikmesi dolunca 2. seviyeye eskale olur ve L2 hedefine bildirim gider

    Adımlar:
    1. İki seviyeli policy'ye düşen problem olayı gönder -> Incident açılır, currentLevel 1, L1 bildirimi gider
    2. Onaylamadan ~1 dk bekle -> currentLevel 2 olur
    3. Bildirim kayıtlarına bak -> escalationLevel 2 olan kayıt vardır
    """
    _, iid = two_levels.open_incident()
    l1 = two_levels.notifications(iid, want=lambda ls: 1 in _levels(ls))
    assert 1 in _levels(l1), f"L1 bildirimi oluşmadı: {l1}"
    inc = two_levels.incident(iid, want=lambda i: (i.get("currentLevel") or 0) >= 2, timeout_s=WAIT_L2_S)
    logs = two_levels.notifications(iid, want=lambda ls: 2 in _levels(ls), timeout_s=30)
    print(f"[eskalasyon] currentLevel={inc.get('currentLevel')} seviyeler={sorted(x for x in _levels(logs) if x)}")
    assert inc.get("currentLevel") == 2, f"{WAIT_L2_S} sn içinde 2. seviyeye geçmedi (currentLevel={inc.get('currentLevel')})"
    assert 2 in _levels(logs), "2. seviye bildirimi gönderilmedi"


def test_acknowledge_stops_escalation(api, two_levels):
    """Onaylanan incident 2. seviyeye eskale olmaz

    Adımlar:
    1. Problem olayı gönder ve L1 bildirimi gelince incident'ı onayla -> Durum acknowledged
    2. L2 gecikmesinden uzun bekle -> currentLevel 1'de kalır; escalationLevel 2 bildirimi yoktur
    """
    _, iid = two_levels.open_incident()
    two_levels.notifications(iid, want=lambda ls: 1 in _levels(ls))
    assert api.post(f"incidents/{iid}/acknowledge", data={}).ok
    time.sleep(L2_DELAY_MIN * 60 + 45)
    inc = two_levels.incident(iid)
    logs = two_levels.notifications(iid, timeout_s=1)
    print(f"[eskalasyon] onay sonrası currentLevel={inc.get('currentLevel')} seviyeler={sorted(x for x in _levels(logs) if x)}")
    assert inc.get("status") == "acknowledged"
    assert inc.get("currentLevel") == 1, f"Onaylanan incident eskale oldu (currentLevel={inc.get('currentLevel')})"
    assert 2 not in _levels(logs), "Onaydan sonra 2. seviye bildirimi gitti"


@known_bug(ESC01)
def test_manual_escalate_moves_to_next_level(api, two_levels):
    """Escalate işlemi incident'ı beklemeden bir sonraki seviyeye taşır

    Adımlar:
    1. Problem olayı gönder -> Incident L1'de
    2. POST incidents/{id}/escalate (not ile) -> currentLevel 2 olur
    3. Bildirim kayıtlarına bak -> escalationLevel 2 bildirimi gönderilmiştir
    """
    _, iid = two_levels.open_incident(severity="high")
    two_levels.notifications(iid, want=lambda ls: 1 in _levels(ls))
    r = api.post(f"incidents/{iid}/escalate", data={"note": "otomasyon elle eskalasyon"})
    assert r.ok, r.text()[:200]
    inc = two_levels.incident(iid, want=lambda i: (i.get("currentLevel") or 0) >= 2)
    logs = two_levels.notifications(iid, want=lambda ls: 2 in _levels(ls), timeout_s=90)
    print(f"[eskalasyon] elle: currentLevel={inc.get('currentLevel')} seviyeler={sorted(x for x in _levels(logs) if x)}")
    assert inc.get("currentLevel") == 2
    assert 2 in _levels(logs), "Elle eskalasyondan sonra 2. seviye bildirimi gitmedi"


def test_initial_delay_holds_notifications(delayed):
    """Routing kuralının başlangıç gecikmesi boyunca bildirim gönderilmez, süre dolunca gönderilir

    Adımlar:
    1. Başlangıç gecikmesi 30 sn olan kurala düşen olay gönder -> Incident açılır; escalationDelayed ve
       escalationStartsAt dolu
    2. 15 sn sonra bildirimlere bak -> Henüz bildirim yok
    3. Gecikme dolunca bak -> L1 bildirimi gönderilmiştir
    """
    _, iid = delayed.open_incident()
    inc = delayed.incident(iid)
    print(f"[gecikme] escalationDelayed={inc.get('escalationDelayed')} escalationStartsAt={inc.get('escalationStartsAt')}")
    assert inc.get("escalationDelayed") is True or inc.get("escalationStartsAt"), "Incident gecikmeli görünmüyor"
    time.sleep(15)
    early = delayed.notifications(iid, timeout_s=1)
    assert not early, f"Gecikme dolmadan bildirim gitti: {early}"
    logs = delayed.notifications(iid, timeout_s=INITIAL_DELAY_S + 60)
    assert logs, "Gecikme dolduktan sonra bildirim gitmedi"


def test_resolved_within_initial_delay_sends_nothing(delayed):
    """Başlangıç gecikmesi içinde kaynakta düzelen alarm hiç bildirim göndermez

    Adımlar:
    1. Başlangıç gecikmesi 30 sn olan kurala düşen problem olayı gönder -> Incident açılır
    2. 5 sn içinde aynı eventId ile ok olayı gönder -> Incident resolved
    3. Gecikmenin bitiminden 30 sn sonrasına kadar bekle -> Hiç bildirim kaydı oluşmaz
    """
    event_id, iid = delayed.open_incident()
    time.sleep(5)
    delayed.send(delayed.event(event_id, status="ok", severity="ok"))
    inc = delayed.incident(iid, want=lambda i: i.get("status") == "resolved")
    assert inc.get("status") == "resolved"
    time.sleep(INITIAL_DELAY_S + 30)
    logs = delayed.notifications(iid, timeout_s=1)
    print(f"[gecikme] gecikme içinde çözülen incident bildirimleri: {len(logs)}")
    assert not logs, f"Gecikme içinde çözülen alarm için bildirim gitti: {logs}"
