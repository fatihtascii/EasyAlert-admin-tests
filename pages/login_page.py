"""Giriş formu. EasyAlert'in kimlik sağlayıcısı henüz kesinleşmediği için alanlar genel seçicilerle bulunur
(Keycloak: #username / #password / #kc-login; diğer formlar: e-posta ve şifre alanı + gönder düğmesi)."""
from playwright.sync_api import Page, expect

EMAIL_SEL = "#username, input[type=email], input[name=email], input[name=username], input[autocomplete=username]"
PASSWORD_SEL = "#password, input[type=password]"
SUBMIT_SEL = "#kc-login, button[type=submit], input[type=submit]"


class LoginPage:
    def __init__(self, page: Page):
        self.page = page
        self.email = page.locator(EMAIL_SEL).first
        self.password = page.locator(PASSWORD_SEL).first
        self.submit = page.locator(SUBMIT_SEL).first

    def open(self):
        self.page.goto("/dashboard")
        return self

    def login(self, email: str, password: str):
        self.email.wait_for(timeout=30000)
        self.email.fill(email)
        if not self.password.is_visible():  # e-posta ve şifre iki adımda soruluyorsa
            self.submit.click()
            self.password.wait_for(timeout=15000)
        self.password.fill(password)
        self.submit.click()
        return self

    def login_and_wait(self, email: str, password: str):
        try:
            self.login(email, password)
            expect(self.page.locator("a[href='/dashboard']").first).to_be_visible(timeout=30000)
        except Exception:
            self.debug_dump("reports/login_fail.png")
            raise
        return self

    def debug_dump(self, path: str):
        """Giriş takılınca nerede kaldığını gösterir: adres, görünür alanlar/düğmeler ve ekran görüntüsü (şifre yazılmaz)."""
        from pathlib import Path
        Path(path).parent.mkdir(exist_ok=True)
        p = self.page
        try:
            p.screenshot(path=path, full_page=True)
        except Exception:
            pass
        info = p.evaluate("""() => {
            const vis = e => !!(e.offsetWidth || e.offsetHeight);
            const t = e => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().slice(0, 40);
            return {
              inputs: [...document.querySelectorAll('input')].filter(vis)
                .map(i => `${i.type}#${i.id}[name=${i.name}][ph=${i.placeholder}]`),
              buttons: [...document.querySelectorAll('button, input[type=submit], a[role=button]')].filter(vis).map(t),
              alerts: [...document.querySelectorAll('[role=alert], .alert, .error, [class*=error]')].filter(vis).map(t),
            };
        }""")
        print(f"\n[giriş] takıldı: {p.url.split('?')[0]}\n[giriş] alanlar: {info['inputs']}\n"
              f"[giriş] düğmeler: {info['buttons']}\n[giriş] uyarılar: {info['alerts']}\n[giriş] ekran görüntüsü: {path}")
