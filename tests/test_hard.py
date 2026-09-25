"""난이도 — 밝혀진 단서를 얼마나 강제하는가.

규칙은 **이 계열 게임이 흔히 하드 모드라고 부르는 것과 같다.** 새로 만들지
않은 이유는, 공유 문구에 붙는 표시가 설명 없이 통해야 하기 때문이다. 우리만
아는 규칙이면 자랑이 안 된다.

1. 초록으로 맞힌 자리는 그대로 둔다. → 🔒 하드
2. 노랑으로 나온 자모는 반드시 넣는다(개수까지). → 😈 헬
3. 둘 다. → 🌶️ 불닭

원조와 다른 점은 **둘을 쪼갤 수 있게 한 것**뿐이다. 두 규칙의 조이는 정도가
꽤 다른데(2번이 훨씬 세다) 하나로 묶여 있으면 그 사이가 없다.

노랑의 **자리** 는 어느 난이도에서도 강제하지 않는다. 노랑은 "여기는 아니다"
라는 뜻이라 어디로 가야 할지는 아직 모르고, 강제하면 풀 수 없는 판이 생긴다.
"""

from __future__ import annotations

from datetime import date

import pytest

from ttobak.game.hard import (
    DIFFICULTIES,
    HardModeError,
    check_difficulty,
    get_difficulty,
    relaxes,
)


def jamos(text: str) -> tuple[str, ...]:
    return tuple(text)


ANSWER = jamos("ㅎㅏㄴㅡㄹ")  # 하늘

NORMAL = get_difficulty("normal")
HARD = get_difficulty("hard")
HELL = get_difficulty("hell")
BULDAK = get_difficulty("buldak")


# --- 난이도 표 자체 ---


def test_난이도가_넷이다() -> None:
    """보통 + 규칙 하나씩 + 둘 다."""
    assert [d.key for d in DIFFICULTIES] == ["normal", "hard", "hell", "buldak"]


def test_불닭은_두_규칙_다() -> None:
    """이름만 다르고 규칙이 같으면 단계를 나눈 뜻이 없다."""
    assert (HARD.keep_correct, HARD.require_present) == (True, False)
    assert (HELL.keep_correct, HELL.require_present) == (False, True)
    assert (BULDAK.keep_correct, BULDAK.require_present) == (True, True)


def test_보통은_아무것도_강제하지_않는다() -> None:
    assert not NORMAL.restricted
    assert all(d.restricted for d in (HARD, HELL, BULDAK))


def test_표시가_서로_다르다() -> None:
    """같은 그림이 두 난이도에 붙으면 공유 문구를 보고 구분할 수 없다."""
    badges = [d.emoji for d in DIFFICULTIES if d.emoji]
    assert len(badges) == len(set(badges)) == 3


def test_연속_성공_표시와_겹치지_않는다() -> None:
    """공유 문구에서 🔥 는 이미 "🔥 5연속" 으로 쓰고 있다.

    같은 줄에 뜻이 다른 같은 그림이 둘 있으면 아무도 못 읽는다.
    """
    assert all(d.emoji != "🔥" for d in DIFFICULTIES)


def test_모르는_이름이면_기본_난이도() -> None:
    """난이도를 지우거나 이름을 바꿔도 그 값을 저장해 둔 사람이 막히면 안 된다."""
    assert get_difficulty("없는모드").key == "normal"
    assert get_difficulty(None).key == "normal"
    assert get_difficulty("").key == "normal"


# --- 규칙 1: 맞힌 자리 고정 (하드) ---


def test_첫_추측은_아무거나_된다() -> None:
    """단서가 없으면 지킬 것도 없다."""
    check_difficulty(BULDAK, jamos("ㄱㅜㄹㅡㅁ"), [], ANSWER)


def test_보통은_단서를_버려도_된다() -> None:
    """정보를 캐려고 일부러 딴 단어를 넣는 것도 하나의 전략이다."""
    previous = [jamos("ㅎㅗㅈㅜㅁ")]
    check_difficulty(NORMAL, jamos("ㄱㅜㄹㅡㅁ"), previous, ANSWER)


