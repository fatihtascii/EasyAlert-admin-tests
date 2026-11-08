"""Smoke: giriş yapılmış kullanıcı menüdeki her sayfayı açabilir (salt okuma)."""
import pytest
from playwright.sync_api import Browser, Page, expect

from config import settings
from pages.sections import SIDEBAR_PAGES

pytestmark = pytest.mark.smoke


def test_logged_out_user_sees_login(browser: Browser):
    """Oturumu olmayan kullanıcı uygulamayı açınca giriş formunu görür

    Adımlar:
    1. Çerezsiz yeni bir tarayıcıda /incidents adresini aç -> Şifre alanı olan giriş formu görünür
    """
    ctx = browser.new_context(base_url=settings.base_url)
    try:
        page = ctx.new_page()
        page.goto("/incidents")
        expect(page.locator("input[type=password]").first).to_be_visible(timeout=30000)
    finally:
        ctx.close()


@pytest.mark.parametrize("page_cls", SIDEBAR_PAGES, ids=lambda c: c.__name__.removesuffix("Page"))
def test_sidebar_page_opens(shared_page: Page, page_cls):
    """Sol menüdeki sayfa doğru adres ve başlıkla açılır

    Dashboard, Incidents, Postmortems, Synthetics, Teams, Schedules, Escalation Policies, Integrations, Alert Rules,
    Escalation Routing, Settings, Users, Groups, Roles, Organization, Usage & Billing ve Subscription ayrı ayrı denenir.

    Adımlar:
    1. Dashboard'a git -> Sol menü görünür
    2. Menüden sayfanın bağlantısına tıkla -> Doğru adrese gidilir ve sayfa başlığı görünür
    """
    page_cls(shared_page).go_home().open_from_sidebar()
