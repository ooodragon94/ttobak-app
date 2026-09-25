"""방 · 오늘의 문제 · 댓글.

이 파일이 지키는 것은 크게 둘이다.

**첫째, 같은 방이면 같은 문제.** 이게 깨지면 순위표도 댓글도 의미가 없다.
사람마다 다른 단어를 풀면 "난 세 번 만에 맞췄다"를 비교할 수 없다.

**둘째, 남의 방이 안 보인다.** 방 코드는 카톡으로 돌아다니는 링크에 실려
있어서, 코드를 아는 것과 회원인 것은 다르다. 그리고 못 푼 사람에게 댓글이
보이면 한 줄로 그날 문제가 끝난다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ttobak.config import Settings
from ttobak.game.rooms import ROOM_CODE_LENGTH, new_room_code
from ttobak.game.rounds import puzzle_for_day
from ttobak.web.app import create_app
from ttobak.web.deps import today
from ttobak.words import load_lexicon


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def lex(settings: Settings):
    return load_lexicon(settings.data_dir, settings.puzzle_lengths)


def player(app, nickname: str) -> TestClient:
    """닉네임으로 참가한 클라이언트. 쿠키가 각자 따로 유지된다."""
    client = TestClient(app)
    client.__enter__()
    client.post("/api/join", json={"nickname": nickname})
    return client


@pytest.fixture
def jio(app):
    return player(app, "지오")


@pytest.fixture
def minsu(app):
    return player(app, "민수")


@pytest.fixture
def stranger(app):
    return player(app, "외부인")


def make_room(client: TestClient, name: str = "친구들") -> str:
    response = client.post("/api/rooms", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def answer_of(code: str, settings: Settings, lex, slot: int = 0) -> str:
    """그 방의 오늘 ``slot`` 번째 정답.

    소금값은 **API 로 안 나온다**(나가면 그것만으로 정답을 계산할 수 있다).
    그래서 DB 에서 직접 읽는다. 테스트만 할 수 있는 일이고, 그게 맞다.
    """
    from ttobak.db import Database

    database = Database(settings.database_path)
    with database.connect() as connection:
        salt = connection.execute(
            "SELECT puzzle_salt FROM rooms WHERE id = ?", (code,)
        ).fetchone()["puzzle_salt"]
    from ttobak.game.rounds import daily_lengths

    return puzzle_for_day(
        salt,
        today().isoformat(),
        lex,
        lengths=daily_lengths(slot, settings.puzzle_lengths),
        slot=slot,
    ).answer


def wrong_guess(code: str, settings: Settings, lex, slot: int = 0) -> str:
    """정답이 **아닌** 같은 길이의 단어.

    고정된 오답을 쓰면 안 된다. 방 소금값이 매번 다르므로 그 단어가 우연히
    정답일 수 있고, 그러면 테스트가 가끔만 깨진다. 실제로 그렇게 깨졌다.
    """
    answer = answer_of(code, settings, lex, slot)
    from ttobak.hangul import decompose

    length = len(decompose(answer))
    for word in lex.for_length(length).words:
        if word != answer:
            return "".join(decompose(word))
    raise AssertionError(f"길이 {length} 사전에 단어가 하나뿐이다")


def solve(client: TestClient, code: str, settings: Settings, lex) -> None:
    """오늘 문제를 **전부** 정답으로 끝낸다. 댓글 테스트의 준비 단계다.

    하루에 여러 문제를 내므로 하나만 풀어서는 댓글을 못 쓴다 — 1번만 끝낸
    사람에게 댓글을 보여 주면 2번에 대한 이야기가 스포일러가 된다.
    """
    from ttobak.game.rounds import DAILY_SLOTS
    from ttobak.hangul import decompose

    for slot in range(DAILY_SLOTS):
        answer = answer_of(code, settings, lex, slot)
        response = client.post(
            f"/api/rooms/{code}/daily/guess",
            json={"guess": "".join(decompose(answer)), "slot": slot},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "won"


# ---------------------------------------------------------------------------
# 방 코드
# ---------------------------------------------------------------------------


def test_방_코드는_추측할_수_없다() -> None:
    """코드가 곧 열쇠다. 순번이나 시각에서 만들면 옆 방을 계산할 수 있다."""
    codes = {new_room_code() for _ in range(500)}
    assert len(codes) == 500, "500개를 뽑았는데 겹쳤다면 난수가 아니다"
    assert all(len(c) == ROOM_CODE_LENGTH for c in codes)


def test_헷갈리는_글자를_안_쓴다() -> None:
    """코드는 카톡으로 옮겨 적히고 말로 불러 주게 된다. 0/O, 1/l 은 뺀다."""
    joined = "".join(new_room_code() for _ in range(200))
    for confusing in "0O1lI":
        assert confusing not in joined


# ---------------------------------------------------------------------------
# 방 만들기 / 들어가기
# ---------------------------------------------------------------------------


def test_방을_만들면_내가_회원이다(jio) -> None:
    code = make_room(jio)
    rooms = jio.get("/api/rooms").json()["rooms"]
    assert [r["id"] for r in rooms] == [code]
    assert rooms[0]["is_owner"] is True
    assert rooms[0]["member_count"] == 1


def test_이름이_비면_거부한다(jio) -> None:
    assert jio.post("/api/rooms", json={"name": "   "}).status_code == 422


def test_초대_링크로_들어간다(jio, minsu) -> None:
    code = make_room(jio)
    response = minsu.post(f"/api/rooms/{code}/join")
    assert response.status_code == 200
    assert response.json()["member_count"] == 2
    assert response.json()["is_owner"] is False


def test_두_번_들어가도_한_명이다(jio, minsu) -> None:
    """링크를 두 번 눌렀을 뿐이다. 오류로 다룰 일이 아니다."""
    code = make_room(jio)
    minsu.post(f"/api/rooms/{code}/join")
    response = minsu.post(f"/api/rooms/{code}/join")
    assert response.status_code == 200
    assert response.json()["member_count"] == 2


def test_나가면_목록에서_사라진다(jio, minsu) -> None:
    code = make_room(jio)
    minsu.post(f"/api/rooms/{code}/join")
    assert minsu.post(f"/api/rooms/{code}/leave").status_code == 204
    assert minsu.get("/api/rooms").json()["rooms"] == []


# ---------------------------------------------------------------------------
# 남의 방은 안 보인다
# ---------------------------------------------------------------------------


def test_회원이_아니면_방이_없는_것처럼_답한다(jio, stranger) -> None:
    """**403 이 아니라 404 여야 한다.**

    403 은 "그 방은 있는데 너는 못 본다"는 뜻이라, 코드를 찍어 보는 사람에게
    맞았다는 신호를 준다. 없는 것처럼 답해야 아무것도 알아낼 수 없다.
    """
    code = make_room(jio)
    assert stranger.get(f"/api/rooms/{code}/daily").status_code == 404
    assert stranger.get(f"/api/rooms/{code}/comments").status_code == 404
    assert stranger.post(f"/api/rooms/{code}/leave").status_code == 404
    assert (
        stranger.post(
            f"/api/rooms/{code}/daily/guess", json={"guess": "ㅎㅏㄴㅡㄹ"}
        ).status_code
        == 404
    )


def test_없는_방도_같은_404(jio) -> None:
    """존재하는 방과 없는 방의 답이 달라지면 그 차이가 곧 정보다."""
    missing = jio.get(f"/api/rooms/{new_room_code()}/daily")
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "bad",
    ["", "짧음", "../../etc/passwd", "'; DROP TABLE rooms; --", "a" * 200],
)
def test_이상한_코드는_DB까지_가지_않는다(jio, bad: str) -> None:
    response = jio.get(f"/api/rooms/{bad}/daily")
    assert response.status_code in (404, 422)


# ---------------------------------------------------------------------------
# 오늘의 문제 — 같은 방이면 같은 문제
# ---------------------------------------------------------------------------


def test_같은_방_사람은_같은_문제를_푼다(jio, minsu, settings, lex) -> None:
    """**이 기능의 존재 이유다.**

    사람마다 다른 문제를 풀면 시도 횟수를 비교할 수도, 풀이를 보여 줄 수도,
    "와 이걸 푸네"라고 할 수도 없다.
    """
    code = make_room(jio)
    minsu.post(f"/api/rooms/{code}/join")

    mine = jio.get(f"/api/rooms/{code}/daily").json()
    theirs = minsu.get(f"/api/rooms/{code}/daily").json()
    assert mine["length"] == theirs["length"]
    assert mine["play_date"] == theirs["play_date"]


def test_다른_방은_다른_문제다(jio, settings, lex) -> None:
    """한 방에서 답을 알아냈다고 다른 방까지 뚫리면 안 된다."""
    from ttobak.db import Database

    first, second = make_room(jio, "A"), make_room(jio, "B")
    database = Database(settings.database_path)
    with database.connect() as connection:
        salts = {
            row["id"]: row["puzzle_salt"]
            for row in connection.execute("SELECT id, puzzle_salt FROM rooms")
        }
    assert salts[first] != salts[second]


def test_풀기_전에는_정답을_안_준다(jio) -> None:
    """응답에 담아 두고 화면에서 안 보여 주는 것은 방어가 아니다."""
    code = make_room(jio)
    state = jio.get(f"/api/rooms/{code}/daily").json()
    assert state["answer"] is None
    assert state["status"] == "playing"


def test_맞히면_정답과_순위가_보인다(jio, settings, lex) -> None:
    code = make_room(jio)
    solve(jio, code, settings, lex)
    state = jio.get(f"/api/rooms/{code}/daily").json()
    assert state["answer"] is not None
    assert state["solved_count"] == 1
    assert state["standings"][0]["is_me"] is True


def test_끝난_판에는_더_못_넣는다(jio, settings, lex) -> None:
    code = make_room(jio)
    solve(jio, code, settings, lex)
    response = jio.post(f"/api/rooms/{code}/daily/guess", json={"guess": "ㅎㅏㄴㅡㄹ"})
    assert response.status_code == 409


def test_순위는_시도_횟수_순이다(jio, minsu, settings, lex) -> None:
    """같은 단어를 풀었으므로 시도 횟수로 바로 줄을 세울 수 있다.

    **어느 문제인지를 반드시 지정한다.** 순위는 문제마다 따로 매겨진다 —
    1번과 2번은 다른 낱말이고 칸 수도 달라서, 둘의 시도 횟수를 더한 값으로
    줄을 세우면 아무 뜻도 없는 등수가 나온다. 여기서 재려는 것은 아래에서
    틀린 추측을 넣은 **1번** 의 순서다.
    """
    code = make_room(jio)
    minsu.post(f"/api/rooms/{code}/join")

    jio.post(
        f"/api/rooms/{code}/daily/guess",
        json={"guess": wrong_guess(code, settings, lex)},
    )
    solve(jio, code, settings, lex)      # 지오는 2번 (틀린 것 포함)
    solve(minsu, code, settings, lex)    # 민수는 1번

    rows = jio.get(f"/api/rooms/{code}/daily?slot=0").json()["standings"]
    assert [r["display_name"] for r in rows] == ["민수", "지오"]


# ---------------------------------------------------------------------------
# 댓글 — 스포일러 방지
# ---------------------------------------------------------------------------


def test_못_푼_사람은_댓글을_못_본다(jio) -> None:
    """**댓글 한 줄이 그날 문제를 끝낸다.**

    "ㄱ으로 시작함"은 물론이고 "받침이 어려웠다"만 해도 힌트다. 문구를
    검사해서 거르는 것은 불가능하므로 규칙으로 막는 수밖에 없다.
    """
    code = make_room(jio)
    assert jio.get(f"/api/rooms/{code}/comments").status_code == 403


def test_못_푼_사람은_댓글을_못_쓴다(jio) -> None:
    code = make_room(jio)
    response = jio.post(f"/api/rooms/{code}/comments", json={"body": "ㄱ으로 시작함"})
    assert response.status_code == 403


def test_풀고_나면_쓸_수_있다(jio, settings, lex) -> None:
    code = make_room(jio)
    solve(jio, code, settings, lex)
    response = jio.post(f"/api/rooms/{code}/comments", json={"body": "와 이걸 푸네"})
    assert response.status_code == 200
    assert [c["body"] for c in response.json()["comments"]] == ["와 이걸 푸네"]


def test_같은_방_사람끼리_보인다(jio, minsu, settings, lex) -> None:
    code = make_room(jio)
    minsu.post(f"/api/rooms/{code}/join")
    solve(jio, code, settings, lex)
    solve(minsu, code, settings, lex)

    jio.post(f"/api/rooms/{code}/comments", json={"body": "겨우 맞춤 ㅋㅋ"})
    rows = minsu.get(f"/api/rooms/{code}/comments").json()["comments"]
    assert [(c["display_name"], c["is_me"]) for c in rows] == [("지오", False)]


def test_빈_댓글은_거부한다(jio, settings, lex) -> None:
    code = make_room(jio)
    solve(jio, code, settings, lex)
    assert (
        jio.post(f"/api/rooms/{code}/comments", json={"body": "   "}).status_code == 422
    )


def test_너무_길면_거부한다(jio, settings, lex) -> None:
    code = make_room(jio)
    solve(jio, code, settings, lex)
    response = jio.post(f"/api/rooms/{code}/comments", json={"body": "가" * 200})
    assert response.status_code == 422


def test_하루_개수에_상한이_있다(jio, settings, lex) -> None:
    """대화를 막는 것이 아니라 한 사람이 화면을 차지하는 것을 막는다."""
    from ttobak.game.comments import MAX_COMMENTS_PER_DAY

    code = make_room(jio)
    solve(jio, code, settings, lex)
    for i in range(MAX_COMMENTS_PER_DAY):
        assert (
            jio.post(f"/api/rooms/{code}/comments", json={"body": f"{i}번째"})
        ).status_code == 200
    over = jio.post(f"/api/rooms/{code}/comments", json={"body": "하나 더"})
    assert over.status_code == 429


def test_스크립트를_써도_글자로만_저장된다(jio, settings, lex) -> None:
    """HTML 을 지우지 않는다. 화면에서 textContent 로만 넣기 때문이다.

    여기서 태그를 지우려 들면 "a < b" 같은 멀쩡한 말이 깨지고, 어설픈 필터를
    우회하는 쪽이 이긴다. 막는 곳은 출력하는 곳 한 군데여야 한다.
    """
    code = make_room(jio)
    solve(jio, code, settings, lex)
    payload = "<script>alert(1)</script>"
    response = jio.post(f"/api/rooms/{code}/comments", json={"body": payload})
    assert response.status_code == 200
    # 있는 그대로 남는다. 화면이 이스케이프한다.
    assert response.json()["comments"][0]["body"] == payload


def test_안_보이는_글자는_지운다(jio, settings, lex) -> None:
    """U+202E 는 뒤 글자를 거꾸로 보이게 만든다. 남을 속이기 너무 쉽다.

    문자를 소스에 그대로 적지 않고 이스케이프로 만든다. 눈에 안 보이는
    글자를 소스에 박아 두면 편집기마다 다르게 보이고, 실제로 이 파일에
    널 바이트가 섞여 들어가 테스트가 통째로 안 읽혔다.
    """
    code = make_room(jio)
    solve(jio, code, settings, lex)

    # chr() 로 만든다. 소스에 그대로 적으면 편집기와 도구를 거치며
    # 깨진다(실제로 널 바이트가 박혀 테스트가 통째로 안 읽혔다).
    payload = chr(0x202E) + "안녕" + chr(0) + chr(0x200B)
    response = jio.post(f"/api/rooms/{code}/comments", json={"body": payload})
    assert response.status_code == 200

    body = response.json()["comments"][0]["body"]
    assert body == "안녕", f"보이지 않는 글자가 남았다: {body!r}"


# ---------------------------------------------------------------------------
# 결과 공유 — 링크에 방 코드가 실려야 한다
# ---------------------------------------------------------------------------


def test_풀기_전에는_공유_문구가_없다(jio) -> None:
    """진행 중에 공유하면 아직 아무것도 없고, 남은 사람에게 힌트가 된다."""
    code = make_room(jio)
    assert jio.get(f"/api/rooms/{code}/daily").json()["share_text"] is None


def test_공유_문구에_방_코드가_들어간다(settings, lex) -> None:
    """**이게 핵심이다.**

    코드가 없으면 받은 사람이 앱만 열리고 같은 방으로 못 들어온다. 그러면
    같은 문제를 푼 사람끼리 비교한다는 이 기능의 전제가 무너진다.
    """
    changed = settings.model_copy(update={"share_url": "https://ttobak.example"})
    from ttobak.web.app import create_app

    with TestClient(create_app(changed)) as client:
        joined = client.post("/api/join", json={"nickname": "공유시험"})
        assert joined.status_code == 200, joined.text
        code = make_room(client)
        solve(client, code, changed, lex)
        share = client.get(f"/api/rooms/{code}/daily").json()["share_text"]

    assert share is not None
    assert f"?room={code}" in share, "링크에 방 코드가 없다"
    assert "친구들" in share, "방 이름이 있어야 어느 방 결과인지 안다"


def test_공유_문구에_정답이_없다(settings, lex) -> None:
    """아직 안 푼 친구가 이 문구를 보고 답을 알면 안 된다."""
    changed = settings.model_copy(update={"share_url": "https://ttobak.example"})
    from ttobak.web.app import create_app

    with TestClient(create_app(changed)) as client:
        joined = client.post("/api/join", json={"nickname": "정답노출시험"})
        assert joined.status_code == 200, joined.text
        code = make_room(client)
        answer = answer_of(code, changed, lex)
        solve(client, code, changed, lex)
        share = client.get(f"/api/rooms/{code}/daily").json()["share_text"]

    assert answer not in share
    from ttobak.hangul import decompose

    assert "".join(decompose(answer)) not in share


def test_1번을_맞히고_2번을_열어도_맞힌_것이_남는다(jio, settings, lex) -> None:
    """**실제로 낸 사고다.**

    1번을 맞히고 2번을 열기만 했는데 순위에 "푸는 중" 이 뜨고 머리글이
    "0/2명이 맞혔어요" 가 됐다. 하루치를 사람 단위로 합치면서, 하나라도
    진행 중이면 통째로 ``playing`` 으로 봤기 때문이다. 맞힌 사실이 화면에서
    사라지는 것은 이 게임에서 제일 하면 안 되는 일이다.

    지금은 순위가 **문제별**이라 1번 순위는 2번을 열든 말든 안 변한다.
    """
    from ttobak.hangul import decompose

    code = make_room(jio)
    answer = answer_of(code, settings, lex, 0)
    res = jio.post(
        f"/api/rooms/{code}/daily/guess",
        json={"guess": "".join(decompose(answer)), "slot": 0},
    )
    assert res.status_code == 200, res.text

    # 2번을 연다 — 여는 것만으로 'playing' 행이 생긴다. 그게 원인이었다.
    jio.get(f"/api/rooms/{code}/daily?slot=1")

    first = jio.get(f"/api/rooms/{code}/daily?slot=0").json()
    me = next(row for row in first["standings"] if row["is_me"])
    assert me["status"] == "won", "1번을 맞혔는데 2번을 열었다고 지워지면 안 된다"
    assert first["solved_count"] == 1


def test_아직_안_푼_방_사람도_순위에_나온다(jio, minsu, settings, lex) -> None:
    """29명짜리 방에 두 줄만 떠서 "왜 두 명밖에 안 뜨노" 를 들었다.

    푼 사람만 보여 주면 방이 텅 빈 것처럼 보인다. 전원을 내보내고 아직
    안 한 사람은 ``none`` 으로 준다 — 어떻게 보여 줄지는 화면이 정한다.
    """
    code = make_room(jio)
    minsu.post(f"/api/rooms/{code}/join")
    solve(jio, code, settings, lex)

    rows = jio.get(f"/api/rooms/{code}/daily?slot=0").json()["standings"]
    by_name = {row["display_name"]: row["status"] for row in rows}
    assert by_name["지오"] == "won"
    assert by_name["민수"] == "none", "방에 있지만 아직 안 푼 사람도 나와야 한다"
    # 등수와 공유 문구의 "n명 중" 은 **푼 사람** 만 센다. 방에 있기만 한
    # 사람까지 세면 등수가 실제보다 대단해 보인다.
    assert jio.get(f"/api/rooms/{code}/daily?slot=0").json()["total_count"] == 1


def test_방_목록이_오늘_남은_문제_수를_알려_준다(jio, settings, lex) -> None:
    """**화면이 "다음에 무엇을 열까" 를 이 값으로 정한다.**

    그날 처음 들어온 사람은 오늘의 문제부터 풀어야 한다. 예전에는 들어오면
    혼자 푸는 판이 먼저 떴고, 그래서 친구들과 겨루려고 들어온 사람이 그냥
    그것만 풀다 나갔다. 오늘의 문제는 **다 같이 같은 낱말**을 푸는 것이라
    그게 이 게임의 중심이다.

    이 값을 서버가 주지 않으면 화면이 방마다 따로 물어봐야 해서 왕복이
    늘고, 그 사이에 일반 판이 잠깐 보였다 바뀐다.
    """
    from ttobak.game.rounds import DAILY_SLOTS
    from ttobak.hangul import decompose

    code = make_room(jio)
    rows = jio.get("/api/rooms").json()["rooms"]
    mine = next(r for r in rows if r["id"] == code)
    assert mine["daily_left"] == DAILY_SLOTS, "아직 하나도 안 풀었다"

    # 1번을 끝낸다.
    answer = answer_of(code, settings, lex, 0)
    # slot 은 **본문**으로 보낸다. 쿼리로 주면 조용히 무시되고 서버가
    # 알아서 고른 칸으로 채점이 간다 — 실제로 그렇게 틀렸다.
    res = jio.post(
        f"/api/rooms/{code}/daily/guess",
        json={"guess": "".join(decompose(answer)), "slot": 0},
    )
    assert res.status_code == 200, res.text

    rows = jio.get("/api/rooms").json()["rooms"]
    mine = next(r for r in rows if r["id"] == code)
    assert mine["daily_left"] == DAILY_SLOTS - 1, "끝낸 것은 빠져야 한다"

    # 남은 칸들도 끝낸다. solve() 는 1번부터 다시 풀려고 해서 409 가 난다.
    for slot in range(1, DAILY_SLOTS):
        rest = answer_of(code, settings, lex, slot)
        res = jio.post(
            f"/api/rooms/{code}/daily/guess",
            json={"guess": "".join(decompose(rest)), "slot": slot},
        )
        assert res.status_code == 200, res.text

    rows = jio.get("/api/rooms").json()["rooms"]
    mine = next(r for r in rows if r["id"] == code)
    assert mine["daily_left"] == 0, "다 끝내면 0 이어야 한다"


def test_다음_문제는_남은_오늘의_문제로_간다() -> None:
    """1번을 맞히고 '다음 문제' 를 눌렀더니 2번이 아니라 엉뚱한 일반 판이
    나왔다는 신고를 받았다. 화면이 무조건 일반 판을 열고 있었다."""
    from pathlib import Path

    app = (
        Path(__file__).resolve().parent.parent
        / "src" / "ttobak" / "static" / "js" / "app.js"
    ).read_text(encoding="utf-8")
    assert "function nextUnfinishedSlot(" in app
    assert "state.room ? nextUnfinishedSlot(state.game) : null" in app, (
        "방에 있을 때만, 그리고 남은 칸이 있을 때만 오늘의 문제로 가야 한다"
    )
    assert "function roomNeedingDaily(" in app, (
        "그날 처음 들어온 사람은 오늘의 문제부터 열어야 한다"
    )
    assert "daily_left" in app, "서버가 준 값을 그대로 써야 한다"


def test_처음_온_사람도_초대_링크로_방에_들어간다(jio) -> None:
    """**초대 링크가 처음 오는 사람에게는 동작하지 않았다.**

    방에 들어가려면 닉네임이 있어야 하는데, 링크를 누른 시점에는 아직 없다.
    서버는 401 을 준다(그게 맞다). 문제는 화면이 그 401 을 오류로 띄우고
    **방 코드를 잊어버린 것**이다. 그래서 이렇게 됐다.

        링크 클릭 → 401 → 닉네임 만듦 → 방에는 안 들어간 사람

    그 상태로 남으면 "방 없는 사람" 으로 취급돼, 꺼 뒀어야 할 운영비
    단추까지 보인다. 실제로 그래서 베타테스터에게 100원을 받았다.

    서버 쪽 계약은 그대로 두고(닉네임 없이 참가시킬 수는 없다), 화면이
    코드를 들고 있다가 닉네임이 생기면 다시 들어가야 한다.
    """
    # 서버 계약: 닉네임 없이는 못 들어간다. 그건 그대로 둔다.
    from fastapi.testclient import TestClient

    from ttobak.web.app import create_app

    with TestClient(create_app(jio.app.state.settings)) as fresh:
        res = fresh.post("/api/rooms/AAAAAAAAAAAAAA/join", json={})
        assert res.status_code == 401


def test_화면이_초대_코드를_들고_있다가_재시도한다() -> None:
    from pathlib import Path

    app = (
        Path(__file__).resolve().parent.parent
        / "src" / "ttobak" / "static" / "js" / "app.js"
    ).read_text(encoding="utf-8")

    assert "let pendingRoom = null;" in app, "못 들어간 코드를 들고 있어야 한다"
    assert "if (error.status === 401) return;" in app, (
        "닉네임이 없어서 못 들어간 것은 오류가 아니다 — 빨간 글씨부터 보이면 안 된다"
    )
    assert "function joinPendingRoom(" in app

    # 닉네임을 만든 직후에 실제로 재시도해야 한다.
    after_join = app[app.index("const me = await Api.join("):]
    assert "await joinPendingRoom();" in after_join[:600], (
        "닉네임이 생긴 뒤 방에 다시 들어가야 한다"
    )
    assert "await loadSupport();" in after_join[:800], (
        "소속이 바뀌었으니 운영비 단추도 다시 판단해야 한다"
    )


# --- 초대 링크 미리보기 ---
#
# 링크를 눌러 처음 온 사람은 아직 닉네임이 없다. 그 사람이 보는 화면이
# "여기가 어느 방인지" 를 못 적으면, 방이 여럿인 사람은 자기가 어디로
# 들어가는지 모르는 채 닉네임부터 정하게 된다.


def test_로그인_없이도_방_이름을_볼_수_있다(app, jio):
    code = make_room(jio, "번개모임")

    # 쿠키가 하나도 없는 새 클라이언트. 링크를 막 누른 사람과 같다.
    with TestClient(app) as guest:
        row = guest.get(f"/api/rooms/{code}/peek")
        assert row.status_code == 200, row.text
        assert row.json()["name"] == "번개모임"
        assert row.json()["member_count"] == 1


def test_미리보기는_이름과_인원만_준다(app, jio):
    """**주는 것이 늘어나면 로그인을 뺀 것이 문제가 된다.**

    회원 명단이나 오늘의 낱말이 여기 실리면, 코드를 아는 사람이 방에
    들어가지 않고도 그 방을 들여다볼 수 있다.
    """
    code = make_room(jio, "번개모임")
    with TestClient(app) as guest:
        assert set(guest.get(f"/api/rooms/{code}/peek").json()) == {
            "name",
            "member_count",
        }


def test_없는_방을_미리보면_404(app):
    with TestClient(app) as guest:
        assert guest.get(f"/api/rooms/{new_room_code()}/peek").status_code == 404
        # 코드 모양부터 틀린 것도 같은 답이어야 한다. 다르게 답하면
        # "이건 형식은 맞다" 가 새어 나간다.
        assert guest.get("/api/rooms/nope/peek").status_code == 404


def test_미리봐도_회원이_되지는_않는다(app, jio, minsu):
    """보는 것과 들어가는 것은 다르다. 미리보기로 인원이 늘면 안 된다."""
    code = make_room(jio, "번개모임")
    minsu.get(f"/api/rooms/{code}/peek")

    # 아직 회원이 아니므로 방 내용은 여전히 404.
    assert minsu.get(f"/api/rooms/{code}/daily").status_code == 404
    with TestClient(app) as guest:
        assert guest.get(f"/api/rooms/{code}/peek").json()["member_count"] == 1


# --- 거절 모양이 두 판에서 같아야 한다 ---
#
# 화면 코드는 하나인데 서버가 두 모양으로 답하면, 한쪽에서만 조용히 기능이
# 사라진다. 실제로 오늘의 문제에서만 신고 단추가 안 붙었다.


def test_오늘의_문제도_사전에_없으면_같은_모양으로_거절한다(jio, settings, lex):
    """``code`` 가 있어야 화면이 "사전에 없는 단어" 를 알아본다.

    문구를 문자열로 비교하게 두면 말투를 한 번만 다듬어도 깨진다. 그래서
    짧은 이름을 같이 보내는데, 오늘의 문제 쪽만 그것을 빠뜨리고 있었다.
    """
    from ttobak.hangul import decompose

    code = make_room(jio)
    answer = answer_of(code, settings, lex, 0)
    # 정답과 길이는 같지만 사전에 없는 자모 나열.
    nonsense = "ㄱ" * len(decompose(answer))

    response = jio.post(
        f"/api/rooms/{code}/daily/guess", json={"guess": nonsense, "slot": 0}
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, dict), "문자열로 주면 code 가 사라진다"
    assert detail["code"] == "unknown_word"
    assert detail["message"]


def test_혼자_푸는_판과_거절_모양이_같다(jio, settings, lex):
    from ttobak.hangul import decompose

    code = make_room(jio)
    nonsense = "ㄱ" * len(decompose(answer_of(code, settings, lex, 0)))

    daily = jio.post(
        f"/api/rooms/{code}/daily/guess", json={"guess": nonsense, "slot": 0}
    )
    solo = jio.post("/api/game/guess", json={"guess": nonsense})

    assert daily.status_code == solo.status_code
    assert set(daily.json()["detail"]) == set(solo.json()["detail"])


def test_힌트를_끄면_오늘의_문제에서도_바로_사라진다(jio, settings, lex):
    """**설정을 바꾼 뒤 판을 다시 받으면 단추가 사라져야 한다.**

    힌트를 그릴지는 서버가 판에 실어 보낸다. 화면은 그 값을 그대로 쓰므로,
    이 값이 안 바뀌면 화면에서 무엇을 해도 단추가 안 사라진다.
    """
    code = make_room(jio)
    answer = answer_of(code, settings, lex, 0)
    from ttobak.hangul import decompose

    wrong = "ㄱ" * len(decompose(answer))
    # 힌트는 몇 번 틀린 뒤에 열린다. 사전에 있는 오답으로 채운다.
    for _ in range(3):
        jio.post(f"/api/rooms/{code}/daily/guess", json={"guess": wrong, "slot": 0})

    jio.put("/api/settings", json={"hints_enabled": True})
    before = jio.get(f"/api/rooms/{code}/daily?slot=0").json()

    jio.put("/api/settings", json={"hints_enabled": False})
    after = jio.get(f"/api/rooms/{code}/daily?slot=0").json()

    assert after["hint_available"] is False
    assert after["hints_left"] == 0
    # 켰을 때와 껐을 때가 실제로 달라야 이 시험이 의미가 있다.
    assert before["hints_left"] >= after["hints_left"]



# --- 사전을 손질해도 판이 깨지지 않는다 ---
#
# 정답 목록은 이제 주기적으로 바뀐다(하이쿠 검토, 신고 반영). 그런데 판은 시작할
# 때 정답을 저장해 두고, 오늘의 문제는 목록에서 새로 계산한다. 그 둘이 어긋나는
# 순간 생기는 사고를 막는다. 목록을 실제로 바꾸는 대신 **저장된 정답을 지금
# 목록이 내지 않는 값으로 바꿔서** 같은 상황을 만든다.


def test_목록이_바뀌어도_한_방은_같은_정답(jio, minsu, settings, lex):
    import sqlite3

    from ttobak.hangul import decompose

    code = make_room(jio)
    assert minsu.post(f"/api/rooms/{code}/join").status_code == 200
    jio.get(f"/api/rooms/{code}/daily?slot=0")

    computed = answer_of(code, settings, lex, 0)
    length = len(decompose(computed))
    other = next(w for w in lex.for_length(length).words if w != computed)
    with sqlite3.connect(settings.database_path) as db:
        db.execute(
            "UPDATE daily_games SET answer = ? WHERE room_id = ? AND slot = 0",
            (other, code),
        )

    # 나중에 연 사람. 지금 목록대로라면 computed 를 받았을 것이다.
    minsu.get(f"/api/rooms/{code}/daily?slot=0")
    with sqlite3.connect(settings.database_path) as db:
        answers = [
            row[0]
            for row in db.execute(
                "SELECT answer FROM daily_games WHERE room_id = ? AND slot = 0",
                (code,),
            )
        ]
    assert len(answers) == 2, "두 사람 다 판이 열려야 한다"
    assert set(answers) == {other}, "같은 방 같은 날은 같은 낱말이어야 한다"


def test_정답이_사전에서_빠져도_그_판은_끝낼_수_있다(jio, settings):
    """정답을 정확히 쳤는데 "사전에 없는 단어" 로 거절되면 그 판은 영영 못 끝난다."""
    import sqlite3

    from ttobak.hangul import jamo_key

    jio.get("/api/game")
    player_id = jio.get("/api/me").json()["player_id"]
    gone = "갸갹"  # 5자모. 시험용 사전에 없는 말이다.
    with sqlite3.connect(settings.database_path) as db:
        db.execute(
            "UPDATE games SET answer = ? WHERE player_id = ? AND status = 'playing'",
            (gone, player_id),
        )

    # 정답이 아닌, 사전에 없는 말은 여전히 거절해야 한다. 구멍을 연 게 아니다.
    other = jio.post("/api/game/guess", json={"guess": jamo_key("갹갸")})
    assert other.status_code == 400
    assert other.json()["detail"]["code"] == "unknown_word"

    hit = jio.post("/api/game/guess", json={"guess": jamo_key(gone)})
    assert hit.status_code == 200, hit.text
    assert hit.json()["status"] == "won"
