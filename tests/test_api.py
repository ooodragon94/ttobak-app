"""HTTP API 통합 테스트.

실제 앱을 임시 데이터베이스 위에 띄우고 참가부터 여러 라운드까지의 흐름을
확인한다. 여러 명이 각자의 문제를 갖는지, 그리고 공개 노출을 대비한 방어가
동작하는지도 여기서 검증한다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import detail_of, join_player
from ttobak.config import Settings
from ttobak.game.rounds import puzzle_for_round
from ttobak.hangul import jamo_key
from ttobak.web.app import create_app
from ttobak.web.deps import make_player_id, today
from ttobak.words import load_lexicon


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def lex(settings: Settings):
    return load_lexicon(settings.data_dir, settings.puzzle_lengths)


def answer_for(settings: Settings, lex, nickname: str, round_no: int = 0) -> str:
    """테스트가 성공 시나리오를 만들려면 정답을 알아야 한다."""
    return puzzle_for_round(
        make_player_id(nickname),
        round_no,
        lex,
        lengths=settings.puzzle_lengths,
        salt=settings.daily_salt,
    ).answer


def wrong_for(lex, answer: str) -> str:
    """정답과 길이가 같으면서 정답이 아닌 사전 단어의 자모 키."""
    words = lex.for_length(len(jamo_key(answer))).words
    return jamo_key(next(word for word in words if word != answer))


def join(client: TestClient, nickname: str) -> None:
    response = client.post("/api/join", json={"nickname": nickname})
    assert response.status_code == 200, response.text


# --- 기본 흐름 ---


def test_헬스체크(client: TestClient):
    assert client.get("/healthz").json()["status"] == "ok"


def test_참가_전에는_게임에_접근할_수_없다(client: TestClient):
    assert client.get("/api/game").status_code == 401


def test_참가하면_첫_문제가_열린다(client: TestClient):
    join(client, "민수")
    game = client.get("/api/game").json()

    assert game["round_no"] == 0
    assert game["status"] == "playing"
    assert game["rows"] == []
    assert game["answer"] is None  # 진행 중에는 정답을 흘리지 않는다
    assert game["length"] in (5, 6, 7)


def test_정답을_맞히면_승리하고_정답이_공개된다(
    client: TestClient, settings: Settings, lex
):
    join(client, "민수")
    answer = answer_for(settings, lex, "민수")
    game = client.post("/api/game/guess", json={"guess": jamo_key(answer)}).json()

    assert game["status"] == "won"
    assert game["answer"] == answer
    assert game["rows"][-1]["marks"] == ["correct"] * game["length"]
    assert game["solved_today"] == 1


def test_틀리면_계속_진행되고_정답은_감춰진다(
    client: TestClient, settings: Settings, lex
):
    join(client, "민수")
    answer = answer_for(settings, lex, "민수")
    game = client.post("/api/game/guess", json={"guess": wrong_for(lex, answer)}).json()

    assert game["status"] == "playing"
    assert game["answer"] is None
    assert len(game["rows"]) == 1


def test_기회를_다_쓰면_패배하고_정답이_공개된다(
    client: TestClient, settings: Settings, lex
):
    join(client, "민수")
    answer = answer_for(settings, lex, "민수")
    wrong = wrong_for(lex, answer)

    for _ in range(settings.max_attempts):
        game = client.post("/api/game/guess", json={"guess": wrong}).json()

    assert game["status"] == "lost"
    assert game["answer"] == answer


# --- 끝없이 이어지는 라운드 ---


def test_맞히면_다음_문제로_넘어간다(client: TestClient, settings: Settings, lex):
    join(client, "민수")
    client.post(
        "/api/game/guess", json={"guess": jamo_key(answer_for(settings, lex, "민수"))}
    )

    game = client.post("/api/game/next").json()
    assert game["round_no"] == 1
    assert game["status"] == "playing"
    assert game["rows"] == []


def test_다음_문제는_직전_정답과_다르다(client: TestClient, settings: Settings, lex):
    first = answer_for(settings, lex, "민수", 0)
    second = answer_for(settings, lex, "민수", 1)
    assert first != second


def test_진행_중에는_다음_문제로_못_넘어간다(
    client: TestClient, settings: Settings, lex
):
    """어려운 문제를 건너뛰어 통계를 부풀리지 못하게 한다."""
    join(client, "민수")
    answer = answer_for(settings, lex, "민수")
    client.post("/api/game/guess", json={"guess": wrong_for(lex, answer)})

    game = client.post("/api/game/next").json()
    assert game["round_no"] == 0
    assert len(game["rows"]) == 1


def test_끝난_판에는_더_제출할_수_없다(client: TestClient, settings: Settings, lex):
    join(client, "민수")
    answer = answer_for(settings, lex, "민수")
    client.post("/api/game/guess", json={"guess": jamo_key(answer)})

    response = client.post("/api/game/guess", json={"guess": wrong_for(lex, answer)})
    assert response.status_code == 400
    assert "다음 문제" in detail_of(response)


def test_새로고침해도_진행_상황이_남는다(client: TestClient, settings: Settings, lex):
    join(client, "민수")
    answer = answer_for(settings, lex, "민수")
    client.post("/api/game/guess", json={"guess": wrong_for(lex, answer)})

    assert len(client.get("/api/game").json()["rows"]) == 1


def test_연속으로_여러_문제를_푼다(client: TestClient, settings: Settings, lex):
    join(client, "민수")
    for round_no in range(4):
        answer = answer_for(settings, lex, "민수", round_no)
        game = client.post("/api/game/guess", json={"guess": jamo_key(answer)}).json()
        assert game["status"] == "won", f"{round_no}번째 라운드"
        assert game["solved_today"] == round_no + 1
        if round_no < 3:
            client.post("/api/game/next")


# --- 입력 검증 ---


def test_사전에_없는_단어는_거절된다(client: TestClient, settings: Settings, lex):
    join(client, "민수")
    length = len(jamo_key(answer_for(settings, lex, "민수")))
    response = client.post("/api/game/guess", json={"guess": "ㅋ" * length})
    assert response.status_code == 400
    assert "사전" in detail_of(response)


def test_길이가_안_맞으면_거절된다(client: TestClient):
    join(client, "민수")
    response = client.post("/api/game/guess", json={"guess": "ㄱ"})
    assert response.status_code == 400
    assert "자모" in detail_of(response)


def test_자판에_없는_글자는_거절된다(client: TestClient):
    join(client, "민수")
    response = client.post("/api/game/guess", json={"guess": "ㄲㅐㅄㅘㅛ"})
    assert response.status_code == 400
    assert "자판" in detail_of(response)


# --- 여러 사람 ---


def test_플레이어마다_판이_따로_간다(client: TestClient, settings: Settings, lex):
    code = join_player(client, "민수")
    answer = answer_for(settings, lex, "민수")
    client.post("/api/game/guess", json={"guess": wrong_for(lex, answer)})
    assert len(client.get("/api/game").json()["rows"]) == 1

    client.post("/api/leave")
    join_player(client, "영희")
    assert client.get("/api/game").json()["rows"] == []

    client.post("/api/leave")
    join_player(client, "민수", code=code)
    assert len(client.get("/api/game").json()["rows"]) == 1


def test_순위표는_많이_맞힌_사람이_위다(client: TestClient, settings: Settings, lex):
    join(client, "고수")
    for round_no in range(2):
        client.post(
            "/api/game/guess",
            json={"guess": jamo_key(answer_for(settings, lex, "고수", round_no))},
        )
        client.post("/api/game/next")

    client.post("/api/leave")
    join(client, "하수")
    answer = answer_for(settings, lex, "하수")
    for _ in range(settings.max_attempts):
        client.post("/api/game/guess", json={"guess": wrong_for(lex, answer)})

    board = client.get("/api/leaderboard").json()
    assert board["played_on"] == today().isoformat()
    assert [row["display_name"] for row in board["entries"]] == ["고수", "하수"]
    assert board["entries"][0]["solved"] == 2
    assert board["entries"][1]["solved"] == 0


def test_통계는_승리를_기록한다(client: TestClient, settings: Settings, lex):
    join(client, "민수")
    client.post(
        "/api/game/guess", json={"guess": jamo_key(answer_for(settings, lex, "민수"))}
    )

    stats = client.get("/api/stats").json()
    assert stats["played"] == 1
    assert stats["wins"] == 1
    assert stats["current_streak"] == 1
    assert stats["guess_distribution"] == {"1": 1}


def test_닉네임은_대소문자와_기호를_무시하고_같은_사람으로_본다(
    client: TestClient, settings: Settings, lex
):
    code = join_player(client, "Minsu")
    answer = answer_for(settings, lex, "Minsu")
    client.post("/api/game/guess", json={"guess": wrong_for(lex, answer)})

    client.post("/api/leave")
    # 정규화하면 같은 사람이므로, 되돌아갈 때도 그 계정의 복구 코드를 쓴다.
    join_player(client, "  minsu  ", code=code)
    assert len(client.get("/api/game").json()["rows"]) == 1


# --- 보안 ---


def test_이상한_닉네임은_거절된다(client: TestClient):
    assert client.post("/api/join", json={"nickname": ""}).status_code == 422
    # 스크립트 태그와 제어 문자는 허용 문자 목록에서 걸린다.
    assert (
        client.post("/api/join", json={"nickname": "<script>x</script>"}).status_code
        == 422
    )
    assert client.post("/api/join", json={"nickname": "민‮su"}).status_code == 422


def test_보안_헤더가_붙는다(client: TestClient):
    headers = client.get("/").headers
    assert "default-src 'self'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"


def test_큰_본문은_거절된다(client: TestClient):
    join(client, "민수")
    response = client.post(
        "/api/game/guess",
        content=b'{"guess":"' + b"a" * 20000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_요청이_너무_잦으면_막힌다(client: TestClient):
    """참가 요청은 분당 60회로 제한된다."""
    codes = [
        client.post("/api/join", json={"nickname": f"손님{n}"}).status_code
        for n in range(70)
    ]
    assert 429 in codes
    assert codes.count(200) <= 60


def test_공개_설정이_아니면_문서가_닫혀_있다(client: TestClient):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404



# --- 복구 코드가 실제로 사람 손에 닿는가 ---
#
# 서버가 코드를 만들어 내려보내도 화면이 그것을 버리면, 그 코드는 존재한 적이
# 없는 것과 같다. 실제로 그 상태였다 — 7명이 코드를 가진 적 없이 자기
# 닉네임에 잠겼다. 그래서 여기서는 **값이 오가는지**만이 아니라 화면이 받을
# 자리를 갖고 있는지까지 본다.


def test_처음_차지하면_코드를_내려준다(claiming_client) -> None:
    body = claiming_client.post("/api/join", json={"nickname": "새사람"}).json()
    assert body["recovery_code"], "처음 차지한 닉네임에는 코드가 나와야 한다"


def test_코드가_없으면_남의_닉네임을_못_쓴다(claiming_client) -> None:
    """**이 게임의 유일한 인증이다.** 지인은 서로 닉네임을 안다."""
    first = claiming_client.post("/api/join", json={"nickname": "임자"}).json()
    assert first["recovery_code"]
    claiming_client.post("/api/leave")

    denied = claiming_client.post("/api/join", json={"nickname": "임자"})
    assert denied.status_code == 409


def test_코드가_맞으면_되찾는다(claiming_client) -> None:
    joined = claiming_client.post("/api/join", json={"nickname": "임자"})
    code = joined.json()["recovery_code"]
    claiming_client.post("/api/leave")

    ok = claiming_client.post(
        "/api/join", json={"nickname": "임자", "recovery_code": code}
    )
    assert ok.status_code == 200
    assert ok.json()["display_name"] == "임자"


def test_하이픈과_대소문자가_흔들려도_통한다(claiming_client) -> None:
    """사람이 손으로 옮겨 적는 값이다. 그 과정에서 반드시 흔들린다."""
    joined = claiming_client.post("/api/join", json={"nickname": "임자"})
    code = joined.json()["recovery_code"]
    claiming_client.post("/api/leave")

    messy = code.replace("-", "").lower()
    assert claiming_client.post(
        "/api/join", json={"nickname": "임자", "recovery_code": messy}
    ).status_code == 200


def test_코드를_새로_만들_수_있다(claiming_client) -> None:
    """코드를 본 적 없이 닉네임에 잠긴 사람들의 유일한 탈출구다.

    쿠키가 살아 있는 동안 새로 받아 두면 그 상태를 벗어난다.
    """
    joined = claiming_client.post("/api/join", json={"nickname": "임자"})
    old = joined.json()["recovery_code"]
    new = claiming_client.post("/api/recovery").json()["recovery_code"]
    assert new and new != old

    claiming_client.post("/api/leave")
    # 새 코드는 통하고,
    assert claiming_client.post(
        "/api/join", json={"nickname": "임자", "recovery_code": new}
    ).status_code == 200
    claiming_client.post("/api/leave")
    # 옛 코드는 못 쓴다. 안 그러면 "새로 만들기" 가 아무 의미가 없다.
    assert claiming_client.post(
        "/api/join", json={"nickname": "임자", "recovery_code": old}
    ).status_code == 409


def test_화면에_코드를_받을_자리가_있다() -> None:
    """**서버가 준 값을 화면이 버리면 기능이 없는 것과 같다.**

    실제로 낸 사고다. ``Api.join`` 이 코드를 보내지도 받지도 않았고,
    409 는 "복구 코드를 넣으세요" 라고만 하고 넣을 칸이 없었다.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "ttobak"
    page = (root / "templates" / "index.html").read_text(encoding="utf-8")
    app = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")
    api = (root / "static" / "js" / "api.js").read_text(encoding="utf-8")

    assert 'id="join-recovery"' in page, "409 일 때 코드를 넣을 칸이 있어야 한다"
    assert 'id="recovery-code"' in page, "받은 코드를 보여 줄 자리가 있어야 한다"
    assert "recovery_code: recoveryCode" in api, "참가할 때 코드를 실어 보내야 한다"
    assert "me?.recovery_code" in app, "받은 코드를 반드시 보여 줘야 한다"


