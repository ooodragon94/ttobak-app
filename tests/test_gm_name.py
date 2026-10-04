"""'GM' 이 들어간 닉네임은 만든 사람만 쓴다.

닉네임이 곧 신원인 게임이라, 아무나 GM 을 달면 운영자를 사칭할 수 있다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ttobak.config import Settings
from ttobak.web.app import create_app

CODE = "gm-test-code"


def client_for(settings: Settings, **overrides) -> TestClient:
    return TestClient(create_app(settings.model_copy(update=overrides)))


@pytest.mark.parametrize("name", ["GM", "gm민수", "민수GM", "G M", "g.m", "Gm 태일"])
def test_암호_없이는_GM_이름을_못_쓴다(settings: Settings, name: str):
    with client_for(settings, gm_code=CODE) as client:
        response = client.post("/api/join", json={"nickname": name})
    assert response.status_code == 409
    assert "GM" in response.json()["detail"]


def test_틀린_암호도_막는다(settings: Settings):
    with client_for(settings, gm_code=CODE) as client:
        response = client.post(
            "/api/join", json={"nickname": "GM태일", "recovery_code": "wrong"}
        )
    assert response.status_code == 409


def test_암호를_넣으면_들어온다_그리고_다시_안_묻는다(settings: Settings):
    with client_for(settings, gm_code=CODE) as client:
        first = client.post(
            "/api/join", json={"nickname": "GM태일", "recovery_code": CODE}
        )
        assert first.status_code == 200
        assert first.json()["display_name"] == "GM태일"
        # 이미 그 계정으로 들어와 있으면(쿠키) 암호 없이 다시 들어온다.
        again = client.post("/api/join", json={"nickname": "GM태일"})
        assert again.status_code == 200


def test_암호를_안_정했으면_아무도_못_쓴다(settings: Settings):
    with client_for(settings, gm_code="") as client:
        response = client.post(
            "/api/join", json={"nickname": "GM", "recovery_code": ""}
        )
    assert response.status_code == 409


def test_GM_이_없는_이름은_그대로(settings: Settings):
    with client_for(settings, gm_code=CODE) as client:
        response = client.post("/api/join", json={"nickname": "민수"})
    assert response.status_code == 200
