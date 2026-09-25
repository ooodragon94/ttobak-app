"""카톡 링크 미리보기(OG 태그).

공유가 이 게임의 핵심이다. 링크를 카톡에 붙였을 때 밋밋한 글자로 뜨면
그만큼 덜 눌린다. 여기서 지키는 것은 셋이다.

1. **태그가 있다.** 없으면 카톡이 제목만 긁어 간다.
2. **이미지가 절대 주소다.** 미리보기를 만드는 쪽은 우리 페이지 밖에서
   이미지를 따로 받아 가므로 상대 경로를 못 푼다. 이걸 틀리면 카드에
   이미지 자리가 비어 나온다 — 가장 흔한 실수다.
3. **이미지가 실제로 받아진다.** 태그만 있고 파일이 없으면 같은 결과다.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from ttobak.config import Settings
from ttobak.web.app import create_app


@pytest.fixture
def client(settings: Settings):
    changed = settings.model_copy(update={"share_url": "https://ttobak.example"})
    with TestClient(create_app(changed)) as test_client:
        yield test_client


def meta(html: str, key: str) -> str | None:
    match = re.search(
        rf'<meta (?:property|name)="{re.escape(key)}" content="([^"]*)"', html
    )
    return match.group(1) if match else None


@pytest.mark.parametrize(
    "key",
    [
        "og:type",
        "og:title",
        "og:description",
        "og:url",
        "og:image",
        "og:image:width",
        "og:image:height",
        "twitter:card",
        "description",
    ],
)
def test_필요한_태그가_다_있다(client: TestClient, key: str) -> None:
    value = meta(client.get("/").text, key)
    assert value, f"{key} 가 비어 있다"


def test_이미지가_절대주소다(client: TestClient) -> None:
    """**여기가 제일 자주 틀린다.**

    상대 경로면 카톡이 이미지를 못 받아 가고, 카드에 이미지 자리가 빈 채로
    뜬다. 우리 브라우저에서는 멀쩡히 보이므로 눈으로는 못 잡는다.
    """
    image = meta(client.get("/").text, "og:image")
    assert image.startswith("https://"), image
    assert meta(client.get("/").text, "og:url").startswith("https://")


def test_이미지가_실제로_받아진다(client: TestClient) -> None:
    """태그만 있고 파일이 없으면 태그가 없는 것과 같다."""
    response = client.get("/static/og.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 1000


def test_이미지_크기가_카드_비율이다() -> None:
    """1200x630 이 아니면 카톡이 위아래를 잘라 글자가 반쯤 사라진다."""
    from pathlib import Path

    from PIL import Image

    path = (
        Path(__file__).resolve().parent.parent
        / "src" / "ttobak" / "static" / "og.png"
    )
    with Image.open(path) as image:
        assert image.size == (1200, 630)


def test_공유_주소가_없으면_요청_주소로_만든다(settings: Settings) -> None:
    """도메인을 아직 안 정했어도 미리보기가 깨지지 않아야 한다."""
    with TestClient(create_app(settings)) as client:
        image = meta(client.get("/").text, "og:image")
    assert image.startswith("http://testserver/")
