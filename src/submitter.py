"""Playwright로 폼을 채우고 캡차를 풀어 글을 제출."""
from __future__ import annotations

import html as _html
import random
import re as _re
import time
from dataclasses import dataclass
from typing import Callable

from playwright.sync_api import Dialog, Page

from . import captcha_solver, humanize
from .content_writer import GeneratedPost
from .dummy_data import DummyIdentity
from .form_analyzer import FormMap
from .humanize import HumanSettings


@dataclass
class SubmitResult:
    success: bool
    message: str
    result_url: str | None = None


def _fill_text(locator, value: str) -> None:
    locator.scroll_into_view_if_needed()
    locator.fill(value)


def _enable_html_option(page: Page) -> None:
    """그누보드 HTML 옵션 체크박스를 활성화한다.

    onclick의 html_auto_br는 confirm 창을 띄우므로, 클릭 대신 JS로
    checked=true + value='html2'(HTML+자동줄바꿈)를 직접 설정한다.
    """
    page.evaluate(
        """() => {
            const el = document.querySelector('#html') || document.querySelector('input[name=\"html\"]');
            if (el) { el.checked = true; el.value = 'html2'; }
        }"""
    )


def _select_last_real(locator) -> None:
    """select에서 placeholder를 제외한 마지막 실제 옵션을 선택한다."""
    try:
        locator.evaluate(
            """el => {
                const opts = [...el.options].filter(o => o.value !== '' && o.value !== '0');
                if (opts.length) {
                    el.value = opts[opts.length - 1].value;
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }"""
        )
    except Exception:
        pass


