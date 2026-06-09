"""게시판 글쓰기 폼 구조 분석 (여러 게시판 시스템 범용 지원).

gnuboard5(wr_*)와 구형 dae_board(b_*) 등 서로 다른 필드명을 모두 지원하며,
명시적 셀렉터 후보 → 키워드 휴리스틱 순으로 폼 요소를 탐지한다.
목록 페이지에서 시작한 경우 글쓰기 버튼을 찾는 기능도 제공한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from playwright.sync_api import Locator, Page

# 필드별 명시적 셀렉터 후보 (앞쪽 우선)
_NAME_SELECTORS = [
    'input[name="wr_name"]', 'input[name="b_name"]', 'input[name="name"]',
    'input[name="mb_name"]', 'input[name="user_name"]', "#wr_name",
    # 부분일치(커스텀 보드: sub74_name 등). filename 등 오탐 방지를 위해 뒤쪽에 배치
    'input[name*="_name"]', 'input[name*="name"]:not([name*="file"])',
]
_PASSWORD_SELECTORS = [
    'input[name="wr_password"]', 'input[name="b_pass"]', 'input[name="password"]',
    'input[name="passwd"]', 'input[name="pass"]', 'input[type="password"]',
    # 부분일치(커스텀 보드: sub74_pass 등)
    'input[name*="pass"]', 'input[name*="passwd"]', 'input[name*="pwd"]',
    'input[name*="_pw"]', 'input[id*="pass"]',
]
_EMAIL_SELECTORS = [
    'input[name="wr_email"]', 'input[name="b_email"]', 'input[name="email"]',
    'input[name="mail"]', 'input[name*="email"]', 'input[type="email"]',
]
_HOMEPAGE_SELECTORS = [
    'input[name="wr_homepage"]', 'input[name="sitelink"]', 'input[name="homepage"]',
    'input[name="url"]', 'input[name="link"]', 'input[name*="homepage"]',
    'input[name*="sitelink"]',
]
_SUBJECT_SELECTORS = [
    'input[name="wr_subject"]', 'input[name="b_title"]', 'input[name="subject"]',
    'input[name="title"]', "#wr_subject",
    # 부분일치(커스텀 보드: sub74_title 등)
    'input[name*="subject"]', 'input[name*="title"]:not([name*="room"])',
]
_CONTENT_TEXTAREA_SELECTORS = [
    'textarea[name="wr_content"]', 'textarea[name="b_comment"]',
    'textarea[name="content"]', 'textarea[name="contents"]',
    'textarea[name="memo"]', 'textarea[name="comment"]', "#wr_content",
    # 부분일치(커스텀 보드: sub74_comment 등)
    'textarea[name*="content"]', 'textarea[name*="comment"]',
    'textarea[name*="memo"]', 'textarea[name*="body"]',
]
_CONTENT_IFRAME_SELECTORS = [
    "iframe.cheditor-frame", "iframe[id*='content']", ".note-editable",
    "iframe[title*='Rich']",
]
_CAPTCHA_IMG_SELECTORS = [
    "#captcha_img", "#zsfImg", "#captcha_Write", "img#captcha",
    "img[src*='captcha']", "img[src*='Captcha']", "img[id*='captcha']",
    "img[src*='kcaptcha']", "img[src*='zmSpamFree']", "img[src*='spamfree']",
]
_CAPTCHA_INPUT_SELECTORS = [
    'input[name="wr_captcha"]', 'input[name="captcha_key"]', 'input[name="zsfCode"]',
    "#zsfCode", "#captcha_key", "#captcha", 'input[name="captcha"]',
    'input[id*="captcha"]',
]
_CAPTCHA_REFRESH_SELECTORS = [
    "#captcha_reload", "a[onclick*='zsfImg']", "a[onclick*='zsf']",
    "[onclick*='refresh_captcha']", "[onclick*='captcha']",
    "a[onclick*='reload']", "button[onclick*='reload']", ".captcha_reload",
]
_SUBMIT_SELECTORS = [
    'input[type="image"]', "#btn_submit", 'button[type="submit"]',
    'input[type="submit"][value*="작성"]', 'input[type="submit"][value*="등록"]',
    "a[onclick*='form_submit']", "a[onclick*='submit']", "[onclick*='form_submit']",
    ".btn_confirm input", ".btn_confirm button", ".btn_confirm a",
    'button:has-text("작성")', 'button:has-text("등록")',
    'input[type="submit"]',
]

# 목록 페이지의 글쓰기 버튼 후보
_WRITE_BUTTON_SELECTORS = [
    'a[href*="write.php"]', 'a[href*="wr_id="][href*="write"]',
    'a:has(img[alt*="글쓰기"])', 'a:has(img[alt*="쓰기"])',
    'a:has(img[alt*="글작성"])', 'a:has(img[alt*="write"])',
    'a:has-text("글쓰기")', 'a:has-text("글작성")', 'a:has-text("쓰기")',
    'input[type="image"][src*="write"]', 'a[href*="mode=write"]',
    'a[href*="/write"]', 'a[href*="write"]', 'a[href*="?write"]',
    'a[onclick*="write"]',
]


@dataclass
class FormMap:
    name: Locator
    password: Locator
    subject: Locator
    content: Locator
    captcha_image: Locator | None
    captcha_input: Locator | None
    captcha_refresh: Locator | None
    submit_button: Locator
    email: Locator | None = None
    homepage: Locator | None = None
    content_is_iframe: bool = False
    captcha_len: int | None = None
    detected: dict[str, bool] = field(default_factory=dict)
    # Cafe24 등 변형 폼 지원
    category: Locator | None = None          # 말머리 select
    subject_is_select: bool = False          # 제목이 select(고정 제목)인 경우
    email_local: Locator | None = None       # 이메일 아이디부(email1)
    email_domain_select: Locator | None = None  # 이메일 도메인 select(email3)
    agreements: Locator | None = None        # 필수 동의 체크박스(그룹)
    public_radio: Locator | None = None      # 비밀글 '공개' 라디오


def _first_existing(page: Page, selectors: list[str]) -> Locator | None:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                return locator
        except Exception:
            continue
    return None


_FIELD_KEYWORDS = {
    "name": ["이름", "성명", "작성자", "name", "nick"],
    "subject": ["제목", "title", "subject"],
    "email": ["이메일", "메일", "email", "mail"],
    "homepage": ["홈페이지", "사이트", "주소", "homepage", "url", "site", "link"],
    "password": ["비밀번호", "비번", "암호", "pass", "pwd", "secret"],
}


def _heuristic_password(page: Page, used: set[str]) -> Locator | None:
    """비밀번호 칸을 추정한다. type=password가 없고 text로 된 커스텀 보드 대응."""
    keywords = _FIELD_KEYWORDS["password"]
    try:
        inputs = page.locator(
            'input[type="password"], input[type="text"], input:not([type])'
        )
        count = min(inputs.count(), 40)
    except Exception:
        return None
    for i in range(count):
        el = inputs.nth(i)
        try:
            attrs = " ".join(
                (el.get_attribute(a) or "")
                for a in ("name", "id", "title", "placeholder", "class")
            ).lower()
        except Exception:
            continue
        if attrs in used:
            continue
        if any(kw.lower() in attrs for kw in keywords):
            used.add(attrs)
            return el
    return None


def _heuristic_text_input(page: Page, field_name: str, used: set[str]) -> Locator | None:
    """키워드 기반으로 text 입력칸을 추정한다 (명시적 셀렉터 실패 시 폴백)."""
    keywords = _FIELD_KEYWORDS.get(field_name, [])
    try:
        inputs = page.locator('input[type="text"]:visible, input:not([type]):visible')
        count = min(inputs.count(), 30)
    except Exception:
        return None
    for i in range(count):
        el = inputs.nth(i)
        try:
            attrs = " ".join(
                (el.get_attribute(a) or "")
                for a in ("name", "id", "title", "placeholder", "class")
            ).lower()
        except Exception:
            continue
        if attrs in used:
            continue
        # 검색 키워드 입력칸 등은 제외
        if field_name == "subject" and ("검색" in attrs or "keyword" in attrs or "search" in attrs):
            continue
        if any(kw.lower() in attrs for kw in keywords):
            used.add(attrs)
            return el
    return None


def _maxlength(locator: Locator | None) -> int | None:
    if locator is None:
        return None
    try:
        raw = locator.get_attribute("maxlength")
        return int(raw) if raw and raw.isdigit() else None
    except Exception:
        return None


def _analyze_cafe24(page: Page) -> FormMap | None:
    """Cafe24 표준 게시판 글쓰기 폼(#boardWriteForm)을 전용 처리한다.

    제목/말머리 select, 이메일 3분할, 보안문자, 개인정보 동의 체크박스 등
    일반 폼과 구조가 크게 달라 별도 경로로 분석한다.
    """
    try:
        if page.locator("#boardWriteForm").count() == 0:
            return None
    except Exception:
        return None

    def opt(selector: str) -> Locator | None:
        loc = page.locator(selector)
        try:
            return loc.first if loc.count() > 0 else None
        except Exception:
            return None

    name = opt("#writer") or opt('#boardWriteForm input[name="writer"]')
    password = opt("#password") or opt('#boardWriteForm input[type="password"]')
    subject = opt("#subject")
    category = opt("#board_category")
    # 주의: 이 페이지엔 레이아웃용 <div id="content">가 따로 있어 #content는 모호하다.
    # 반드시 실제 textarea(name=content)를 지정한다.
    content = (
        opt('#boardWriteForm textarea[name="content"]')
        or opt('textarea[name="content"]')
        or opt("textarea#content")
        or opt("#boardWriteForm textarea")
    )
    email_local = opt("#email1")
    email_domain = opt("#email3")
    captcha_image = opt("#captcha_Write") or opt("#boardWriteForm img[id*='captcha']")
    captcha_input = (
        opt('#boardWriteForm input[name="captcha"]')
        or opt('input#captcha[name="captcha"]')
        or opt("#captcha")
    )
    captcha_refresh = opt("[onclick*='refresh_captcha']")
    submit_button = opt("[onclick*='form_submit']")
    agreements = page.locator('#boardWriteForm input[type="checkbox"]')
    public_radio = opt("#secure0") or opt('#boardWriteForm input[name="secure"]')

    if name is None or password is None or subject is None or content is None or submit_button is None:
        return None

    subject_is_select = False
    try:
        subject_is_select = subject.evaluate("e => e.tagName.toLowerCase()") == "select"
    except Exception:
        pass

    has_agreement = False
    try:
        has_agreement = agreements.count() > 0
    except Exception:
        pass

    return FormMap(
        name=name,
        password=password,
        subject=subject,
        content=content,
        captcha_image=captcha_image,
        captcha_input=captcha_input,
        captcha_refresh=captcha_refresh,
        submit_button=submit_button,
        email=None,
        homepage=None,
        content_is_iframe=False,
        captcha_len=_maxlength(captcha_input),
        category=category,
        subject_is_select=subject_is_select,
        email_local=email_local,
        email_domain_select=email_domain,
        agreements=agreements if has_agreement else None,
        public_radio=public_radio,
        detected={
            "cafe24": True,
            "captcha": captcha_input is not None,
            "category": category is not None,
            "email_split": email_local is not None,
            "agreement": has_agreement,
            "subject_select": subject_is_select,
        },
    )


def analyze_form(page: Page) -> FormMap:
    """현재 페이지에서 글쓰기 폼 요소를 탐지한다."""
    cafe24 = _analyze_cafe24(page)
    if cafe24 is not None:
        return cafe24

    used: set[str] = set()

    name = _first_existing(page, _NAME_SELECTORS) or _heuristic_text_input(page, "name", used)
    password = _first_existing(page, _PASSWORD_SELECTORS) or _heuristic_password(page, used)
    email = _first_existing(page, _EMAIL_SELECTORS) or _heuristic_text_input(page, "email", used)
    homepage = _first_existing(page, _HOMEPAGE_SELECTORS) or _heuristic_text_input(page, "homepage", used)
    subject = _first_existing(page, _SUBJECT_SELECTORS) or _heuristic_text_input(page, "subject", used)

    content_textarea = _first_existing(page, _CONTENT_TEXTAREA_SELECTORS)
    if content_textarea is None:
        # 이름 없는 첫 textarea 폴백
        content_textarea = _first_existing(page, ["textarea"])
    content_iframe = _first_existing(page, _CONTENT_IFRAME_SELECTORS)
    content_is_iframe = content_textarea is None and content_iframe is not None
    content = content_textarea or content_iframe

    captcha_image = _first_existing(page, _CAPTCHA_IMG_SELECTORS)
    captcha_input = _first_existing(page, _CAPTCHA_INPUT_SELECTORS)
    captcha_refresh = _first_existing(page, _CAPTCHA_REFRESH_SELECTORS)
    submit_button = _first_existing(page, _SUBMIT_SELECTORS)

    if name is None or password is None or subject is None or content is None:
        raise RuntimeError(
            "필수 폼 요소를 찾지 못했습니다. 목록 페이지이거나, 로그인 필요, "
            "또는 폼 구조가 예상과 다를 수 있습니다."
        )
    if submit_button is None:
        raise RuntimeError("제출 버튼을 찾지 못했습니다.")

    captcha_len: int | None = None
    if captcha_input is not None:
        try:
            raw = captcha_input.get_attribute("maxlength")
            captcha_len = int(raw) if raw and raw.isdigit() else None
        except Exception:
            captcha_len = None

    return FormMap(
        name=name,
        password=password,
        subject=subject,
        content=content,
        captcha_image=captcha_image,
        captcha_input=captcha_input,
        captcha_refresh=captcha_refresh,
        submit_button=submit_button,
        email=email,
        homepage=homepage,
        content_is_iframe=content_is_iframe,
        captcha_len=captcha_len,
        detected={
            "email": email is not None,
            "homepage": homepage is not None,
            "captcha": captcha_input is not None,
            "content_iframe": content_is_iframe,
        },
    )


def find_write_button(page: Page) -> Locator | None:
    """목록 페이지에서 글쓰기 버튼/링크를 찾는다."""
    return _first_existing(page, _WRITE_BUTTON_SELECTORS)
