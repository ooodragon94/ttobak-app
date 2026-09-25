"""후원 신고와 감사 표시.

**후원 여부를 자동으로 알 방법이 없다.** 카카오페이 QR 은 우리 서버에
아무것도 알려 주지 않는다 — 웹훅도 API 도 없고, 돈은 상대 앱에서 주인 앱으로
바로 간다. 진짜 결제 연동은 사업자등록이 필요해 이 규모에 맞지 않는다.

그래서 본인이 "보냈어요" 를 누른 것을 그대로 믿는다. 거짓으로 얻는 것이
배지 하나뿐이라 검증에 드는 복잡도가 값어치보다 크다. 여기서 지키는 것은
"믿되 기록은 남긴다" 뿐이다 — 나중에 주인이 카카오페이 내역과 대조할 수 있게.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ttobak.config import Settings
from ttobak.web.app import create_app


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        test_client.post("/api/join", json={"nickname": "지오"})
        yield test_client


def test_보냈어요를_누르면_기록된다(client: TestClient) -> None:
    response = client.post("/api/support/thanks", json={"amount": 1000})
    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_여러_번_보내면_횟수가_는다(client: TestClient) -> None:
    """두 번째부터는 감사 문구가 달라진다. 같은 말을 반복하면 성의가 없다."""
    for expected in (1, 2, 3):
        body = client.post("/api/support/thanks", json={"amount": 500}).json()
        assert body["count"] == expected


def test_참가하지_않으면_못_보낸다(settings: Settings) -> None:
    with TestClient(create_app(settings)) as anonymous:
        assert anonymous.post(
            "/api/support/thanks", json={"amount": 1000}
        ).status_code == 401


def test_말도_안_되는_금액은_거부한다(client: TestClient) -> None:
    """실수로 0 이 몇 개 더 붙는 것을 막는다. 기록이 이상해지면 대조가 안 된다."""
    assert client.post(
        "/api/support/thanks", json={"amount": -1}
    ).status_code == 422
    assert client.post(
        "/api/support/thanks", json={"amount": 99_999_999}
    ).status_code == 422


def test_순위표에_배지가_붙는다(client: TestClient) -> None:
    """이게 유일한 보답이다. 안 붙으면 후원 기능 자체가 무의미해진다."""
    before = client.get("/api/leaderboard").json()["entries"]
    assert all(not row["supporter"] for row in before)

    client.post("/api/support/thanks", json={"amount": 1000})

    # 순위표에 뜨려면 오늘 한 판을 끝내야 한다. 그건 다른 테스트가 다루므로
    # 여기서는 저장소가 이름을 제대로 돌려주는지만 본다.
    from ttobak.db.repository import Database

    database = Database(client.app.state.settings.database_path)
    assert "지오" in database.supporter_names()
