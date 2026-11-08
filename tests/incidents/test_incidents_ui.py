"""Arayüz: Incidents listesi (arama, filtreler) ve detay sayfası (not, Acknowledge, Resolve).

Incident'lar otomasyon düzeninde (tests/e2e/helpers.py, yalnız EA_NOTIFY_EMAIL'e bildirim) webhook ile açılır;
arayüzde yapılan işlemin sonucu API'den doğrulanır. Modül sonunda açık kalanlar çözülür ve kurulum silinir.
"""
import re
import uuid

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import automation_route, level

pytestmark = [pytest.mark.ui, pytest.mark.data_producing]


@pytest.fixture(scope="module")
def route(api, anon_api):
    with automation_route(api, anon_api, lambda uid: [level(1, uid)]) as r:
        yield r


@pytest.fixture(scope="module")
def incident(route) -> dict:
    """Listeleme/filtre testlerinin paylaştığı triggered + critical incident."""
    event_id, inc_id = route.open_incident()
    inc = route.incident(inc_id)
    return {"id": inc_id, "title": inc.get("title"), "number": inc.get("incidentNumber"), "event_id": event_id}


def _row(page: Page, inc_id: str):
    return page.locator(f"main a[href='/incidents/{inc_id}']").first


def _is_list_request(r) -> bool:
    return r.request.method == "GET" and re.search(r"/api/v1/incidents\?", r.url) is not None


def _search(page: Page, text: str) -> str:
    """Listeyi açar, arama kutusuna yazar; giden liste isteğinin sorgu kısmını döner."""
    page.goto("/incidents")
    box = page.get_by_placeholder("Search incidents...")
    expect(box).to_be_visible(timeout=20000)
    with page.expect_response(lambda r: _is_list_request(r) and "search=" in r.url, timeout=15000) as info:
        box.fill(text)
    return info.value.url.split("?", 1)[1]


def _filter(page: Page, name: str, option: str) -> str:
    """Filtre açılır panelinden seçenek seçer; giden liste isteğinin sorgu kısmını döner."""
    page.locator("main").get_by_role("button", name=name, exact=True).click()
    pop = page.get_by_role("dialog").last
    expect(pop).to_be_visible(timeout=5000)
    opt = pop.get_by_role("option", name=re.compile(option, re.I))
    if not opt.count():
        opt = pop.get_by_role("checkbox", name=re.compile(option, re.I))
    if not opt.count():
        opt = pop.get_by_text(re.compile(rf"^\s*{option}\s*$", re.I))
    if not opt.count():
        print(f"\n[ui] '{name}' paneli: {pop.inner_text()[:400]!r}")
    with page.expect_response(lambda r: _is_list_request(r) and f"{name.lower()}=" in r.url.lower(),
                              timeout=15000) as info:
        opt.first.click()
        apply = pop.get_by_role("button", name=re.compile(r"^apply", re.I))
        if apply.count():
            apply.first.click()
    page.keyboard.press("Escape")
    return info.value.url.split("?", 1)[1]


def test_search_finds_incident(shared_page: Page, incident, route):
    """Arama kutusu incident'ı başlığa göre bulur ve yalnız eşleşenleri listeler

    Adımlar:
    1. Incidents sayfasında arama kutusuna otomasyon etiketini yaz -> Liste isteği search parametresiyle gider
    2. Listeye bak -> Otomasyon incident'ı numarası ve başlığıyla görünür; diğer satırların hepsi etiketi içerir
    """
    page = shared_page
    query = _search(page, route.tag)
    assert f"search={route.tag}" in query, query
    expect(_row(page, incident["id"])).to_be_visible(timeout=15000)
    row = page.locator("main tr, main [role=row]").filter(has=_row(page, incident["id"])).first
    expect(row).to_contain_text(f"#{incident['number']}")
    expect(row).to_contain_text(incident["title"])
    rows = page.locator("main tr, main [role=row]").filter(has=page.locator("a[href^='/incidents/']"))
    for text in rows.all_inner_texts():
        assert route.tag in text, f"Aramayla ilgisiz satır listelendi: {text[:80]!r}"


