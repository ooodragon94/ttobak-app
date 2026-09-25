"""응원하기(후원).

광고 대신 이걸 먼저 넣은 이유는 **지급 문턱**이다. 애드센스는 13만 원이
쌓여야 주는데 친구 100명 규모에서는 몇 년이 걸린다. 후원은 누가 한 번
누르면 그날 들어온다.

여기서 지키는 것은 하나다 — **링크를 안 정했으면 버튼이 안 보인다.**
눌렀는데 아무 데도 안 가는 버튼은 없느니만 못하다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ttobak.config import Settings
from ttobak.web.app import create_app


def client_with(settings: Settings, support_url: str) -> TestClient:
    changed = settings.model_copy(update={"support_url": support_url})
    return TestClient(create_app(changed))


def test_링크가_없으면_기능이_꺼진다(settings: Settings) -> None:
    """**이 파일에서 가장 중요한 테스트다.**

    링크를 안 정했는데 버튼만 떠 있으면 친구가 눌렀을 때 아무 일도 안 난다.
    후원을 못 받는 것보다 나쁘다 — "만들다 말았네"가 되니까.
    """
    with client_with(settings, "") as client:
        body = client.get("/api/support").json()
    assert body["url"] == ""
    assert body["providers"] == []


# --- 단계별 금액 링크 ---


# --- 송금 수단 ---


def test_둘_다_설정하면_둘_다_나온다(settings: Settings) -> None:
    """사람마다 깔린 앱이 다르다. 하나만 두면 그쪽을 안 쓰는 사람은 그만둔다."""
    changed = settings.model_copy(
        update={
            "support_toss": "https://toss.me/누군가/{amount}",
            "support_kakao": "https://qr.kakaopay.com/ABC",
        }
    )
    with TestClient(create_app(changed)) as client:
        body = client.get("/api/support").json()
    assert [p["key"] for p in body["providers"]] == ["toss", "kakao"]


def test_하나만_설정하면_하나만_나온다(settings: Settings) -> None:
    """선택지가 하나뿐인데 고르라고 하면 군더더기다(화면이 안 그린다)."""
    changed = settings.model_copy(
        update={"support_toss": "https://toss.me/누군가/{amount}"}
    )
    with TestClient(create_app(changed)) as client:
        body = client.get("/api/support").json()
    assert [p["key"] for p in body["providers"]] == ["toss"]


def test_기타_주소도_수단으로_잡힌다(settings: Settings) -> None:
    """토스도 카카오도 아닌 곳(Buy Me a Coffee 등)을 쓸 수도 있다."""
    with client_with(settings, "https://example.com/coffee") as client:
        body = client.get("/api/support").json()
    assert [p["key"] for p in body["providers"]] == ["other"]
    assert body["providers"][0]["url"] == "https://example.com/coffee"


# --- 문구 ---


def test_후원_화면에_부탁하는_말이_없다() -> None:
    """"보태 주세요" 는 후원을 부탁으로 만들고, 안 누른 사람을 미안하게 한다.

    친구들끼리 하는 게임에서 만들면 안 되는 감정이다.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "ttobak"
    page = Path(root / "templates" / "index.html").read_text(encoding="utf-8")
    start = page.index('id="support"')
    sheet = page[start : page.index("</div>", page.index("support__note", start))]
    for begging in ("보태 주", "부탁드", "도와주세요"):
        assert begging not in sheet, f"후원 화면에 부탁하는 말: {begging}"


# --- 금액을 링크에 실을 수 있는지 (수단마다 다르다) ---


def test_수단마다_자기_주소를_들고_온다(settings: Settings) -> None:
    """화면은 고른 수단의 주소로 버튼 하나를 만든다.

    단계별 금액을 없앴으므로(카카오페이 QR 이 금액을 못 실어서) 수단마다
    필요한 것은 주소 하나뿐이다.
    """
    changed = settings.model_copy(
        update={
            "support_toss": "https://toss.me/누군가",
            "support_kakao": "https://qr.kakaopay.com/ABC",
        }
    )
    with TestClient(create_app(changed)) as client:
        providers = client.get("/api/support").json()["providers"]
    urls = {p["key"]: p["url"] for p in providers}
    assert urls == {
        "toss": "https://toss.me/누군가",
        "kakao": "https://qr.kakaopay.com/ABC",
    }