def test_한_번도_안_치고_포기해도_판이_보인다(client, settings) -> None:
    """**실제로 사람을 가둔 사고다.**

    한 글자도 안 치고 포기하면 공유할 격자가 없다. 그때 공유 문구를 만드는
    함수는 예외를 던진다 — 빈 격자를 지어내는 것보다 낫기 때문이다.

    그런데 그 함수가 **판을 보여 주는 길목**에 있었다. 그래서 예외가 그대로
    올라가 판 전체가 500 이 됐고, 포기는 이미 기록된 뒤라 다시 들어와도
    계속 500 이었다. 그 사람은 게임에서 영영 빠져나올 수 없었다.

    친구가 "포기했더니 아무것도 안 된다" 고 말해 주기 전까지, 서버 로그에는
    ``GET /api/game 500`` 만 반복해서 찍히고 있었다.

    공유 문구가 없는 것은 아쉬운 일이고, 판을 못 보는 것은 못 쓰는 일이다.
    """
    join_player(client, "포기맨")
    assert client.post("/api/game/next").status_code == 200

    resigned = client.post("/api/game/resign")
    assert resigned.status_code == 200, resigned.text
    body = resigned.json()
    assert body["status"] == "lost"
    assert body["answer"], "포기하면 정답은 알려 준다"
    assert body["share_text"] is None, "칠 것이 없으면 공유 문구도 없다"

    # 핵심: 다시 들어와도 판이 보여야 한다. 여기가 500 이면 갇힌다.
    again = client.get("/api/game")
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "lost"

    # 그리고 다음 문제로 넘어갈 수 있어야 한다.
    assert client.post("/api/game/next").status_code == 200
    assert client.get("/api/game").json()["status"] == "playing"
