"""계정을 지운다. **기본은 미리보기고, 지우려면 따로 말해야 한다.**

개발하면서 만든 시연·시험 계정이 실제 방에 그대로 남아, 친구 방 인원이
실제보다 두 배로 보였다. 그걸 치우려고 만든 도구다.

왜 손으로 안 지우고 도구를 만들었나
-----------------------------------

``DELETE FROM players`` 한 줄이면 될 것 같지만, 이 스키마에서는 그게
**방을 통째로 날릴 수 있다.**

    rooms.owner_id TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE

방 주인을 지우면 방이 지워지고, 방이 지워지면 그 방의 참가자·오늘의 문제·
한마디가 전부 딸려 간다. 지우려던 것은 계정 하나인데 스물아홉 명의 기록이
사라진다. 경고도 없다.

그래서 이 도구는 **방 주인을 거부한다.** 그리고 지우기 전에 무엇이 딸려
가는지 세어서 보여 준다. 사람이 숫자를 보고 판단할 수 있어야 한다.

이름을 코드에 적어 두지 않는다
------------------------------

지울 대상은 인자로 받는다. "이번에 지울 것" 목록을 파일에 박아 두면 그
목록이 곧 낡은 주석이 되고, 다음에 쓸 때 남의 계정을 지운다.

사용법::

    python tools/prune_players.py --db var/ttobak.sqlite3 테스터 테 타
    python tools/prune_players.py --db var/ttobak.sqlite3 테스터 --yes
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

#: 사람에게 보여 줄 때 세는 것들. (표 이름, 설명)
COUNTED = (
    ("games", "혼자 푼 판"),
    ("daily_games", "오늘의 문제"),
    ("room_members", "방 참가"),
    ("comments", "한마디"),
)


def rows_owned(connection: sqlite3.Connection, table: str, player_id: str) -> int:
    """그 사람 앞으로 달린 줄 수."""
    sql = f"SELECT COUNT(*) FROM {table} WHERE player_id = ?"  # noqa: S608
    return connection.execute(sql, (player_id,)).fetchone()[0]


def rooms_owned(connection: sqlite3.Connection, player_id: str) -> list[str]:
    """그 사람이 **주인인** 방 이름들. 하나라도 있으면 지우면 안 된다."""
    return [
        row[0]
        for row in connection.execute(
            "SELECT name FROM rooms WHERE owner_id = ?", (player_id,)
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nicknames", nargs="*", help="지울 닉네임")
    parser.add_argument(
        "--inactive-days",
        type=int,
        help="이 일수 동안 안 들어온 사람을 대상에 더한다",
    )
    parser.add_argument(
        "--db", type=Path, required=True, help="데이터베이스 파일"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="진짜로 지운다. 없으면 무엇이 지워질지 보여 주기만 한다",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"데이터베이스가 없습니다: {args.db}")
        return 1

    if not args.nicknames and args.inactive_days is None:
        print("지울 닉네임이나 --inactive-days 중 하나는 있어야 합니다.")
        return 1

    connection = sqlite3.connect(args.db)
    # 켜지 않으면 CASCADE 가 동작하지 않아 딸린 줄이 남는다. SQLite 는
    # 연결마다 꺼진 채로 시작한다 — 이것이 기본값인 것을 잊기 쉽다.
    connection.execute("PRAGMA foreign_keys = ON")

    nicknames = list(args.nicknames)
    if args.inactive_days is not None:
        # **마지막 접속 시각으로 고른다.** 판 수로 고르면 오래 열심히 하다
        # 그만둔 사람이 남고, 어제 처음 들어온 사람이 지워진다.
        cutoff = (datetime.now(UTC) - timedelta(days=args.inactive_days)).isoformat()
        stale = [
            row[0]
            for row in connection.execute(
                "SELECT display_name FROM players WHERE last_seen_at < ?"
                " ORDER BY last_seen_at",
                (cutoff,),
            )
        ]
        print(f"{args.inactive_days}일 넘게 안 들어온 사람 {len(stale)}명")
        nicknames += [name for name in stale if name not in nicknames]

    targets: list[tuple[str, str]] = []
    missing: list[str] = []
    blocked: list[tuple[str, list[str]]] = []

    for nickname in nicknames:
        row = connection.execute(
            "SELECT id, display_name FROM players WHERE display_name = ?",
            (nickname,),
        ).fetchone()
        if row is None:
            missing.append(nickname)
            continue
        owned = rooms_owned(connection, row[0])
        if owned:
            blocked.append((nickname, owned))
            continue
        targets.append((row[0], row[1]))

    for nickname in missing:
        print(f"  없음      {nickname}")

    for nickname, owned in blocked:
        # 지우면 방이 통째로 사라진다. 사람이 손으로 주인을 넘긴 뒤에만
        # 지울 수 있게 한다 — 자동으로 넘겨 주면 그게 더 위험하다.
        print(f"  거부      {nickname} — 방 주인이다: {', '.join(owned)}")

    if not targets:
        print("\n지울 것이 없습니다.")
        return 1 if blocked else 0

    print(f"\n지울 계정 {len(targets)}개")
    total = dict.fromkeys(COUNTED, 0)
    for player_id, name in targets:
        counts = {
            label: rows_owned(connection, table, player_id) for table, label in COUNTED
        }
        for key in COUNTED:
            total[key] += counts[key[1]]
        detail = " · ".join(f"{label} {n}" for label, n in counts.items() if n)
        print(f"  {name:14} {detail or '기록 없음'}")

    print("\n함께 사라지는 것")
    for (_, label), n in total.items():
        print(f"  {label:12} {n}")

    if not args.yes:
        print("\n미리보기입니다. 진짜로 지우려면 --yes 를 붙이세요.")
        return 0

    connection.executemany(
        "DELETE FROM players WHERE id = ?", [(player_id,) for player_id, _ in targets]
    )
    connection.commit()
    left = connection.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    print(f"\n지웠습니다. 남은 계정 {left}개")
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
