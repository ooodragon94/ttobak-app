"""힌트 기능 테스트.

힌트는 도와주는 장치지만 게임을 무너뜨리면 안 된다. 그래서 두 가지를 못박는다.

- 충분히 헤매기 전에는 열리지 않는다.
- 아무리 써도 정답을 통째로 알려 주지는 않는다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import detail_of, join_player
from ttobak.config import Settings
from ttobak.game.rounds import puzzle_for_round
from ttobak.game.service import HINT_AFTER_ATTEMPTS
from ttobak.hangul import decompose, jamo_key
from ttobak.web.app import create_app
from ttobak.web.deps import make_player_id
from ttobak.words import load_lexicon


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def lex(settings: Settings):
    return load_lexicon(settings.data_dir, settings.puzzle_lengths)


def answer_for(settings: Settings, lex, nickname: str, round_no: int = 0) -> str:
    return puzzle_for_round(
        make_player_id(nickname),
        round_no,
        lex,
        lengths=settings.puzzle_lengths,
        salt=settings.daily_salt,
    ).answer


def wrong_for(lex, answer: str) -> str:
    words = lex.for_length(len(jamo_key(answer))).words
    return jamo_key(next(word for word in words if word != answer))


def join(client: TestClient, nickname: str = "민수", *, hints: bool = True) -> None:
    """참가한다. 힌트는 개인 설정이라 기본이 꺼짐이므로 켜 주고 시작한다."""
    assert client.post("/api/join", json={"nickname": nickname}).status_code == 200
    if hints:
        response = client.put("/api/settings", json={"hints_enabled": True})
        assert response.status_code == 200
        assert response.json()["hints_enabled"] is True


def miss(client: TestClient, lex, answer: str, times: int) -> dict:
    """``times`` 번 틀린다."""
    wrong = wrong_for(lex, answer)
    game: dict = {}
    for _ in range(times):
        game = client.post("/api/game/guess", json={"guess": wrong}).json()
    return game


def test_처음에는_힌트가_없다(client: TestClient):
    join(client)
    game = client.get("/api/game").json()
    assert game["hint_available"] is False
    # 칸 수만큼의 목록인데 아직 아무것도 안 열렸다.
    assert all(slot is None for slot in game["hints"])
    assert game["hints_left"] == 0


def test_덜_틀렸으면_힌트를_거절한다(client: TestClient, settings: Settings, lex):
    join(client)
    answer = answer_for(settings, lex, "민수")
    miss(client, lex, answer, HINT_AFTER_ATTEMPTS - 1)

    response = client.post("/api/game/hint")
    assert response.status_code == 400
    assert "더 시도하면" in detail_of(response)


def test_세_번_틀리면_힌트가_열린다(client: TestClient, settings: Settings, lex):
    join(client)
    answer = answer_for(settings, lex, "민수")
    game = miss(client, lex, answer, HINT_AFTER_ATTEMPTS)

    assert game["hint_available"] is True
    assert game["hints_left"] >= 1


def test_힌트는_앞에서부터_한_개씩_열린다(client: TestClient, settings: Settings, lex):
    join(client)
    answer = answer_for(settings, lex, "민수")
    jamos = decompose(answer)
    miss(client, lex, answer, HINT_AFTER_ATTEMPTS)

    game = client.post("/api/game/hint").json()
    # 아직 아무것도 못 맞혔으므로 첫 칸이 열린다.
    assert game["hints"][0] == jamos[0]
    assert all(slot is None for slot in game["hints"][1:])


def test_틀릴수록_힌트가_하나씩_더_열린다(client: TestClient, settings: Settings, lex):
    """헤맨 만큼만 도와준다. 처음부터 힌트로 밀고 갈 수 없다."""
    join(client)
    answer = answer_for(settings, lex, "민수")
    miss(client, lex, answer, HINT_AFTER_ATTEMPTS)

    assert client.post("/api/game/hint").status_code == 200
    # 아직 한 번 더 틀리지 않았으므로 두 번째 힌트는 거절된다.
    second = client.post("/api/game/hint")
    assert second.status_code == 400
    assert "더 열 수 있는 힌트가 없습니다" in detail_of(second)

    miss(client, lex, answer, 1)
    game = client.post("/api/game/hint").json()
    assert len([s for s in game["hints"] if s]) == 2


def test_정답을_통째로_알려_주지는_않는다(client: TestClient, settings: Settings, lex):
    """끝까지 최소 두 칸은 가려져 있어야 한다."""
    join(client)
    answer = answer_for(settings, lex, "민수")
    length = len(decompose(answer))

    revealed = 0
    for _ in range(settings.max_attempts):
        miss(client, lex, answer, 1)
        while client.post("/api/game/hint").status_code == 200:
            revealed += 1
        game = client.get("/api/game").json()
        if game["status"] != "playing":
            break

    assert revealed <= length - 2


def test_힌트를_써도_채점은_그대로다(client: TestClient, settings: Settings, lex):
    join(client)
    answer = answer_for(settings, lex, "민수")
    miss(client, lex, answer, HINT_AFTER_ATTEMPTS)
    client.post("/api/game/hint")

    game = client.post("/api/game/guess", json={"guess": jamo_key(answer)}).json()
    assert game["status"] == "won"
    assert game["rows"][-1]["marks"] == ["correct"] * game["length"]


def test_끝난_판에는_힌트를_못_쓴다(client: TestClient, settings: Settings, lex):
    join(client)
    answer = answer_for(settings, lex, "민수")
    client.post("/api/game/guess", json={"guess": jamo_key(answer)})

    response = client.post("/api/game/hint")
    assert response.status_code == 400
    assert "진행 중인 판이 없습니다" in detail_of(response)


def test_힌트를_쓰면_공유_문구에_표시된다(client: TestClient, settings: Settings, lex):
    """도움을 받고도 안 받은 척하면 기록 비교가 의미를 잃는다."""
    join(client)
    answer = answer_for(settings, lex, "민수")
    miss(client, lex, answer, HINT_AFTER_ATTEMPTS)
    client.post("/api/game/hint")

    game = client.post("/api/game/guess", json={"guess": jamo_key(answer)}).json()
    assert "💡1" in game["share_text"]


def test_힌트를_안_쓰면_표시도_없다(client: TestClient, settings: Settings, lex):
    join(client)
    answer = answer_for(settings, lex, "민수")
    game = client.post("/api/game/guess", json={"guess": jamo_key(answer)}).json()
    assert "💡" not in game["share_text"]


def test_힌트는_새로고침해도_남는다(client: TestClient, settings: Settings, lex):
    join(client)
    answer = answer_for(settings, lex, "민수")
    miss(client, lex, answer, HINT_AFTER_ATTEMPTS)
    client.post("/api/game/hint")

    game = client.get("/api/game").json()
    assert len([s for s in game["hints"] if s]) == 1


def test_다음_문제에서는_힌트가_초기화된다(client: TestClient, settings: Settings, lex):
    join(client)
    answer = answer_for(settings, lex, "민수")
    miss(client, lex, answer, HINT_AFTER_ATTEMPTS)
    client.post("/api/game/hint")
    miss(client, lex, answer, settings.max_attempts - HINT_AFTER_ATTEMPTS)

    game = client.post("/api/game/next").json()
    # 칸 수만큼의 목록인데 아직 아무것도 안 열렸다.
    assert all(slot is None for slot in game["hints"])
    assert game["hint_available"] is False


def test_새_플레이어는_힌트가_꺼져_있다(client: TestClient):
    """개인 기본값이 꺼짐이라 아무도 모르게 켜지지 않는다."""
    client.post("/api/join", json={"nickname": "민수"})
    assert client.get("/api/settings").json()["hints_enabled"] is False


def test_설정을_켜야_힌트를_쓸_수_있다(client: TestClient, settings: Settings, lex):
    join(client, hints=False)
    answer = answer_for(settings, lex, "민수")
    miss(client, lex, answer, HINT_AFTER_ATTEMPTS)

    game = client.get("/api/game").json()
    assert game["hint_available"] is False
    assert game["hints_left"] == 0

    response = client.post("/api/game/hint")
    assert response.status_code == 400
    assert "설정에서 힌트를 켜야" in detail_of(response)

    # 설정을 켜면 바로 쓸 수 있다.
    client.put("/api/settings", json={"hints_enabled": True})
    assert client.get("/api/game").json()["hint_available"] is True
    assert client.post("/api/game/hint").status_code == 200


def test_설정은_사람마다_따로_간다(client: TestClient):
    """한 사람이 켰다고 다른 사람까지 켜지면 안 된다.

    닉네임 선점이 생긴 뒤로 남의 이름으로 되돌아가려면 복구 코드가 필요하다.
    그래서 처음 받은 코드를 들고 다닌다.
    """
    code = join_player(client, "민수")
    client.put("/api/settings", json={"hints_enabled": True})
    client.post("/api/leave")

    join_player(client, "영희")
    assert client.get("/api/settings").json()["hints_enabled"] is False

    client.post("/api/leave")
    join_player(client, "민수", code=code)
    assert client.get("/api/settings").json()["hints_enabled"] is True


def test_설정은_다시_끌_수_있다(client: TestClient):
    join(client, hints=True)
    assert (
        client.put("/api/settings", json={"hints_enabled": False}).json()[
            "hints_enabled"
        ]
        is False
    )


def test_서버가_힌트를_안_주면_켤_수_없다(settings: Settings):
    """전체 스위치를 끄면 개인 설정으로도 못 켠다."""
    off = settings.model_copy(update={"hints_offered": False})
    with TestClient(create_app(off)) as client:
        client.post("/api/join", json={"nickname": "민수"})
        assert client.get("/api/settings").json()["hints_offered"] is False

        response = client.put("/api/settings", json={"hints_enabled": True})
        assert response.status_code == 400
