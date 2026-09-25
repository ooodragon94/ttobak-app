"""동시 요청으로 점수를 조작할 수 있는가.

적대적 리뷰가 지적한 두 가지다. 둘 다 **읽고 → 검사하고 → 쓰는** 사이에
잠금이 없어서 생겼다. 요청을 동시에 여러 개 보내면 전부 같은 값을 읽고
전부 검사를 통과한다.

고친 방법도 같다. **검사를 SQL 의 WHERE 로 옮겼다.** 조건이 UPDATE 안에
있으면 읽기와 쓰기 사이가 없어져서 하나만 통과한다.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from ttobak.db.repository import ConcurrentGuessError, Database


@pytest.fixture
def seeded(database: Database):
    """추측 하나가 들어간 판."""
    database.upsert_player("민수", "민수")
    from datetime import date

    database.start_round("민수", 0, "하늘", date(2026, 9, 5))
    return database


# ----------------------------------------------------------------------
# M2 — 힌트를 동시에 요청해 정답을 통째로 열 수 있었다
# ----------------------------------------------------------------------


def test_힌트를_동시에_열_번_요청해도_한_번만_는다(seeded: Database) -> None:
    """**이게 제일 나빴다.**

    화면은 ``정답[:hints_used]`` 를 보여 준다. 그래서 이 값이 부풀면
    정답이 통째로 열린다. 열 개를 동시에 보내면 실제로 10 이 됐다.
    """
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: seeded.use_hint("민수", 0, 1), range(10)))

    granted = [r for r in results if r is not None]
    assert len(granted) == 1, f"{len(granted)}개가 통과했다 — 상한이 안 걸린다"
    assert seeded.get_game("민수", 0).hints_used == 1


def test_상한까지는_정상적으로_열린다(seeded: Database) -> None:
    """막다가 정상 사용까지 막으면 안 된다."""
    assert seeded.use_hint("민수", 0, 3) is not None
    assert seeded.use_hint("민수", 0, 3) is not None
    assert seeded.use_hint("민수", 0, 3) is not None
    assert seeded.use_hint("민수", 0, 3) is None  # 상한 도달
    assert seeded.get_game("민수", 0).hints_used == 3


# ----------------------------------------------------------------------
# M3 — 추측을 동시에 보내 한 기회로 여러 단어를 채점받을 수 있었다
# ----------------------------------------------------------------------


def test_같은_기회로_두_번_저장할_수_없다(seeded: Database) -> None:
    """응답은 둘 다 채점돼 오는데 저장은 하나만 남았다.

    즉 한 번의 기회로 두 단어의 색을 알 수 있었다. 오늘의 문제는 시도
    횟수로 줄을 세우므로 그대로 순위 조작이 된다.
    """
    seeded.save_progress("민수", 0, ("첫추측",), "playing")

    # 둘 다 "지금 1개 있다" 를 읽고 2개짜리 목록을 만들었다고 하자.
    seeded.save_progress("민수", 0, ("첫추측", "둘째"), "playing")
    with pytest.raises(ConcurrentGuessError):
        seeded.save_progress("민수", 0, ("첫추측", "다른둘째"), "playing")

    assert seeded.get_game("민수", 0).guesses == ("첫추측", "둘째")


def test_동시에_여섯_개를_보내면_하나만_남는다(seeded: Database) -> None:
    def attempt(word: str):
        try:
            seeded.save_progress("민수", 0, (word,), "playing")
            return True
        except ConcurrentGuessError:
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, [f"단어{i}" for i in range(6)]))

    assert sum(results) == 1, f"{sum(results)}개가 통과했다 — 기회가 공짜가 된다"
    assert len(seeded.get_game("민수", 0).guesses) == 1


def test_순서대로_보내면_정상이다(seeded: Database) -> None:
    """방어가 정상 플레이를 막으면 안 된다."""
    seeded.save_progress("민수", 0, ("하나",), "playing")
    seeded.save_progress("민수", 0, ("하나", "둘"), "playing")
    seeded.save_progress("민수", 0, ("하나", "둘", "셋"), "won")
    record = seeded.get_game("민수", 0)
    assert record.guesses == ("하나", "둘", "셋")
    assert record.status == "won"


def test_새로_만든_DB도_WAL_이다(tmp_path) -> None:
    """**이건 증상이 없는 종류의 회귀다.**

    ``journal_mode`` 는 파일 헤더에 박히는 값이라, 한 번 손으로 켜 두면
    코드가 안 켜도 계속 WAL 로 남는다. 실제로 이 저장소는 오랫동안
    "WAL 모드라..." 라고 주석에만 적어 두고 켜는 코드가 없었는데,
    돌아가던 파일이 이미 WAL 이라 아무도 몰랐다.

    그래서 **새로 만든 파일**로 확인한다. 파일을 지우고 재시작하거나 덤프에서
    복원하면 바로 그 상황이 되고, 그때 쓰기 처리량이 몇 배 떨어진다.
    """
    from ttobak.db import Database

    db = Database(tmp_path / "새것.sqlite3")
    db.initialize()
    with db.connect() as connection:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal", f"새 DB 가 {mode} 모드다. WAL 이어야 한다"
