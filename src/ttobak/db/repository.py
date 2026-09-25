"""SQLite 접근 계층.

라우터가 SQL을 직접 쓰지 않도록 모든 질의를 여기에 모은다. 트래픽이 가정용
규모라 커넥션 풀 대신 요청마다 커넥션을 열고 닫는다. WAL 모드라 읽기와 쓰기가
서로를 막지 않는다.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

__all__ = [
    "ConcurrentGuessError",
    "Database",
    "GameRecord",
    "LeaderboardEntry",
    "Player",
    "PlayerStats",
]


class ConcurrentGuessError(RuntimeError):
    """같은 판에 다른 추측이 먼저 반영됐을 때.

    동시에 여러 번 보내 한 번의 기회로 여러 단어를 채점받는 것을 막는다.
    """

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

#: 플레이어를 읽을 때 쓰는 컬럼 목록. 한곳에 두어 쿼리마다 어긋나지 않게 한다.
_PLAYER_COLUMNS = (
    "SELECT id, display_name, created_at, last_seen_at, hints_enabled, relation,"
    " share_theme, puzzle_lengths, max_attempts, difficulty"
)


def _utcnow() -> str:
    """ISO-8601 UTC 타임스탬프. 저장되는 모든 시각은 이 형식을 쓴다."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _carry_over_hard_mode(
    connection: sqlite3.Connection, table: str, existing: set[str]
) -> None:
    """예전 ``hard_mode`` 참/거짓 컬럼을 새 ``difficulty`` 열쇠로 옮긴다.

    난이도가 켬/끔 하나였던 시절에는 두 규칙(자리 고정 + 자모 필수)이 늘 같이
    걸렸다. 그 상태와 지금 같은 것은 ``buldak`` 이므로 그리로 옮긴다.

    ``existing`` 은 **컬럼을 더하기 전** 의 컬럼 이름들이다. 옛 컬럼이 없는
    새 데이터베이스에서 이 함수를 부르면 SQL 이 그냥 터지므로 먼저 확인한다.

    옛 컬럼은 지우지 않고 남긴다. SQLite 의 ``DROP COLUMN`` 은 버전을 타고,
    한 번 옮기고 나면 아무도 안 읽는 컬럼이라 남아 있어도 해가 없다.
    """
    if "hard_mode" not in existing:
        return
    connection.execute(
        f"UPDATE {table} SET difficulty = 'buldak' WHERE hard_mode = 1"  # noqa: S608
    )


@dataclass(frozen=True)
class Player:
    id: str
    display_name: str
    created_at: str
    last_seen_at: str
    #: 이 사람이 힌트를 쓰기로 했는지. 기본은 꺼짐이다.
    hints_enabled: bool = False
    #: 공유 격자를 그릴 테마 이름.
    share_theme: str = "classic"
    #: 이 사람이 고른 자모 길이들. ``None`` 이면 서버 기본값 전부를 쓴다.
    puzzle_lengths: tuple[int, ...] | None = None
    #: 이 사람이 고른 시도 횟수. ``None`` 이면 서버 기본값을 쓴다.
    max_attempts: int | None = None
    #: 이 사람이 고른 난이도 열쇠(``game.hard.DIFFICULTIES``).
    difficulty: str = "normal"
    #: 방 주인과 어떤 사이인지("대학동기", "회사동료"...). 선택이라 빈 값이 정상.
    relation: str = ""


@dataclass(frozen=True)
class GameRecord:
    """한 플레이어의 한 라운드 상태."""

    player_id: str
    round_no: int
    answer: str
    status: str
    guesses: tuple[str, ...]
    started_at: str
    finished_at: str | None
    played_on: date
    #: 이 판에서 쓴 힌트 수.
    hints_used: int = 0
    #: 판을 시작할 때의 시도 횟수. ``None`` 이면 서버 기본값.
    max_attempts: int | None = None
    #: 이 판의 난이도. 판을 열 때 박아 둔다.
    difficulty: str = "normal"

    @property
    def is_finished(self) -> bool:
        return self.status != "playing"

    @property
    def attempts(self) -> int:
        return len(self.guesses)


@dataclass(frozen=True)
class Room:
    """방 하나."""

    id: str
    name: str
    owner_id: str
    created_at: str
    puzzle_salt: str
    #: 지금 인원. 목록을 그릴 때 쓴다.
    member_count: int = 0
    #: 이 방 회원에게 응원하기를 보여 줄지.
    #:
    #: **기본은 켜짐이다.** 대부분의 방에는 보여도 되고, 안 보여야 하는 쪽이
    #: 예외다. 가까운 친구들 방처럼 돈 이야기가 껄끄러운 곳만 주인이 끈다.
    support_enabled: bool = True


@dataclass(frozen=True)
class DailyRecord:
    """방의 '오늘의 문제' 한 판.

    :class:`GameRecord` 와 모양이 비슷하지만 일부러 따로 둔다. 이쪽은 라운드
    번호가 없고 방과 날짜가 열쇠라, 하나로 합치면 두 경우 모두에서 의미가
    없는 필드를 들고 다니게 된다.
    """

    room_id: str
    play_date: date
    player_id: str
    answer: str
    status: str
    guesses: tuple[str, ...]
    started_at: str
    finished_at: str | None
    hints_used: int = 0
    #: 그날 몇 번째 문제인가. 하루에 여러 개를 내므로 열쇠의 일부다.
    slot: int = 0

    @property
    def is_finished(self) -> bool:
        return self.status != "playing"

    @property
    def attempts(self) -> int:
        return len(self.guesses)


@dataclass(frozen=True)
class DailyStanding:
    """방의 오늘 순위 한 줄.

    오늘의 문제는 **모두가 같은 단어**를 푸는 하루 한 판이라, 일반 순위표와
    달리 '몇 번 만에 맞혔나'로 바로 줄을 세울 수 있다. 그게 이 방식의 핵심이다.
    """

    player_id: str
    display_name: str
    #: 방장과의 사이. 비어 있을 수 있다.
    relation: str
    #: ``won`` / ``lost`` / ``playing``, 그리고 아직 손도 안 댔으면 ``none``.
    status: str
    #: 이 문제에 쓴 시도 횟수. 적을수록 잘한 것이다.
    attempts: int
    hints_used: int
    finished_at: str | None


@dataclass(frozen=True)
class Comment:
    """오늘의 문제에 남긴 한 줄."""

    id: int
    player_id: str
    display_name: str
    body: str
    created_at: str


@dataclass(frozen=True)
class LeaderboardEntry:
    """오늘 하루 한 사람의 성적."""

    display_name: str
    solved: int
    played: int
    #: 맞힌 판들의 평균 시도 횟수. 하나도 못 맞혔으면 ``None``.
    average_attempts: float | None
    #: 맞힌 판 중 가장 적은 시도 횟수. 하나도 못 맞혔으면 ``None``.
    best_attempts: int | None = None
    #: 방장과의 사이. 비어 있을 수 있다.
    relation: str = ""


@dataclass(frozen=True)
class PlayerStats:
    played: int
    wins: int
    current_streak: int
    max_streak: int
    #: 시도 횟수 -> 그 횟수로 성공한 판 수.
    guess_distribution: dict[int, int]

    @property
    def win_rate(self) -> float:
        return self.wins / self.played if self.played else 0.0

    @property
    def average_attempts(self) -> float | None:
        """맞힌 판들의 평균 시도 횟수. 한 판도 못 맞혔으면 ``None``.

        분포에서 다시 계산한다. 별도 컬럼을 두면 두 값이 어긋날 수 있는데,
        하나에서 유도하면 그럴 일이 없다.
        """
        total = sum(count for count in self.guess_distribution.values())
        if not total:
            return None
        weighted = sum(
            attempts * count for attempts, count in self.guess_distribution.items()
        )
        return weighted / total


