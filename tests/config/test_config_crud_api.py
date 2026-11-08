"""API: yapılandırma kayıtlarının yaşam döngüsü ve doğrulamaları.

Teams, Schedules, Escalation Policies, Integrations, Escalation Routing ve Alert Rules için:
oluştur -> listede/aramada görünür -> getById aynı -> güncelle kalıcı -> sil -> 404 ve listede yok.
Kayıt adları `otomasyon` ile başlar; test sonunda silinir. Routing ve alert rule kayıtları pasif oluşturulur ve
koşulları hiçbir gerçek alarma uymaz (gerçek alarmları etkilemez). Bildirim hedefi gerekirse yalnız EA_NOTIFY_EMAIL.
"""
import pytest

from config import settings
from tests.e2e.helpers import automation_route, level, notify_user
from utils.api_client import body, describe
from utils.markers import known_bug
from utils.random_data import unique_name

pytestmark = pytest.mark.data_producing

NEVER = "otomasyon-hicbir-alarm-eslesmez"

CFG01 = "CFG-01: Routing kuralında 30 sn altındaki başlangıç gecikmesi (ör. 10 sn) API'de kabul ediliyor"
CFG02 = "CFG-02: Routing kuralında kullanılan escalation policy silinebiliyor; kural silinmiş policy'ye bağlı kalıyor"
CFG04 = "CFG-04: Entegrasyon API cevabındaki webhookUrl localhost:8000 adresini gösteriyor"
CFG03 = "CFG-03: Çizelge geçersiz saat dilimiyle (Mars/Olympus) oluşturulabiliyor"


def _ok(r) -> dict:
    assert r.ok, describe(r)
    return (body(r) or {}).get("data") or {}


def _items(r) -> list:
    d = (body(r) or {}).get("data")
    return d if isinstance(d, list) else (d or {}).get("items") or []


@pytest.fixture(scope="module")
def user(api) -> dict:
    return notify_user(api)


def _bodies(user_id: str) -> dict:
    """Kaynak -> (oluşturma gövdesi üreticisi, güncellenecek alanlar)."""
    return {
        "teams": (lambda n: {"name": n, "slug": n.replace("_", "-"), "description": "otomasyon",
                             "members": [{"userId": user_id, "role": "lead"}]}, {"description": "otomasyon güncel"}),
        "schedules": (lambda n: {"name": n, "description": "otomasyon", "timezone": "Europe/Istanbul",
                                 "rotationType": "weekly", "layers": [{"name": "L1", "priority": 0,
                                                                       "rotationUserIds": [user_id]}]},
                      {"description": "otomasyon güncel"}),
        "escalationPolicies": (lambda n: {"name": n, "description": "otomasyon", "isDefault": False,
                                          "levels": [level(1, user_id)]}, {"description": "otomasyon güncel"}),
        "integrations": (lambda n: {"name": n, "sourceType": "custom", "description": "otomasyon"},
                         {"description": "otomasyon güncel"}),
        "escalationRouting": (lambda n: {"name": n, "description": "otomasyon", "priority": 1000, "isActive": False,
                                         "conditions": [{"field": "title", "operator": "equals", "value": NEVER}]},
                              {"description": "otomasyon güncel"}),
        "alertRules": (lambda n: {"name": n, "description": "otomasyon", "priority": 999,
                                  "conditions": {"all": [{"field": "title", "operator": "equals", "value": NEVER}]},
                                  "actions": [{"type": "add_tags", "tags": {"otomasyon": "1"}}]},
                       {"description": "otomasyon güncel"}),
    }


RESOURCES = ["teams", "schedules", "escalationPolicies", "integrations", "escalationRouting", "alertRules"]