def test_하드는_맞힌_자리를_바꾸면_거부한다() -> None:
    """0번이 ㅎ 로 초록이었는데 다른 것을 넣으면 단서를 버리는 것이다."""
    previous = [jamos("ㅎㅗㅈㅜㅁ")]  # ㅎ 가 0번에서 초록
    with pytest.raises(HardModeError, match="1번째 칸"):
        check_difficulty(HARD, jamos("ㄱㅜㄹㅡㅁ"), previous, ANSWER)


def test_하드는_맞힌_자리를_지키면_통과한다() -> None:
    previous = [jamos("ㅎㅗㅈㅜㅁ")]
    check_difficulty(HARD, jamos("ㅎㅏㄴㅡㄹ"), previous, ANSWER)


def test_하드는_나온_자모를_빼도_봐준다() -> None:
    """**이것이 하드와 헬을 가르는 지점이다.**

    ㄴ 이 노랑으로 나왔지만 하드는 자리 규칙만 본다. 남은 칸으로 계속
    탐색할 수 있어서 헬보다 훨씬 숨통이 트인다.
    """
    previous = [jamos("ㄴㅗㅂㅣㅅ")]  # ㄴ 이 0번에서 노랑
    check_difficulty(HARD, jamos("ㄱㅗㄱㅣㅁ"), previous, ANSWER)


# --- 규칙 2: 나온 자모 필수 (헬) ---


def test_헬은_나온_자모를_빼면_거부한다() -> None:
    """ㄴ 이 **노랑**으로 나왔으면 다음에도 넣어야 한다.

    "ㄴㅗㅂㅣㅅ" 의 ㄴ 은 0번인데 정답의 ㄴ 은 2번이라 노랑이 된다.
    (초록이면 자리 규칙에 걸려 다른 이유로 막히므로, 노랑 규칙만 재려면
     자리가 달라야 한다.)
    """
    previous = [jamos("ㄴㅗㅂㅣㅅ")]
    with pytest.raises(HardModeError, match="ㄴ"):
        check_difficulty(HELL, jamos("ㄱㅗㄱㅣㅁ"), previous, ANSWER)


def test_헬은_맞힌_자리를_옮겨도_봐준다() -> None:
    """**이것이 헬과 불닭을 가르는 지점이다.**

    ㅎ 를 0번에서 맞혔지만 헬은 자모만 본다. ㅎ 를 넣기만 하면 어디에
    두든 통과한다.
    """
    previous = [jamos("ㅎㅗㅈㅜㅁ")]  # ㅎ 0번 초록, ㅗ/ㅈ/ㅜ/ㅁ 없음
    check_difficulty(HELL, jamos("ㄱㅜㅎㅏㄴ"), previous, ANSWER)
    with pytest.raises(HardModeError, match="1번째 칸"):
        check_difficulty(BULDAK, jamos("ㄱㅜㅎㅏㄴ"), previous, ANSWER)


def test_나온_자모의_자리는_안_따진다() -> None:
    """**노랑은 '여기는 아니다' 일 뿐 어디인지는 모른다.**

    자리까지 강제하면 풀 수 없는 판이 생긴다. ㄴ 을 0번에서 봤지만 3번에
    넣어도 규칙 위반이 아니다.
    """
    previous = [jamos("ㄴㅗㅂㅣㅅ")]
    check_difficulty(BULDAK, jamos("ㄱㅗㅂㄴㅣ"), previous, ANSWER)


