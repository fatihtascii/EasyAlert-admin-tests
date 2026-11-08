import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} tanımlı değil. .env.example'ı .env olarak kopyalayıp doldur.")
    return value


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_url: str
    email: str
    password: str


settings = Settings(
    base_url=os.getenv("BASE_URL", "https://dev-admin.easyalert.io").rstrip("/"),
    api_url=os.getenv("API_URL", "https://dev-api.easyalert.io").rstrip("/"),
    email=_require("EA_EMAIL"),
    password=_require("EA_PASSWORD"),
)
