"""libSQL(Turso) 커넥션을 ``sqlite3`` 처럼 쓰게 하는 얇은 변환기.

왜 필요한가
-----------

스트림릿 무료 배포는 파일이 남지 않는다. 앱이 잠들었다 깨거나 다시 배포되면
디스크가 처음으로 돌아가서, 지금처럼 SQLite 파일 하나에 모든 기록을 두면
매번 날아간다. 그래서 기록은 Turso(원격 libSQL)에 둔다.

libSQL 은 SQLite 에서 갈라져 나온 것이라 SQL 문법이 같다. JSON 함수, 중복 처리
(``ON CONFLICT``), 트랜잭션, 바뀐 줄 수(``rowcount``)가 전부 그대로 된다. 그래서
저장 코드(:mod:`ttobak.db.repository`)는 한 줄도 안 바꾼다.

**딱 하나가 다르다.** 파이썬 ``libsql`` 모듈에는 ``row_factory`` 가 없어서 결과를
튜플로만 준다. 저장 코드는 전부 ``row["answer"]`` 처럼 이름으로 꺼내므로, 그
자리만 여기서 메운다.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Sequence
from typing import Any

#: 원격 DB 에 쓴 시간의 누계. 느릴 때 "DB 가 느린가, 다른 게 느린가" 를 가르는
#: 데 쓴다. 여러 사람의 요청이 동시에 더하므로 잠금을 건다.
_stats_lock = threading.Lock()
_stats = {"connects": 0, "connect_ms": 0.0, "queries": 0, "query_ms": 0.0}


def _add(kind: str, started: float) -> None:
    elapsed = (time.perf_counter() - started) * 1000
    with _stats_lock:
        _stats[kind + "s" if kind == "connect" else "queries"] += 1
        _stats[kind + "_ms"] += elapsed


def stats() -> dict[str, float]:
    """지금까지의 누계를 복사해 준다. 앞뒤로 두 번 재서 빼면 그 사이 몫이 된다."""
    with _stats_lock:
        return dict(_stats)


class Row:
    """``sqlite3.Row`` 처럼 이름으로도, 번호로도 꺼낼 수 있는 결과 한 줄.

    ``dict(row)`` 가 되려면 ``keys()`` 와 이름 꺼내기가 있어야 한다. 저장 코드가
    실제로 쓰는 것은 이름 꺼내기와 ``dict(row)`` 두 가지다.
    """

    __slots__ = ("_names", "_values")

    def __init__(self, names: dict[str, int], values: Sequence[Any]) -> None:
        self._names = names
        self._values = tuple(values)

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, str):
            return self._values[self._names[key]]
        return self._values[key]

    def keys(self) -> list[str]:
        return list(self._names)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        pairs = ", ".join(f"{name}={self[name]!r}" for name in self._names)
        return f"Row({pairs})"


class Cursor:
    """결과를 :class:`Row` 로 바꿔 주는 커서. 나머지는 원래 커서에 넘긴다."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor
        description = cursor.description or ()
        self._names = {column[0]: index for index, column in enumerate(description)}

    def _wrap(self, values: Sequence[Any] | None) -> Row | None:
        return None if values is None else Row(self._names, values)

    def fetchone(self) -> Row | None:
        return self._wrap(self._cursor.fetchone())

    def fetchall(self) -> list[Row]:
        return [Row(self._names, values) for values in self._cursor.fetchall()]

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._cursor.lastrowid

    @property
    def description(self) -> Any:
        return self._cursor.description


