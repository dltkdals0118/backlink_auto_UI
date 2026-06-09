"""애플리케이션 설정 로딩."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from dotenv import load_dotenv

# override=True: OS 환경변수에 이미 설정된 placeholder(예: OPENAI_API_KEY=sk-...)가
# .env의 실제 값을 가리지 않도록 .env를 우선 적용한다.
load_dotenv(override=True)


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Settings:
    openai_api_key: str
    openai_model: str
    openai_vision_model: str
    target_url: str
    headless: bool
    max_captcha_retries: int
    request_delay: float
    tesseract_cmd: str | None
    adb_cmd: str
    ip_off_wait: float
    ip_on_wait: float
    ip_verify_timeout: float

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            openai_vision_model=os.getenv("OPENAI_VISION_MODEL", "gpt-4o"),
            target_url=os.getenv("TARGET_URL", ""),
            headless=_as_bool(os.getenv("HEADLESS"), True),
            max_captcha_retries=int(os.getenv("MAX_CAPTCHA_RETRIES", "5")),
            request_delay=float(os.getenv("REQUEST_DELAY", "2")),
            tesseract_cmd=os.getenv("TESSERACT_CMD") or shutil.which("tesseract"),
            adb_cmd=os.getenv("ADB_CMD") or shutil.which("adb") or "adb",
            ip_off_wait=float(os.getenv("IP_OFF_WAIT", "4")),
            ip_on_wait=float(os.getenv("IP_ON_WAIT", "5")),
            ip_verify_timeout=float(os.getenv("IP_VERIFY_TIMEOUT", "40")),
        )


settings = Settings.load()
