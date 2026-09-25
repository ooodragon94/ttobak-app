"""적대적 보안 리뷰에서 나온 지적들을 고친 뒤 그 상태를 고정한다.

여기 있는 테스트는 전부 **실제로 뚫려 있던 것**이다. 지어낸 위협이 아니라
리뷰어가 코드를 읽고 "이렇게 하면 뚫린다"고 지적한 경로를 그대로 재현한다.

되돌아가기 쉬운 것들이라 못 박아 둔다. 특히 레이트리밋 키는 한 줄만 바꿔도
제한 전체가 조용히 무의미해지는데, 겉으로는 아무 증상이 없다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ttobak.config import Settings
from ttobak.web.app import create_app
from ttobak.web.security import GLOBAL_RULE, RateLimitMiddleware, RateLimitRule


def _locked(settings: Settings) -> Settings:
    """닉네임 잠금을 켠 설정.

    기본값은 **꺼짐**이다. 카카오톡 인앱 브라우저가 쿠키를 안 남기는 경우가
    있어서, 켜 두면 사칭범이 아니라 **본인이** 자기 이름에 못 들어온다.
    그래서 잠금 자체를 재는 시험은 여기서 명시적으로 켠다.

    픽스처가 아니라 평범한 함수다. 픽스처로 두면 pytest 가 직접 호출을
    막는다 — 여기서는 설정을 값으로 받아 그때그때 바꿔 쓰는 쪽이 맞다.
    """
    return settings.model_copy(update={"require_recovery_code": True})


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# H1 — 레이트리밋 키를 위조할 수 없어야 한다
# ---------------------------------------------------------------------------


def make_middleware(unsign=None) -> RateLimitMiddleware:
    return RateLimitMiddleware(app=None, unsign=unsign)  # type: ignore[arg-type]


class FakeRequest:
    """미들웨어가 보는 만큼만 흉내 낸 요청."""

    def __init__(self, *, cookies=None, headers=None, host="10.0.0.1"):
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})()
        self.url = type("U", (), {"path": "/api/game"})()


def test_XFF_를_더_이상_읽지_않는다() -> None:
    """**이게 H1 의 핵심이다.**

    프록시는 ``X-Forwarded-For`` 를 지우지 않고 **뒤에** 실제 주소를 붙인다.
    그래서 맨 앞 항목은 클라이언트가 적어 보낸 값이다. 그걸 키로 쓰면
    요청마다 아무 주소나 넣어 한도를 무한히 피할 수 있다.
    """
    rule = RateLimitRule(limit=10, window_seconds=60, key_by_cookie=False)
    middleware = make_middleware()

    first = middleware._identity(
        FakeRequest(headers={"x-forwarded-for": "1.2.3.4"}), rule
    )
    second = middleware._identity(
        FakeRequest(headers={"x-forwarded-for": "9.9.9.9"}), rule
    )
    # XFF 를 바꿔도 키가 그대로여야 한다(둘 다 실제 접속 주소로 떨어진다).
    assert first == second


def test_CF_헤더는_쓴다() -> None:
    """Cloudflare 가 **덮어쓰는** 헤더라 클라이언트가 못 정한다."""
    rule = RateLimitRule(limit=10, window_seconds=60, key_by_cookie=False)
    middleware = make_middleware()
    key = middleware._identity(
        FakeRequest(headers={"cf-connecting-ip": "203.0.113.7"}), rule
    )
    assert "203.0.113.7" in key


def test_서명이_깨진_쿠키는_신원으로_안_쓴다() -> None:
    """쿠키를 문자열 그대로 키로 쓰면 값을 바꿔 가며 한도를 피할 수 있다."""

    def unsign(raw: str) -> str:
        if raw != "진짜서명":
            raise ValueError("서명 불일치")
        return "player-1"

    rule = RateLimitRule(limit=10, window_seconds=60)
    middleware = make_middleware(unsign)

    forged_a = middleware._identity(
        FakeRequest(cookies={"ttobak_player": "가짜1"}), rule
    )
    forged_b = middleware._identity(
        FakeRequest(cookies={"ttobak_player": "가짜2"}), rule
    )
    assert forged_a == forged_b, "위조 쿠키로 키가 갈리면 한도를 피할 수 있다"

    real = middleware._identity(
        FakeRequest(cookies={"ttobak_player": "진짜서명"}), rule
    )
    assert real == "p:player-1"
    assert real != forged_a


# ---------------------------------------------------------------------------
# H2 — 전역 버킷이 남을 막는 무기가 되면 안 된다
# ---------------------------------------------------------------------------


def test_전역_한도는_기본으로_꺼져_있다() -> None:
    """모든 방문자를 한 통에 세면 한 사람이 전원을 429 로 만들 수 있다.

    막으려고 넣은 것이 서비스를 멈추는 가장 싼 방법이 되어 있었다.
    """
    assert GLOBAL_RULE is None


def test_한_사람이_많이_써도_다른_사람은_멀쩡하다(settings: Settings) -> None:
    """전역 버킷이 살아 있으면 이 테스트가 깨진다."""
    with TestClient(create_app(settings)) as attacker:
        attacker.post("/api/join", json={"nickname": "폭주"})
        for _ in range(200):
            attacker.get("/api/game")

    with TestClient(create_app(settings)) as friend:
        response = friend.post("/api/join", json={"nickname": "친구"})
        assert response.status_code == 200, "남의 폭주 때문에 못 들어오면 안 된다"


# ---------------------------------------------------------------------------
# M1 — 본문 크기 제한을 청크 전송으로 우회할 수 없어야 한다
# ---------------------------------------------------------------------------


def test_Content_Length_로_큰_본문은_거절(client: TestClient) -> None:
    response = client.post(
        "/api/join",
        content=b"x" * 100_000,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_청크_전송으로도_우회할_수_없다(client: TestClient) -> None:
    """**Content-Length 없이 보내면 예전에는 그냥 통과했다.**

    통과하면 서버가 본문 전체를 메모리에 올린 뒤 파싱을 시도한다. 큰 것을
    여러 개 보내면 이 PC 의 메모리가 밀려 올라가고, 같은 PC 에서 도는
    다른 서비스까지 함께 느려진다.
    """

    def chunks():
        for _ in range(40):  # 256KB × 40 = 10MB
            yield b"x" * (256 * 1024)

    response = client.post(
        "/api/join",
        content=chunks(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_정상_요청은_그대로_된다(client: TestClient) -> None:
    """방어를 넣다가 정상 사용까지 막으면 아무 의미가 없다."""
    response = client.post("/api/join", json={"nickname": "정상"})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# H3 — 닉네임 위장의 피해를 줄인다
# ---------------------------------------------------------------------------


def test_남의_닉네임으로는_아예_못_들어온다(settings: Settings) -> None:
    """**지인 위협 모델에서 제일 큰 구멍이었다.**

    비밀번호가 없으니 닉네임을 아는 사람이 곧 그 사람이 됐다. 인터넷
    무작위 공격에는 의미가 없지만(이름을 모르니까) 지인은 안다. 실제로
    남의 진행 중인 판이 보이고 기회를 대신 소모시킬 수 있었다.
    """
    with TestClient(create_app(_locked(settings))) as owner:
        response = owner.post("/api/join", json={"nickname": "민수"})
        assert response.status_code == 200
        assert response.json()["recovery_code"], "처음 차지하면 복구 코드를 줘야 한다"

    with TestClient(create_app(_locked(settings))) as troll:
        blocked = troll.post("/api/join", json={"nickname": "민수"})
        assert blocked.status_code == 409

        # 정규화하면 같은 사람이 되는 변형도 막혀야 한다.
        for variant in ("민 수", "민수ㅋㅋ", "  민수  "):
            attempt = troll.post("/api/join", json={"nickname": variant})
            assert attempt.status_code == 409, variant


def test_복구_코드가_있으면_되찾는다(settings: Settings) -> None:
    """기기를 바꾸거나 브라우저를 지웠을 때의 길은 열어 둬야 한다."""
    with TestClient(create_app(settings)) as first_device:
        code = first_device.post("/api/join", json={"nickname": "민수"}).json()[
            "recovery_code"
        ]

    with TestClient(create_app(settings)) as new_device:
        response = new_device.post(
            "/api/join", json={"nickname": "민수", "recovery_code": code}
        )
        assert response.status_code == 200
        assert response.json()["display_name"] == "민수"
        # 코드는 처음 한 번만 준다. 이미 임자인 계정에 다시 발급하면 안 된다.
        assert response.json()["recovery_code"] is None


def test_틀린_복구_코드는_거절한다(settings: Settings) -> None:
    with TestClient(create_app(_locked(settings))) as owner:
        owner.post("/api/join", json={"nickname": "민수"})

    with TestClient(create_app(_locked(settings))) as troll:
        response = troll.post(
            "/api/join", json={"nickname": "민수", "recovery_code": "AAAA-BBB-CCC"}
        )
        assert response.status_code == 409


def test_다시_들어와도_표시_이름을_덮어쓰지_않는다(client: TestClient) -> None:
    """정규화하면 같은 id 라 "민수ㅋㅋ" 로 들어와도 이름이 바뀌면 안 된다.

    지금은 선점 때문에 애초에 못 들어오지만, 선점을 지나온 경우(본인이
    복구 코드로 돌아온 경우)에도 처음 정한 이름이 유지돼야 한다.
    """
    code = client.post("/api/join", json={"nickname": "민수"}).json()["recovery_code"]
    assert client.get("/api/me").json()["display_name"] == "민수"

    client.post("/api/leave")
    client.post("/api/join", json={"nickname": "민수ㅋㅋ", "recovery_code": code})
    assert client.get("/api/me").json()["display_name"] == "민수"


def test_리더보드는_참가한_사람만_본다(settings: Settings) -> None:
    """닉네임 목록은 곧 "아무나 될 수 있는 사람들의 명단" 이다."""
    with TestClient(create_app(settings)) as anonymous:
        assert anonymous.get("/api/leaderboard").status_code == 401


# ---------------------------------------------------------------------------
# M4 — 출제 시드가 기본값이면 안 된다
# ---------------------------------------------------------------------------


def test_배포용_설정에_기본_소금값이_남아_있지_않다() -> None:
    """소금값이 기본이면 소스만 있는 사람이 남의 라운드 정답을 미리 계산한다.

    ``.env`` 는 배포 환경의 실제 설정이다. 테스트가 여기를 보는 것이
    이상해 보이지만, **이 값이 기본으로 돌아가는 순간 게임이 무의미해지고
    코드만 봐서는 알 수 없다.**
    """
    from pathlib import Path

    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.is_file():
        pytest.skip(".env 가 없다(개발 환경)")
    text = env.read_text(encoding="utf-8")
    assert "TTOBAK_DAILY_SALT=" in text, "출제 소금값을 정해 두지 않았다"
    assert "TTOBAK_SECRET_KEY=change-me-in-production" not in text


def test_비밀_파일이_프로젝트_안에_없다() -> None:
    """zip 으로 백업하거나 git init 하는 순간 같이 나간다."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    leaked = [p.name for p in root.glob("*.key")] + [p.name for p in root.glob("*.pem")]
    assert not leaked, f"개인키가 프로젝트 루트에 있다: {leaked}"

    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("*.key", "*.crt", ".env"):
        assert pattern in ignore, f".gitignore 에 {pattern} 이 없다"


