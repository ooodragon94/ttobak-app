"""하위 경로에 걸렸을 때도 화면이 뜨는지 확인한다.

이 앱은 두 군데에 동시에 걸려 있다.

- ``https://<호스트>:8443/`` — 루트
- ``https://<호스트>/ttobak/`` — 하위 경로

Tailscale Funnel이 ``/ttobak`` 접두사를 떼고 넘기므로 **서버는 자기가 어디에
걸려 있는지 알 수 없다.** 알려 주는 헤더도 없다(직접 확인했다). 그래서 화면
쪽에서 상대 주소로 풀고, 끝에 슬래시가 없으면 스크립트가 붙여 준다.

이 파일은 그 두 장치가 살아 있는지 못박는다. 실제로 슬래시가 빠져서 화면이
통째로 안 뜬 적이 있다.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from ttobak.config import Settings
from ttobak.web.app import BOOTSTRAP_SCRIPT, BOOTSTRAP_SCRIPT_HASH, create_app


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def page(client: TestClient) -> str:
    response = client.get("/")
    assert response.status_code == 200
    return response.text


def test_자원_주소에_앞_슬래시가_없다(client: TestClient):
    """앞에 슬래시가 붙으면 하위 경로에 걸렸을 때 엉뚱한 곳을 찾는다."""
    html = page(client)
    assert 'href="/static/' not in html
    assert 'src="/static/' not in html
    assert 'href="static/' in html
    assert html.count('src="static/js/') == 3


def test_API_주소에도_앞_슬래시가_없다(client: TestClient):
    script = client.get("/static/js/api.js").text
    assert 'request("/api/' not in script
    assert 'request("api/' in script


def test_슬래시를_붙이는_스크립트가_페이지에_있다(client: TestClient):
    assert BOOTSTRAP_SCRIPT in page(client)


def test_그_스크립트가_CSP에서_허용된다(client: TestClient):
    """해시가 빠지면 브라우저가 스크립트를 막아 다시 빈 화면이 된다."""
    policy = client.get("/").headers["content-security-policy"]
    assert f"'{BOOTSTRAP_SCRIPT_HASH}'" in policy

    script_src = next(
        part.strip()
        for part in policy.split(";")
        if part.strip().startswith("script-src")
    )
    assert "'self'" in script_src
    # 해시로 정확히 한 줄만 열어 준다. 통째로 여는 것과는 다르다.
    assert "unsafe-inline" not in script_src


def test_해시가_스크립트에서_유도된다():
    """둘을 따로 적어 두면 코드를 고쳤을 때 조용히 어긋난다."""
    import base64
    import hashlib

    expected = "sha256-" + base64.b64encode(
        hashlib.sha256(BOOTSTRAP_SCRIPT.encode("utf-8")).digest()
    ).decode("ascii")
    assert expected == BOOTSTRAP_SCRIPT_HASH


def test_스크립트가_루트에서는_아무것도_안_한다():
    """루트(`/`)는 이미 슬래시로 끝나므로 넘어가야 한다. 안 그러면 무한 새로고침."""
    assert "location.pathname!=='/'" in BOOTSTRAP_SCRIPT
    assert "endsWith('/')" in BOOTSTRAP_SCRIPT


def test_스크립트가_방문_기록을_남기지_않는다():
    """`assign` 을 쓰면 뒤로 가기가 슬래시 없는 주소로 돌아가 계속 튕긴다."""
    assert "location.replace(" in BOOTSTRAP_SCRIPT
    assert "location.assign(" not in BOOTSTRAP_SCRIPT


def test_정적_파일은_상대_주소로도_받아진다(client: TestClient):
    """브라우저가 `/ttobak/static/...` 으로 부르면 Funnel이 접두사를 떼고
    서버에는 `/static/...` 으로 들어온다. 그 경로가 살아 있어야 한다."""
    html = page(client)
    for match in re.findall(r'(?:href|src)="(static/[^"]+)"', html):
        assert client.get("/" + match).status_code == 200, match
