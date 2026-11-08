"""Arayüz: yapılandırma sayfalarındaki oluşturma diyalogları.

Kayıt arayüzden oluşturulur, API ile doğrulanır ve API ile silinir. Boş form gönderiminde istek gitmemesi beklenir.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from config import settings
from pages.sections import EscalationPoliciesPage, IntegrationsPage, SchedulesPage, TeamsPage
from utils.api_client import body
from utils.random_data import unique_name

OPEN_BTN = re.compile(r"^\s*(\+\s*)?(create|new|add)\b", re.I)
SUBMIT_BTN = re.compile(r"^\s*(create|save)\b", re.I)

UI_CASES = [
    (TeamsPage, "teams"),
    (IntegrationsPage, "integrations"),
    (EscalationPoliciesPage, "escalationPolicies"),
    (SchedulesPage, "schedules"),
]


def _open_dialog(page: Page, page_cls):
    page_cls(page).open()
    page.locator("main").get_by_role("button", name=OPEN_BTN).first.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def _name_field(dialog):
    """Ad alanı: etiketle bulunamazsa diyalogdaki ilk metin kutusu."""
    by_label = dialog.get_by_label(re.compile(r"name", re.I))
    if by_label.count():
        return by_label.first
    by_ph = dialog.get_by_placeholder(re.compile(r"name|ad", re.I))
    if by_ph.count():
        return by_ph.first
    return dialog.locator("input:not([type=hidden]):not([type=checkbox]):not([type=radio]), textarea").first


def _dump(dialog):
    """Hata ayıklama: diyalogdaki alanlar ve butonlar (değer yazdırılmaz)."""
    fields = dialog.locator("input, textarea, select, [role=combobox]").evaluate_all(
        "els => els.map(e => [e.tagName, e.type || '', e.id, e.name || '', e.placeholder || '',"
        " e.getAttribute('aria-label') || '', (e.labels && e.labels[0] && e.labels[0].innerText) || ''])")
    buttons = dialog.get_by_role("button").all_inner_texts()
    print(f"\n[ui] diyalog alanları: {fields}\n[ui] diyalog butonları: {buttons}")


def _close(page: Page):
    page.keyboard.press("Escape")


@pytest.mark.parametrize(("page_cls", "res"), UI_CASES, ids=[r for _, r in UI_CASES])
def test_empty_form_is_not_submitted(shared_page: Page, page_cls, res):
    """Oluşturma diyaloğu ad boşken gönderilmez

    Teams, Integrations, Escalation Policies ve Schedules sayfalarında ayrı ayrı denenir.

    Adımlar:
    1. Sayfayı aç ve oluşturma diyaloğunu aç -> Diyalog görünür, Name alanı boş
    2. Hiçbir alanı doldurmadan Create'e bas -> Oluşturma isteği gönderilmez; diyalog açık kalır ve hata/zorunlu alan uyarısı görünür
    """
    page = shared_page
    posts: list[str] = []
    handler = lambda req: posts.append(req.url) if req.method == "POST" and req.url.rstrip("/").endswith(f"/{res}") else None  # noqa: E731
    page.on("request", handler)
    try:
        dialog = _open_dialog(page, page_cls)
        expect(dialog.locator("input, textarea").first).to_be_visible(timeout=10000)
        expect(_name_field(dialog)).to_have_value("")
        submit = dialog.get_by_role("button", name=SUBMIT_BTN).last
        if submit.is_enabled():
            submit.click()
        page.wait_for_timeout(1500)
        assert not posts, f"Boş form için istek gönderildi: {posts}"
        expect(dialog).to_be_visible()
    finally:
        page.remove_listener("request", handler)
        _close(page)


@pytest.mark.data_producing
@pytest.mark.parametrize(("page_cls", "res"), UI_CASES[:2], ids=[r for _, r in UI_CASES[:2]])
def test_create_from_ui(shared_page: Page, api, page_cls, res):
    """Arayüzden oluşturulan kayıt listede görünür ve API ile okunabilir

    Teams ve Integrations (Custom kaynak tipi) sayfalarında ayrı ayrı denenir.

    Adımlar:
    1. Oluşturma diyaloğunu aç, Name alanına otomasyon adı yaz (gerekirse slug da) -> Alanlar dolu
    2. Create'e bas -> İstek 2xx döner, diyalog kapanır
       (Integrations: Webhook URL diyaloğu açılır, adres API adresi + yeni token; Close ile kapanır)
    3. Sayfadaki listeyi kontrol et -> Yeni kayıt adıyla görünür
    4. API'de adla ara -> Kayıt bulunur (test sonunda silinir)
    """
    page = shared_page
    name = unique_name()
    rid = None
    try:
        dialog = _open_dialog(page, page_cls)
        expect(dialog.locator("input, textarea").first).to_be_visible(timeout=10000)
        _dump(dialog)
        _name_field(dialog).fill(name)
        slug = dialog.get_by_label(re.compile(r"slug", re.I))
        if slug.count() and not slug.first.input_value():
            slug.first.fill(name)
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.rstrip("/").endswith(f"/{res}")) as info:
            dialog.get_by_role("button", name=SUBMIT_BTN).last.click()
        resp = info.value
        assert resp.ok, f"Oluşturma isteği {resp.status}"
        created = (resp.json() or {}).get("data") or {}
        rid = created.get("id")
        if res == "integrations":
            hook = page.get_by_role("dialog", name="Webhook URL")
            expect(hook).to_be_visible(timeout=10000)
            url = hook.get_by_role("textbox").first.input_value()
            assert created.get("webhookToken") and url.endswith(f"/webhooks/ingest/{created['webhookToken']}"), (
                "Webhook URL diyaloğundaki adres yeni entegrasyonun token'ını içermiyor")
            assert url.startswith(settings.api_url), "Webhook URL diyaloğundaki adres API adresiyle başlamıyor"
            hook.get_by_role("button", name="Close").first.click()
        expect(page.get_by_role("dialog")).to_have_count(0, timeout=10000)
        expect(page.locator("main").get_by_text(name).first).to_be_visible(timeout=10000)
        found = [x for x in (body(api.get(res, params={"search": name})) or {}).get("data") or [] if x.get("name") == name]
        assert found, "Kayıt API'de bulunamadı"
        rid = rid or found[0]["id"]
    finally:
        if page.get_by_role("dialog").count():
            _close(page)
        if not rid:
            found = [x for x in (body(api.get(res, params={"search": name})) or {}).get("data") or [] if x.get("name") == name]
            rid = found[0]["id"] if found else None
        if rid:
            print(f"\n[ui] temizlik {res}: {api.delete(f'{res}/{rid}').status}")
