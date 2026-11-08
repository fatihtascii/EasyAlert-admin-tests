"""Testlerde ortak kullanılan pytest işaretleri."""
import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


def known_bug(reason: str):
    """Bilinen ve dev ekibine bildirilmiş uygulama hatası.

    strict=True: hata düzelirse test XPASS olur ve suite kırmızıya döner -> o zaman
    bu işaret kaldırılmalı. Tüm bilinen hataların listesi: `pytest -rx` (XFAIL satırları).

    raises: yalnızca doğrulama hatası (AssertionError, expect(...)) ve Playwright bekleme
    zaman aşımı "bilinen hata" sayılır. Ağ kopması, giriş hatası, kod hatası (AttributeError,
    KeyError ...) gibi başka bir hata FAILED/ERROR görünür; böylece site erişilemezken
    bilinen hatalar yanlışlıkla "hâlâ duruyor" (XFAIL) görünmez.
    """
    return pytest.mark.xfail(
        reason=f"BİLİNEN HATA: {reason}",
        strict=True,
        raises=(AssertionError, PlaywrightTimeoutError),
    )
