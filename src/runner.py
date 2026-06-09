"""CLI/웹에서 공용으로 쓰는 자동 등록 파이프라인.

print 대신 log 콜백을 받아 진행 상황을 외부로 전달한다.
"""
from __future__ import annotations

import random
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable

from playwright.sync_api import sync_playwright

from config import settings
from src import captcha_solver, humanize, ip_rotator
from src.content_writer import generate_post, random_topic
from src.dummy_data import generate_identity
from src.form_analyzer import analyze_form, find_write_button
from src.humanize import HumanSettings
from src.scraper import scrape_site
from src.submitter import fill_form, submit

LogFn = Callable[[str], None]


@dataclass
class RunOptions:
    url: str
    topic: str | None = None
    manual: bool = False
    headless: bool = True
    dry_run: bool = False
    backlink_url: str | None = None
    backlink_text: str | None = None
    repeat: int = 1
    rotate_ip: bool = False
    rotate_every: int = 1
    mobile: bool = False
    human: HumanSettings = field(default_factory=HumanSettings)


@dataclass
class RunResult:
    code: int  # 0=성공, 1=실패, 2=설정 오류
    success: bool
    message: str
    subject: str | None = None
    result_url: str | None = None


_UNAVAILABLE_KEYWORDS = [
    "데이터 전송량 초과",
    "전송량 초과",
    "트래픽 초과",
    "일일 데이터 전송량",
    "Bandwidth Limit Exceeded",
    "Traffic Exceeded",
]


def _detect_unavailable(page) -> str | None:
    """사이트가 트래픽 초과 등으로 정상 페이지가 아닌지 감지한다."""
    try:
        title = page.title() or ""
        body = page.locator("body").inner_text()[:500]
    except Exception:
        return None
    haystack = f"{title}\n{body}"
    if any(kw in haystack for kw in _UNAVAILABLE_KEYWORDS):
        return (
            "대상 사이트가 일일 데이터 전송량(트래픽) 한도를 초과했습니다. "
            "사이트 호스팅 트래픽이 리셋되거나 한도가 늘어난 뒤 다시 시도하세요. "
            f"(현재 페이지 제목: {title.strip()})"
        )
    return None


def _resolve_write_form(page, log: LogFn):
    """글쓰기 폼을 찾는다. 목록 페이지면 글쓰기 버튼을 눌러 폼으로 이동한 뒤 분석한다."""
    try:
        return analyze_form(page)
    except RuntimeError:
        button = find_write_button(page)
        if button is None:
            raise
        log("      글쓰기 폼이 없어 '글쓰기' 버튼을 클릭합니다...")
        try:
            button.click()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1200)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"글쓰기 버튼 클릭 실패: {exc}")
        return analyze_form(page)


def _validate(options: RunOptions, log: LogFn) -> RunResult | None:
    if not options.url:
        log("오류: URL이 필요합니다 (.env의 TARGET_URL 또는 입력값).")
        return RunResult(2, False, "URL 없음")

    key = settings.openai_api_key.strip()
    if not key or key.startswith("sk-...") or len(key) < 20:
        log(
            "오류: 유효한 OPENAI_API_KEY가 없습니다. .env에 실제 키를 입력하고 "
            "저장했는지 확인하세요. (현재 placeholder 또는 빈 값)"
        )
        return RunResult(2, False, "OPENAI_API_KEY 미설정")
    return None