@pytest.mark.parametrize("res", RESOURCES)
def test_crud_lifecycle(api, user, res, soft):
    """Yapılandırma kaydı oluşturulur, listelenir, okunur, güncellenir ve silinir

    Teams, Schedules, Escalation Policies, Integrations, Escalation Routing ve Alert Rules ayrı ayrı denenir.

    Adımlar:
    1. POST ile otomasyon adlı kayıt oluştur -> 2xx; cevapta id ve ad
    2. GET liste (search=ad) -> Kayıt listede bir kez
    3. GET {id} -> Ad ve açıklama gönderilenle aynı
    4. PUT ile açıklamayı değiştir, tekrar oku -> Yeni açıklama kalıcı
    5. DELETE {id} -> 2xx; GET {id} 404; liste aramasında yok
    """
    make, change = _bodies(user["userId"])[res]
    name = unique_name()
    rec = _ok(api.post(res, data=make(name)))
    rid = rec.get("id")
    try:
        soft.check(bool(rid) and rec.get("name") == name, f"{res}: oluşturma cevabında id ve ad var ({rid})")
        listed = [x for x in _items(api.get(res, params={"search": name, "size": 50})) if x.get("id") == rid]
        soft.check(len(listed) == 1, f"{res}: aramada bir kez listelenir (bulunan {len(listed)})")
        got = _ok(api.get(f"{res}/{rid}"))
        soft.check(got.get("name") == name and got.get("description") == "otomasyon", f"{res}: getById ad ve açıklama aynı ({got.get('name')})")
        _ok(api.put(f"{res}/{rid}", data=change))
        got = _ok(api.get(f"{res}/{rid}"))
        soft.check(got.get("description") == change["description"], f"{res}: güncellenen açıklama kalıcı ({got.get('description')})")
        soft.check(got.get("name") == name, f"{res}: kısmi güncelleme adı korur ({got.get('name')})")
    finally:
        r = api.delete(f"{res}/{rid}")
        soft.check(r.ok, f"{res}: silme 2xx ({r.status})")
    r = api.get(f"{res}/{rid}")
    soft.check(r.status == 404, f"{res}: silinen kayıt okununca 404 ({r.status})")
    soft.check(not [x for x in _items(api.get(res, params={"search": name})) if x.get("id") == rid],
               f"{res}: silinen kayıt listede yok")
    soft.assert_all()


INVALID = [
    ("teams", {"name": "", "slug": "otomasyon-x"}, "boş ad"),
    ("teams", {"name": "otomasyon", "slug": "Büyük Harf ve Boşluk"}, "geçersiz slug"),
    ("teams", {"name": "x" * 256, "slug": "otomasyon-uzun"}, "256 karakter ad"),
    ("schedules", {"name": ""}, "boş ad"),
    pytest.param("schedules", {"name": "otomasyon-tz", "timezone": "Mars/Olympus"}, "geçersiz saat dilimi",
                 marks=known_bug(CFG03), id="schedules-geçersiz saat dilimi"),
    ("schedules", {"name": "otomasyon-rot", "rotationType": "monthly"}, "geçersiz rotasyon"),
    ("escalationPolicies", {"name": ""}, "boş ad"),
    ("escalationPolicies", {"name": "otomasyon-retry", "levels": [{"level": 1, "retryDelaySeconds": 5}]}, "retry 5 sn"),
    ("escalationPolicies", {"name": "otomasyon-retry", "levels": [{"level": 1, "retryDelaySeconds": 301}]}, "retry 301 sn"),
    ("escalationPolicies", {"name": "otomasyon-call", "levels": [{"level": 1, "callMaxRetries": 6}]}, "6 arama tekrarı"),
    ("escalationPolicies", {"name": "otomasyon-lvl", "levels": [{"level": 21}]}, "seviye 21"),
    ("integrations", {"name": "otomasyon-src", "sourceType": "bilinmeyen"}, "geçersiz kaynak tipi"),
    ("integrations", {"name": "", "sourceType": "custom"}, "boş ad"),
    ("escalationRouting", {"name": "otomasyon-p0", "priority": 0, "isActive": False,
                           "conditions": [{"field": "title", "operator": "equals", "value": NEVER}]}, "priority 0"),
    ("escalationRouting", {"name": "otomasyon-p1001", "priority": 1001, "isActive": False,
                           "conditions": [{"field": "title", "operator": "equals", "value": NEVER}]}, "priority 1001"),
    ("escalationRouting", {"name": "otomasyon-op", "isActive": False,
                           "conditions": [{"field": "title", "operator": "yok_boyle", "value": NEVER}]}, "geçersiz operatör"),
]
INVALID = [x if hasattr(x, "marks") else pytest.param(*x, id=f"{x[0]}-{x[2]}") for x in INVALID]


