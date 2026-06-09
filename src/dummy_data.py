"""랜덤 더미 작성자 정보 생성."""
from __future__ import annotations

import random
import string
from dataclasses import dataclass

from faker import Faker

_faker = Faker("ko_KR")


@dataclass
class DummyIdentity:
    name: str
    password: str
    email: str
    homepage: str


def _random_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def generate_identity() -> DummyIdentity:
    """그누보드 비회원 작성에 사용할 더미 신원 정보를 생성한다."""
    name = _faker.name()
    username = _faker.user_name()
    # Cafe24 등 쇼핑몰 이메일 select 목록과 맞추기(naver/gmail/daum)
    domain = random.choice(["naver.com", "gmail.com", "daum.net"])
    email = f"{username}@{domain}"
    homepage = _faker.url()
    return DummyIdentity(
        name=name,
        password=_random_password(),
        email=email,
        homepage=homepage,
    )