def test_search_without_match_shows_no_rows(shared_page: Page):
    """Hiçbir incident'a uymayan aramada liste boş kalır

    Adımlar:
    1. Arama kutusuna var olmayan bir metin yaz -> Liste isteği gider
    2. Listeye bak -> Hiç incident satırı yok; sayfa hata vermez
    """
    page = shared_page
    _search(page, f"otomasyon-yok-{uuid.uuid4().hex[:8]}")
    page.wait_for_timeout(1000)
    expect(page.locator("main a[href^='/incidents/']")).to_have_count(0)
    expect(page.get_by_role("heading", name="Incidents")).to_be_visible()


@pytest.mark.parametrize(("flt", "match", "miss"), [("Status", "Triggered", "Resolved"),
                                                    ("Severity", "Critical", "Info")])
def test_filter_narrows_list(shared_page: Page, incident, route, flt, match, miss):
    """Filtre seçimi listeyi daraltır: uyan değerde incident görünür, uymayanda görünmez

    Status (Triggered / Resolved) ve Severity (Critical / Info) filtreleri ayrı ayrı denenir.

    Adımlar:
    1. Otomasyon etiketiyle ara -> Incident görünür
    2. Filtrede incident'a uymayan değeri seç -> İstek filtre parametresiyle gider; incident listede yok
    3. Sayfayı yeniden aç, ara ve uyan değeri seç -> İstek filtre parametresiyle gider; incident listede
    """
    page = shared_page
    _search(page, route.tag)
    expect(_row(page, incident["id"])).to_be_visible(timeout=15000)
    query = _filter(page, flt, miss)
    assert miss.lower() in query.lower(), query
    expect(_row(page, incident["id"])).to_be_hidden(timeout=10000)
    _search(page, route.tag)
    query = _filter(page, flt, match)
    assert match.lower() in query.lower(), query
    expect(_row(page, incident["id"])).to_be_visible(timeout=10000)


def test_row_opens_detail(shared_page: Page, incident, route):
    """Listedeki satıra tıklayınca incident detay sayfası açılır

    Adımlar:
    1. Etiketle ara ve incident satırına tıkla -> Adres /incidents/<id>
    2. Detay sayfasına bak -> Başlık incident başlığı; Acknowledge, Assign, Escalate, Resolve butonları ve not alanı görünür
    """
    page = shared_page
    _search(page, route.tag)
    _row(page, incident["id"]).click()
    expect(page).to_have_url(re.compile(rf"/incidents/{incident['id']}$"))
    expect(page.locator("main").get_by_role("heading", name=incident["title"])).to_be_visible(timeout=15000)
    for name in ("Acknowledge", "Assign", "Escalate", "Resolve"):
        expect(page.get_by_role("button", name=name, exact=True)).to_be_visible()
    expect(page.get_by_placeholder("Add a note...")).to_be_visible()


def test_add_note(shared_page: Page, api, incident):
    """Detay sayfasından not eklenir; not boşken Add pasiftir

    Adımlar:
    1. Incident detayını aç -> Not alanı boş, Add butonu pasif
    2. Not yaz -> Add aktif olur
    3. Add'e bas -> POST notes 2xx; not metni sayfada görünür, alan temizlenir
    4. Sayfayı yenile -> Not hâlâ görünür
    """
    page = shared_page
    page.goto(f"/incidents/{incident['id']}")
    box = page.get_by_placeholder("Add a note...")
    add = page.get_by_role("button", name="Add", exact=True)
    expect(box).to_be_visible(timeout=20000)
    expect(add).to_be_disabled()
    note = f"otomasyon notu {uuid.uuid4().hex[:6]}"
    box.fill(note)
    expect(add).to_be_enabled()
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/notes")) as info:
        add.click()
    assert info.value.ok, f"Not isteği {info.value.status}"
    expect(page.locator("main").get_by_text(note)).to_be_visible(timeout=10000)
    expect(box).to_have_value("")
    page.reload()
    expect(page.locator("main").get_by_text(note)).to_be_visible(timeout=20000)