class Connection:
    """``sqlite3.Connection`` 자리에 끼우는 libSQL 커넥션."""

    def __init__(self, connection: Any, *, remote: bool = False) -> None:
        self._connection = connection
        self._remote = remote

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> Cursor:
        started = time.perf_counter()
        try:
            return Cursor(self._connection.execute(sql, tuple(parameters)))
        finally:
            _add("query", started)

    def executemany(self, sql: str, rows: Any) -> Cursor:
        return Cursor(self._connection.executemany(sql, rows))

    def executescript(self, script: str) -> None:
        """여러 문장을 **한 문장씩** 보낸다.

        libsql 의 ``executescript`` 는 로컬 파일에서는 되는데 **원격(Turso)에서는
        조용히 아무 일도 안 했다.** 표를 만드는 스키마가 통째로 빠진 채 다음
        단계로 넘어가서 "games 표가 없다" 로 처음 드러났다. 그래서 문장을 나눠
        하나씩 보낸다. 나누는 기준은 SQLite 가 직접 판단하게 한다
        (:func:`sqlite3.complete_statement`) — 세미콜론으로 대충 자르면 문자열이나
        트리거 안의 세미콜론에서 틀린다.
        """
        for statement in split_statements(script):
            # 저장 방식(저널 모드)은 **원격이면 서버가 정한다.** Turso 는 이
            # 문장을 아예 거절한다("SQL not allowed statement").
            if self._remote and _code_of(statement).upper().startswith(
                "PRAGMA JOURNAL_MODE"
            ):
                continue
            self._connection.execute(statement)

    def commit(self) -> None:
        started = time.perf_counter()
        try:
            self._connection.commit()
        finally:
            _add("query", started)

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def sync(self) -> None:
        """원격(Turso)과 맞춘다. 원격 없이 파일로만 열었으면 아무 일도 안 한다."""
        sync = getattr(self._connection, "sync", None)
        if sync is not None:
            sync()


def split_statements(script: str) -> Iterator[str]:
    """SQL 스크립트를 실행할 수 있는 문장 단위로 나눈다. 주석만 있는 조각은 버린다."""
    import sqlite3

    buffer: list[str] = []
    for line in script.splitlines(keepends=True):
        buffer.append(line)
        chunk = "".join(buffer)
        if sqlite3.complete_statement(chunk):
            if _has_code(chunk):
                yield chunk.strip()
            buffer = []
    rest = "".join(buffer)
    if _has_code(rest):
        yield rest.strip()


def _code_of(chunk: str) -> str:
    """주석(--)과 빈 줄을 뺀 실제 SQL. 문장이 무엇으로 시작하는지 볼 때 쓴다."""
    lines = (line.split("--", 1)[0].strip() for line in chunk.splitlines())
    return " ".join(line for line in lines if line)


def _has_code(chunk: str) -> bool:
    """주석(--)과 빈 줄, 세미콜론만 있는 조각이 아닌가."""
    return bool(_code_of(chunk).strip(";").strip())


def connect(
    path: str, *, url: str | None = None, auth_token: str | None = None
) -> Connection:
    """libSQL 커넥션을 연다.

    - ``url`` 이 있으면 Turso 에 **직접** 붙는다. 모든 질의가 원격으로 간다.
    - 없으면 로컬 파일로 연다(같은 SQL 이 libSQL 에서 도는지 시험할 때).

    **복제본 방식을 쓰지 않는 이유**: libSQL 에는 로컬 파일을 복제본으로 두고 읽기는
    거기서, 쓰기만 원격으로 보내는 방식도 있다. 빠르지만, 스트림릿에서는 여러
    사람의 요청이 저마다 커넥션을 열어 같은 복제본 파일을 동시에 만진다. 그때
    동기화 상태가 어긋나면 **방금 누가 쓴 기록이 다른 사람에게 안 보이는** 일이
    생길 수 있다. 게임은 "같은 방 같은 순위" 가 핵심이라 그 위험을 지지 않는다.
    느리면 그때 재고 바꾼다.
    """
    import libsql

    started = time.perf_counter()
    try:
        if url:
            raw = libsql.connect(url, auth_token=auth_token or "")
            return Connection(raw, remote=True)
        return Connection(libsql.connect(path))
    finally:
        _add("connect", started)
