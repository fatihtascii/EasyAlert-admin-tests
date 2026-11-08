"""API istemcisi: dev-api'ye giriş yapılmış oturumun kimliğiyle istek atar.

Uygulama Bearer başlığı kullanıyorsa o yakalanır; kullanmıyorsa (oturum çerezle taşınıyorsa) API bağlamı girişten
kaydedilen depolama durumuyla (.auth/state.json, çerezler) açılır. Token/çerez değerleri yazdırılmaz.
"""
import json
from typing import Any

from playwright.sync_api import APIResponse, Browser

from config import settings
from pages.login_page import LoginPage

API_PREFIX = "/api/v1/"


def capture_auth_headers(browser: Browser, storage_state: str | None = None) -> dict[str, str]:
    """Uygulamanın dev-api isteklerindeki authorization ve x-*tenant* başlıklarını döner (çerezle çalışıyorsa boş)."""
    ctx = browser.new_context(base_url=settings.base_url, storage_state=storage_state)
    page = ctx.new_page()
    headers: dict[str, str] = {}

    def on_request(req):
        if settings.api_url not in req.url:
            return
        for k, v in req.headers.items():
            if (k == "authorization" or (k.startswith("x-") and "tenant" in k)) and k not in headers:
                headers[k] = v

    page.on("request", on_request)
    try:
        if storage_state:
            page.goto("/incidents")
        else:
            LoginPage(page).open().login_and_wait(settings.email, settings.password)
            page.goto("/incidents")
        for _ in range(30):
            if "authorization" in headers:
                break
            page.wait_for_timeout(500)
    finally:
        ctx.close()
    print(f"\n[api] yakalanan başlık adları: {sorted(headers) or 'yok (oturum çerezle taşınıyor)'}")
    return headers


def body(resp: APIResponse) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text()[:500]


def describe(resp: APIResponse) -> str:
    """Hata mesajları için kısa özet (başlık değerleri yok)."""
    b = body(resp)
    text = json.dumps(b, ensure_ascii=False)[:300] if not isinstance(b, str) else b[:300]
    return f"{resp.status} {resp.url.split(API_PREFIX)[-1]} -> {text}"
