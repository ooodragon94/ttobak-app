"""옛 데이터베이스에 나중에 생긴 컬럼을 붙이는 것(``Database._migrate``).

``CREATE TABLE IF NOT EXISTS`` 는 이미 있는 표를 건드리지 않는다. 그래서 컬럼을
새로 더하면 쓰던 데이터베이스에는 따로 붙여 줘야 하고, 그 일을 ``_migrate`` 가
한다. 2026-10-06 이 함수를 "컬럼 목록 + 반복" 으로 다시 짜면서 이 시험을 만들었다
(그 전에는 이 길을 지나는 시험이 없었다).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from ttobak.db import Database
from ttobak.db.repository import _ADDED_COLUMNS

# 이 시험은 "옛 로컬 파일" 을 올리는 이야기다. 가짜 Turso 로 돌릴 때는 저장이
# 그 파일이 아니라 원격 쪽으로 가므로 해당이 없다.
pytestmark = pytest.mark.skipif(
    os.environ.get("TTOBAK_TEST_FAKE_TURSO") == "1",
    reason="옛 로컬 파일 마이그레이션 시험. 원격(Turso)에는 해당 없음",
)

# 컬럼들이 생기기 전의 표. 옛 켬/끔 하드모드(hard_mode)가 있던 시절이다.
OLD_SCHEMA = """
CREATE TABLE players (
    id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
    created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    tailscale_node TEXT, tailscale_user TEXT,
    hard_mode INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE games (
    player_id TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    round_no INTEGER NOT NULL, answer TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'playing', guesses TEXT NOT NULL DEFAULT '[]',
    started_at TEXT NOT NULL, finished_at TEXT, played_on TEXT NOT NULL,
    hard_mode INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, round_no)
);
CREATE TABLE rooms (
    id TEXT PRIMARY KEY, name TEXT NOT NULL,
    owner_id TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL, puzzle_salt TEXT NOT NULL
);
CREATE TABLE daily_games (
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    play_date TEXT NOT NULL,
    player_id TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    answer TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'playing',
    guesses TEXT NOT NULL DEFAULT '[]', started_at TEXT NOT NULL,
    finished_at TEXT, hints_used INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (room_id, play_date, player_id)
);
INSERT INTO players VALUES ('old', '옛사람', 't', 't', NULL, NULL, 1);
INSERT INTO players VALUES ('easy', '보통사람', 't', 't', NULL, NULL, 0);
INSERT INTO games (player_id, round_no, answer, started_at, played_on, hard_mode)
    VALUES ('old', 0, '하늘', 't', '2026-09-01', 1);
INSERT INTO rooms VALUES ('ROOM', '방', 'old', 't', 's');
INSERT INTO daily_games (room_id, play_date, player_id, answer, started_at)
    VALUES ('ROOM', '2026-09-01', 'old', '구름', 't');
"""


def columns(path: Path, table: str) -> set[str]:
    with sqlite3.connect(path) as db:
        return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def test_옛_데이터베이스에_빠진_컬럼이_다_붙는다(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(OLD_SCHEMA)

    Database(path).initialize()

    for table, column, _ in _ADDED_COLUMNS:
        assert column in columns(path, table), f"{table}.{column} 이 안 붙었다"
    assert "slot" in columns(path, "daily_games")


def test_옛_하드모드는_불닭으로_옮기고_기록은_그대로다(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(OLD_SCHEMA)

    Database(path).initialize()

    with sqlite3.connect(path) as db:
        players = dict(db.execute("SELECT id, difficulty FROM players"))
        game = db.execute("SELECT answer, difficulty FROM games").fetchone()
        daily = db.execute("SELECT answer, slot FROM daily_games").fetchone()
    assert players == {"old": "buldak", "easy": None}
    assert game == ("하늘", "buldak")
    # 하루 한 문제 시절의 판은 1번 문제(slot 0)가 된다.
    assert daily == ("구름", 0)


def test_두_번_돌려도_안전하다(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(OLD_SCHEMA)
    Database(path).initialize()
    Database(path).initialize()
    assert "slot" in columns(path, "daily_games")