# ---------------------------------------------------------------------------
# 압축 — 어디에 걸고 어디에 안 거는가


def test_정적_파일은_압축해서_보낸다(client: TestClient) -> None:
    """첫 방문 102KB 를 그대로 내보내면 사람이 몰릴 때 회선이 먼저 막힌다."""
    res = client.get("/static/js/app.js", headers={"Accept-Encoding": "gzip"})
    assert res.status_code == 200
    assert res.headers.get("content-encoding") == "gzip"


def test_API_응답은_압축하지_않는다(client: TestClient) -> None:
    """**압축은 크기로 내용을 흘린다(BREACH).**

    API 응답에는 비밀(복구 코드)과 공격자가 넣을 수 있는 값(닉네임)이 같이
    담긴다. 둘이 한 응답에 있으면 크기 변화를 반복해서 재어 비밀을 한 글자씩
    좁혀 갈 수 있다. 어차피 몇백 바이트라 줄여도 얻는 것이 없으므로 뺀다.

    이건 **켜기는 쉽고 되돌리기는 어려운** 종류라 못 박아 둔다. 나중에
    누군가 "왜 API 는 압축이 없지" 하고 전역 GZip 으로 바꾸면 이 시험이 운다.
    """
    client.post("/api/join", json={"nickname": "압축이"})   # 세션 쿠키를 받는다
    res = client.get("/api/settings", headers={"Accept-Encoding": "gzip"})
    assert res.status_code == 200
    assert res.headers.get("content-encoding") != "gzip"