def _enable_wal(connection: sqlite3.Connection) -> None:
    """쓰기 로그(WAL) 모드를 켠다.

    **이 파일 맨 위 설명은 오랫동안 거짓말이었다.** "WAL 모드라 읽기와 쓰기가
    서로를 막지 않는다" 고 적어 두고, 정작 켜는 코드가 어디에도 없었다.
    돌아가던 서버가 WAL 이었던 것은 언젠가 손으로 한 번 켰기 때문이다 —
    journal_mode 는 **파일 헤더에 박히는 값**이라 한 번 켜면 계속 남는다.

    그래서 증상이 안 보였다. 데이터베이스 파일을 새로 만드는 순간
    (새 설치, 덤프에서 복원, 파일을 지우고 재시작) 조용히 기본값인 DELETE 로
    돌아가고, 쓰기 처리량이 몇 배 떨어지는데 아무도 안 알려 준다.

    두 모드가 커밋 한 번에 하는 일이 다르다.

    DELETE
        원본 페이지를 롤백 저널에 복사 → fsync → 본 파일 수정 → fsync →
        저널 삭제 → 디렉터리 fsync. 디스크에 진짜로 닿는 왕복이 여러 번이다.
    WAL
        바뀐 페이지를 로그 파일 **끝에 덧붙이고** fsync 한 번. 본 파일로
        옮기는 일(체크포인트)은 나중에 몰아서 한다.

    이 기계에서 재 보니 커밋 300번 기준 DELETE 146/초, WAL 620/초였다.

    덤으로 **읽는 사람이 쓰는 사람을 막지 않는다.** DELETE 모드에서는 쓰는
    동안 파일 전체가 잠겨 읽기도 멈춘다. 순위표를 보는 사람이 추측을 제출하는
    사람을 기다리게 만들 이유가 없다.

    ``synchronous`` 는 건드리지 않는다. NORMAL 로 낮추면 훨씬 빨라지지만
    (여기서 재 보니 35배) 그건 갑자기 전원이 나갔을 때 **최근 커밋 몇 개를
    잃어도 된다**는 뜻이다. 남의 게임 기록을 그렇게 다룰 이유가 없다.
    """
    connection.execute("PRAGMA journal_mode = WAL")


