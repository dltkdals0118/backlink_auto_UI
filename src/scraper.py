"""사이트 스크래핑으로 업종/키워드 컨텍스트 추출 (EEAT 본문용)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

_STOPWORDS = {"바로가기", "로그인", "회원가입", "검색", "장바구니", "사이트맵", "메뉴"}


@dataclass
class SiteContext:
    title: str = ""
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    text_snippet: str = ""

    def as_prompt_context(self) -> str:
        parts = []
        if self.title:
            parts.append(f"사이트명/제목: {self.title}")
        if self.description:
            parts.append(f"설명: {self.description}")
        if self.keywords:
            parts.append(f"주요 키워드: {', '.join(self.keywords)}")
        if self.text_snippet:
            parts.append(f"본문 일부: {self.text_snippet}")
        return "\n".join(parts)


def _base_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def scrape_site(write_url: str, timeout: int = 10) -> SiteContext:
    """글쓰기 URL의 메인 도메인을 스크래핑해 업종 컨텍스트를 추출한다.

    네트워크 실패 시 빈 컨텍스트를 반환해 전체 파이프라인을 막지 않는다.
    """
    home = _base_url(write_url)
    try:
        resp = requests.get(home, headers=_HEADERS, timeout=timeout)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return SiteContext()

    title = (soup.title.string or "").strip() if soup.title else ""

    description = ""
    meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    if meta_desc and meta_desc.get("content"):
        description = meta_desc["content"].strip()

    keywords: list[str] = []
    meta_kw = soup.find("meta", attrs={"name": "keywords"})
    if meta_kw and meta_kw.get("content"):
        keywords = [k.strip() for k in meta_kw["content"].split(",") if k.strip()]

    # 메뉴/헤딩에서 업종 키워드 보강
    for tag in soup.find_all(["h1", "h2", "h3", "a"]):
        text = tag.get_text(strip=True)
        if 1 < len(text) <= 10 and text not in _STOPWORDS and not text.isdigit():
            if text not in keywords:
                keywords.append(text)
    keywords = keywords[:20]

    body_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    text_snippet = body_text[:600]

    return SiteContext(
        title=title,
        description=description,
        keywords=keywords,
        text_snippet=text_snippet,
    )
