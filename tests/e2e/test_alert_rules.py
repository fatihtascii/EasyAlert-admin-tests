"""Uçtan uca Alert Rules: gelen alarmı bastırma, öncelik/etiket/alan değiştirme, kural sırası ve Stop Processing.

Kurallar tenant genelinde çalıştığı için her kuralın koşulu yalnız bu çalışmanın olaylarını yakalar
(title contains "<çalışma etiketi>-<senaryo>"); kurallar test sonunda silinir. Olaylar automation_route ile
yalnız test kullanıcısına bildirilen otomasyon policy'sine yönlenir.

Aksiyon tipi adları API şemasında listelenmediği için ilk kullanımda aday adlarla denenir (ör. set_priority,
setPriority); API'nin kabul ettiği ad çıktıda yazar.
"""
import pytest

from tests.e2e.helpers import automation_route, data, level
from utils.api_client import body, describe
from utils.markers import known_bug
from utils.random_data import unique_name

pytestmark = [pytest.mark.e2e, pytest.mark.data_producing]

AR01 = ("AR-01: Alert rule'un Set Priority, Add Tags ve Set Field aksiyonları kaydediliyor ama kurala uyan alarmdan "
        "açılan incident'a uygulanmıyor (öncelik boş, etiket eklenmiyor, alan değişmiyor); aynı koşulla Suppress çalışıyor")
ACTION_CANDIDATES = {
    "suppress": ["suppress", "drop"],
    "set_priority": ["set_priority", "setPriority"],
    "add_tags": ["add_tags", "addTags"],
    "set_field": ["set_field", "setField"],
}


@pytest.fixture(scope="module")
def route(api, anon_api):
    with automation_route(api, anon_api, lambda uid: [level(1, uid)]) as r:
        yield r


@pytest.fixture(scope="module")
def rules(api):
    """Kural oluşturucu; oluşturulan tüm kuralları sonda siler."""
    created: list[str] = []

    def make(scenario_key: str, actions: list, priority: int = 1, stop: bool = False, logic: str = "all") -> dict:
        payload = {"name": unique_name(), "description": "otomasyon e2e (test sonunda silinir)", "priority": priority,
                   "stopProcessing": stop,
                   "conditions": {logic: [{"field": "title", "operator": "contains", "value": scenario_key}]},
                   "actions": actions}
        r = api.post("alertRules", data=payload)
        rule = data(r)
        created.append(rule["id"])
        saved = data(api.get(f"alertRules/{rule['id']}")) or {}
        print(f"[kural] kaydedilen aksiyonlar: {saved.get('actions')} aktif={saved.get('isActive')}")
        return rule

    yield make
    for rid in created:
        print(f"\n[kural] temizlik: {api.delete(f'alertRules/{rid}').status}")


def _action(api, kind: str, **fields) -> dict:
    """Aksiyonun API'nin kabul ettiği tip adıyla gövdesi (aday adları zararsız bir kuralla dener)."""
    cache = _action.__dict__.setdefault("cache", {})
    if kind not in cache:
        for cand in ACTION_CANDIDATES[kind]:
            r = api.post("alertRules", data={"name": unique_name(), "priority": 999,
                                             "conditions": {"all": [{"field": "title", "operator": "equals",
                                                                     "value": "otomasyon-hicbir-alarm-eslesmez"}]},
                                             "actions": [{"type": cand, **fields}]})
            if r.ok:
                rid = (body(r).get("data") or {}).get("id")
                if rid:
                    api.delete(f"alertRules/{rid}")
                cache[kind] = cand
                break
            print(f"[kural] '{cand}' kabul edilmedi: {describe(r)[:200]}")
        print(f"[kural] {kind} aksiyon tipi: {cache.get(kind)}")
        assert kind in cache, f"{kind} için kabul edilen aksiyon tipi bulunamadı: {ACTION_CANDIDATES[kind]}"
    return {"type": cache[kind], **fields}


def _scenario(route, name: str) -> str:
    return f"{route.tag}-{name}"


def test_suppress_rule_drops_alert(api, route, rules):
    """Suppress aksiyonlu kurala uyan alarm incident açmaz; uymayan benzer alarm açar

    Adımlar:
    1. Başlığı "<etiket>-suppress" içeren alarmları bastıran kural oluştur
    2. Kurala uyan problem olayı gönder -> Webhook 200; incident açılmaz (incidentCreated=false, incidentId yok)
    3. Kurala uymayan bir olay gönder -> Incident açılır
    """
    key = _scenario(route, "suppress")
    rules(key, [_action(api, "suppress")])
    res = route.send(route.event(f"e2e-{key}"))
    print(f"[kural] suppress: status={res.get('status')} incidentCreated={res.get('incidentCreated')} action={res.get('incidentAction')}")
    assert res.get("incidentCreated") is not True and not res.get("incidentId"), f"Bastırılan alarm incident açtı: {res}"
    _, iid = route.open_incident()
    assert iid


@known_bug(AR01)
def test_set_priority_rule(api, route, rules):
    """Set Priority aksiyonu incident'ın önceliğini değiştirir

    Adımlar:
    1. Başlığı "<etiket>-prio" içeren alarmların önceliğini P2 yapan kural oluştur
    2. Kurala uyan problem olayı gönder -> Incident açılır; priority P2
    """
    key = _scenario(route, "prio")
    rules(key, [_action(api, "set_priority", priority="P2", value="P2")])
    _, iid = route.open_incident(event_id=f"e2e-{key}")
    inc = route.incident(iid)
    print(f"[kural] set_priority: priority={inc.get('priority')}")
    assert inc.get("priority") == "P2", f"Öncelik P2 olmadı: {inc.get('priority')}"


