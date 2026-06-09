"""서울컴퓨터자수 질문답변 자동 등록 — CLI 진입점.

흐름: 폼 분석 → 더미데이터 → 사이트 스크래핑 → AI 본문(EEAT) → 캡차 OCR → 제출
"""
from __future__ import annotations

import argparse
import sys

from config import settings
from src.humanize import HumanSettings
from src.runner import RunOptions, run_batch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="그누보드 질문답변 게시판 자동 글 등록"
    )
    parser.add_argument("--url", default=settings.target_url, help="글쓰기 폼 URL")
    parser.add_argument("--topic", default=None, help="AI 본문 주제 힌트")
    parser.add_argument(
        "--manual", action="store_true", help="캡차 OCR 실패 시 수동 입력 폴백"
    )
    parser.add_argument(
        "--no-headless", dest="headless", action="store_false", help="브라우저 창 표시"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="폼 작성까지만 하고 제출 생략"
    )
    parser.add_argument("--backlink-url", default=None, help="본문에 삽입할 백링크 URL")
    parser.add_argument(
        "--backlink-text", default=None, help="백링크 앵커 텍스트"
    )
    parser.add_argument(
        "--repeat", type=int, default=1, help="반복 등록 횟수"
    )
    parser.add_argument(
        "--rotate-ip", action="store_true", help="ADB로 유동 IP 변경 사용"
    )
    parser.add_argument(
        "--rotate-every", type=int, default=1, help="몇 글당 IP를 변경할지"
    )
    parser.add_argument(
        "--human", action="store_true", help="사람처럼 행동(UA/Referer/마우스/스크롤/타이핑)"
    )
    parser.add_argument(
        "--mobile", action="store_true", help="모바일 UA로 접속(m.* 사이트는 자동 적용)"
    )
    parser.set_defaults(headless=settings.headless)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    options = RunOptions(
        url=args.url,
        topic=args.topic,
        manual=args.manual,
        headless=args.headless,
        dry_run=args.dry_run,
        backlink_url=args.backlink_url,
        backlink_text=args.backlink_text,
        repeat=args.repeat,
        rotate_ip=args.rotate_ip,
        rotate_every=args.rotate_every,
        mobile=args.mobile,
        human=HumanSettings(enabled=args.human),
    )
    try:
        return run_batch(options, log=print).code
    except KeyboardInterrupt:
        print("\n중단됨.")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"오류: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
