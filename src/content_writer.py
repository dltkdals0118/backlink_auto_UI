"""OpenAI를 사용해 EEAT 구조의 제목/본문을 생성."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass

from openai import OpenAI

from .scraper import SiteContext

# 주제 미입력 시 사용할 다양한 랜덤 주제 풀
_RANDOM_TOPICS = [
    "자동차 타이어 교체 시기와 관리법",
    "캠핑 초보를 위한 장비 추천",
    "집에서 키우기 쉬운 반려식물",
    "여름철 강아지 건강관리 팁",
    "재택근무 책상 정리와 인테리어",
    "가성비 좋은 무선 이어폰 후기",
    "주말 당일치기 국내 여행지 추천",
    "홈트레이닝으로 체지방 줄이기",
    "초보자를 위한 주식 투자 기초",
    "전기요금 아끼는 생활 습관",
    "겨울철 피부 건조 관리법",
    "다이어트 도시락 메뉴 아이디어",
    "중고차 구매 시 체크리스트",
    "노트북 발열 줄이는 방법",
    "원룸 수납 공간 활용 꿀팁",
    "커피 머신 종류와 선택 기준",
    "아이와 함께 가기 좋은 실내 놀이터",
    "러닝화 고르는 법과 추천",
    "캡슐 커피 vs 원두 커피 비교",
    "스마트폰 배터리 오래 쓰는 법",
    "제철 과일로 만드는 간단 디저트",
    "전기차 충전과 유지비 후기",
    "헬스장 초보 운동 루틴",
    "비 오는 날 실내 데이트 코스",
    "공기청정기 필터 관리 주기",
    "직장인 점심 도시락 추천",
    "겨울 난방비 절약 인테리어",
    "반려묘 화장실 모래 비교",
    "면역력 높이는 생활 습관",
    "주방 세제·청소 꿀팁",
]


def random_topic() -> str:
    return random.choice(_RANDOM_TOPICS)


@dataclass
class GeneratedPost:
    subject: str
    content: str
    model_used: str = ""


_SYSTEM_PROMPT = """당신은 한국어 콘텐츠 작가입니다.
주어진 주제에 대해 게시판에 올릴 자연스러운 글(경험/후기/정보성)을 EEAT 원칙으로 작성합니다.

EEAT:
- Experience(경험): 실제 경험을 1인칭으로 구체적으로 서술
- Expertise(전문성): 주제에 대한 구체적이고 정확한 디테일
- Authoritativeness(권위): 신뢰할 만한 근거나 요소를 자연스럽게 언급
- Trustworthiness(신뢰): 과장·광고 표현을 피하고 사실 기반의 진솔한 톤 유지

규칙:
- 사람이 직접 쓴 듯 자연스러운 구어체
- 200~500자 분량
- 제목과 본문은 반드시 주어진 주제를 중심으로 작성한다
- 결과는 반드시 JSON으로만 출력: {"subject": "...", "content": "..."}"""


def _build_user_prompt(context: SiteContext, topic: str | None) -> str:
    # 주제가 주어지면 주제를 글의 핵심으로 삼는다 (사이트 업종에 끌려가지 않도록
    # 사이트 컨텍스트는 주입하지 않는다).
    if topic:
        return (
            "다음 주제로 글을 작성하세요. 이 주제가 글의 핵심이며, "
            "제목과 본문 모두 반드시 이 주제를 중심으로 작성해야 합니다.\n\n"
            f"[주제] {topic}\n\n"
            '결과는 JSON {"subject": "제목", "content": "본문"} 형식으로만 응답하세요.'
        )

    # 주제 미지정 시: 사이트 정보를 바탕으로 관련 문의/후기 글 작성
    parts = ["아래 사이트 정보를 참고하여 게시판 문의/후기 글을 작성하세요.\n"]
    ctx = context.as_prompt_context()
    if ctx:
        parts.append("[사이트 정보]\n" + ctx + "\n")
    parts.append('결과는 JSON {"subject": "제목", "content": "본문"} 형식으로만 응답하세요.')
    return "\n".join(parts)


def _parse_json(raw: str) -> GeneratedPost:
    text = raw.strip()
    if text.startswith("```"):
        # ```json ... ``` 펜스 제거
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    data = json.loads(text)
    return GeneratedPost(
        subject=str(data.get("subject", "")).strip(),
        content=str(data.get("content", "")).strip(),
    )


def _is_reasoning_model(model: str) -> bool:
    """o1/o3/o4 등 추론 계열 모델인지 판별."""
    return model.lower().startswith(("o1", "o3", "o4"))


def _create_completion(client: OpenAI, model: str, user_prompt: str):
    """모델 계열에 맞는 파라미터로 chat completion을 호출한다.

    추론 모델(o1 등)은 temperature/response_format/system 역할을 지원하지 않으므로
    시스템 지침을 user 메시지에 통합하고 해당 파라미터를 생략한다.
    """
    if _is_reasoning_model(model):
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": _SYSTEM_PROMPT + "\n\n" + user_prompt},
            ],
        )
    return client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.9,
        response_format={"type": "json_object"},
    )


def generate_post(
    *,
    api_key: str,
    model: str,
    context: SiteContext,
    topic: str | None = None,
    fallback_model: str = "gpt-4o",
) -> GeneratedPost:
    """EEAT 구조의 제목+본문을 생성한다.

    model 호출이 실패하면(접근 권한 없음/모델명 오류 등) fallback_model로 1회 재시도.
    """
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")

    client = OpenAI(api_key=api_key)
    user_prompt = _build_user_prompt(context, topic)

    used = model
    try:
        response = _create_completion(client, model, user_prompt)
    except Exception as exc:  # noqa: BLE001
        if fallback_model and fallback_model != model:
            used = fallback_model
            response = _create_completion(client, fallback_model, user_prompt)
        else:
            raise RuntimeError(f"콘텐츠 생성 실패: {exc}") from exc

    raw = response.choices[0].message.content or ""
    post = _parse_json(raw)
    if not post.subject or not post.content:
        raise RuntimeError("AI 응답에서 제목/본문을 파싱하지 못했습니다.")
    post.model_used = used
    return post