@known_bug(AR01)
def test_add_tags_rule(api, route, rules):
    """Add Tags aksiyonu incident'a etiket ekler, olaydaki etiketleri korur

    Adımlar:
    1. Başlığı "<etiket>-tags" içeren alarmlara {"otomasyon": "evet"} etiketi ekleyen kural oluştur
    2. Kurala uyan problem olayı gönder -> Incident etiketlerinde otomasyon=evet ve olaydaki automation etiketi var
    """
    key = _scenario(route, "tags")
    rules(key, [_action(api, "add_tags", tags={"otomasyon": "evet"})])
    _, iid = route.open_incident(event_id=f"e2e-{key}")
    tags = route.incident(iid).get("tags") or {}
    print(f"[kural] add_tags: tags={tags}")
    assert tags.get("otomasyon") == "evet", f"Etiket eklenmedi: {tags}"
    assert tags.get("automation") == route.tag, f"Olaydaki etiket kayboldu: {tags}"


@known_bug(AR01)
def test_set_field_rule(api, route, rules):
    """Set Field aksiyonu incident alanının değerini değiştirir

    Adımlar:
    1. Başlığı "<etiket>-field" içeren alarmların service alanını "otomasyon-set-field" yapan kural oluştur
    2. Kurala uyan problem olayı gönder -> Incident'ın service alanı "otomasyon-set-field"
    """
    key = _scenario(route, "field")
    rules(key, [_action(api, "set_field", field="service", value="otomasyon-set-field")])
    _, iid = route.open_incident(event_id=f"e2e-{key}")
    inc = route.incident(iid)
    print(f"[kural] set_field: service={inc.get('service')}")
    assert inc.get("service") == "otomasyon-set-field", f"Alan değişmedi: {inc.get('service')}"


@known_bug(AR01)
def test_rule_priority_and_stop_processing(api, route, rules):
    """Kurallar priority sırasıyla uygulanır; Stop Processing açık kural sonrakileri durdurur

    Adımlar:
    1. Aynı alarma uyan iki kural oluştur: priority 10 (etiket a=1, Stop Processing açık), priority 20 (etiket b=1)
    2. Alarm gönder -> Incident'ta a=1 var, b yok
    3. İlk kuralda Stop Processing'i kapat (PUT) ve yeni alarm gönder -> Incident'ta hem a=1 hem b=1 var
    """
    key = _scenario(route, "order")
    first = rules(key, [_action(api, "add_tags", tags={"a": "1"})], priority=10, stop=True)
    rules(key, [_action(api, "add_tags", tags={"b": "1"})], priority=20)
    _, iid = route.open_incident(event_id=f"e2e-{key}-1")
    tags1 = route.incident(iid).get("tags") or {}
    r = api.put(f"alertRules/{first['id']}", data={"stopProcessing": False})
    assert r.ok, describe(r)
    _, iid2 = route.open_incident(event_id=f"e2e-{key}-2")
    tags2 = route.incident(iid2).get("tags") or {}
    print(f"[kural] stop açık: {tags1} | stop kapalı: {tags2}")
    assert tags1.get("a") == "1" and "b" not in tags1, f"Stop Processing sonraki kuralı durdurmadı: {tags1}"
    assert tags2.get("a") == "1" and tags2.get("b") == "1", f"İki kural birlikte uygulanmadı: {tags2}"


def test_inactive_rule_not_applied(api, route, rules):
    """Pasif kural alarmları etkilemez

    Adımlar:
    1. Başlığı "<etiket>-inactive" içeren alarmları bastıran kural oluştur ve pasifleştir (isActive=false)
    2. Kurala uyan olay gönder -> Alarm bastırılmaz; incident açılır
    """
    key = _scenario(route, "inactive")
    rule = rules(key, [_action(api, "suppress")])
    r = api.put(f"alertRules/{rule['id']}", data={"isActive": False})
    assert r.ok, describe(r)
    _, iid = route.open_incident(event_id=f"e2e-{key}")
    assert iid, "Pasif kural alarmı bastırdı"


@pytest.mark.parametrize(("case", "payload"), [
    ("ad yok", {"conditions": {"all": [{"field": "title", "operator": "equals", "value": "x"}]}, "actions": []}),
    ("geçersiz operatör", {"name": "otomasyon-gecersiz", "conditions": {"all": [{"field": "title", "operator": "yok_boyle",
                                                                                "value": "x"}]}, "actions": []}),
    ("koşul alanı eksik", {"name": "otomasyon-gecersiz", "conditions": {"all": [{"operator": "equals", "value": "x"}]},
                           "actions": []}),
], ids=["ad-yok", "gecersiz-operator", "alan-eksik"])
def test_invalid_rule_rejected(api, case, payload):
    """Geçersiz alert rule gövdesi 4xx ile reddedilir, kayıt oluşmaz

    Adımlar:
    1. Adsız, geçersiz operatörlü ya da koşul alanı eksik kural gönder -> 4xx (ör. 422), 5xx değil
    """
    r = api.post("alertRules", data=payload)
    print(f"[kural] {case}: {describe(r)[:160]}")
    if r.ok:  # yanlışlıkla oluştuysa temizle
        api.delete(f"alertRules/{(body(r).get('data') or {}).get('id')}")
    assert 400 <= r.status < 500, describe(r)
