"""오래된 기록 정리 — 무엇을 지우고 무엇을 **절대 안 지우는지**.

공짜 게임이라 기록을 많이 쌓아 두지 않는다(30일). 오래 안 온 계정도 지운다
(3일). 지우는 일은 되돌릴 수 없으니, 지워야 할 것보다 **남겨야 할 것**을 더
꼼꼼히 본다. 특히 방장을 지우면 방이 통째로 사라진다.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from ttobak.config import Settings
from ttobak.db import Database
from ttobak.web.app import create_app

TODAY = date(2026, 9, 25)


def ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")


def day_ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


def seed(path) -> None:
    """방장 한 명, 활동 중인 사람 한 명, 오래 안 온 사람 한 명과 그들의 기록."""
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys = ON")
        people = [("owner", ago(40)), ("active", ago(1)), ("dormant", ago(10))]
        for pid, seen in people:
            db.execute(
                "INSERT INTO players (id, display_name, created_at, last_seen_at)"
                " VALUES (?, ?, ?, ?)",
                (pid, pid, seen, seen),
            )
        db.execute(
            "INSERT INTO rooms (id, name, owner_id, created_at, puzzle_salt)"
            " VALUES ('ROOM', '방', 'owner', ?, 's')",
            (ago(40),),
        )
        for pid in ("owner", "active", "dormant"):
            db.execute(
                "INSERT INTO room_members (room_id, player_id, joined_at)"
                " VALUES ('ROOM', ?, ?)",
                (pid, ago(40)),
            )
        for round_no, age in ((0, 40), (1, 2)):
            db.execute(
                "INSERT INTO games (player_id, round_no, answer, status, guesses,"
                " started_at, finished_at, played_on)"
                " VALUES ('active', ?, '하늘', 'won', '[]', ?, ?, ?)",
                (round_no, ago(age), ago(age), day_ago(age)),
            )
        for age in (40, 0):
            db.execute(
                "INSERT INTO daily_games (room_id, play_date, player_id, answer,"
                " status, guesses, started_at, slot)"
                " VALUES ('ROOM', ?, 'active', '하늘', 'won', '[]', ?, 0)",
                (day_ago(age), ago(age)),
            )
            db.execute(
                "INSERT INTO comments (room_id, play_date, player_id, body, created_at)"
                " VALUES ('ROOM', ?, 'active', '와', ?)",
                (day_ago(age), ago(age)),
            )
        reports = [
            ("ㄱㄴㄷㄹㅁ", "added", ago(40)),     # 오래됐고 처리 끝남 → 지움
            ("ㅂㅅㅇㅈㅊ", "pending", ago(40)),   # 오래됐어도 대기 중 → 남김
            ("ㅋㅌㅍㅎㄱ", "rejected", ago(2)),   # 최근 → 남김
        ]
        for jamos, status, when in reports:
            db.execute(
                "INSERT INTO word_reports (jamos, length, player_id, created_at,"
                " status, reviewed_at) VALUES (?, 5, 'active', ?, ?, ?)",
                (jamos, when, status, when if status != "pending" else None),
            )


def count(path, sql: str) -> int:
    with sqlite3.connect(path) as db:
        return db.execute(sql).fetchone()[0]


def test_30일_지난_기록만_지운다(settings: Settings):
    database = Database(settings.database_path)
    database.initialize()
    seed(settings.database_path)

    removed = database.prune(today=TODAY, keep_days=30, dormant_days=0)
    path = settings.database_path

    assert removed["games"] == 1 and count(path, "SELECT COUNT(*) FROM games") == 1
    assert removed["daily_games"] == 1
    assert count(path, "SELECT COUNT(*) FROM daily_games") == 1
    assert removed["comments"] == 1
    assert count(path, "SELECT COUNT(*) FROM comments") == 1
    # 대기 중인 신고는 오래됐어도 남는다. 지우면 신고가 없던 일이 된다.
    left = {
        row[0]
        for row in sqlite3.connect(path).execute("SELECT status FROM word_reports")
    }
    assert left == {"pending", "rejected"}


def test_오래_안_온_사람은_지우되_방장은_남긴다(settings: Settings):
    database = Database(settings.database_path)
    database.initialize()
    seed(settings.database_path)

    removed = database.prune(today=TODAY, keep_days=0, dormant_days=3)
    ids = {
        row[0]
        for row in sqlite3.connect(settings.database_path).execute(
            "SELECT id FROM players"
        )
    }
    assert removed["players"] == 1
    assert ids == {"owner", "active"}, "방장은 40일 안 왔어도 남아야 한다"
    assert count(settings.database_path, "SELECT COUNT(*) FROM rooms") == 1


def test_0이면_아무것도_안_지운다(settings: Settings):
    database = Database(settings.database_path)
    database.initialize()
    seed(settings.database_path)

    assert database.prune(today=TODAY, keep_days=0, dormant_days=0) == {}
    assert count(settings.database_path, "SELECT COUNT(*) FROM games") == 2


def test_앱이_켜질_때_정리한다(settings: Settings):
    """스트림릿 무료 배포에는 예약 작업이 없다. 앱이 스스로 해야 한다."""
    database = Database(settings.database_path)
    database.initialize()
    seed(settings.database_path)

    with TestClient(create_app(settings)):
        pass

    ids = {
        row[0]
        for row in sqlite3.connect(settings.database_path).execute(
            "SELECT id FROM players"
        )
    }
    assert "dormant" not in ids
    assert count(settings.database_path, "SELECT COUNT(*) FROM games") == 1
