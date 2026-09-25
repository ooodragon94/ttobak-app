"""지금 또박 DB 를 Turso 로 옮긴다. 스트림릿 이전 때 **한 번** 쓴다.

쓰는 법 (PowerShell)::

    cd <또박 폴더>
    $env:TTOBAK_TURSO_URL   = "libsql://…turso.io"
    $env:TTOBAK_TURSO_TOKEN = "…"
    .venv\\Scripts\\python.exe tools\\copy_to_turso.py --source var\\ttobak.sqlite3

토큰을 명령줄 인자로 받지 않는 이유: 인자는 프로세스 목록과 셸 기록에 남는다.
환경 변수는 그 창을 닫으면 사라진다.

무엇을 하나
-----------

1. 운영 DB 를 **읽기 전용으로** 열어 그 순간의 사본을 뜬다. 서버가 돌고 있어도
   안전한 방법(SQLite 백업 API)이다. 운영 DB 에는 아무것도 쓰지 않는다.
2. Turso 에 표를 만든다. 앱이 쓰는 것과 **같은 코드**(:class:`Database`)로 만들어서
   스키마가 어긋날 일이 없다.
3. 표마다 줄을 옮기고, 끝나면 양쪽 줄 수를 비교해 보여 준다.

Turso 에 이미 플레이어가 있으면 멈춘다. 두 번 돌려서 기록이 겹치는 것을 막는다.
그래도 덮어쓰려면 ``--force`` (그때는 Turso 쪽을 먼저 비운다).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

#: 운영 DB 기본 위치. 서버를 돌리던 폴더의 var/ 아래다.
DEFAULT_SOURCE = ROOT / "var" / "ttobak.sqlite3"

#: 옮기는 순서. 다른 표를 가리키는(외래 키) 표는 가리켜지는 표 뒤에 온다.
ORDER = [
    "players",
    "rooms",
    "room_members",
    "games",
    "daily_games",
    "comments",
    "supporters",
    "word_reports",
]


def snapshot(source: Path) -> Path:
    """운영 DB 를 읽기 전용으로 열어 임시 사본을 만든다."""
    target = Path(tempfile.mkdtemp(prefix="ttobak-copy-")) / "snapshot.sqlite3"
    live = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    copy = sqlite3.connect(target)
    live.backup(copy)
    live.close()
    copy.close()
    return target


def tables(connection: sqlite3.Connection) -> list[str]:
    names = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%'"
        )
    ]
    known = [name for name in ORDER if name in names]
    return known + sorted(name for name in names if name not in ORDER)


def columns(connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--target-file",
        type=Path,
        help="Turso 대신 이 로컬 파일로 옮긴다(시험용). TURSO 주소가 없을 때만.",
    )
    parser.add_argument(
        "--force", action="store_true", help="Turso 에 기록이 있어도 비우고 옮긴다"
    )
    args = parser.parse_args()

    remote = os.environ.get("TTOBAK_TURSO_URL")
    if not remote and not args.target_file:
        print("TTOBAK_TURSO_URL 이 없습니다. 파일 첫머리의 쓰는 법을 보세요.")
        return 1
    if not remote:
        os.environ["TTOBAK_DB_DRIVER"] = "libsql"
    if not args.source.exists():
        print(f"운영 DB 가 없습니다: {args.source}")
        return 1

    from ttobak.db.repository import Database

    source_path = snapshot(args.source)
    source = sqlite3.connect(source_path)
    placeholder = Path(tempfile.gettempdir()) / "unused.sqlite3"
    target = Database(args.target_file or placeholder)
    where = "Turso (원격)" if remote else f"로컬 시험 파일 {args.target_file}"
    print("옮길 곳:", where)

    # 앱과 같은 코드로 표를 만든다.
    target.initialize()

    with target.connect() as conn:
        existing = conn.execute("SELECT COUNT(*) AS n FROM players").fetchone()["n"]
    if existing and not args.force:
        print(f"옮길 곳에 이미 플레이어가 {existing}명 있습니다.")
        print("두 번 옮기지 않으려고 멈춥니다.")
        print("정말 덮어쓰려면 --force 를 붙이세요.")
        return 1

    names = tables(source)
    with target.connect() as conn:
        if existing:
            # 가리키는 표부터 지운다(외래 키 순서의 반대).
            for table in reversed(names):
                conn.execute(f"DELETE FROM {table}")
        for table in names:
            wanted = set(columns(conn, table))
            shared = [c for c in columns(source, table) if c in wanted]
            if not shared:
                continue
            listed = ", ".join(shared)
            marks = ", ".join("?" for _ in shared)
            rows = source.execute(f"SELECT {listed} FROM {table}").fetchall()
            for row in rows:
                sql = f"INSERT INTO {table} ({listed}) VALUES ({marks})"
                conn.execute(sql, tuple(row))
            print(f"  {table}: {len(rows)}줄 옮김")

    # 옮긴 뒤 다시 세어 본다. "옮겼다고 찍힌 것" 과 "실제로 들어간 것" 은 다르다.
    ok = True
    with target.connect() as conn:
        for table in names:
            want = source.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            got = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            mark = "OK" if want == got else "다름!"
            ok &= want == got
            print(f"  확인 {table}: 원본 {want} / 옮긴 곳 {got}  {mark}")
    source.close()
    print("끝. 전부 맞습니다." if ok else "!! 줄 수가 다른 표가 있습니다. 위를 보세요.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
