"""API: sağlık uçları ve kimlik doğrulama."""
from config import settings
from utils.api_client import body, describe


def test_health_endpoints(anon_api):
    """Sağlık uçları kimliksiz çağrıda 200 döner

    Adımlar:
    1. GET /health/healthz ve /health/readyz -> 200
    """
    for path in ("health/healthz", "health/readyz"):
        r = anon_api.get(path)
        print(f"\n[sağlık] {path}: {describe(r)[:150]}")
        assert r.ok, describe(r)


def test_me_without_auth_is_anonymous(anon_api):
    """Kimliksiz /auth/me isteği kullanıcı bilgisi döndürmez

    Uç tasarım gereği 200 döner ama oturumun açık olmadığını bildirir.

    Adımlar:
    1. Authorization başlığı olmadan GET /auth/me -> authenticated=false, user ve tenantId boş
    """
    r = anon_api.get("auth/me")
    data = (body(r) or {}).get("data") or {}
    print(f"\n[auth] kimliksiz auth/me: {describe(r)[:300]}")
    assert r.status in (200, 401), describe(r)
    assert data.get("authenticated") in (False, None), f"Kimliksiz istek oturum açık gösteriyor: {data}"
    assert not data.get("user") and not data.get("tenantId"), f"Kimliksiz istekte kullanıcı/tenant bilgisi döndü: {data}"


def test_me_returns_current_user(api):
    """Oturumdaki kullanıcının bilgisi /auth/me'den alınır

    Adımlar:
    1. Uygulamadan yakalanan token ile GET /auth/me -> 200; cevapta kullanıcının e-postası vardır
    """
    r = api.get("auth/me")
    assert r.ok, describe(r)
    assert (body(r).get("data") or {}).get("authenticated") is True, describe(r)
    assert settings.email.lower() in str(body(r)).lower(), "auth/me cevabında kullanıcı e-postası yok"
