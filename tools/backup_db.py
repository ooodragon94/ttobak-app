"""데이터베이스를 안전하게 떠 둔다.

왜 파일 복사가 아니라 이 도구인가
---------------------------------

또박은 WAL 모드로 돈다. 즉 **최근에 쓴 내용이 본 파일에 아직 없다.**
옆의 ``-wal`` 파일에 있다가 나중에 옮겨진다. 그래서 탐색기에서
``ttobak.sqlite3`` 하나만 복사하면 **반쪽짜리를 복사한 것**이고, 그게
백업인 줄 알고 있다가 정작 필요할 때 최근 기록이 없는 것을 발견하게 된다.

``sqlite3`` 명령줄 도구의 ``.backup`` 이 정석이지만 이 PC 에는 깔려 있지
않다. 파이썬 표준 라이브러리의 ``Connection.backup()`` 이 같은 일을 한다 —
돌고 있는 데이터베이스를 잠그지 않고, WAL 까지 합쳐서, 일관된 한 벌을 뜬다.

**뜬 다음 열어 본다.** 한 번도 열어 본 적 없는 백업은 백업이 아니다.
이 도구는 뜨자마자 표를 세어 보고 결과를 알려 준다.

사용법::

    python tools/backup_db.py
    python tools/backup_db.py --keep 14
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "var" / "ttobak.sqlite3"
DEFAULT_OUT = PROJECT_ROOT / "var" / "backups"

#: 백업이 제대로 떠졌는지 보려고 세어 보는 표들.
CHECKED = ("players", "games", "daily_games", "rooms", "comments")


def make_backup(db_path: Path, out_dir: Path) -> Path:
    """돌고 있는 데이터베이스를 그대로 한 벌 뜬다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # 초까지 넣는다. 분 단위로 하면 같은 분에 두 번 뜰 때 앞의 것을 조용히
    # 덮어써서, 백업이 하나 늘어난 줄 알았는데 그대로인 일이 생긴다.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"ttobak-{stamp}.sqlite3"

    source = sqlite3.connect(db_path)
    try:
        destination = sqlite3.connect(target)
        try:
            # 이 한 줄이 핵심이다. 파일을 읽는 것이 아니라 데이터베이스에게
            # "네 상태를 저기로 옮겨 적어" 라고 시킨다. 그래서 도중에 쓰기가
            # 들어와도 앞뒤가 맞는 한 벌이 나온다.
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return target


def verify(path: Path) -> dict[str, int]:
    """뜬 백업을 실제로 열어서 표를 세어 본다."""
    connection = sqlite3.connect(path)
    try:
        # 파일이 깨졌는지부터 본다. 세는 것만으로는 못 잡는 손상이 있다.
        state = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if state != "ok":
            raise RuntimeError(f"백업이 손상됐습니다: {state}")
        counts = {}
        for table in CHECKED:
            try:
                sql = f"SELECT COUNT(*) FROM {table}"  # noqa: S608
                counts[table] = connection.execute(sql).fetchone()[0]
            except sqlite3.OperationalError:
                continue  # 아직 없는 표는 건너뛴다
        return counts
    finally:
        connection.close()


def prune(out_dir: Path, keep: int) -> list[Path]:
    """오래된 백업을 지운다. 새것부터 ``keep`` 개만 남긴다."""
    files = sorted(out_dir.glob("ttobak-*.sqlite3"), reverse=True)
    doomed = files[keep:]
    for path in doomed:
        path.unlink()
    return doomed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--keep", type=int, default=7, help="남겨 둘 백업 개수 (기본 7)"
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"데이터베이스가 없습니다: {args.db}")
        return 1

    target = make_backup(args.db, args.out)
    counts = verify(target)

    size = target.stat().st_size / 1024
    print(f"떴습니다: {target}  ({size:,.0f} KB)")
    print("  " + " · ".join(f"{name} {n}" for name, n in counts.items()))

    removed = prune(args.out, args.keep)
    if removed:
        print(f"  오래된 백업 {len(removed)}개 지움 (최근 {args.keep}개 유지)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
