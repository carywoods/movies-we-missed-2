from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    environment: str
    port: int
    site_url: str
    database_path: Path
    session_secret: str
    amazon_associate_tag: str
    imbh_base_url: str
    admin_email: str
    admin_password: str
    email_provider: str
    email_api_key: str
    email_from: str
    metadata_provider: str
    metadata_api_key: str
    model_provider: str
    model_api_key: str
    trust_proxy: bool

    @classmethod
    def from_env(cls) -> "Config":
        environment = os.getenv("APP_ENV", "development").strip().lower()
        site_url = os.getenv("SITE_URL", "http://localhost:8080").rstrip("/")
        parsed = urlparse(site_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError("SITE_URL must be an absolute http(s) URL")
        session_secret = os.getenv("SESSION_SECRET", "")
        if environment == "production" and len(session_secret) < 32:
            raise RuntimeError("SESSION_SECRET must contain at least 32 characters in production")
        if not session_secret:
            session_secret = "development-only-change-before-deploy"
        database_path = Path(os.getenv("DATABASE_PATH", "data/mwm.db")).expanduser()
        return cls(
            environment=environment,
            port=int(os.getenv("PORT", "8080")),
            site_url=site_url,
            database_path=database_path,
            session_secret=session_secret,
            amazon_associate_tag=os.getenv("AMAZON_ASSOCIATE_TAG", "").strip(),
            imbh_base_url=os.getenv("IMBH_BASE_URL", "https://itsmadebyhand.com/").rstrip("/") + "/",
            admin_email=os.getenv("ADMIN_EMAIL", "").strip().lower(),
            admin_password=os.getenv("ADMIN_PASSWORD", ""),
            email_provider=os.getenv("EMAIL_PROVIDER", "disabled").strip().lower(),
            email_api_key=os.getenv("EMAIL_API_KEY", ""),
            email_from=os.getenv("EMAIL_FROM", "Movies We Missed <club@example.com>"),
            metadata_provider=os.getenv("METADATA_PROVIDER", "disabled").strip().lower(),
            metadata_api_key=os.getenv("METADATA_API_KEY", ""),
            model_provider=os.getenv("MODEL_PROVIDER", "disabled").strip().lower(),
            model_api_key=os.getenv("MODEL_API_KEY", ""),
            trust_proxy=_bool("TRUST_PROXY", False),
        )

    @property
    def secure_cookies(self) -> bool:
        return self.site_url.startswith("https://")

    @property
    def email_enabled(self) -> bool:
        return self.email_provider != "disabled" and bool(self.email_api_key)

