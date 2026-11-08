"""Keşif (assert yok): Incidents liste ve detay sayfasındaki kontrolleri yazdırır.

Otomasyon düzeninde (yalnız EA_NOTIFY_EMAIL'e bildirim) bir incident açar; sayfada hiçbir aksiyona basmaz,
sonunda incident çözülür ve kurulum silinir. Çalıştırma: pytest tests/explore -s -m explore
"""
import pytest
from playwright.sync_api import Browser

from config import settings
from tests.e2e.helpers import automation_route, level

pytestmark = pytest.mark.explore

JS = """root => {
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const t = e => (e.innerText || e.getAttribute('aria-label') || e.getAttribute('title') || '').trim().replace(/\\s+/g,' ').slice(0,60);
  const q = s => [...root.querySelectorAll(s)].filter(vis);
  return {
    headings: q('h1,h2,h3').map(t),
    buttons: q('button,[role=button]').map(e => [t(e), e.getAttribute('aria-haspopup')||'', e.disabled?'disabled':'']),
    inputs: q('input,textarea').map(e => [e.type, e.placeholder||'', e.getAttribute('aria-label')||'']),
    combos: q('[role=combobox],select').map(t),
    tabs: q('[role=tab]').map(e => [t(e), e.getAttribute('aria-selected')]),
    th: q('th,[role=columnheader]').map(t),
    rowSample: q('tbody tr,[role=row]').slice(0,2).map(t),
    links: q('main a[href*=incidents]').slice(0,3).map(e => e.getAttribute('href')),
  };
}"""


def _dump(page, label):
    page.wait_for_timeout(2500)
    info = page.locator("main").first.evaluate(JS)
    print(f"\n===== {label}: {page.url}")
    for k, v in info.items():
        print(f"{k}: {v}")


def test_explore_incidents(browser: Browser, auth_state, api, anon_api):
    """Keşif: Incidents liste ve detay sayfası yapısı"""
    with automation_route(api, anon_api, lambda uid: [level(1, uid)]) as route:
        _, inc_id = route.open_incident()
        ctx = browser.new_context(base_url=settings.base_url, storage_state=auth_state,
                                  viewport={"width": 1600, "height": 1000})
        page = ctx.new_page()
        try:
            page.goto("/incidents")
            _dump(page, "liste")
            for name in page.locator("main [aria-haspopup], main [role=combobox]").all()[:6]:
                try:
                    label = (name.inner_text() or "").strip()[:30]
                    name.click(timeout=3000)
                    page.wait_for_timeout(600)
                    opts = page.locator("[role=option],[role=menuitem],[role=menuitemcheckbox]").all_inner_texts()
                    print(f"menü '{label}': {[o.strip()[:30] for o in opts][:15]}")
                    page.keyboard.press("Escape")
                except Exception as e:  # keşif: hata önemsiz
                    print(f"menü açılamadı: {type(e).__name__}")
            search = page.locator("main input[type=search], main input[placeholder*='earch' i]").first
            if search.count():
                with page.expect_response(lambda r: "/incidents" in r.url and r.request.method == "GET", timeout=10000) as info:
                    search.fill(route.tag)
                print(f"arama isteği: {info.value.url.split('/api/v1/')[-1]}")
                _dump(page, "arama sonrası")
            page.goto(f"/incidents/{inc_id}")
            _dump(page, "detay")
        finally:
            ctx.close()
