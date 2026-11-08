import uuid
from datetime import datetime


def unique_name(prefix: str = "otomasyon") -> str:
    """otomasyon<AAGGSSddss><4 hex>: testin oluşturduğu kayıtları ayırt etmek ve temizlemek için."""
    return f"{prefix}{datetime.now().strftime('%m%d%H%M%S')}{uuid.uuid4().hex[:4]}"