@pytest.mark.parametrize(("res", "payload", "case"), INVALID, )
def test_invalid_payload_rejected(api, res, payload, case):
    """Geçersiz yapılandırma gövdesi 4xx ile reddedilir ve kayıt oluşmaz

    Boş ad, sınır dışı uzunluk, geçersiz slug/saat dilimi/rotasyon/kaynak tipi, retry ve seviye sınırları,
    routing priority sınırları ve geçersiz operatör ayrı ayrı denenir.

    Adımlar:
    1. Geçersiz gövdeyle POST -> 4xx (ör. 422), 5xx değil; kayıt oluşmaz
    """
    r = api.post(res, data=payload)
    print(f"\n[doğrulama] {res} {case}: {describe(r)[:160]}")
    if r.ok:
        rid = (body(r).get("data") or {}).get("id")
        if rid:
            api.delete(f"{res}/{rid}")
    assert r.status < 500, describe(r)
    assert 400 <= r.status < 500, f"{res}: {case} kabul edildi ({r.status})"


@known_bug(CFG01)
def test_routing_initial_delay_minimum(api):
    """Routing kuralının başlangıç gecikmesi 0 ya da en az 30 sn olabilir (arayüzdeki kural)

    Adımlar:
    1. initialDelaySeconds=10 ile pasif kural oluştur -> 4xx
    2. initialDelaySeconds=0 ve 30 -> Kabul edilir (kayıtlar silinir)
    """
    results = {}
    for delay in (10, 0, 30):
        r = api.post("escalationRouting", data={"name": unique_name(), "priority": 1000, "isActive": False,
                                                "initialDelaySeconds": delay,
                                                "conditions": [{"field": "title", "operator": "equals", "value": NEVER}]})
        results[delay] = r.status
        if r.ok:
            api.delete(f"escalationRouting/{(body(r).get('data') or {}).get('id')}")
    print(f"\n[doğrulama] routing gecikme: {results}")
    assert 400 <= results[10] < 500, "10 sn gecikme kabul edildi (arayüz en az 30 sn diyor)"
    assert results[0] < 300 and results[30] < 300


def test_duplicate_team_slug_rejected(api):
    """Aynı slug ile ikinci ekip oluşturulamaz

    Adımlar:
    1. Ekip oluştur
    2. Aynı slug ile ikinci ekibi oluşturmayı dene -> 4xx (ör. 409); ilk ekip etkilenmez
    """
    name = unique_name()
    first = _ok(api.post("teams", data={"name": name, "slug": name}))
    try:
        r = api.post("teams", data={"name": name + "b", "slug": name})
        print(f"\n[doğrulama] aynı slug: {describe(r)[:160]}")
        if r.ok:
            api.delete(f"teams/{(body(r).get('data') or {}).get('id')}")
        assert 400 <= r.status < 500, describe(r)
    finally:
        api.delete(f"teams/{first['id']}")


def test_team_members_add_and_remove(api, user):
    """Ekibe üye eklenir ve çıkarılır

    Adımlar:
    1. Üyesiz ekip oluştur -> members boş
    2. POST teams/{id}/members ile test kullanıcısını ekle -> Ekipte 1 üye
    3. Üyeyi sil -> Ekip yine üyesiz
    """
    name = unique_name()
    team = _ok(api.post("teams", data={"name": name, "slug": name}))
    try:
        assert not team.get("members")
        _ok(api.post(f"teams/{team['id']}/members", data={"userId": user["userId"], "role": "member"}))
        members = _ok(api.get(f"teams/{team['id']}")).get("members") or []
        print(f"\n[ekip] üyeler: {[m.get('userId') == user['userId'] for m in members]}")
        assert len(members) == 1
        mid = members[0].get("id") or members[0].get("userId")
        assert api.delete(f"teams/{team['id']}/members/{mid}").ok
        assert not _ok(api.get(f"teams/{team['id']}")).get("members")
    finally:
        api.delete(f"teams/{team['id']}")


