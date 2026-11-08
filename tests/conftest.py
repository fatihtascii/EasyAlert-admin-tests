"""Ortak fixture'lar: giriş yapılmış paylaşılan sekme, API bağlamları ve otomatik işaretler."""
from collections.abc import Generator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright

from config import settings
from pages.login_page import LoginPage
from utils.api_client import API_PREFIX, capture_auth_headers
from utils.soft_checks import SoftChecks

TESTS_DIR = Path(__file__).parent
AUTH_STATE = Path(".auth/state.json")


def pytest_collection_modifyitems(config, items):
    for item in items:
        rel = Path(item.fspath).relative_to(TESTS_DIR)
        item.add_marker(pytest.mark.api if rel.parts[0] == "api" else pytest.mark.ui)


@pytest.fixture(scope="session")
def base_url():
    return settings.base_url


@pytest.fixture(scope="session")
def auth_state(browser: Browser) -> str:
    """Oturum boyunca bir kez giriş yapılır; çerez/depolama durumu .auth/state.json'a yazılır."""
    ctx = browser.new_context(base_url=settings.base_url)
    page = ctx.new_page()
    LoginPage(page).open().login_and_wait(settings.email, settings.password)
    AUTH_STATE.parent.mkdir(exist_ok=True)
    ctx.storage_state(path=str(AUTH_STATE))
    ctx.close()
    return str(AUTH_STATE)


@pytest.fixture(scope="module")
def shared_page(browser: Browser, auth_state) -> Generator[Page, None, None]:
    """Bir test dosyasındaki testlerin paylaştığı, girişi yapılmış tek sekme (salt okuma testleri için)."""
    ctx = browser.new_context(base_url=settings.base_url, storage_state=auth_state,
                              viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    page.goto("/dashboard")
    yield page
    ctx.close()


@pytest.fixture(scope="session")
def api_auth_headers(browser: Browser, auth_state) -> dict[str, str]:
    return capture_auth_headers(browser, auth_state)


@pytest.fixture(scope="session")
def api(playwright: Playwright, auth_state, api_auth_headers):
    """Girişli API bağlamı: yakalanan başlıklar + oturum çerezleri."""
    ctx = playwright.request.new_context(base_url=settings.api_url + API_PREFIX, extra_http_headers=api_auth_headers,
                                         storage_state=auth_state)
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="session")
def anon_api(playwright: Playwright):
    ctx = playwright.request.new_context(base_url=settings.api_url + API_PREFIX)
    yield ctx
    ctx.dispose()


@pytest.fixture
def soft() -> SoftChecks:
    return SoftChecks()