def test_acknowledge_from_detail(shared_page: Page, route):
    """Detay sayfasındaki Acknowledge incident'ı onaylar

    Adımlar:
    1. Yeni otomasyon incident'ının detayını aç -> Acknowledge butonu görünür
    2. Acknowledge'a bas -> İstek 2xx; API'de durum acknowledged, onaylayan dolu
    3. Sayfaya bak -> Acknowledge butonu artık görünmez ya da pasif; Resolve hâlâ kullanılabilir
    """
    page = shared_page
    _, inc_id = route.open_incident()
    page.goto(f"/incidents/{inc_id}")
    ack = page.get_by_role("button", name="Acknowledge", exact=True)
    expect(ack).to_be_visible(timeout=20000)
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/acknowledge")) as info:
        ack.click()
    assert info.value.ok, f"Acknowledge isteği {info.value.status}"
    inc = route.incident(inc_id, want=lambda i: i.get("status") == "acknowledged")
    assert inc.get("status") == "acknowledged", inc.get("status")
    expect(ack.and_(page.locator(":enabled"))).to_have_count(0, timeout=10000)
    expect(page.get_by_role("button", name="Resolve", exact=True)).to_be_enabled()


def test_resolve_with_note_from_detail(shared_page: Page, route):
    """Detay sayfasındaki Resolve diyaloğu çözüm notuyla incident'ı çözer

    Adımlar:
    1. Yeni otomasyon incident'ının detayını aç ve Resolve'a bas -> Çözüm diyaloğu açılır
    2. Çözüm notunu yaz ve onayla -> İstek 2xx; diyalog kapanır
    3. API'den incident'ı oku -> Durum resolved, resolutionNote yazılan not
    """
    page = shared_page
    _, inc_id = route.open_incident()
    page.goto(f"/incidents/{inc_id}")
    page.get_by_role("button", name="Resolve", exact=True).click()
    dialog = page.get_by_role("dialog").last
    expect(dialog).to_be_visible(timeout=10000)
    note = f"otomasyon çözüm {uuid.uuid4().hex[:6]}"
    field = dialog.locator("textarea, input[type=text]")
    if field.count():
        field.first.fill(note)
    else:
        print(f"\n[ui] Resolve diyaloğunda not alanı yok: {dialog.inner_text()[:300]!r}")
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/resolve")) as info:
        dialog.get_by_role("button", name=re.compile(r"resolve", re.I)).last.click()
    assert info.value.ok, f"Resolve isteği {info.value.status}"
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=10000)
    inc = route.incident(inc_id, want=lambda i: i.get("status") == "resolved")
    assert inc.get("status") == "resolved", inc.get("status")
    if field.count():
        assert inc.get("resolutionNote") == note, f"resolutionNote: {inc.get('resolutionNote')!r}"


def test_list_reflects_status_change(shared_page: Page, api, route):
    """API ile çözülen incident listede Resolved durumuyla görünür

    Adımlar:
    1. Yeni otomasyon incident'ı aç ve API ile çöz
    2. Etiketle ara -> Incident satırının STATUS sütununda Resolved yazar
    """
    page = shared_page
    _, inc_id = route.open_incident()
    assert api.post(f"incidents/{inc_id}/resolve", data={"resolutionNote": "otomasyon"}).ok
    route.incident(inc_id, want=lambda i: i.get("status") == "resolved")
    _search(page, route.tag)
    row = page.locator("main tr, main [role=row]").filter(has=page.locator(f"a[href='/incidents/{inc_id}']")).first
    expect(row).to_contain_text(re.compile("resolved", re.I), timeout=15000)