def test_같은_자모가_두_개면_두_개를_넣어야_한다() -> None:
    """"ㅏ 가 두 개 있다" 를 알고도 하나만 쓰는 것은 단서를 버리는 것이다."""
    answer = jamos("ㅅㅏㄹㅏㅁ")  # 사람 — ㅏ 가 둘
    previous = [jamos("ㅁㅏㄷㅏㅇ")]  # ㅏ 가 두 자리에서, ㅁ 이 한 자리에서 확인된다
    # ㅁ 은 넣었지만 ㅏ 는 하나뿐이라 개수 규칙에 걸린다. 다른 자모를 빠뜨리면
    # 그쪽이 먼저 걸려서 개수 규칙을 재지 못한다.
    with pytest.raises(HardModeError, match="ㅏ"):
        check_difficulty(HELL, jamos("ㅁㅏㅅㅗㅈ"), previous, answer)
    check_difficulty(HELL, jamos("ㅅㅏㄹㅏㅁ"), previous, answer)


# --- 둘 다 (불닭) ---


def test_불닭은_여러_줄의_단서를_모두_지켜야_한다() -> None:
    # ㅎ 는 0번에서 초록, ㄴ 은 0번에서 노랑(정답의 ㄴ 은 2번).
    previous = [jamos("ㅎㅗㅈㅜㅁ"), jamos("ㄴㅗㅂㅣㅅ")]
    check_difficulty(BULDAK, jamos("ㅎㅏㄴㅡㄹ"), previous, ANSWER)
    with pytest.raises(HardModeError):
        check_difficulty(BULDAK, jamos("ㅎㅏㄹㅡㅁ"), previous, ANSWER)  # ㄴ 이 빠졌다


# --- 설정과 게임에 실제로 걸리는지 ---
#
# 위의 시험들은 규칙 함수만 본다. 아래는 **그 함수가 실제로 불리는지** 를
# 본다. 규칙이 아무리 맞아도 서버가 안 부르면 아무 소용이 없다.


@pytest.fixture
def client(settings):
    from fastapi.testclient import TestClient

    from ttobak.web.app import create_app

    with TestClient(create_app(settings)) as test_client:
        test_client.post("/api/join", json={"nickname": "난이도"})
        yield test_client


def test_설정에_난이도_선택지가_실린다(client) -> None:
    """화면이 이 목록으로 칸을 그린다. 서버가 안 주면 칸이 하나도 안 뜬다."""
    body = client.get("/api/settings").json()
    assert body["difficulty"] == "normal"
    keys = [choice["key"] for choice in body["difficulty_choices"]]
    assert keys == [d.key for d in DIFFICULTIES]
    # 규칙 참/거짓도 함께 와야 화면이 색 칸을 맞게 그린다.
    buldak = next(c for c in body["difficulty_choices"] if c["key"] == "buldak")
    assert buldak["keep_correct"] and buldak["require_present"]


def test_고른_난이도가_저장된다(client) -> None:
    saved = client.put("/api/settings", json={"difficulty": "hell"}).json()
    assert saved["difficulty"] == "hell"
    assert client.get("/api/settings").json()["difficulty"] == "hell"


def test_없는_난이도는_거부한다(client) -> None:
    """아무 문자열이나 받으면 읽을 때 조용히 보통으로 떨어진다.

    저장은 됐다는데 게임은 안 바뀌는 상태가 되고, 사용자는 자기가 뭘
    잘못했는지 알 수 없다.
    """
    assert client.put("/api/settings", json={"difficulty": "우주"}).status_code == 400
    assert client.get("/api/settings").json()["difficulty"] == "normal"


def _first_guess(client, settings) -> str:
    """지금 판에 낼 수 있는 아무 단어. 길이를 판에서 읽어 고른다."""
    from ttobak.words import load_lexicon

    length = client.get("/api/game").json()["length"]
    lex = load_lexicon(settings.data_dir, settings.puzzle_lengths)
    return sorted(lex.for_length(length).allowed_keys)[0]


def test_안_친_판은_난이도만_바뀐다(client) -> None:
    """아직 한 번도 안 쳤으면 잃을 것이 없다. 그대로 갈아 준다.

    여기서 판을 새로 열거나 패배로 적으면, 설정을 구경만 해도 손해가 난다.
    """
    client.put("/api/settings", json={"difficulty": "buldak"})
    client.post("/api/game/next")
    assert client.get("/api/game").json()["difficulty"] == "buldak"

    client.put("/api/settings", json={"difficulty": "normal"})
    assert client.get("/api/game").json()["difficulty"] == "normal"


