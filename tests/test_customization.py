"""공유 테마와 순위표 칭호 테스트."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import detail_of
from ttobak.config import Settings
from ttobak.db import LeaderboardEntry
from ttobak.game.rounds import puzzle_for_round
from ttobak.game.themes import DEFAULT_THEME, THEMES, get_theme
from ttobak.game.titles import assign_titles, rank_medal
from ttobak.hangul import jamo_key
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


def entry(name: str, **kwargs) -> LeaderboardEntry:
    values = {
        "display_name": name,
        "solved": 0,
        "played": 0,
        "average_attempts": None,
        "best_attempts": None,
    }
    values.update(kwargs)
    return LeaderboardEntry(**values)


# --- 테마 ---


def test_모든_테마의_그림이_서로_다르다():
    """세 그림이 겹치면 격자를 읽을 수 없다."""
    for theme in THEMES.values():
        squares = {theme.correct, theme.present, theme.absent}
        assert len(squares) == 3, f"{theme.key} 테마의 그림이 겹칩니다"


def test_테마마다_이름과_맛보기가_있다():
    for theme in THEMES.values():
        assert theme.label
        assert len(theme.preview) > 0


def test_모르는_테마는_기본값으로_돌아간다():
    """저장된 설정이 없어진 테마를 가리켜도 공유가 죽으면 안 된다."""
    assert get_theme("이런건없음").key == DEFAULT_THEME
    assert get_theme(None).key == DEFAULT_THEME


def test_테마를_바꾸면_공유_격자가_바뀐다(client: TestClient, settings: Settings, lex):
    client.post("/api/join", json={"nickname": "민수"})
    client.put("/api/settings", json={"share_theme": "heart"})

    answer = answer_for(settings, lex, "민수")
    game = client.post("/api/game/guess", json={"guess": jamo_key(answer)}).json()

    assert "💚" in game["share_text"]
    assert "🟩" not in game["share_text"]


def test_새_플레이어는_기본_테마다(client: TestClient):
    client.post("/api/join", json={"nickname": "민수"})
    assert client.get("/api/settings").json()["share_theme"] == DEFAULT_THEME


def test_테마_목록을_내려준다(client: TestClient):
    client.post("/api/join", json={"nickname": "민수"})
    themes = client.get("/api/settings").json()["themes"]
    assert len(themes) == len(THEMES)
    assert {t["key"] for t in themes} == set(THEMES)


def test_없는_테마는_거절된다(client: TestClient):
    client.post("/api/join", json={"nickname": "민수"})
    response = client.put("/api/settings", json={"share_theme": "무지개색"})
    assert response.status_code == 400
    assert "없는 테마" in detail_of(response)


def test_테마는_사람마다_따로_간다(client: TestClient):
    client.post("/api/join", json={"nickname": "민수"})
    client.put("/api/settings", json={"share_theme": "moon"})
    client.post("/api/leave")

    client.post("/api/join", json={"nickname": "영희"})
    assert client.get("/api/settings").json()["share_theme"] == DEFAULT_THEME


# --- 메달 ---


def test_상위_세_명만_메달을_받는다():
    assert rank_medal(1) == "🥇"
    assert rank_medal(2) == "🥈"
    assert rank_medal(3) == "🥉"
    assert rank_medal(4) == ""


# --- 칭호 ---


def test_한_사람이_칭호를_독식하지_않는다():
    """위에서부터 훑되 이미 받은 사람은 건너뛴다."""
    entries = [
        entry("고수", solved=5, played=5, average_attempts=2.0, best_attempts=1),
        entry("중수", solved=3, played=4, average_attempts=3.0, best_attempts=2),
        entry("하수", solved=1, played=5, average_attempts=5.0, best_attempts=5),
    ]
    titles = assign_titles(entries)
    assert len(set(titles)) == len(titles)
    assert len(titles) >= 2, "여러 명이 칭호를 나눠 가져야 한다"


def test_한_번에_맞힌_사람이_한_방을_받는다():
    entries = [
        entry("느긋", solved=3, played=3, average_attempts=4.0, best_attempts=3),
        entry("한방", solved=1, played=1, average_attempts=1.0, best_attempts=1),
    ]
    titles = assign_titles(entries)
    assert titles["한방"].key == "one_shot"


def test_한_판도_안_끝낸_사람은_칭호가_없다():
    titles = assign_titles([entry("구경꾼", solved=0, played=0)])
    assert titles == {}


def test_순위표에_메달과_칭호가_실린다(client: TestClient, settings: Settings, lex):
    client.post("/api/join", json={"nickname": "민수"})
    answer = answer_for(settings, lex, "민수")
    client.post("/api/game/guess", json={"guess": jamo_key(answer)})

    row = client.get("/api/leaderboard").json()["entries"][0]
    assert row["medal"] == "🥇"
    assert row["title"], "칭호가 붙어야 한다"
    assert row["is_me"] is True
    assert row["best_attempts"] == 1


def test_남의_줄은_내_줄로_표시되지_않는다(client: TestClient, settings: Settings, lex):
    client.post("/api/join", json={"nickname": "민수"})
    client.post(
        "/api/game/guess", json={"guess": jamo_key(answer_for(settings, lex, "민수"))}
    )
    client.post("/api/leave")
    client.post("/api/join", json={"nickname": "영희"})

    rows = client.get("/api/leaderboard").json()["entries"]
    mine = [row for row in rows if row["is_me"]]
    assert mine == [] or all(row["display_name"] == "영희" for row in mine)


# --- 방장과의 사이 ---
#
# 로그인이 없는 게임이라 순위표에 낯선 닉네임만 줄줄이 뜬다. 선택으로
# 한 줄 적어 두면 "저 사람이 누구더라" 가 줄어든다. **선택이라는 점이
# 핵심**이라, 안 적어도 아무 데도 안 걸려야 한다.


def test_소개는_안_적어도_가입된다(client: TestClient):
    assert client.post("/api/join", json={"nickname": "민수"}).status_code == 200
    assert client.get("/api/settings").json()["relation"] == ""


def test_가입할_때_적은_소개가_설정에_남는다(client: TestClient):
    client.post("/api/join", json={"nickname": "민수", "relation": "대학 동기"})
    assert client.get("/api/settings").json()["relation"] == "대학 동기"


def test_소개를_설정에서_고칠_수_있다(client: TestClient):
    client.post("/api/join", json={"nickname": "민수", "relation": "대학 동기"})
    saved = client.put("/api/settings", json={"relation": "고등 동창"}).json()
    assert saved["relation"] == "고등 동창"
    assert client.get("/api/settings").json()["relation"] == "고등 동창"


def test_소개를_비우면_지워진다(client: TestClient):
    client.post("/api/join", json={"nickname": "민수", "relation": "대학 동기"})
    assert client.put("/api/settings", json={"relation": "  "}).json()["relation"] == ""


def test_다시_들어와도_소개가_안_지워진다(client: TestClient):
    """기기를 바꿔 복구 코드로 다시 들어오는 사람은 소개 칸을 비워 둔다.

    그 빈 값으로 덮어쓰면 **가만히 있던 소개가 사라진다.** 그래서 join 은
    값이 있을 때만 저장한다.
    """
    code = client.post(
        "/api/join", json={"nickname": "민수", "relation": "대학 동기"}
    ).json()["recovery_code"]
    client.post("/api/leave")

    client.post("/api/join", json={"nickname": "민수", "recovery_code": code})
    assert client.get("/api/settings").json()["relation"] == "대학 동기"


def test_순위표에_소개가_실린다(client: TestClient, settings: Settings, lex):
    client.post("/api/join", json={"nickname": "민수", "relation": "대학 동기"})
    client.post(
        "/api/game/guess", json={"guess": jamo_key(answer_for(settings, lex, "민수"))}
    )

    row = client.get("/api/leaderboard").json()["entries"][0]
    assert row["relation"] == "대학 동기"


def test_전날_연_판을_오늘_맞히면_오늘_순위에_든다(
    client: TestClient, settings: Settings, lex
):
    """순위는 판을 **끝낸** 날로 센다.

    판을 연 날로 세면, 전날 열어 둔 판을 오늘 맞힌 사람이 오늘 순위에 안 보인다.
    결과 창에서 방금 맞혔는데 "아직 참가자가 없습니다" 가 뜨는 꼴이 된다.
    """
    import sqlite3

    client.post("/api/join", json={"nickname": "민수"})
    client.post(
        "/api/game/guess", json={"guess": jamo_key(answer_for(settings, lex, "민수"))}
    )
    with sqlite3.connect(settings.database_path) as db:
        db.execute("UPDATE games SET played_on = '2000-01-01'")

    entries = client.get("/api/leaderboard").json()["entries"]
    assert [row["display_name"] for row in entries] == ["민수"]
