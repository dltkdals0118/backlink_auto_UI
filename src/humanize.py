"""실제 사람처럼 보이게 하는 안티봇 풋프린트 유틸.

- User-Agent / Accept-Language / 뷰포트 / 타임존 랜덤화
- Referer(검색 유입/사이트 유입) 랜덤화 + AI 검색어 생성
- 마우스 이동, 스크롤, 글자 단위 타이핑 등 휴먼라이크 행동
- 모든 범위는 HumanSettings로 UI에서 조절 가능
"""
from __future__ import annotations

import random
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable

LogFn = Callable[[str], None]

_DESKTOP_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]
_MOBILE_UAS = [
    "Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
]
_DESKTOP_VIEWPORTS = [
    (1920, 1080), (1536, 864), (1440, 900), (1366, 768), (1600, 900),
]
_MOBILE_VIEWPORTS = [(390, 844), (412, 915), (360, 800)]
_ACCEPT_LANGS = [
    "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "ko-KR,ko;q=0.9",
    "ko,en-US;q=0.8,en;q=0.6",
]
_SEARCH_ENGINES = [
    ("https://search.naver.com/search.naver?query=", "naver"),
    ("https://www.google.com/search?q=", "google"),
    ("https://www.bing.com/search?q=", "bing"),
    ("https://search.daum.net/search?q=", "daum"),
]


@dataclass
class HumanSettings:
    enabled: bool = False
    device: str = "desktop"        # desktop | mobile | random
    referer_mode: str = "search"   # none | search | site | random
    min_delay_ms: int = 400
    max_delay_ms: int = 1500
    scroll_min: int = 2
    scroll_max: int = 6
    mouse_min: int = 3
    mouse_max: int = 8
    typing: bool = True
    use_ai: bool = True


def _resolve_device(device: str, rng: random.Random) -> str:
    if device == "random":
        return rng.choice(["desktop", "mobile"])
    return device


def pick_user_agent(device: str, rng: random.Random) -> str:
    pool = _MOBILE_UAS if device == "mobile" else _DESKTOP_UAS
    return rng.choice(pool)


def mobile_context_kwargs(rng: random.Random) -> dict:
    """휴먼라이크 설정과 무관하게 모바일 UA 컨텍스트만 구성한다.

    기기 감지로 데스크톱 접속 시 m.* → www.* 로 리다이렉트하는 사이트 대응용.
    """
    ua = pick_user_agent("mobile", rng)
    w, h = rng.choice(_MOBILE_VIEWPORTS)
    return {
        "user_agent": ua,
        "locale": "ko-KR",
        "timezone_id": "Asia/Seoul",
        "viewport": {"width": w, "height": h},
        "is_mobile": True,
        "has_touch": True,
        "extra_http_headers": {"Accept-Language": rng.choice(_ACCEPT_LANGS)},
    }


def build_context_kwargs(
    s: HumanSettings, rng: random.Random, force_device: str | None = None
) -> dict:
    """browser.new_context()에 넘길 옵션을 구성한다.

    force_device가 주어지면 설정값 대신 해당 기기(desktop/mobile)를 사용한다.
    """
    device = force_device or _resolve_device(s.device, rng)
    ua = pick_user_agent(device, rng)
    if device == "mobile":
        w, h = rng.choice(_MOBILE_VIEWPORTS)
        is_mobile, has_touch = True, True
    else:
        w, h = rng.choice(_DESKTOP_VIEWPORTS)
        is_mobile, has_touch = False, False

    headers = {
        "Accept-Language": rng.choice(_ACCEPT_LANGS),
        "Upgrade-Insecure-Requests": "1",
    }
    return {
        "user_agent": ua,
        "locale": "ko-KR",
        "timezone_id": "Asia/Seoul",
        "viewport": {"width": w, "height": h},
        "is_mobile": is_mobile,
        "has_touch": has_touch,
        "extra_http_headers": headers,
    }


def _base_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


def pick_referer(
    s: HumanSettings, target_url: str, query: str | None, rng: random.Random
) -> str | None:
    """방문 경로(Referer)를 결정한다."""
    mode = s.referer_mode
    if mode == "random":
        mode = rng.choice(["none", "search", "site"])
    if mode == "none":
        return None
    if mode == "site":
        return _base_url(target_url)
    # search
    q = (query or "").strip() or "추천"
    base, _name = rng.choice(_SEARCH_ENGINES)
    return base + urllib.parse.quote(q)


def ai_search_query(api_key: str, model: str, topic: str | None) -> str | None:
    """주제에 맞는 자연스러운 한국어 검색어를 AI로 생성한다."""
    if not api_key or not topic:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            temperature=1.0,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"'{topic}' 주제로 사람들이 네이버나 구글에 입력할 법한 "
                        "짧은 한국어 검색어 1개만 출력하세요. 설명·따옴표 없이 검색어만."
                    ),
                }
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return text.strip('"').splitlines()[0][:40] or None
    except Exception:
        return None


def delay(s: HumanSettings, rng: random.Random) -> None:
    lo = max(0, s.min_delay_ms)
    hi = max(lo, s.max_delay_ms)
    time.sleep(rng.uniform(lo, hi) / 1000.0)


def human_browse(page, s: HumanSettings, rng: random.Random, log: LogFn = print) -> None:
    """페이지에서 마우스 이동 + 스크롤 + 머무름으로 사람처럼 행동한다."""
    try:
        vp = page.viewport_size or {"width": 1366, "height": 768}
        w, h = vp["width"], vp["height"]

        moves = rng.randint(s.mouse_min, max(s.mouse_min, s.mouse_max))
        for _ in range(moves):
            page.mouse.move(rng.randint(0, w - 1), rng.randint(0, h - 1), steps=rng.randint(5, 25))
            time.sleep(rng.uniform(0.05, 0.3))

        scrolls = rng.randint(s.scroll_min, max(s.scroll_min, s.scroll_max))
        for _ in range(scrolls):
            dy = rng.randint(150, 600)
            if rng.random() < 0.2:
                dy = -rng.randint(100, 300)
            page.mouse.wheel(0, dy)
            delay(s, rng)
        log(f"      휴먼 행동: 마우스 {moves}회, 스크롤 {scrolls}회")
    except Exception:
        pass


def human_type(locator, text: str, s: HumanSettings, rng: random.Random) -> None:
    """글자 단위로 타이핑한다 (사람처럼)."""
    try:
        locator.scroll_into_view_if_needed()
        locator.click()
    except Exception:
        pass
    per_char = rng.randint(30, 120)
    try:
        locator.press_sequentially(text, delay=per_char)
    except Exception:
        try:
            locator.type(text, delay=per_char)
        except Exception:
            locator.fill(text)