class Database:
    """SQLite 파일 하나를 감싸는 저장소.

    두 가지로 열 수 있다.

    - **sqlite3** (기본): 이 PC 에서 파일 하나로 돈다. 지금까지의 방식.
    - **libsql**: 스트림릿 배포용. 디스크가 남지 않는 곳이라 기록은 Turso(원격)에
      두고, 로컬 파일은 읽기를 빠르게 하는 복제본으로만 쓴다.

    고르는 것은 환경 변수다. ``TTOBAK_TURSO_URL`` 이 있으면 libsql 로 원격에
    붙고, ``TTOBAK_DB_DRIVER=libsql`` 이면 원격 없이 로컬 파일을 libsql 로 연다
    (같은 SQL 이 libsql 에서 도는지 시험할 때 쓴다).
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._turso_url = os.environ.get("TTOBAK_TURSO_URL") or None
        self._turso_token = os.environ.get("TTOBAK_TURSO_TOKEN") or None
        driver = os.environ.get("TTOBAK_DB_DRIVER", "").strip().lower()
        self._use_libsql = bool(self._turso_url) or driver == "libsql"

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        """데이터베이스 파일과 스키마를 준비한다. 여러 번 호출해도 안전하다."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            # 쓰기 로그(WAL) 모드는 **로컬 파일**에 거는 것이다. 원격(Turso)은
            # 저장 방식을 서버가 정하므로 건드리지 않는다.
            #
            # 로컬이면 libsql 이어도 반드시 켠다. 처음에 libsql 이면 무조건 껐더니,
            # 읽는 쪽이 쓰는 쪽을 막아서 동시에 들어온 요청이 기다리지도 못하고
            # 바로 "잠겼다" 로 실패했다(동시 요청 시험이 매번 깨짐).
            if not self._turso_url:
                _enable_wal(connection)
            connection.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
            self._migrate(connection)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """이미 만들어진 표에 나중에 생긴 컬럼을 붙인다.

        ``CREATE TABLE IF NOT EXISTS`` 는 표가 이미 있으면 아무것도 하지 않는다.
        그래서 컬럼을 새로 추가하면 새 데이터베이스에만 생기고 쓰던 것에는
        안 생긴다. 기존 기록을 지우지 않으려면 여기서 따로 붙여 줘야 한다.

        마이그레이션 도구를 들이기에는 이르므로, 필요한 컬럼이 있는지 보고
        없으면 더하는 식으로 최소한만 한다. 여러 번 실행해도 안전하다.
        """

        def columns_of(table: str) -> set[str]:
            rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
            return {row["name"] for row in rows}

        game_columns = columns_of("games")
        if "difficulty" not in game_columns:
            # 이 판의 난이도. **판마다 박아 둬야** 다 풀고 나서 설정을 올려
            # "불닭모드로 풀었다" 고 자랑하는 것을 막는다.
            #
            # NULL 이 기본 난이도를 뜻한다. 문자열 기본값을 넣지 않는 이유는
            # 난이도 이름을 나중에 바꾸면 옛 행에 죽은 값이 남기 때문이다.
            connection.execute("ALTER TABLE games ADD COLUMN difficulty TEXT")
            _carry_over_hard_mode(connection, "games", game_columns)
        if "max_attempts" not in game_columns:
            # **판 시작 시점의 시도 횟수를 박아 둔다.**
            #
            # 정답을 스냅숏하는 것과 같은 이유다. 설정을 바꿨다고 풀던 판의
            # 규칙이 바뀌면 안 된다 — 특히 줄이면 그 자리에서 패배가 된다.
            # NULL 은 이 컬럼이 생기기 전의 옛 판이라 서버 기본값으로 본다.
            connection.execute("ALTER TABLE games ADD COLUMN max_attempts INTEGER")
        if "hints_used" not in game_columns:
            connection.execute(
                "ALTER TABLE games ADD COLUMN hints_used INTEGER NOT NULL DEFAULT 0"
            )
        player_columns = columns_of("players")
        if "recovery_hash" not in player_columns:
            # 닉네임 선점용. 비밀번호 없이도 "먼저 쓴 사람이 임자" 를 만든다.
            #
            # 기존 계정은 NULL 로 남는다. 그 계정들은 다음에 그 닉네임으로
            # 들어오는 사람이 임자가 되고 그때 코드를 받는다. 지금 쓰는
            # 사람이 대개 본인이라 실질적 위험은 낮지만, 완전히 깨끗하게
            # 가려면 공개 전에 players 표를 비우면 된다.
            connection.execute("ALTER TABLE players ADD COLUMN recovery_hash TEXT")
        if "hints_enabled" not in player_columns:
            connection.execute(
                "ALTER TABLE players ADD COLUMN hints_enabled"
                " INTEGER NOT NULL DEFAULT 0"
            )
        if "puzzle_lengths" not in player_columns:
            # 이 사람이 풀고 싶은 자모 길이. JSON 배열 문자열이다.
            #
            # **NULL 이 "서버 기본값 전부" 를 뜻한다.** 빈 배열과 구분해야
            # 하는데, 빈 배열이면 낼 문제가 없어 게임이 멈춘다. NULL 을
            # 기본으로 두면 설정을 건드린 적 없는 사람은 지금까지와 똑같이
            # 동작한다.
            connection.execute("ALTER TABLE players ADD COLUMN puzzle_lengths TEXT")
        if "slot" not in columns_of("daily_games"):
            # **기본키가 바뀐다.** SQLite 는 기본키를 고칠 수 없어서 표를
            # 새로 만들고 옮기는 수밖에 없다. 옛 판은 전부 1번 문제(slot 0)로
            # 본다 — 그때는 하루에 하나뿐이었으니 사실 그대로다.
            connection.executescript(
                """
                CREATE TABLE daily_games_new (
                    room_id     TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
                    play_date   TEXT NOT NULL,
                    player_id   TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                    answer      TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'playing'
                                CHECK (status IN ('playing', 'won', 'lost')),
                    guesses     TEXT NOT NULL DEFAULT '[]',
                    started_at  TEXT NOT NULL,
                    finished_at TEXT,
                    hints_used  INTEGER NOT NULL DEFAULT 0,
                    slot        INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (room_id, play_date, slot, player_id)
                );
                INSERT INTO daily_games_new
                    (room_id, play_date, player_id, answer, status, guesses,
                     started_at, finished_at, hints_used, slot)
                SELECT room_id, play_date, player_id, answer, status, guesses,
                       started_at, finished_at, hints_used, 0
                  FROM daily_games;
                DROP TABLE daily_games;
                ALTER TABLE daily_games_new RENAME TO daily_games;
                CREATE INDEX IF NOT EXISTS idx_daily_room_date
                    ON daily_games (room_id, play_date, status);
                """
            )

        room_columns = columns_of("rooms")
        if "support_enabled" not in room_columns:
            # 기본 1 = 켜짐. 이미 있는 방들도 지금까지와 똑같이 동작한다 —
            # 마이그레이션이 조용히 기능을 꺼 버리면 안 된다.
            connection.execute(
                "ALTER TABLE rooms ADD COLUMN support_enabled"
                " INTEGER NOT NULL DEFAULT 1"
            )
        if "difficulty" not in player_columns:
            connection.execute("ALTER TABLE players ADD COLUMN difficulty TEXT")
            _carry_over_hard_mode(connection, "players", player_columns)
        if "max_attempts" not in player_columns:
            # 이 사람이 쓸 시도 횟수. NULL 이면 서버 기본값을 쓴다.
            connection.execute("ALTER TABLE players ADD COLUMN max_attempts INTEGER")
        if "relation" not in player_columns:
            # 방 주인과 어떤 사이인지. 선택 입력이라 빈 문자열이 기본이다.
            connection.execute(
                "ALTER TABLE players ADD COLUMN relation"
                " TEXT NOT NULL DEFAULT ''"
            )
        if "share_theme" not in player_columns:
            connection.execute(
                "ALTER TABLE players ADD COLUMN share_theme"
                " TEXT NOT NULL DEFAULT 'classic'"
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """커넥션을 열고 커밋/롤백까지 책임지는 컨텍스트 매니저."""
        if self._use_libsql:
            from ttobak.db import libsql_adapter

            connection = libsql_adapter.connect(
                str(self._path),
                url=self._turso_url,
                auth_token=self._turso_token,
            )
            if not self._turso_url:
                # sqlite3.connect(timeout=5.0) 와 같은 것. libsql 로컬 파일은 기본
                # 대기 시간이 0 이라, 두 요청이 겹치면 기다리지 않고 바로
                # "잠겼다" 로 실패한다. 동시에 열 번 힌트를 요청하는 시험이 정확히
                # 그렇게 깨졌다. 원격(Turso)은 서버가 순서를 정하므로 필요 없다.
                connection.execute("PRAGMA busy_timeout = 5000")
        else:
            connection = sqlite3.connect(self._path, timeout=5.0)
            connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    # --- 플레이어 ---

    def upsert_player(
        self,
        player_id: str,
        display_name: str,
        *,
        tailscale_node: str | None = None,
        tailscale_user: str | None = None,
    ) -> Player:
        """플레이어를 만들거나, 이미 있으면 표시 이름과 접속 정보를 갱신한다."""
        now = _utcnow()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO players (id, display_name, created_at, last_seen_at,
                                     tailscale_node, tailscale_user)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    -- **표시 이름은 다시 덮어쓰지 않는다.**
                    --
                    -- 식별자는 정규화한 값이라 "민수", "민 수", "민수ㅋㅋ" 가
                    -- 모두 같은 id 가 된다. 덮어쓰면 아무나 `민수ㅋㅋ` 로
                    -- 들어와 진짜 민수의 순위표 이름을 바꿔 버릴 수 있다.
                    -- 처음 정한 이름을 그대로 둔다.
                    last_seen_at   = excluded.last_seen_at,
                    tailscale_node = COALESCE(excluded.tailscale_node,
                                              players.tailscale_node),
                    tailscale_user = COALESCE(excluded.tailscale_user,
                                              players.tailscale_user)
                """,
                (player_id, display_name, now, now, tailscale_node, tailscale_user),
            )
            row = connection.execute(
                _PLAYER_COLUMNS + " FROM players WHERE id = ?",
                (player_id,),
            ).fetchone()
        return _to_player(row)

    def recovery_hash_of(self, player_id: str) -> tuple[bool, str | None]:
        """(계정이 있는가, 복구 코드 해시). 없는 계정이면 ``(False, None)``.

        존재 여부와 해시를 함께 돌려주는 이유: 부르는 쪽이 "없는 계정",
        "선점 안 된 옛 계정", "선점된 계정" 셋을 구분해야 하는데 질의를
        두 번 하면 그 사이에 값이 바뀔 수 있다.
        """
        with self.connect() as connection:
            row = connection.execute(
                "SELECT recovery_hash FROM players WHERE id = ?", (player_id,)
            ).fetchone()
        if row is None:
            return False, None
        return True, row["recovery_hash"]

    def set_recovery_hash(self, player_id: str, recovery_hash: str) -> None:
        """복구 코드 해시를 심는다. **이미 있으면 덮어쓰지 않는다.**

        덮어쓰기를 허용하면 남의 계정에 내 코드를 심어 통째로 가져갈 수 있다.
        ``WHERE recovery_hash IS NULL`` 이 그걸 막는다 — 한 번 임자가 정해진
        계정은 다시 주인이 바뀌지 않는다.
        """
        with self.connect() as connection:
            connection.execute(
                "UPDATE players SET recovery_hash = ?"
                " WHERE id = ? AND recovery_hash IS NULL",
                (recovery_hash, player_id),
            )

    def replace_recovery_hash(self, player_id: str, recovery_hash: str) -> None:
        """복구 코드 해시를 **덮어쓴다.**

        ``set_recovery_hash`` 의 ``WHERE recovery_hash IS NULL`` 가드가 없다.
        그 가드는 "닉네임을 아는 사람이 남의 계정에 자기 코드를 심는 것" 을
        막는 장치인데, 여기서는 그 위협이 성립하지 않는다 — **부르는 쪽이
        이미 그 계정의 쿠키를 확인한 뒤**이기 때문이다. 쿠키를 가졌다는 것은
        이미 그 계정으로 게임을 하고 있다는 뜻이라, 코드를 바꿀 수 있다고 해서
        새로 얻는 권한이 없다.

        **이 메서드는 본인 확인을 마친 자리에서만 불러야 한다.** 참가(join)
        경로에서는 절대 쓰면 안 된다. 거기서 쓰면 위 가드가 무의미해진다.
        """
        with self.connect() as connection:
            connection.execute(
                "UPDATE players SET recovery_hash = ? WHERE id = ?",
                (recovery_hash, player_id),
            )

    def get_player(self, player_id: str) -> Player | None:
        with self.connect() as connection:
            row = connection.execute(
                _PLAYER_COLUMNS + " FROM players WHERE id = ?",
                (player_id,),
            ).fetchone()
        return _to_player(row) if row else None

    def update_preferences(
        self,
        player_id: str,
        *,
        hints_enabled: bool | None = None,
        relation: str | None = None,
        share_theme: str | None = None,
        puzzle_lengths: tuple[int, ...] | None = None,
        max_attempts: int | None = None,
        difficulty: str | None = None,
    ) -> Player:
        """개인 설정을 바꾼다. 준 항목만 반영한다.

        여러 설정을 한 메서드로 처리한다. 설정이 늘 때마다 메서드를 새로 만들면
        라우터가 그만큼 갈라진다. 여기서 갱신할 컬럼만 골라 한 번에 쓴다.
        """
        assignments: list[str] = []
        values: list[object] = []
        if hints_enabled is not None:
            assignments.append("hints_enabled = ?")
            values.append(1 if hints_enabled else 0)
        if relation is not None:
            assignments.append("relation = ?")
            values.append(relation)
        if share_theme is not None:
            assignments.append("share_theme = ?")
            values.append(share_theme)
        if puzzle_lengths is not None:
            # 빈 튜플은 "전부 다시" 라는 뜻으로 NULL 을 넣는다. 빈 배열을
            # 그대로 저장하면 낼 문제가 없어 게임이 멈춘다.
            assignments.append("puzzle_lengths = ?")
            values.append(
                json.dumps(sorted(puzzle_lengths)) if puzzle_lengths else None
            )
        if max_attempts is not None:
            assignments.append("max_attempts = ?")
            values.append(max_attempts)
        if difficulty is not None:
            assignments.append("difficulty = ?")
            values.append(difficulty)

        with self.connect() as connection:
            if assignments:
                connection.execute(
                    f"UPDATE players SET {', '.join(assignments)} WHERE id = ?",
                    (*values, player_id),
                )
            row = connection.execute(
                _PLAYER_COLUMNS + " FROM players WHERE id = ?",
                (player_id,),
            ).fetchone()
        return _to_player(row)

    # --- 라운드 ---

    def latest_game(self, player_id: str) -> GameRecord | None:
        """가장 최근 라운드. 한 판도 시작하지 않았으면 ``None``."""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM games
                 WHERE player_id = ?
                 ORDER BY round_no DESC
                 LIMIT 1
                """,
                (player_id,),
            ).fetchone()
        return _to_game(row) if row else None

    def get_game(self, player_id: str, round_no: int) -> GameRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM games WHERE player_id = ? AND round_no = ?",
                (player_id, round_no),
            ).fetchone()
        return _to_game(row) if row else None

    def start_round(
        self,
        player_id: str,
        round_no: int,
        answer: str,
        played_on: date,
        max_attempts: int | None = None,
        difficulty: str = "normal",
    ) -> GameRecord:
        """라운드를 만든다. 이미 있으면 기존 판을 그대로 돌려준다.

        ``ON CONFLICT DO NOTHING`` 덕분에 같은 요청이 동시에 두 번 들어와도 판이
        둘로 갈라지지 않는다. 정답을 함께 저장하므로 사전이나 소금값이 바뀌어도
        진행 중인 판은 시작할 때의 정답으로 계속 채점된다.
        """
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO games (player_id, round_no, answer, status,
                                   guesses, started_at, played_on, max_attempts,
                                   difficulty)
                VALUES (?, ?, ?, 'playing', '[]', ?, ?, ?, ?)
                ON CONFLICT(player_id, round_no) DO NOTHING
                """,
                (
                    player_id,
                    round_no,
                    answer,
                    _utcnow(),
                    played_on.isoformat(),
                    max_attempts,
                    difficulty,
                ),
            )
            row = connection.execute(
                "SELECT * FROM games WHERE player_id = ? AND round_no = ?",
                (player_id, round_no),
            ).fetchone()
        return _to_game(row)

    def set_game_difficulty(
        self, player_id: str, round_no: int, difficulty: str, *,
        require_untouched: bool = True,
    ) -> GameRecord | None:
        """진행 중인 판의 난이도를 갈아 준다.

        기본은 **아직 한 번도 안 친 판만** 이다. 조건을 SQL 에 함께 넣는
        이유는 검사와 갱신 사이에 판이 바뀔 수 있기 때문이다. 파이썬에서
        "추측이 없네" 를 확인하고 갱신하면, 그 사이에 들어온 추측이 조용히
        다른 난이도로 채점된다. ``json_array_length(guesses) = 0`` 이 그것을
        막는다 — 한 글자라도 쳤으면 ``None`` 이 돌아간다.

        ``require_untouched=False`` 는 **규칙을 빼기만 할 때**만 쓴다.
        그때는 위 경합이 해가 없다. 사이에 낀 추측은 더 엄한 옛 규칙으로
        검사를 통과한 것이라, 느슨해진 규칙으로도 당연히 통과한다.
        반대 방향에는 절대 쓰면 안 된다.
        """
        untouched = "AND json_array_length(guesses) = 0" if require_untouched else ""
        with self.connect() as connection:
            connection.execute(
                f"""
                UPDATE games SET difficulty = ?
                 WHERE player_id = ? AND round_no = ?
                   AND status = 'playing'
                   {untouched}
                """,  # noqa: S608
                (difficulty, player_id, round_no),
            )
            row = connection.execute(
                "SELECT * FROM games WHERE player_id = ? AND round_no = ?",
                (player_id, round_no),
            ).fetchone()
        return _to_game(row) if row else None

    def save_progress(
        self,
        player_id: str,
        round_no: int,
        guesses: Sequence[str],
        status: str,
    ) -> GameRecord:
        """추측 목록 전체와 상태를 갱신한다.

        추측 하나를 이어붙이는 대신 목록 전체를 덮어쓴다. 호출자가 이미 검증을
        끝낸 결과를 그대로 반영하므로 부분 갱신보다 어긋날 여지가 적다.
        """
        finished_at = _utcnow() if status != "playing" else None
        # 낙관적 잠금.
        #
        # 이 목록은 "읽은 것 + 새 추측 하나" 다. 그러니 저장할 때 **읽었을
        # 때의 개수** 가 그대로 남아 있어야 맞다. 그 사이에 다른 요청이
        # 하나를 더 넣었다면 우리가 계산한 목록은 그 추측을 지워 버린다.
        #
        # 이게 없으면 추측 여섯 개를 동시에 보내 **한 번의 기회로 여섯 단어의
        # 색을 다 알아낼 수 있었다.** 응답은 여섯 개 다 채점돼 돌아오는데
        # 저장은 하나만 남기 때문이다.
        expected = max(len(guesses) - 1, 0)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE games
                   SET guesses = ?, status = ?, finished_at = ?
                 WHERE player_id = ? AND round_no = ?
                   AND json_array_length(guesses) = ?
                """,
                (
                    json.dumps(list(guesses), ensure_ascii=False),
                    status,
                    finished_at,
                    player_id,
                    round_no,
                    expected,
                ),
            )
            if cursor.rowcount == 0:
                raise ConcurrentGuessError(
                    "방금 다른 요청이 먼저 반영됐습니다. 다시 시도해 주세요."
                )
            row = connection.execute(
                "SELECT * FROM games WHERE player_id = ? AND round_no = ?",
                (player_id, round_no),
            ).fetchone()
        return _to_game(row)

    def abandon_round(self, player_id: str, round_no: int) -> GameRecord | None:
        """진행 중인 판을 패배로 닫는다. 추측은 그대로 둔다.

        ``save_progress`` 를 쓰지 않는 이유: 그쪽은 "읽은 목록 + 새 추측
        하나" 를 저장한다고 보고 낙관적 잠금을 건다. 포기는 추측을 더하지
        않으므로 그 전제가 안 맞아 늘 충돌로 잡힌다. 하는 일이 다르면
        메서드도 달라야 한다.

        ``status = 'playing'`` 조건이 잠금 역할을 한다. 이미 끝난 판을
        다시 패배로 덮어쓰지 않는다 — 이겨서 끝난 판을 지운 판으로
        바꿔 버리면 기록이 거짓말이 된다.
        """
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE games SET status = 'lost', finished_at = ?
                 WHERE player_id = ? AND round_no = ? AND status = 'playing'
                """,
                (_utcnow(), player_id, round_no),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM games WHERE player_id = ? AND round_no = ?",
                (player_id, round_no),
            ).fetchone()
        return _to_game(row) if row else None

    def use_hint(
        self, player_id: str, round_no: int, allowance: int
    ) -> GameRecord | None:
        """힌트 사용 횟수를 하나 올린다. **상한을 넘으면 ``None``.**

        읽고 더해서 쓰는 대신 SQL 안에서 증가시킨다. 그런데 그것만으로는
        부족했다 — **상한 검사가 파이썬 쪽에 있었기 때문이다.**

        힌트 요청 열 개를 동시에 보내면 열 개 모두 "지금 0개 썼고 한 개까지
        쓸 수 있다" 를 읽고 통과한 뒤, 각자 +1 을 실행해 10 이 됐다. 화면은
        ``정답[:hints_used]`` 를 보여 주므로 **정답이 통째로 열렸다.**

        그래서 상한을 ``WHERE`` 로 옮긴다. 조건이 SQL 안에 있으면 읽기와 쓰기
        사이가 없어져서 동시에 와도 한 번만 통과한다. 통과 못 했으면
        ``rowcount`` 가 0 이고, 그때 ``None`` 을 돌려준다.
        """
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE games
                   SET hints_used = hints_used + 1
                 WHERE player_id = ? AND round_no = ? AND hints_used < ?
                """,
                (player_id, round_no, allowance),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM games WHERE player_id = ? AND round_no = ?",
                (player_id, round_no),
            ).fetchone()
        return _to_game(row)

    # --- 후원 ---

    def report_word(self, jamos: str, length: int, player_id: str) -> None:
        """"이건 진짜 단어인데요" 신고를 받는다.

        같은 자모를 여러 명이 신고하면 줄을 늘리지 않고 **표를 올린다.**
        표가 많은 것이 먼저 볼 것이고, 한 사람이 같은 말을 여러 번 눌러도
        표는 한 번만 오른다면 좋겠지만, 그러려면 (자모, 사람) 쌍을 다 들고
        있어야 한다. 친구 서른 명 규모에서 지불할 복잡도가 아니다.
        """
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO word_reports (jamos, length, player_id, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(jamos) DO UPDATE SET
                    votes = votes + 1,
                    -- 이미 기각한 말을 다시 신고하면 한 번 더 보게 되돌린다.
                    -- 사람이 여럿 같은 말을 하면 내 판정이 틀렸을 수 있다.
                    status = CASE WHEN word_reports.status = 'rejected'
                                  THEN 'pending' ELSE word_reports.status END
                """,
                (jamos, length, player_id, _utcnow()),
            )

    def pending_word_reports(self, limit: int = 50) -> list[dict]:
        """아직 판정하지 않은 신고. 표 많은 순."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, jamos, length, votes, created_at"
                "  FROM word_reports WHERE status = 'pending'"
                " ORDER BY votes DESC, id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve_word_report(
        self, report_id: int, status: str, word: str | None, note: str
    ) -> None:
        """신고를 판정 완료로 표시한다."""
        with self.connect() as connection:
            connection.execute(
                "UPDATE word_reports SET status = ?, word = ?, note = ?,"
                "       reviewed_at = ? WHERE id = ?",
                (status, word, note, _utcnow(), report_id),
            )

    def add_supporter(self, player_id: str, amount: int) -> int:
        """후원했다고 알려 온 것을 기록하고, 그 사람의 총 후원 횟수를 준다.

        **본인 신고를 그대로 믿는다.** 카카오페이는 우리에게 아무것도 알려
        주지 않으므로 확인할 방법이 없다. 거짓으로 얻는 것이 배지 하나뿐이라
        검증 장치를 만들 값어치가 없다고 봤다.
        """
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO supporters (player_id, amount, created_at)"
                " VALUES (?, ?, ?)",
                (player_id, amount, _utcnow()),
            )
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM supporters WHERE player_id = ?",
                (player_id,),
            ).fetchone()
        return int(row["n"])

    def supporter_ids(self) -> set[str]:
        """배지를 붙일 사람들. 순위표를 그릴 때 한 번에 읽는다.

        줄마다 따로 물으면 30명이면 질의가 30번이다. 한 번에 집합으로 받아
        메모리에서 맞춘다.
        """
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT player_id FROM supporters"
            ).fetchall()
        return {row["player_id"] for row in rows}

    def supporter_names(self) -> set[str]:
        """배지를 붙일 사람들의 **표시 이름**.

        순위표가 id 가 아니라 표시 이름으로 줄을 세우기 때문이다. id 로만
        들고 있으면 순위표 쪽에서 다시 이름을 찾아야 하고, 그러면 줄마다
        질의가 하나씩 는다.
        """
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT p.display_name FROM supporters s"
                " JOIN players p ON p.id = s.player_id"
            ).fetchall()
        return {row["display_name"] for row in rows}

    # --- 집계 ---

    def leaderboard(self, since: str, until: str) -> list[LeaderboardEntry]:
        """``since`` 이상 ``until`` 미만에 **끝낸** 판으로 매긴 순위.

        시각은 판에 저장된 ``finished_at`` 과 같은 모양(UTC ISO)이어야 한다.
        :func:`ttobak.clock.day_bounds_utc` 로 하루를 바꿔 넘긴다. 판을 연 날
        (``played_on``)로 세지 않는 이유는 순위 API 쪽 주석에 적었다.

        문제가 끝없이 이어지므로 '몇 번 만에 맞혔나'로는 줄을 세울 수 없다.
        그래서 **오늘 몇 문제를 맞혔는지** 를 첫 기준으로 삼고, 같으면 평균 시도
        횟수가 적은 사람을 위에 둔다.
        """
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT p.display_name,
                       p.relation,
                       SUM(CASE WHEN g.status = 'won' THEN 1 ELSE 0 END) AS solved,
                       SUM(CASE WHEN g.status != 'playing' THEN 1 ELSE 0 END)
                           AS played,
                       AVG(CASE WHEN g.status = 'won'
                                THEN json_array_length(g.guesses) END)
                           AS average_attempts,
                       MIN(CASE WHEN g.status = 'won'
                                THEN json_array_length(g.guesses) END)
                           AS best_attempts
                  FROM games AS g
                  JOIN players AS p ON p.id = g.player_id
                 WHERE g.finished_at >= ? AND g.finished_at < ?
                 GROUP BY g.player_id, p.display_name
                HAVING played > 0
                 ORDER BY solved DESC,
                          average_attempts ASC,
                          played ASC
                """,
                (since, until),
            ).fetchall()
        return [
            LeaderboardEntry(
                display_name=row["display_name"],
                relation=row["relation"] or "",
                solved=row["solved"] or 0,
                played=row["played"] or 0,
                average_attempts=(
                    round(row["average_attempts"], 2)
                    if row["average_attempts"] is not None
                    else None
                ),
                best_attempts=row["best_attempts"],
            )
            for row in rows
        ]

    # --- 방 ---

    def create_room(
        self, room_id: str, name: str, owner_id: str, puzzle_salt: str
    ) -> Room:
        """방을 만들고 만든 사람을 회원으로 넣는다.

        만드는 것과 들어가는 것을 한 트랜잭션에 둔다. 나뉘어 있으면 중간에
        죽었을 때 **주인이 없는 방**이 남고, 그 방은 아무도 못 들어가는데
        지워지지도 않는다.
        """
        now = _utcnow()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO rooms (id, name, owner_id, created_at, puzzle_salt)"
                " VALUES (?, ?, ?, ?, ?)",
                (room_id, name, owner_id, now, puzzle_salt),
            )
            connection.execute(
                "INSERT INTO room_members (room_id, player_id, joined_at)"
                " VALUES (?, ?, ?)",
                (room_id, owner_id, now),
            )
        return Room(
            id=room_id,
            name=name,
            owner_id=owner_id,
            created_at=now,
            puzzle_salt=puzzle_salt,
            member_count=1,
            support_enabled=True,
        )

    def get_room(self, room_id: str) -> Room | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT r.*, (SELECT COUNT(*) FROM room_members m"
                "             WHERE m.room_id = r.id) AS member_count"
                "  FROM rooms AS r WHERE r.id = ?",
                (room_id,),
            ).fetchone()
        return _to_room(row) if row else None

    def is_member(self, room_id: str, player_id: str) -> bool:
        """이 사람이 그 방 회원인가.

        **방을 다루는 모든 요청이 이걸 먼저 물어야 한다.** 방 코드는 링크에
        실려 돌아다니므로, 코드를 아는 것과 회원인 것은 다르다.
        """
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM room_members WHERE room_id = ? AND player_id = ?",
                (room_id, player_id),
            ).fetchone()
        return row is not None

    def join_room(self, room_id: str, player_id: str) -> None:
        """방에 넣는다. 이미 회원이면 아무 일도 하지 않는다."""
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO room_members (room_id, player_id, joined_at)"
                " VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                (room_id, player_id, _utcnow()),
            )

    def leave_room(self, room_id: str, player_id: str) -> None:
        """방에서 나온다. 기록(판, 댓글)은 지우지 않는다.

        지우면 다른 사람이 보던 오늘 순위표에서 한 줄이 사라지고, 남이 남긴
        댓글의 맥락이 깨진다. 나가는 것은 '앞으로 안 본다'는 뜻이지 '없던 일로
        한다'가 아니다.
        """
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM room_members WHERE room_id = ? AND player_id = ?",
                (room_id, player_id),
            )

    def rooms_of(self, player_id: str) -> list[Room]:
        """이 사람이 속한 방들. 최근에 들어간 순."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT r.*, (SELECT COUNT(*) FROM room_members m2"
                "             WHERE m2.room_id = r.id) AS member_count"
                "  FROM rooms AS r"
                "  JOIN room_members AS m ON m.room_id = r.id"
                " WHERE m.player_id = ?"
                " ORDER BY m.joined_at DESC",
                (player_id,),
            ).fetchall()
        return [_to_room(row) for row in rows]

    def count_rooms_owned(self, player_id: str) -> int:
        """이 사람이 만든 방 수. 자동 생성으로 DB 를 채우는 것을 막는 데 쓴다."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM rooms WHERE owner_id = ?", (player_id,)
            ).fetchone()
        return int(row["n"])

    def set_room_support(self, room_id: str, enabled: bool) -> None:
        """이 방에서 응원하기를 보여 줄지 정한다. 방 주인만 부를 수 있다.

        누가 부를 수 있는지는 라우터가 판단한다. 저장소는 시키는 대로 쓴다.
        """
        with self.connect() as connection:
            connection.execute(
                "UPDATE rooms SET support_enabled = ? WHERE id = ?",
                (1 if enabled else 0, room_id),
            )

    def support_open_for(self, player_id: str) -> bool:
        """이 사람에게 응원하기를 보여 줄지.

        규칙은 하나다 — **켜 둔 방이 하나라도 있으면 보여 준다.**
        방이 아예 없는 사람에게도 보여 준다.

        이 조합이 나온 이유
        -------------------

        내가 만든 방(친구들방·지인들방)에 있는 사람들은 베타테스터다.
        테스트해 주는 사람에게 돈 이야기를 꺼내는 것은 껄끄럽고, 껄끄러우면
        피드백이 줄어든다. 그래서 그 방들은 끈다.

        그런데 그 친구가 **자기 방을 따로 만들면** 이야기가 다르다. 그건
        자기 사람들을 데려와 쓰는 것이고, 그때는 보여도 된다. 그래서
        "꺼진 방에 속하면 무조건 숨김" 이 아니라 "켜진 방이 하나라도 있으면
        보임" 으로 둔다.

        방이 없는 사람은 링크로 들어와 혼자 푸는 사람이다. 누구의 베타테스터도
        아니므로 보여 준다.

        사람 기준으로 판단하는 이유는 응원하기가 방 화면이 아니라 설정에 있는
        전역 메뉴여서다. 받는 사람은 어차피 만든 사람 한 명이라, 방마다 다르게
        보이면 "누구를 응원하는가" 가 헷갈린다.
        """
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT COUNT(*) AS total,"
                "       COALESCE(SUM(r.support_enabled), 0) AS enabled"
                "  FROM room_members AS m"
                "  JOIN rooms AS r ON r.id = m.room_id"
                " WHERE m.player_id = ?",
                (player_id,),
            ).fetchone()
        # 방이 없으면(total 0) 보여 준다. 있으면 켜진 것이 하나라도 있어야 한다.
        return rows["total"] == 0 or rows["enabled"] > 0

    def count_members(self, room_id: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM room_members WHERE room_id = ?",
                (room_id,),
            ).fetchone()
        return int(row["n"])

    # --- 오늘의 문제 ---

    def start_daily(
        self,
        room_id: str,
        play_date: date,
        player_id: str,
        answer: str,
        slot: int = 0,
    ) -> DailyRecord:
        """오늘 판을 만든다. 이미 있으면 그대로 돌려준다.

        기본키가 (방, 날짜, 사람)이라 **하루 한 판이 DB 수준에서 보장된다.**
        코드로 세지 않으므로 요청이 동시에 두 번 들어와도 판이 갈라지지 않는다.

        정답을 함께 저장하는 이유는 일반 라운드와 같다. 사전이 바뀌어도 이미
        시작한 판은 시작할 때의 정답으로 채점돼야 한다.
        """
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO daily_games (room_id, play_date, player_id, answer,"
                "                         status, guesses, started_at, slot)"
                " VALUES (?, ?, ?, ?, 'playing', '[]', ?, ?)"
                " ON CONFLICT(room_id, play_date, slot, player_id) DO NOTHING",
                (room_id, play_date.isoformat(), player_id, answer, _utcnow(), slot),
            )
            row = connection.execute(
                "SELECT * FROM daily_games"
                " WHERE room_id = ? AND play_date = ? AND slot = ? AND player_id = ?",
                (room_id, play_date.isoformat(), slot, player_id),
            ).fetchone()
        return _to_daily(row)

    def get_daily(
        self, room_id: str, play_date: date, player_id: str, slot: int = 0
    ) -> DailyRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM daily_games"
                " WHERE room_id = ? AND play_date = ? AND slot = ? AND player_id = ?",
                (room_id, play_date.isoformat(), slot, player_id),
            ).fetchone()
        return _to_daily(row) if row else None

    def room_daily_answer(
        self, room_id: str, play_date: date, slot: int = 0
    ) -> str | None:
        """그 방에서 그날 그 문제를 **누군가 이미 열었다면** 그 정답.

        오늘의 문제는 정답 목록에서 매번 계산한다. 그런데 목록이 하루 중간에
        바뀌면(사전 손질, 신고 반영) 먼저 연 사람과 나중에 연 사람의 낱말이
        달라진다. "같은 방 같은 날은 같은 낱말" 이 이 기능의 전제라서, 먼저
        연 사람의 것을 기준으로 삼는다.
        """
        with self.connect() as connection:
            row = connection.execute(
                "SELECT answer FROM daily_games"
                " WHERE room_id = ? AND play_date = ? AND slot = ?"
                " ORDER BY started_at LIMIT 1",
                (room_id, play_date.isoformat(), slot),
            ).fetchone()
        return row["answer"] if row else None

    def dailies_of(
        self, room_id: str, play_date: date, player_id: str
    ) -> dict[int, DailyRecord]:
        """이 사람의 그날 판들을 슬롯 번호로 묶어 돌려준다.

        화면이 "1번은 끝, 2번은 푸는 중" 을 한눈에 보여 주려면 둘 다 필요하다.
        슬롯마다 따로 물으면 커넥션을 그만큼 더 연다.
        """
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM daily_games"
                " WHERE room_id = ? AND play_date = ? AND player_id = ?",
                (room_id, play_date.isoformat(), player_id),
            ).fetchall()
        return {row["slot"]: _to_daily(row) for row in rows}

    def save_daily(
        self,
        room_id: str,
        play_date: date,
        player_id: str,
        guesses: tuple[str, ...],
        status: str,
        hints_used: int | None = None,
        expect_attempts: int | None = None,
        slot: int = 0,
    ) -> DailyRecord | None:
        """오늘 판의 진행을 저장한다.

        ``status != 'playing'`` 이면 끝난 시각을 박는다. 그 시각이 순위표에서
        같은 시도 횟수끼리 줄을 세우는 기준이 된다(먼저 푼 사람이 위).
        """
        finished_at = _utcnow() if status != "playing" else None
        # 낙관적 잠금. ``expect_attempts`` 를 주면 **읽었을 때의 개수가 그대로
        # 남아 있을 때만** 저장한다. 그 사이에 다른 요청이 하나를 넣었다면
        # 우리가 만든 목록은 그 추측을 지워 버린다.
        guard = "" if expect_attempts is None else " AND json_array_length(guesses) = ?"
        tail: tuple = (room_id, play_date.isoformat(), slot, player_id)
        if expect_attempts is not None:
            tail = (*tail, expect_attempts)

        with self.connect() as connection:
            if hints_used is None:
                cursor = connection.execute(
                    "UPDATE daily_games SET guesses = ?, status = ?,"
                    "       finished_at = COALESCE(?, finished_at)"
                    " WHERE room_id = ? AND play_date = ? AND slot = ?"
                    "   AND player_id = ?" + guard,
                    (
                        json.dumps(list(guesses), ensure_ascii=False),
                        status,
                        finished_at,
                        *tail,
                    ),
                )
            else:
                cursor = connection.execute(
                    "UPDATE daily_games SET guesses = ?, status = ?,"
                    "       hints_used = ?,"
                    "       finished_at = COALESCE(?, finished_at)"
                    " WHERE room_id = ? AND play_date = ? AND slot = ?"
                    "   AND player_id = ?" + guard,
                    (
                        json.dumps(list(guesses), ensure_ascii=False),
                        status,
                        hints_used,
                        finished_at,
                        *tail,
                    ),
                )
            if expect_attempts is not None and cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM daily_games"
                " WHERE room_id = ? AND play_date = ? AND slot = ? AND player_id = ?",
                (room_id, play_date.isoformat(), slot, player_id),
            ).fetchone()
        return _to_daily(row)

    def abandon_daily(
        self, room_id: str, play_date: date, player_id: str, slot: int = 0
    ) -> DailyRecord | None:
        """진행 중인 오늘의 문제를 패배로 닫는다.

        ``status = 'playing'`` 조건이 잠금 역할을 한다. 이미 이겨서 끝난 판을
        패배로 덮어쓰면 순위표가 거짓말을 하게 된다.
        """
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE daily_games SET status = 'lost', finished_at = ?"
                " WHERE room_id = ? AND play_date = ? AND slot = ?"
                "   AND player_id = ? AND status = 'playing'",
                (_utcnow(), room_id, play_date.isoformat(), slot, player_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM daily_games"
                " WHERE room_id = ? AND play_date = ? AND slot = ? AND player_id = ?",
                (room_id, play_date.isoformat(), slot, player_id),
            ).fetchone()
        return _to_daily(row) if row else None

    def use_daily_hint(
        self, room_id: str, play_date: date, player_id: str, slot: int, allowance: int
    ) -> DailyRecord | None:
        """오늘의 문제에서 힌트를 하나 연다. **상한을 넘으면 ``None``.**

        일반 라운드의 ``use_hint`` 와 같은 이유로 상한을 ``WHERE`` 에 둔다.
        파이썬에서 검사하고 갱신하면, 힌트 요청을 동시에 열 개 보냈을 때
        열 개가 모두 통과해 정답이 통째로 열린다(실제로 그랬다).
        """
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE daily_games
                   SET hints_used = hints_used + 1
                 WHERE room_id = ? AND play_date = ? AND slot = ?
                   AND player_id = ? AND hints_used < ?
                """,
                (room_id, play_date.isoformat(), slot, player_id, allowance),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM daily_games"
                " WHERE room_id = ? AND play_date = ? AND slot = ? AND player_id = ?",
                (room_id, play_date.isoformat(), slot, player_id),
            ).fetchone()
        return _to_daily(row) if row else None

    def daily_standings(
        self, room_id: str, play_date: date, slot: int
    ) -> list[DailyStanding]:
        """방의 **그 문제** 순위. 방 사람 전원이 한 줄씩 나온다.

        왜 문제별로 나누는가
        --------------------

        전에는 하루치를 사람 단위로 합쳐서 보여 줬는데, 문제가 둘이 되자
        곧바로 틀렸다. **1번을 맞히고 2번을 열기만 해도 '푸는 중'** 이 되어
        방금 맞힌 사실이 화면에서 사라졌다. 실제로 그 화면을 봤다.

        합치는 것 자체가 안 되는 일이었다. 1번과 2번은 **다른 낱말이고 칸
        수도 다르다.** 그런 둘의 시도 횟수를 더한 값으로 등수를 매기면,
        5칸을 3번에 맞힌 사람과 7칸을 3번에 맞힌 사람이 같은 줄에 선다.
        비교가 성립하는 것은 **같은 문제를 푼 사람들 사이**뿐이고, 그게
        애초에 오늘의 문제를 두는 이유다.

        화면에도 이미 ①② 전환 단추가 있다. 순위도 거기에 맞추면
        보고 있는 문제와 순위가 늘 같은 것을 가리킨다.

        왜 안 푼 사람까지 넣는가
        ------------------------

        29명짜리 방인데 순위에 두 줄만 떠서 "왜 나는 두 명밖에 안 뜨노" 라는
        말을 들었다. 푼 사람만 보여 주니 방이 텅 빈 것처럼 보인 것이다.
        전원을 내보내고 아직 안 한 사람은 ``none`` 으로 표시한다 —
        누가 남았는지는 화면이 정한다.

        정렬: 맞힌 사람 → 못 맞힌 사람 → 푸는 중 → 아직 안 함.
        맞힌 사람끼리는 시도 적은 순 → 힌트 적게 쓴 순 → 먼저 끝낸 순.
        힌트를 넣는 이유는 같은 3번이라도 힌트 없이 푼 쪽이 더 잘한 것이기
        때문이다.
        """
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT m.player_id,
                       p.display_name,
                       p.relation,
                       COALESCE(d.status, 'none') AS status,
                       COALESCE(json_array_length(d.guesses), 0) AS attempts,
                       COALESCE(d.hints_used, 0) AS hints_used,
                       d.finished_at AS finished_at
                  FROM room_members AS m
                  JOIN players AS p ON p.id = m.player_id
                  LEFT JOIN daily_games AS d
                         ON d.room_id = m.room_id
                        AND d.player_id = m.player_id
                        AND d.play_date = ?
                        AND d.slot = ?
                 WHERE m.room_id = ?
                 ORDER BY CASE status
                              WHEN 'won' THEN 0
                              WHEN 'lost' THEN 1
                              WHEN 'playing' THEN 2
                              ELSE 3
                          END,
                          attempts ASC,
                          hints_used ASC,
                          COALESCE(finished_at, '') ASC,
                          p.display_name ASC
                """,
                (play_date.isoformat(), slot, room_id),
            ).fetchall()
        return [
            DailyStanding(
                player_id=row["player_id"],
                display_name=row["display_name"],
                relation=row["relation"] or "",
                status=row["status"],
                attempts=row["attempts"],
                hints_used=row["hints_used"],
                finished_at=row["finished_at"],
            )
            for row in rows
        ]

    # --- 댓글 ---

    def add_comment(
        self, room_id: str, play_date: date, player_id: str, body: str
    ) -> Comment:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO comments (room_id, play_date, player_id, body,"
                "                      created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (room_id, play_date.isoformat(), player_id, body, _utcnow()),
            )
            row = connection.execute(
                "SELECT c.id, c.player_id, p.display_name, c.body, c.created_at"
                "  FROM comments AS c JOIN players AS p ON p.id = c.player_id"
                " WHERE c.id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return _to_comment(row)

    def comments(self, room_id: str, play_date: date) -> list[Comment]:
        """그 방의 그날 댓글. 오래된 것부터.

        **부르는 쪽이 자격을 먼저 확인해야 한다.** 오늘 문제를 아직 안 끝낸
        사람에게 이걸 주면 댓글 한 줄이 그날 문제를 통째로 망친다.
        저장소는 그 판단을 하지 않는다.
        """
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT c.id, c.player_id, p.display_name, c.body, c.created_at"
                "  FROM comments AS c JOIN players AS p ON p.id = c.player_id"
                " WHERE c.room_id = ? AND c.play_date = ?"
                " ORDER BY c.id ASC",
                (room_id, play_date.isoformat()),
            ).fetchall()
        return [_to_comment(row) for row in rows]

    def count_comments_today(
        self, room_id: str, play_date: date, player_id: str
    ) -> int:
        """이 사람이 오늘 이 방에 남긴 수. 도배를 막는 데 쓴다."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM comments"
                " WHERE room_id = ? AND play_date = ? AND player_id = ?",
                (room_id, play_date.isoformat(), player_id),
            ).fetchone()
        return int(row["n"])

    def player_stats(self, player_id: str) -> PlayerStats:
        """개인 통계. 연속 기록은 끝난 판만 라운드 역순으로 세어 계산한다."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT round_no, status, json_array_length(guesses) AS attempts
                  FROM games
                 WHERE player_id = ? AND status != 'playing'
                 ORDER BY round_no DESC
                """,
                (player_id,),
            ).fetchall()

        played = len(rows)
        wins = sum(1 for row in rows if row["status"] == "won")

        distribution: dict[int, int] = {}
        for row in rows:
            if row["status"] == "won":
                distribution[row["attempts"]] = distribution.get(row["attempts"], 0) + 1

        current_streak = 0
        for row in rows:
            if row["status"] != "won":
                break
            current_streak += 1

        max_streak = running = 0
        for row in reversed(rows):
            running = running + 1 if row["status"] == "won" else 0
            max_streak = max(max_streak, running)

        return PlayerStats(
            played=played,
            wins=wins,
            current_streak=current_streak,
            max_streak=max_streak,
            guess_distribution=distribution,
        )