def test_schedule_on_call_now(api, user):
    """Tek kullanıcılı, 24 saat geçerli çizelgede nöbetçi o kullanıcıdır

    Adımlar:
    1. Tek katmanlı, tek kullanıcılı çizelge oluştur
    2. GET schedules/{id}/onCallNow -> onCallUsers'ta test kullanıcısı var
    """
    sched = _ok(api.post("schedules", data={"name": unique_name(), "timezone": "Europe/Istanbul", "rotationType": "weekly",
                                            "layers": [{"name": "L1", "priority": 0, "rotationUserIds": [user["userId"]]}]}))
    try:
        now = _ok(api.get(f"schedules/{sched['id']}/onCallNow"))
        ids = [p.get("userId") for p in now.get("onCallUsers") or []]
        print(f"\n[çizelge] nöbetçi: {[p.get('userName') for p in now.get('onCallUsers') or []]}")
        assert user["userId"] in ids, f"Nöbetçi test kullanıcısı değil: {now}"
    finally:
        api.delete(f"schedules/{sched['id']}")


@known_bug(CFG02)
def test_policy_in_use_by_routing_cannot_be_deleted(api, user):
    """Routing kuralında kullanılan policy silinmeye çalışılınca engellenir

    Adımlar:
    1. Policy ve onu kullanan pasif routing kuralı oluştur
    2. Policy'yi silmeyi dene -> 4xx (ör. 409) ve policy hâlâ okunabilir
    3. Önce kuralı, sonra policy'yi sil -> İkisi de silinir
    """
    pol = _ok(api.post("escalationPolicies", data={"name": unique_name(), "levels": [level(1, user["userId"])]}))
    rule = _ok(api.post("escalationRouting", data={"name": unique_name(), "priority": 1000, "isActive": False,
                                                   "escalationPolicyId": pol["id"],
                                                   "conditions": [{"field": "title", "operator": "equals", "value": NEVER}]}))
    try:
        r = api.delete(f"escalationPolicies/{pol['id']}")
        print(f"\n[policy] kullanımdayken silme: {describe(r)[:160]}")
        still = api.get(f"escalationPolicies/{pol['id']}").ok
        assert 400 <= r.status < 500 and still, "Routing kuralında kullanılan policy silindi"
    finally:
        api.delete(f"escalationRouting/{rule['id']}")
        api.delete(f"escalationPolicies/{pol['id']}")


def test_regenerated_webhook_token_invalidates_old(api, anon_api):
    """Token yenilenince eski webhook adresi olay kabul etmez

    Olay, otomasyon routing'ine bağlı entegrasyonla denenir: yanlışlıkla kabul edilse bile yalnız test kullanıcısına
    bildirim gider.

    Adımlar:
    1. Otomasyon düzenindeki entegrasyonun token'ını yenile -> Yeni token eskisinden farklı
    2. Eski token'la olay gönder -> 404; incident açılmaz
    """
    with automation_route(api, anon_api, lambda uid: [level(1, uid)]) as route:
        old = route.token
        new = _ok(api.post(f"integrations/{route.ids['integration']}/regenerateToken", data={})).get("webhookToken")
        assert new and new != old, "Token değişmedi"
        r = anon_api.post(f"webhooks/ingest/{old}", data=route.event())
        print(f"\n[entegrasyon] eski token: {describe(r)[:160]}")
        assert r.status == 404, describe(r)


@known_bug(CFG04)
def test_integration_webhook_url_uses_public_api(api):
    """Entegrasyon cevabındaki webhookUrl dışarıdan erişilebilen API adresini gösterir

    Adımlar:
    1. Custom entegrasyon oluştur -> webhookUrl alanı dolu
    2. webhookUrl'i kontrol et -> API adresi + /webhooks/ingest/<token>; localhost içermez (kayıt silinir)
    """
    rec = _ok(api.post("integrations", data={"name": unique_name(), "sourceType": "custom"}))
    try:
        url = rec.get("webhookUrl") or ""
        print(f"\n[entegrasyon] webhookUrl ana makinesi: {url.split('/api/')[0]}")
        assert url.startswith(settings.api_url) and "localhost" not in url, "webhookUrl genel API adresini göstermiyor"
        assert url.endswith(f"/webhooks/ingest/{rec.get('webhookToken')}")
    finally:
        api.delete(f"integrations/{rec['id']}")