def test_금액을_고르라고_하지_않는다() -> None:
    """카카오페이 QR 은 주소에 금액을 못 싣는다.

    그런데도 "300원 / 1,000원" 같은 단계를 늘어놓으면, 눌러 봐야 결제창은
    비어 있고 결국 앱에서 직접 쳐야 한다. 고를 이유가 없는 선택지다.
    그래서 단계를 없애고 버튼 하나만 둔다.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "ttobak"
    page = (root / "templates" / "index.html").read_text(encoding="utf-8")
    script = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")

    assert "직접 넣어" not in page, "금액을 직접 넣으라는 안내는 변명으로 읽힌다"
    assert "renderSupportButton" in script, "버튼 하나를 그리는 자리가 있어야 한다"
    assert "renderSupportTiers" not in script, "단계 렌더러가 남아 있으면 안 된다"


# --- 방별로 응원하기를 끄기 ---
#
# 친구들은 베타테스터다. 테스트해 주는 사람에게 돈 이야기를 꺼내는 것은
# 껄끄럽고, 껄끄러우면 피드백이 줄어든다. 그래서 방 단위로 끌 수 있게 했다.


def _client(settings: Settings) -> TestClient:
    changed = settings.model_copy(
        update={"support_kakao": "https://qr.kakaopay.com/ABC"}
    )
    return TestClient(create_app(changed))


def test_기본은_켜져_있다(settings: Settings) -> None:
    """마이그레이션이 조용히 기능을 꺼 버리면 안 된다."""
    with _client(settings) as client:
        client.post("/api/join", json={"nickname": "주인"})
        room = client.post("/api/rooms", json={"name": "새방"}).json()
        assert room["support_enabled"] is True
        assert client.get("/api/support").json()["providers"], "기본은 보여야 한다"


def test_끄면_창이_열릴_거리가_없어진다(settings: Settings) -> None:
    """**화면에서 버튼만 감추는 것으로는 부족하다.**

    감추는 것과 없는 것은 다르다. 서버가 빈 응답을 주면 버튼이 안 뜨는 것은
    물론이고 창 자체가 열리지 않는다 — 개발자 도구로 함수를 직접 불러도
    보여 줄 것이 없다.
    """
    with _client(settings) as client:
        client.post("/api/join", json={"nickname": "주인"})
        room = client.post("/api/rooms", json={"name": "친구들방"}).json()

        off = client.post(f"/api/rooms/{room['id']}/support", json={"enabled": False})
        assert off.status_code == 200
        assert off.json()["support_enabled"] is False

        body = client.get("/api/support").json()
        assert body["providers"] == []
        assert body["url"] == ""


def test_다시_켤_수_있다(settings: Settings) -> None:
    with _client(settings) as client:
        client.post("/api/join", json={"nickname": "주인"})
        room = client.post("/api/rooms", json={"name": "방"}).json()
        client.post(f"/api/rooms/{room['id']}/support", json={"enabled": False})
        client.post(f"/api/rooms/{room['id']}/support", json={"enabled": True})
        assert client.get("/api/support").json()["providers"]


def test_자기_방을_만들면_다시_보인다(settings: Settings) -> None:
    """**끈 방에 속해 있어도, 켜진 방이 하나라도 있으면 보여 준다.**

    내가 만든 방(친구들방·지인들방)의 사람들은 베타테스터라 껐다. 그런데
    그 친구가 자기 방을 따로 만들면 이야기가 다르다 — 자기 사람들을 데려와
    쓰는 것이고, 그때는 보여도 된다.
    """
    with _client(settings) as client:
        client.post("/api/join", json={"nickname": "주인"})
        friends = client.post("/api/rooms", json={"name": "친구들방"}).json()
        client.post(f"/api/rooms/{friends['id']}/support", json={"enabled": False})
        assert client.get("/api/support").json()["providers"] == []

        # 자기 방을 따로 만든다. 새 방은 기본이 켜짐이다.
        client.post("/api/rooms", json={"name": "내방"})
        assert client.get("/api/support").json()["providers"], (
            "켜진 방이 생겼는데도 안 보인다"
        )


def test_어느_방에도_없으면_보인다(settings: Settings) -> None:
    """링크로 들어와 혼자 푸는 사람은 누구의 친구도 아니다."""
    with _client(settings) as client:
        client.post("/api/join", json={"nickname": "혼자"})
        assert client.get("/api/support").json()["providers"]


def test_주인이_아니면_못_바꾼다(settings: Settings) -> None:
    """남의 방 설정을 건드릴 수 있으면 방을 끄고 켜는 장난이 가능해진다."""
    with _client(settings) as client:
        client.post("/api/join", json={"nickname": "주인"})
        room = client.post("/api/rooms", json={"name": "방"}).json()
        client.post("/api/leave")

        client.post("/api/join", json={"nickname": "손님"})
        client.post(f"/api/rooms/{room['id']}/join")
        denied = client.post(
            f"/api/rooms/{room['id']}/support", json={"enabled": False}
        )
        assert denied.status_code == 403


def test_회원이_아니면_방을_모르는_것과_같다(settings: Settings) -> None:
    """403 은 "그 방이 있다" 를 알려 준다. 회원이 아니면 404 여야 한다."""
    with _client(settings) as client:
        client.post("/api/join", json={"nickname": "주인"})
        room = client.post("/api/rooms", json={"name": "방"}).json()
        client.post("/api/leave")

        client.post("/api/join", json={"nickname": "남"})
        r = client.post(f"/api/rooms/{room['id']}/support", json={"enabled": False})
        assert r.status_code == 404


def test_방에_들어간_뒤_다시_물어본다() -> None:
    """**실제로 돈을 잘못 받은 사고다.**

    운영비 보내기를 보여 줄지는 "내가 어느 방에 속했는가" 로 정해진다.
    그런데 화면은 그것을 **처음 한 번만** 물어봤다. 초대 링크로 들어오면
    이런 순서가 된다.

        00:57  링크로 들어옴 — 아직 방이 없음 → 서버 "보여 줘도 된다"
        00:58  친구 방(꺼진 방)에 참가됨 → 아무도 다시 안 물어봄
        01:08  친구가 그 단추를 눌러 100원을 보냄

    베타테스터에게 돈을 받은 셈이라 돌려줘야 했다. 그래서 방 소속이
    바뀌는 **모든 자리**에서 다시 물어봐야 한다.
    """
    from pathlib import Path

    app = (
        Path(__file__).resolve().parent.parent
        / "src" / "ttobak" / "static" / "js" / "app.js"
    ).read_text(encoding="utf-8")

    # 초대 링크로 참가한 직후
    assert "await Api.joinRoom(code);" in app
    join_block = app[app.index("await Api.joinRoom(code);"):]
    assert "await loadSupport();" in join_block[:600], (
        "링크로 방에 들어간 뒤 다시 물어봐야 한다"
    )

    # 방을 새로 만든 직후
    create_block = app[app.index("await Api.createRoom(name);"):]
    assert "await loadSupport();" in create_block[:500], (
        "방을 만들면 소속이 바뀐다"
    )

    # 끄는 쪽도 처리해야 한다. 켜기만 하면 한 번 뜬 단추가 안 사라진다.
    assert "el.settingsSupport.hidden = !show;" in app, (
        "보여 줄지 말지를 매번 다시 정해야 한다 — 켜기만 하면 안 사라진다"
    )