def _fill_cafe24_email(
    page: Page,
    email_local,
    email_domain_select,
    email: str,
    *,
    use_typing: bool = False,
    human=None,
    rng=None,
) -> None:
    """Cafe24 이메일 3분할 입력. 목록에 없는 도메인(hanmail.net 등)은 직접입력(etc)."""
    local, _, domain = email.partition("@")
    local = local or "user"
    domain = domain or "gmail.com"
    _fill_input(email_local, local, use_typing=use_typing, human=human, rng=rng)

    try:
        known: list[str] = page.evaluate(
            """() => {
                const sel = document.getElementById('email3');
                if (!sel) return [];
                return [...sel.options].map(o => o.value).filter(v => v && v !== 'etc');
            }"""
        )
    except Exception:
        known = []

    if domain in known:
        try:
            email_domain_select.select_option(value=domain)
        except Exception:
            page.evaluate(
                """(d) => {
                    const sel = document.getElementById('email3');
                    if (!sel) return;
                    sel.value = d;
                    sel.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                domain,
            )
    else:
        # 직접입력: email3=etc 후 readonly email2에 도메인 직접 기입
        try:
            email_domain_select.select_option(value="etc")
        except Exception:
            page.evaluate(
                """() => {
                    const sel = document.getElementById('email3');
                    if (!sel) return;
                    sel.value = 'etc';
                    sel.dispatchEvent(new Event('change', { bubbles: true }));
                }"""
            )
        page.wait_for_timeout(150)
        page.evaluate(
            """(d) => {
                const e2 = document.getElementById('email2');
                if (!e2) return;
                e2.removeAttribute('readonly');
                e2.readOnly = false;
                e2.value = d;
                e2.dispatchEvent(new Event('input', { bubbles: true }));
                e2.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            domain,
        )
    page.wait_for_timeout(150)


def _fire_field_events(locator) -> None:
    """Cafe24 fw-filter 검증이 인식하도록 input/change/blur 이벤트를 발생시킨다."""
    try:
        locator.evaluate(
            """el => {
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }"""
        )
    except Exception:
        pass


def _fill_input(locator, value: str, *, use_typing: bool = False, human=None, rng=None) -> None:
    locator.scroll_into_view_if_needed()
    try:
        locator.click()
    except Exception:
        pass
    if use_typing and human and rng:
        humanize.human_type(locator, value, human, rng)
        humanize.delay(human, rng)
    else:
        locator.fill(value)
    _fire_field_events(locator)


def _sync_value(locator, value: str) -> None:
    """숨김/에디터 연동 textarea 대비: 값을 JS로 직접 세팅하고 이벤트를 발생시킨다."""
    try:
        locator.evaluate(
            "(el, v) => { el.value = v;"
            " el.dispatchEvent(new Event('input', {bubbles:true}));"
            " el.dispatchEvent(new Event('change', {bubbles:true})); }",
            value,
        )
    except Exception:
        pass


def _to_html(text: str) -> str:
    """평문 본문을 HTML로 변환한다(줄바꿈→<br>). 끝에 붙은 백링크 <a>는 원형 유지."""
    m = _re.search(r"<a\s.*?</a>", text, _re.S | _re.I)
    if m:
        plain = _html.escape(text[: m.start()]).replace("\n", "<br>")
        return plain + text[m.start():]
    return _html.escape(text).replace("\n", "<br>")


def _to_cafe24_content(text: str) -> str:
    """Cafe24 본문용 HTML. <a> 등 금지 태그는 평문으로 변환하고 <br>만 허용."""

    def _anchor_to_plain(m: _re.Match) -> str:
        url = m.group(1)
        label = _re.sub(r"<[^>]+>", "", m.group(2)).strip()
        return f"{label}: {url}" if label else url

    text = _re.sub(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        _anchor_to_plain,
        text,
        flags=_re.S | _re.I,
    )
    text = _re.sub(r"<[^>]+>", "", text)
    return _html.escape(text).replace("\n", "<br>")


def _fill_captcha_field(page: Page, code: str, password_locator=None, password_value: str = "") -> None:
    """보안문자 입력. 비밀번호 칸으로 잘못 들어가는 것을 방지한다."""
    page.evaluate(
        """(code) => {
            const el = document.querySelector(
                '#boardWriteForm input[name="captcha"], input#captcha[name="captcha"]'
            );
            if (!el) return;
            el.focus();
            el.value = code;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
        }""",
        code,
    )
    if password_locator is not None and password_value:
        try:
            current = password_locator.input_value()
            if current == code or (len(current) <= 8 and current != password_value):
                password_locator.fill(password_value)
                _fire_field_events(password_locator)
        except Exception:
            pass


def _fill_richtext(page: Page, content_locator, html_body: str) -> None:
    """Cafe24(Froala) 본문 입력: #content_BODY 에디터 + textarea(name=content) 동시 주입."""
    editor_selectors = [
        "#content_BODY",
        "body.fr-view[contenteditable='true']",
        ".fr-element[contenteditable='true']",
        ".fr-view[contenteditable='true']",
    ]
    filled_editor = False
    for sel in editor_selectors:
        try:
            ed = page.locator(sel).first
            if ed.count() == 0:
                continue
            ed.scroll_into_view_if_needed()
            ed.click()
            ed.evaluate(
                """(el, h) => {
                    el.innerHTML = h;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('keyup', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                }""",
                html_body,
            )
            filled_editor = True
            break
        except Exception:
            continue

    _sync_value(content_locator, html_body)

    # Froala API가 있으면 textarea 동기화 시도
    if filled_editor:
        try:
            page.evaluate(
                """(h) => {
                    const ta = document.querySelector('textarea[name="content"]');
                    if (ta) ta.value = h;
                    if (window.FroalaEditor && window.FroalaEditor.INSTANCES) {
                        for (const k in FroalaEditor.INSTANCES) {
                            const inst = FroalaEditor.INSTANCES[k];
                            if (inst && inst.html && inst.html.set) inst.html.set(h);
                        }
                    }
                }""",
                html_body,
            )
        except Exception:
            pass


def _check_all(group_locator) -> None:
    """체크박스 그룹을 모두 체크한다(필수 동의 등)."""
    try:
        count = group_locator.count()
        for i in range(count):
            cb = group_locator.nth(i)
            try:
                if not cb.is_checked():
                    cb.check(force=True)
            except Exception:
                cb.evaluate("el => { el.checked = true; el.dispatchEvent(new Event('change',{bubbles:true})); }")
    except Exception:
        pass


def fill_cafe24_fields(
    page: Page,
    form: FormMap,
    identity: DummyIdentity,
    post: GeneratedPost,
    *,
    human: HumanSettings | None = None,
    rng: random.Random | None = None,
) -> None:
    """Cafe24 글쓰기 폼을 지정 순서로 채운다.

    순서: 말머리/제목 → 작성자 → 이메일 → 비밀번호 → 본문
    (캡차·개인정보 동의는 submit 단계에서 마지막에 처리)
    """
    rng = rng or random.Random()
    use_typing = bool(human and human.enabled and human.typing)

    # 1) 말머리 / 제목 select
    if form.category is not None:
        _select_last_real(form.category)
    if form.subject_is_select:
        _select_last_real(form.subject)
    else:
        _fill_input(form.subject, post.subject, use_typing=use_typing, human=human, rng=rng)

    # 2) 작성자
    _fill_input(form.name, identity.name, use_typing=use_typing, human=human, rng=rng)

    # 3) 이메일 (email1 + email3 select / 직접입력 → email2)
    if form.email_local is not None and form.email_domain_select is not None:
        _fill_cafe24_email(
            page,
            form.email_local,
            form.email_domain_select,
            identity.email,
            use_typing=use_typing,
            human=human,
            rng=rng,
        )

    # 4) 비밀번호
    _fill_input(form.password, identity.password, use_typing=use_typing, human=human, rng=rng)

    # 비밀글 '공개'
    if form.public_radio is not None:
        try:
            form.public_radio.check(force=True)
        except Exception:
            pass

    # 5) 본문 (Froala #content_BODY + textarea)
    try:
        page.wait_for_selector(
            "#content_BODY, body.fr-view[contenteditable='true'], textarea[name='content']",
            timeout=6000,
        )
    except Exception:
        pass
    page.wait_for_timeout(300)
    _fill_richtext(page, form.content, _to_cafe24_content(post.content))


def fill_form(
    page: Page,
    form: FormMap,
    identity: DummyIdentity,
    post: GeneratedPost,
    *,
    enable_html: bool = False,
    human: HumanSettings | None = None,
    rng: random.Random | None = None,
) -> None:
    """캡차·동의를 제외한 폼 필드를 채운다."""
    if form.detected.get("cafe24"):
        fill_cafe24_fields(page, form, identity, post, human=human, rng=rng)
        return

    rng = rng or random.Random()
    use_typing = bool(human and human.enabled and human.typing)

    def set_text(locator, value: str) -> None:
        if use_typing:
            humanize.human_type(locator, value, human, rng)
            humanize.delay(human, rng)
        else:
            _fill_text(locator, value)

    set_text(form.name, identity.name)
    set_text(form.password, identity.password)

    if form.email is not None:
        set_text(form.email, identity.email)
    if form.homepage is not None:
        set_text(form.homepage, identity.homepage)

    if form.subject_is_select:
        _select_last_real(form.subject)
    else:
        set_text(form.subject, post.subject)

    if enable_html:
        _enable_html_option(page)

    if form.content_is_iframe:
        frame = form.content.content_frame()
        if frame is not None:
            body = frame.locator("body")
            body.click()
            body.fill(post.content)
    else:
        try:
            set_text(form.content, post.content)
        except Exception:
            pass
        _sync_value(form.content, post.content)

    if form.public_radio is not None:
        try:
            form.public_radio.check(force=True)
        except Exception:
            pass

    if form.agreements is not None:
        _check_all(form.agreements)


def _read_captcha_bytes(form: FormMap) -> bytes | None:
    if form.captcha_image is None:
        return None
    try:
        return form.captcha_image.screenshot()
    except Exception:
        return None


def _refresh_captcha(page: Page, form: FormMap) -> None:
    if form.captcha_refresh is not None:
        try:
            form.captcha_refresh.click()
            page.wait_for_timeout(800)
            return
        except Exception:
            pass
    # 폴백: 캡차 이미지를 다시 로드하기 위해 약간 대기
    page.wait_for_timeout(500)


def submit(
    page: Page,
    form: FormMap,
    *,
    max_retries: int,
    manual_fallback: bool,
    dry_run: bool,
    request_delay: float,
    solve_fn: Callable[[bytes, int | None], str] | None = None,
    log: Callable[[str], None] = print,
    identity: DummyIdentity | None = None,
    post: GeneratedPost | None = None,
    human: HumanSettings | None = None,
    rng: random.Random | None = None,
) -> SubmitResult:
    """캡차를 풀고 폼을 제출한다. 실패 시 캡차를 새로고침하며 재시도.

    Cafe24는 재시도마다 작성자/이메일/본문을 다시 채운 뒤
    캡차 → 개인정보 동의 → 제출 순으로 진행한다.
    """
    if solve_fn is None:
        solve_fn = lambda b, n: captcha_solver.solve_from_bytes(b, expected_len=n)

    is_cafe24 = bool(form.detected.get("cafe24"))

    def _prepare_cafe24() -> None:
        if is_cafe24 and identity and post:
            fill_cafe24_fields(page, form, identity, post, human=human, rng=rng)

    def _finalize_before_submit() -> None:
        if form.agreements is not None:
            _check_all(form.agreements)

    # 캡차가 없는 게시판이면 바로 제출
    if form.captcha_input is None:
        if is_cafe24:
            _prepare_cafe24()
            _finalize_before_submit()
        if dry_run:
            return SubmitResult(True, "[dry-run] 캡차 없음. 제출 생략.")
        return _do_submit(page, form, request_delay)

    last_message = "캡차 처리 실패"
    for attempt in range(1, max_retries + 1):
        # Cafe24: 매 시도마다 작성자·이메일·본문부터 다시 채움
        if is_cafe24:
            _prepare_cafe24()

        image_bytes = _read_captcha_bytes(form)
        if image_bytes is None:
            return SubmitResult(False, "캡차 이미지를 캡처하지 못했습니다.")

        expected = form.captcha_len
        code = solve_fn(image_bytes, expected)
        source = "AI"

        if not code and manual_fallback:
            code = captcha_solver.prompt_manual(image_bytes)
            source = "수동"

        if not code:
            last_message = f"[{attempt}/{max_retries}] 캡차 인식 실패"
            log(last_message)
            _refresh_captcha(page, form)
            continue

        log(f"[{attempt}/{max_retries}] 캡차 인식({source}): {code}")
        if is_cafe24:
            _fill_captcha_field(
                page, code,
                password_locator=form.password,
                password_value=identity.password if identity else "",
            )
        else:
            _fill_input(form.captcha_input, code)

        if dry_run:
            _finalize_before_submit()
            return SubmitResult(True, f"[dry-run] 폼 작성 완료. 캡차={code}. 제출 생략.")

        _finalize_before_submit()
        result = _do_submit(page, form, request_delay)
        if result.success:
            return result

        last_message = result.message
        log(f"[{attempt}/{max_retries}] 제출 실패: {result.message}")
        try:
            form.captcha_input.fill("")
        except Exception:
            pass
        _refresh_captcha(page, form)

    return SubmitResult(False, f"최대 재시도 초과: {last_message}")


def _do_submit(page: Page, form: FormMap, request_delay: float) -> SubmitResult:
    """제출 버튼 클릭 후 결과를 판별한다.

    그누보드는 캡차 오류 등을 alert(dialog)로 알리는 경우가 많다.
    """
    dialog_message: dict[str, str] = {}

    def on_dialog(dialog: Dialog) -> None:
        dialog_message["text"] = dialog.message
        dialog.accept()

    page.on("dialog", on_dialog)
    before_url = page.url
    try:
        time.sleep(request_delay)
        form.submit_button.click()
        page.wait_for_timeout(2500)
    except Exception as exc:  # noqa: BLE001
        page.remove_listener("dialog", on_dialog)
        return SubmitResult(False, f"제출 클릭 오류: {exc}")

    page.remove_listener("dialog", on_dialog)

    if dialog_message:
        return SubmitResult(False, f"경고창: {dialog_message['text']}")

    # 글쓰기 페이지를 벗어났으면 성공으로 간주
    cur = page.url
    left_write = "write.php" not in cur and "write.html" not in cur and "/write" not in cur
    if left_write and cur != before_url:
        return SubmitResult(True, "글 등록 성공", result_url=cur)

    # URL이 그대로면 본문에 오류 메시지가 있는지 확인
    body_text = page.locator("body").inner_text()
    if "비밀번호" in body_text and "필수" in body_text:
        return SubmitResult(False, "필수 입력 누락 가능성")
    return SubmitResult(False, "제출 후 페이지 전환이 없었습니다(캡차 오류 가능).")
