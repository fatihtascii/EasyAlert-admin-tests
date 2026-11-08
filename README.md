# easyalert-admin-tests

EasyAlert yönetim paneli (dev-admin.easyalert.io) ve API'si (dev-api.easyalert.io) için Playwright (Python) + pytest
test otomasyonu. Yapı easycontact-admin-tests ile aynıdır; case'ler NG Test'teki **EasyAlert** tenant'ında yönetilir.

## Kurulum

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # EA_EMAIL / EA_PASSWORD doldur
```

API şeması (uçlar ve gövdeler için referans, git'e girmez):

```bash
curl -s https://dev-api.easyalert.io/openapi.json -o openapi.json
```

## Çalıştırma

```bash
pytest                      # hepsi
pytest -m smoke             # menü sayfaları + giriş yönlendirmesi
pytest tests/api            # API (tarayıcısız; token girişle yakalanır)
pytest --headed -k Incidents
```

## Klasörler

| Klasör | İçerik |
|---|---|
| `pages/` | Sayfa nesneleri (`sections.py`: menü sayfaları ve başlıkları) |
| `tests/smoke/` | Hızlı temel kontroller |
| `tests/api/` | Doğrudan API testleri |
| `utils/` | API istemcisi, `known_bug` işareti, yumuşak kontroller |

## Kurallar

- Kimlik bilgileri yalnız `.env`'den okunur; token ve şifre yazdırılmaz.
- Testlerin oluşturduğu kayıtların adı `otomasyon` ile başlar ve test sonunda silinir.
- Gerçek kişilere bildirim gidebilecek akışlarda (policy hedefleri) yalnız test kullanıcıları/kanalları kullanılır.
- Test docstring'i: ilk satır NG Test başlığı, "Adımlar:" altında `eylem -> beklenen`.
