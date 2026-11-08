"""Tüm sayfa nesnelerinin ortak tabanı: menüden açma ve başlık bekleme."""
import re

from playwright.sync_api import Locator, Page, expect


class BasePage:
    path = "/"
    heading_text: str = ""

    def __init__(self, page: Page):
        self.page = page
        self.dialog = page.get_by_role("dialog")

    @property
    def heading(self) -> Locator:
        return self.page.locator("main").get_by_role("heading", name=self.heading_text, exact=True).first

    @property
    def sidebar_link(self) -> Locator:
        return self.page.locator(f"a[href='{self.path}']").first

    def open(self):
        self.page.goto(self.path)
        expect(self.heading).to_be_visible(timeout=20000)
        return self

    def go_home(self):
        self.page.goto("/dashboard")
        expect(self.page.locator("a[href='/dashboard']").first).to_be_visible(timeout=20000)
        return self

    def open_from_sidebar(self):
        self.sidebar_link.click()
        expect(self.page).to_have_url(re.compile(re.escape(self.path) + r"/?(\?.*)?$"))
        expect(self.heading).to_be_visible(timeout=20000)
        return self