def run_pipeline(options: RunOptions, log: LogFn = print) -> RunResult:
    """전체 파이프라인 실행. 진행 로그는 log 콜백으로 전달."""
    invalid = _validate(options, log)
    if invalid is not None:
        return invalid

    log("[1/5] 사이트 스크래핑 중...")
    context = scrape_site(options.url)
    if context.title:
        log(f"      사이트: {context.title}")

    # 사이트가 트래픽 초과 등으로 막혀 있으면 AI 호출(비용) 전에 즉시 중단
    haystack = f"{context.title}\n{context.text_snippet}"
    if any(kw in haystack for kw in _UNAVAILABLE_KEYWORDS):
        msg = (
            "대상 사이트가 일일 데이터 전송량(트래픽) 한도를 초과했습니다. "
            "트래픽이 리셋되거나 한도가 늘어난 뒤 다시 시도하세요. "
            f"(현재 페이지 제목: {context.title.strip()})"
        )
        log(f"오류: {msg}")
        return RunResult(1, False, msg)

    # 주제 미입력 시 매번 다양한 랜덤 주제로 생성
    topic = options.topic or random_topic()
    if not options.topic:
        log(f"      랜덤 주제: {topic}")

    log(f"[2/5] AI 본문(EEAT) 생성 중... (모델: {settings.openai_model})")
    post = generate_post(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        context=context,
        topic=topic,
    )
    if post.model_used and post.model_used != settings.openai_model:
        log(f"      알림: '{settings.openai_model}' 호출 실패로 '{post.model_used}'로 대체 생성했습니다.")
    log(f"      제목: {post.subject}")

    # 백링크(SEO) 삽입: HTML 앵커를 본문 끝에 추가
    use_html = False
    if options.backlink_url:
        anchor_text = options.backlink_text or options.backlink_url
        anchor = (
            f'<a href="{options.backlink_url}" target="_blank" '
            f'rel="noopener">{anchor_text}</a>'
        )
        post.content = f"{post.content}\n\n{anchor}"
        use_html = True
        log(f"      백링크 삽입: {anchor}")

    identity = generate_identity()
    log(f"[3/5] 더미데이터 생성: {identity.name} / {identity.email}")

    captcha_solver.configure_tesseract(settings.tesseract_cmd)

    def solve_captcha(image_bytes: bytes, expected_len: int | None) -> str:
        # 1순위: OpenAI 비전, 2순위: Tesseract OCR
        code = captcha_solver.solve_with_openai(
            image_bytes,
            api_key=settings.openai_api_key,
            model=settings.openai_vision_model,
            expected_len=expected_len,
        )
        if not code:
            code = captcha_solver.solve_from_bytes(
                image_bytes, expected_len=expected_len
            )
        return code

    # 모바일 사이트(m.*/mobile.*) 자동 감지: 데스크톱 UA면 www로 리다이렉트되어
    # 폼을 못 찾는 사이트가 있어, 모바일 UA로 접속한다.
    host = urllib.parse.urlparse(options.url).netloc.lower()
    auto_mobile = host.startswith("m.") or host.startswith("mobile.")
    want_mobile = options.mobile or auto_mobile

    # 휴먼라이크(안티봇) 설정: 컨텍스트 옵션 / Referer 구성
    human = options.human
    rng = random.Random()
    context_kwargs: dict = {}
    referer: str | None = None
    if human.enabled:
        query = None
        if human.referer_mode in ("search", "random"):
            query = (
                humanize.ai_search_query(settings.openai_api_key, settings.openai_vision_model, topic)
                if human.use_ai
                else topic
            )
        force_device = "mobile" if want_mobile else None
        context_kwargs = humanize.build_context_kwargs(human, rng, force_device=force_device)
        referer = humanize.pick_referer(human, options.url, query, rng)
        log(f"      UA: {context_kwargs.get('user_agent', '')[:50]}...")
        log(f"      Referer: {referer or '(없음)'}")
    elif want_mobile:
        context_kwargs = humanize.mobile_context_kwargs(rng)
        reason = "사용자 지정" if options.mobile else f"모바일 도메인({host}) 감지"
        log(f"      모바일 모드({reason}): 모바일 UA로 접속합니다.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=options.headless)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        try:
            log(f"[4/5] 폼 분석 중: {options.url}")
            goto_kwargs = {"wait_until": "domcontentloaded"}
            if referer:
                goto_kwargs["referer"] = referer
            page.goto(options.url, **goto_kwargs)

            # 호스팅 트래픽 초과 등으로 안내 페이지가 뜬 경우 명확히 보고
            unavailable = _detect_unavailable(page)
            if unavailable:
                log(f"오류: {unavailable}")
                return RunResult(1, False, unavailable, post.subject, None)

            if human.enabled:
                humanize.human_browse(page, human, rng, log)

            form = _resolve_write_form(page, log)
            log(f"      탐지 결과: {form.detected} (캡차 {form.captcha_len}자리)")

            if human.enabled:
                humanize.human_browse(page, human, rng, log)

            fill_form(
                page, form, identity, post,
                enable_html=use_html,
                human=human if human.enabled else None,
                rng=rng,
            )

            log("[5/5] 캡차 처리 및 제출...")
            result = submit(
                page,
                form,
                max_retries=settings.max_captcha_retries,
                manual_fallback=options.manual,
                dry_run=options.dry_run,
                request_delay=settings.request_delay,
                solve_fn=solve_captcha,
                log=log,
                identity=identity,
                post=post,
                human=human if human.enabled else None,
                rng=rng,
            )
        finally:
            context.close()
            browser.close()

    log("-" * 40)
    if result.success:
        log(f"성공: {result.message}")
        if result.result_url:
            log(f"등록 URL: {result.result_url}")
        return RunResult(0, True, result.message, post.subject, result.result_url)

    log(f"실패: {result.message}")
    return RunResult(1, False, result.message, post.subject, None)


def run_batch(options: RunOptions, log: LogFn = print) -> RunResult:
    """반복 등록 + N회(글)당 IP 변경.

    options.repeat 횟수만큼 글을 등록하며, rotate_ip가 켜져 있으면
    rotate_every 글마다(0, N, 2N...) IP를 변경한다.
    """
    count = max(1, options.repeat)
    rotate_every = max(1, options.rotate_every)

    # 설정 검증은 첫 글 등록 직전 run_pipeline에서 수행되지만,
    # 반복 모드에서는 시작 전에 한 번 미리 검증해 빠르게 중단한다.
    invalid = _validate(options, log)
    if invalid is not None:
        return invalid

    if count == 1 and not options.rotate_ip:
        return run_pipeline(options, log=log)

    success = 0
    last_url: str | None = None
    for i in range(count):
        if options.rotate_ip and (i % rotate_every == 0):
            log(f"===== IP 변경 시도 (글 {i + 1}부터 적용) =====")
            ok = ip_rotator.rotate_ip(
                settings.adb_cmd,
                off_wait=settings.ip_off_wait,
                on_wait=settings.ip_on_wait,
                verify_timeout=settings.ip_verify_timeout,
                log=log,
            )
            if not ok:
                log("경고: IP 변경에 실패했습니다. (테더링/ADB/CGNAT 확인) 같은 IP로 계속 진행합니다.")

        log(f"===== [{i + 1}/{count}] 글 등록 시작 =====")
        result = run_pipeline(options, log=log)
        if result.success:
            success += 1
            last_url = result.result_url or last_url
        # 설정 오류(코드 2)면 반복을 계속할 의미가 없으므로 중단
        if result.code == 2:
            return result

        if i < count - 1:
            time.sleep(settings.request_delay)

    msg = f"총 {count}개 중 {success}개 등록 성공"
    log("=" * 40)
    log(msg)
    return RunResult(0 if success > 0 else 1, success > 0, msg, None, last_url)