def _to_player(row: sqlite3.Row) -> Player:
    """DB 행 하나를 ``Player``로 변환한다."""
    return Player(
        id=row["id"],
        display_name=row["display_name"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        hints_enabled=bool(row["hints_enabled"]),
        relation=row["relation"] or "",
        share_theme=row["share_theme"],
        # NULL 이면 "서버 기본값 전부". 빈 배열과 구분해야 한다 —
        # 빈 배열이면 낼 문제가 없어 게임이 멈춘다.
        puzzle_lengths=(
            tuple(json.loads(row["puzzle_lengths"]))
            if row["puzzle_lengths"]
            else None
        ),
        max_attempts=row["max_attempts"],
        difficulty=row["difficulty"] or "normal",
    )


def _to_room(row: sqlite3.Row) -> Room:
    return Room(
        id=row["id"],
        name=row["name"],
        owner_id=row["owner_id"],
        created_at=row["created_at"],
        puzzle_salt=row["puzzle_salt"],
        # 인원 수는 **모든 방 조회가 함께 세어 와야 한다.**
        #
        # 없으면 여기서 KeyError 로 바로 터진다. 그게 맞다 — 기본값 0으로
        # 넘기면 "회원이 0명인 방"이 조용히 화면에 뜨고, 그게 버그인지
        # 진짜 빈 방인지 구분할 방법이 없다.
        member_count=row["member_count"],
        support_enabled=bool(row["support_enabled"]),
    )


def _to_comment(row: sqlite3.Row) -> Comment:
    return Comment(
        id=row["id"],
        player_id=row["player_id"],
        display_name=row["display_name"],
        body=row["body"],
        created_at=row["created_at"],
    )


def _to_daily(row: sqlite3.Row) -> DailyRecord:
    """DB 행 하나를 ``DailyRecord``로 변환한다."""
    return DailyRecord(
        room_id=row["room_id"],
        play_date=date.fromisoformat(row["play_date"]),
        player_id=row["player_id"],
        answer=row["answer"],
        status=row["status"],
        guesses=tuple(json.loads(row["guesses"])),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        hints_used=row["hints_used"],
        slot=row["slot"],
    )


def _to_game(row: sqlite3.Row) -> GameRecord:
    """DB 행 하나를 ``GameRecord``로 변환한다."""
    return GameRecord(
        player_id=row["player_id"],
        round_no=row["round_no"],
        answer=row["answer"],
        status=row["status"],
        guesses=tuple(json.loads(row["guesses"])),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        played_on=date.fromisoformat(row["played_on"]),
        hints_used=row["hints_used"],
        # 판을 열 때 박아 둔 시도 횟수. 여기서 빠뜨리면 저장은 되는데 읽을
        # 때 사라져서, DB 에는 4 가 들어 있는데 화면은 6 을 보여 준다.
        # 실제로 그 상태였고 테스트가 잡았다.
        max_attempts=row["max_attempts"],
        difficulty=row["difficulty"] or "normal",
    )
