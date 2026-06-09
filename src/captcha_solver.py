"""캡차(kcaptcha 숫자 이미지) 인식 처리.

1순위: OpenAI 비전 모델로 스크린샷의 숫자를 직접 인식 (정확도 높음).
2순위: Tesseract OCR (전처리 후 숫자 인식) — 비전 실패/키 없음 시 폴백.
3순위: 수동 입력 폴백.
"""
from __future__ import annotations

import base64
import io
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from PIL import Image

OUTPUT_DIR = Path("output")


def _upscale_png(image_bytes: bytes, factor: int = 3) -> bytes:
    """캡차 이미지를 확대/선명화하여 비전 모델이 읽기 쉽게 만든다."""
    pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = pil.size
    pil = pil.resize((w * factor, h * factor), Image.LANCZOS)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def _clean(text: str) -> str:
    """모델 응답에서 ASCII 영숫자만 남긴다 (한글 거절 문장 등 제거)."""
    return "".join(ch for ch in text if ch.isascii() and ch.isalnum())


def _ask_vision_once(client, model: str, b64: str, expected_len: int | None) -> str:
    length_hint = f" 정확히 {expected_len}글자입니다." if expected_len else ""
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "이 이미지는 자동등록방지(CAPTCHA)로, 약간 회전·기울임·노이즈가 "
                            "있는 문자(주로 숫자 0-9, 간혹 영문)가 표시되어 있습니다. "
                            f"왼쪽부터 순서대로 한 글자도 빠짐없이 읽어주세요.{length_hint} "
                            "오직 그 문자열만 출력하고 공백·설명·따옴표는 절대 붙이지 마세요."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
    )
    return _clean(resp.choices[0].message.content or "")


def solve_with_openai(
    image_bytes: bytes,
    *,
    api_key: str,
    model: str,
    expected_len: int | None = None,
    samples: int = 3,
) -> str:
    """OpenAI 비전 모델로 캡차를 인식한다.

    이미지를 확대해 high-detail로 전송하고, 여러 번 질의해 다수결(합의)로
    가장 신뢰도 높은 결과를 고른다. 실패 시 빈 문자열.
    """
    if not api_key:
        return ""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        try:
            prepared = _upscale_png(image_bytes)
        except Exception:
            prepared = image_bytes
        b64 = base64.b64encode(prepared).decode()

        results: list[str] = []
        for _ in range(max(1, samples)):
            try:
                code = _ask_vision_once(client, model, b64, expected_len)
            except Exception:
                continue
            if not code:
                continue
            results.append(code)
            # 길이가 맞는 동일 결과가 2번 나오면 조기 종료
            if expected_len:
                matched = [r for r in results if len(r) == expected_len]
                if matched and Counter(matched).most_common(1)[0][1] >= 2:
                    break

        if not results:
            return ""
        # 기대 길이에 맞는 결과 우선, 그 중 최빈값 선택
        if expected_len:
            matched = [r for r in results if len(r) == expected_len]
            if matched:
                return Counter(matched).most_common(1)[0][0]
        return Counter(results).most_common(1)[0][0]
    except Exception:
        return ""


def configure_tesseract(tesseract_cmd: str | None) -> None:
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def _preprocess(image_bytes: bytes) -> np.ndarray:
    """캡차 이미지 바이트를 OCR 친화적인 이진 이미지로 전처리."""
    pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    arr = np.array(pil)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    # 확대로 글자 해상도 확보
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

    # 대비 강화
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)

    # Otsu 이진화 (글자가 어두운 경우 반전)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.mean(binary) < 127:
        binary = cv2.bitwise_not(binary)

    # 노이즈 제거 (작은 점/선)
    kernel = np.ones((2, 2), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    binary = cv2.medianBlur(binary, 3)

    return binary


def _ocr_digits(binary: np.ndarray) -> str:
    config = "--psm 7 -c tessedit_char_whitelist=0123456789"
    text = pytesseract.image_to_string(binary, config=config)
    return "".join(ch for ch in text if ch.isdigit())


def solve_from_bytes(image_bytes: bytes, *, expected_len: int | None = None) -> str:
    """이미지 바이트에서 캡차 숫자를 추출한다. 실패 시 빈 문자열."""
    try:
        binary = _preprocess(image_bytes)
        digits = _ocr_digits(binary)
    except Exception:
        return ""
    if expected_len and len(digits) != expected_len:
        return digits  # 호출부에서 자릿수 검증/재시도
    return digits


def save_captcha(image_bytes: bytes, name: str = "captcha.png") -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_bytes(image_bytes)
    return path


def prompt_manual(image_bytes: bytes) -> str:
    """수동 폴백: 캡차 이미지를 저장하고 콘솔에서 입력받는다."""
    path = save_captcha(image_bytes)
    print(f"[수동 입력] 캡차 이미지를 확인하세요: {path.resolve()}")
    return input("캡차 숫자를 입력하세요: ").strip()