def test_친_뒤에_바꾸면_포기로_적고_새_판을_연다(client, settings) -> None:
    """**갇히지 않게 하는 탈출구다.**

    불닭모드는 초록 자리 고정과 노랑 자모 포함을 동시에 요구해서, 조건을
    만족하는 단어가 사전에 하나도 없는 상태가 될 수 있다. 그러면 무엇을 쳐도
    거절당하고, 거절당하니 시도 횟수도 안 줄어 **지지도 못한 채 갇힌다.**

    **탈출에 대가를 물리지 않는다.** 한때 이 경우에도 판을 패배로 적고 새
    문제를 열었는데, 그건 갇힌 사람에게 벌을 주는 것이었다. 실제로 항의를
    받았고, 그 사람은 불닭을 **고른 적도 없었다** — 옛 켬/끔 하드모드가
    자동으로 불닭으로 옮겨진 계정이었다.

    느슨해지는 쪽으로는 자랑거리가 안 생기므로 막을 이유가 없다. 판에 박힌
    난이도도 같이 내려가서 공유 문구가 거짓말하지 않는다.
    """
    client.put("/api/settings", json={"difficulty": "buldak"})
    client.post("/api/game/next")
    before = client.get("/api/game").json()
    client.post("/api/game/guess", json={"guess": _first_guess(client, settings)})
    guessed = client.get("/api/game").json()

    played = client.get("/api/stats").json()["played"]
    client.put("/api/settings", json={"difficulty": "normal"})

    after = client.get("/api/game").json()
    assert after["difficulty"] == "normal", "판의 난이도도 같이 내려가야 한다"
    assert after["round_no"] == before["round_no"], "판이 바뀌면 안 된다"
    assert after["rows"] == guessed["rows"], "쳤던 것이 그대로 남아야 한다"
    assert after["status"] == "playing"
    assert client.get("/api/stats").json()["played"] == played, (
        "잃은 판이 없으므로 기록도 안 늘어야 한다"
    )


def test_난이도를_올리면_풀던_판을_잃는다(client, settings) -> None:
    """올리는 쪽은 막아야 한다.

    쉬운 규칙으로 절반을 풀어 놓고 불닭으로 올리면, 공유 문구에 불닭 표시가
    붙어서 불닭으로 푼 것처럼 보인다. **그게 진짜 자랑 방지 지점이다.**
    """
    client.post("/api/game/next")
    before = client.get("/api/game").json()
    client.post("/api/game/guess", json={"guess": _first_guess(client, settings)})

    played = client.get("/api/stats").json()["played"]
    client.put("/api/settings", json={"difficulty": "buldak"})

    after = client.get("/api/game").json()
    assert after["round_no"] == before["round_no"] + 1, "새 판이 열려야 한다"
    assert after["rows"] == [], "새 판은 비어 있어야 한다"
    assert client.get("/api/stats").json()["played"] == played + 1, (
        "포기한 판이 기록에 남아야 한다"
    )


def test_친_판이_있어야_확인을_받는다(client, settings) -> None:
    """잃을 것이 없는데 매번 물으면 잔소리가 되고, 잔소리는 안 읽힌다.

    그리고 **어느 쪽으로 바꾸느냐**로도 갈린다. 규칙을 더하는 쪽만 판을
    잃는다. 지금 판이 보통이므로 나머지 셋이 대상이고, 보통은 아니다.
    """
    client.post("/api/game/next")
    assert client.get("/api/settings").json()["costly_difficulties"] == []

    client.post("/api/game/guess", json={"guess": _first_guess(client, settings)})
    costly = client.get("/api/settings").json()["costly_difficulties"]
    assert set(costly) == {"hard", "hell", "buldak"}
    assert "normal" not in costly, "지금 난이도 그대로 두는 것이 손해일 리 없다"


