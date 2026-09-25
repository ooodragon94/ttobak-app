"""사람마다 다른 자모 길이로 풀기.

지금까지는 서버가 정한 길이(5·6·7·8)가 돌아가며 나왔다. 8칸이 부담스러운
사람도 있고 5칸만 빠르게 여러 판 하고 싶은 사람도 있다.

여기서 지키는 것은 하나다. **어떤 설정에서도 낼 문제가 있어야 한다.**
빈 목록을 그대로 쓰면 게임이 멈추므로, 그 경우 서버 기본값으로 되돌린다.
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


def test_기본은_서버가_내는_길이_전부(client: TestClient, settings: Settings) -> None:
    """설정을 건드린 적 없는 사람은 지금까지와 똑같이 동작해야 한다."""
    body = client.get("/api/settings").json()
    assert body["puzzle_lengths"] == list(settings.puzzle_lengths)
    assert body["available_lengths"] == list(settings.puzzle_lengths)


def test_고른_길이만_저장된다(client: TestClient) -> None:
    body = client.put("/api/settings", json={"puzzle_lengths": [5, 6]}).json()
    assert body["puzzle_lengths"] == [5, 6]
    # 다시 읽어도 남아 있어야 한다.
    assert client.get("/api/settings").json()["puzzle_lengths"] == [5, 6]


def test_고른_길이만_출제된다(client: TestClient) -> None:
    """**이게 이 기능의 전부다.** 저장만 되고 출제가 안 바뀌면 의미가 없다."""
    client.put("/api/settings", json={"puzzle_lengths": [5]})

    seen = set()
    for _ in range(8):
        game = client.get("/api/game").json()
        seen.add(game["length"])
        # 다음 문제로 넘어가려면 지금 판을 끝내야 한다. 여기서는 길이만
        # 보면 되므로 포기하고 넘긴다.
        client.post("/api/game/next")
    assert seen == {5}, f"5칸만 나와야 하는데 {seen} 가 나왔다"


def test_빈_목록은_전부로_되돌린다(client: TestClient, settings: Settings) -> None:
    """**전부 끄면 낼 문제가 없어 게임이 멈춘다.**

    막지 않으면 설정 한 번으로 자기 계정을 못 쓰게 만들 수 있다.
    """
    client.put("/api/settings", json={"puzzle_lengths": [5]})
    body = client.put("/api/settings", json={"puzzle_lengths": []}).json()
    assert body["puzzle_lengths"] == list(settings.puzzle_lengths)

    # 게임도 정상적으로 열려야 한다.
    assert client.get("/api/game").status_code == 200


def test_서버가_안_내는_길이는_거부한다(client: TestClient) -> None:
    """사전에 없는 길이를 고르면 출제할 수 없다."""
    response = client.put("/api/settings", json={"puzzle_lengths": [99]})
    assert response.status_code == 400


def test_설정은_사람마다_따로_간다(client: TestClient, settings: Settings) -> None:
    client.put("/api/settings", json={"puzzle_lengths": [5]})
    client.post("/api/leave")
    client.post("/api/join", json={"nickname": "민수"})
    assert client.get("/api/settings").json()["puzzle_lengths"] == list(
        settings.puzzle_lengths
    )


def test_진행_중이던_판은_안_바뀐다(client: TestClient) -> None:
    """설정을 바꿨다고 풀던 문제가 갈리면 안 된다.

    판을 시작할 때 정답을 저장해 두므로 안전하다. 그 보장을 못 박아 둔다.
    """
    before = client.get("/api/game").json()
    client.put("/api/settings", json={"puzzle_lengths": [5]})
    after = client.get("/api/game").json()
    assert after["length"] == before["length"]
    assert after["round_no"] == before["round_no"]


# ---------------------------------------------------------------------------
# 시도 횟수
# ---------------------------------------------------------------------------


def test_기본은_서버_설정값(client: TestClient, settings: Settings) -> None:
    body = client.get("/api/settings").json()
    assert body["max_attempts"] == settings.max_attempts
    assert body["attempt_choices"] == [4, 5, 6, 7]


def test_시도_횟수를_바꿀_수_있다(client: TestClient) -> None:
    body = client.put("/api/settings", json={"max_attempts": 4}).json()
    assert body["max_attempts"] == 4
    assert client.get("/api/settings").json()["max_attempts"] == 4


def test_범위_밖은_거부한다(client: TestClient) -> None:
    """1번이면 운이고 20번이면 다 맞힌다. 둘 다 게임이 아니다."""
    for bad in (1, 3, 8, 100):
        assert client.put(
            "/api/settings", json={"max_attempts": bad}
        ).status_code == 400, bad


def test_진행_중이던_판은_규칙이_안_바뀐다(client: TestClient) -> None:
    """**이게 스냅숏을 두는 이유다.**

    판 도중에 횟수를 줄이면 그 자리에서 패배가 된다. 설정을 만졌다고
    풀던 판을 잃으면 안 된다.
    """
    before = client.get("/api/game").json()
    assert before["max_attempts"] == 6

    client.put("/api/settings", json={"max_attempts": 4})
    after = client.get("/api/game").json()
    assert after["max_attempts"] == 6, "풀던 판의 규칙이 바뀌었다"


def test_다음_판부터_적용된다(client: TestClient, settings: Settings) -> None:
    """판을 **끝내야** 다음 문제가 열린다.

    ``/api/game/next`` 는 진행 중인 판이 있으면 그대로 둔다(의도된 동작 —
    안 그러면 어려운 문제를 건너뛸 수 있다). 그래서 먼저 맞히고 넘어간다.
    """
    from ttobak.game.rounds import puzzle_for_round
    from ttobak.hangul import decompose
    from ttobak.web.deps import make_player_id
    from ttobak.words import load_lexicon

    client.put("/api/settings", json={"max_attempts": 4})

    lex = load_lexicon(settings.data_dir, settings.puzzle_lengths)
    current = client.get("/api/game").json()
    answer = puzzle_for_round(
        make_player_id("지오"),
        current["round_no"],
        lex,
        lengths=settings.puzzle_lengths,
        salt=settings.daily_salt,
    ).answer
    won = client.post(
        "/api/game/guess", json={"guess": "".join(decompose(answer))}
    ).json()
    assert won["status"] == "won"
    # 설정을 먼저 바꿨으므로 이 판도 4로 열렸다. 판이 **열린 시점**의 값을
    # 쓰는 것이지 서버 기본값을 쓰는 것이 아니다.
    assert won["max_attempts"] == 4

    client.post("/api/game/next")
    assert client.get("/api/game").json()["max_attempts"] == 4


# --- 사전에 빠진 말 찾기 ---
#
# 사전은 공개 목록에서 만든 것이라 멀쩡한 말이 빠져 있다. '휴게실' 은 있는데
# '탕비실' 은 없었다. 그걸 알아내는 유일한 경로가 친구의 카톡이면, 말 안 하고
# 그냥 접는 사람은 셀 수도 없다.


def test_손으로_추가한_말이_실제로_통과한다(settings: Settings) -> None:
    """``data/extra-allowed.txt`` 에 적었는데 안 먹으면 적은 뜻이 없다.

    시험용 사전이 아니라 **실제 배포 사전**을 읽는다. 여기서만큼은 진짜
    데이터를 봐야 한다 — 미니 사전으로는 원본의 누락을 잴 수 없다.
    """
    from ttobak.config import Settings as RealSettings
    from ttobak.hangul import decompose
    from ttobak.words import load_lexicon

    real = RealSettings()
    lexicon = load_lexicon(real.data_dir, real.puzzle_lengths)
    for word in ("탕비실", "자료실"):
        jamos = decompose(word)
        assert len(jamos) in real.puzzle_lengths, f"{word} 길이가 서버 범위 밖"
        assert lexicon.for_length(len(jamos)).contains("".join(jamos)), (
            f"{word} 이 사전에 없다"
        )


def test_거절_로그를_읽어_모을_수_있다() -> None:
    """로그만 남기고 볼 방법이 없으면 안 남긴 것과 같다."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from tools.missing_words import collect

    sample = (
        "2026-09-05 12:00:00 INFO ttobak.game.service | "
        "사전에 없어서 거절: ㅌㅏㅇㅂㅣㅅㅣㄹ (자모 8개)\n"
        "관계없는 줄\n"
        "2026-09-05 12:01:00 INFO ttobak.game.service | "
        "사전에 없어서 거절: ㅌㅏㅇㅂㅣㅅㅣㄹ (자모 8개)\n"
    )
    counts = collect(sample)
    assert counts[("ㅌㅏㅇㅂㅣㅅㅣㄹ", 8)] == 2
    assert len(counts) == 1, "관계없는 줄까지 세면 안 된다"


# --- 규칙으로 만들어지는 말 ---
#
# 국어사전은 '친구들' 을 표제어로 싣지 않는다. 규칙으로 만들어지기 때문이다 —
# 실으려면 모든 명사의 복수형을 실어야 한다. 그래서 36만 단어짜리 사전을 써도
# 이 부류는 통째로 빠져 있고, 목록에 하나씩 더하는 방식으로는 못 따라잡는다.