def test_끝난_판은_난이도가_안_바뀐다(client, settings) -> None:
    """**여기가 진짜 자랑 방지다.**

    다 푼 뒤에 난이도를 올려서 공유 문구에 표시를 붙이는 것을 막는다.
    """
    client.put("/api/settings", json={"difficulty": "hard"})
    client.post("/api/game/next")
    length = client.get("/api/game").json()["length"]

    from ttobak.words import load_lexicon

    lex = load_lexicon(settings.data_dir, settings.puzzle_lengths)
    for guess in sorted(lex.for_length(length).allowed_keys):
        if client.get("/api/game").json()["status"] != "playing":
            break
        client.post("/api/game/guess", json={"guess": guess})

    finished = client.get("/api/game").json()
    assert finished["status"] != "playing"

    client.put("/api/settings", json={"difficulty": "buldak"})
    assert client.get("/api/game").json()["difficulty"] == "hard", (
        "끝난 판의 난이도가 바뀌면 표시가 거짓말이 된다"
    )


def test_보통이_아니면_힌트를_못_쓴다(client, settings) -> None:
    """난이도의 값어치는 "아무 도움 없이 풀었다" 는 데 있다.

    힌트를 허용하면 공유 문구의 표시가 의미를 잃는다.
    """
    client.put("/api/settings", json={"hints_enabled": True, "difficulty": "hard"})
    client.post("/api/game/next")

    state = client.get("/api/game").json()
    assert state["hint_available"] is False
    # 못 쓰는 힌트가 몇 개 남았다고 적혀 있으면 눌러 보고 거절당한다.
    assert state["hints_left"] == 0
    assert client.post("/api/game/hint").status_code == 400


def test_공유_문구에_난이도_표시가_붙는다() -> None:
    """서버가 규칙을 강제했을 때만 붙으므로 자랑해도 되는 표시다."""
    from ttobak.game.share import build_share_text

    def headline(difficulty: str) -> str:
        return build_share_text(
            nickname="누구",
            played_on=date(2026, 1, 1),
            round_no=0,
            status="won",
            max_attempts=6,
            marks_per_row=[["correct"] * 5],
            played=1,
            win_rate=1.0,
            average_attempts=1.0,
            difficulty=difficulty,
        ).splitlines()[0]

    assert "🌶️" in headline("buldak")
    assert "😈" in headline("hell")
    assert "🔒" in headline("hard")
    # 보통은 아무것도 안 붙는다. 표시가 늘 붙으면 표시의 뜻이 없다.
    plain = headline("normal")
    assert not any(badge in plain for badge in ("🌶️", "😈", "🔒"))


# --- 느슨해지는 방향인가 ---


def test_규칙을_빼기만_하면_느슨해진_것이다() -> None:
    """풀던 판을 살릴지 버릴지가 여기서 갈린다."""
    assert relaxes(NORMAL, BULDAK)
    assert relaxes(HARD, BULDAK)
    assert relaxes(HELL, BULDAK)
    assert relaxes(NORMAL, HARD)
    assert relaxes(NORMAL, HELL)


def test_규칙을_하나라도_더하면_아니다() -> None:
    """올리는 쪽은 판을 잃는 게 맞다. 쉬운 규칙으로 반쯤 풀어 놓고 올려서
    불닭으로 푼 척하는 것을 막아야 한다."""
    assert not relaxes(BULDAK, NORMAL)
    assert not relaxes(HARD, NORMAL)
    assert not relaxes(HELL, NORMAL)
    # 하드 → 헬은 자리 고정을 빼는 대신 자모 필수를 더한다. 맞바꾸기지
    # 느슨해지는 것이 아니다.
    assert not relaxes(HELL, HARD)
    assert not relaxes(HARD, HELL)


def test_같은_난이도는_느슨한_쪽으로_친다() -> None:
    """바뀐 게 없으면 판을 건드릴 이유도 없다."""
    assert all(relaxes(d, d) for d in DIFFICULTIES)
