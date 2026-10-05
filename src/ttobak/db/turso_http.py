"""Turso 를 HTTP(Hrana 파이프라인)로 부르는 커넥션. ``sqlite3`` 처럼 쓴다.

왜 libsql 패키지를 안 쓰나 — 서버 전체가 멈췄다
-----------------------------------------------

2026-10-05 배포된 앱이 아예 안 떴다(스트림릿 "Huh. This isn't supposed to
happen"). 재 보니 ``libsql`` 파이썬 패키지는 **원격 질의를 기다리는 동안 GIL 을
쥐고 있었다.** 질의 한 번(0.3초) 동안 같은 프로세스의 다른 스레드가 전부 멈췄다
(옆에서 5ms 마다 깨는 스레드의 간격이 345ms 까지 벌어짐).

스트림릿은 한 프로세스에서 웹 서버·모든 사람의 화면·상태 검사를 같이 돌린다.
그래서 DB 를 한 번 부를 때마다 **모두가** 멈췄고, 친구 여럿이 동시에 하면 멈춤이
쌓여 클라우드의 상태 검사가 실패 → 앱이 죽은 것으로 처리됐다.

``httpx`` 는 소켓을 기다리는 동안 GIL 을 놓는다. 그래서 Turso 의 HTTP API 를
직접 부른다. 왕복 수는 예전과 같다(질의 한 번 = 요청 한 번).

트랜잭션
--------

sqlite3 의 기본 동작을 흉내 낸다: **쓰기 문장(INSERT/UPDATE/DELETE/REPLACE)이
처음 나올 때 BEGIN** 을 붙이고, ``commit()`` 에서 COMMIT, ``rollback()`` 에서
ROLLBACK 한다. 트랜잭션 동안은 서버 쪽 스트림(baton)을 이어 써야 같은 트랜잭션이
된다. 읽기만 하는 문장은 스트림 없이 한 번에 열고·실행하고·닫는다 — 끝에 따로
닫으러 갈 필요가 없어 왕복이 늘지 않는다.

외래 키(ON DELETE CASCADE)는 쓰기 트랜잭션을 시작할 때 같은 요청에
``PRAGMA foreign_keys = ON`` 을 실어 켠다. 왕복이 더 들지 않는다.
"""

from __future__ import annotations

import base64
import sqlite3
import time
from collections.abc import Iterator, Sequence
from typing import Any

import httpx

from ttobak.db import libsql_adapter
from ttobak.db.libsql_adapter import Row, _code_of, split_statements

__all__ = ["Connection", "TursoError", "connect"]

#: 처음 나오면 트랜잭션을 여는 문장들(sqlite3 의 옛 기본 동작과 같다).
_WRITES = ("INSERT", "UPDATE", "DELETE", "REPLACE")

TIMEOUT_SECONDS = 20

#: HTTP 클라이언트를 만드는 곳. 시험에서 가짜 Turso(tests/fake_turso.py)로 바꿔 끼운다.
_client_factory = httpx.Client


class TursoError(sqlite3.DatabaseError):
    """Turso 가 문장을 거절했다. sqlite3 오류처럼 잡을 수 있게 그 자식으로 둔다."""


def _encode(value: Any) -> dict[str, Any]:
    """파이썬 값 → Hrana 값."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {
            "type": "blob",
            "base64": base64.b64encode(bytes(value)).decode("ascii"),
        }
    return {"type": "text", "value": str(value)}


def _decode(cell: dict[str, Any]) -> Any:
    """Hrana 값 → 파이썬 값."""
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    if kind == "blob":
        return base64.b64decode(cell.get("base64", ""))
    return cell.get("value")


class Cursor:
    """한 문장의 결과. sqlite3 커서에서 저장 코드가 쓰는 것만 있다."""

    def __init__(self, result: dict[str, Any] | None) -> None:
        result = result or {}
        cols = result.get("cols") or []
        self._names = {col.get("name") or f"col{i}": i for i, col in enumerate(cols)}
        self._rows = [
            Row(self._names, [_decode(c) for c in row])
            for row in result.get("rows") or []
        ]
        self._next = 0
        self.rowcount = int(result.get("affected_row_count") or 0)
        rowid = result.get("last_insert_rowid")
        self.lastrowid = int(rowid) if rowid is not None else None
        self.description = tuple(
            (name, None, None, None, None, None, None) for name in self._names
        )

    def fetchone(self) -> Row | None:
        if self._next >= len(self._rows):
            return None
        row = self._rows[self._next]
        self._next += 1
        return row

    def fetchall(self) -> list[Row]:
        rows = self._rows[self._next :]
        self._next = len(self._rows)
        return rows

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())


class Connection:
    """Turso 데이터베이스 하나에 대한 커넥션. 한 번에 한 스레드만 쓴다(풀이 보장)."""

    def __init__(self, url: str, auth_token: str) -> None:
        base = url.replace("libsql://", "https://", 1).rstrip("/")
        self._client = _client_factory(
            base_url=base,
            headers={"Authorization": f"Bearer {auth_token}"} if auth_token else {},
            timeout=TIMEOUT_SECONDS,
        )
        self._baton: str | None = None
        self._base_url: str | None = None  # 서버가 "이 스트림은 저기로" 라고 알려 주면
        self._in_tx = False

    # --- 서버와 주고받기 ---

    def _pipeline(
        self, requests: list[dict[str, Any]], *, keep: bool
    ) -> list[dict[str, Any]]:
        """요청 묶음을 한 번에 보낸다. ``keep`` 이면 스트림(baton)을 이어 둔다."""
        body = {
            "baton": self._baton,
            "requests": requests if keep else [*requests, {"type": "close"}],
        }
        url = (
            f"{self._base_url}/v2/pipeline"
            if self._base_url and self._baton
            else "/v2/pipeline"
        )
        started = time.perf_counter()
        try:
            response = self._client.post(url, json=body)
        finally:
            libsql_adapter._add("query", started)
        if response.status_code >= 400:
            # 스트림이 끊겼으면(오래 놀았거나 서버가 옮겨짐) 다음 요청은 새로 연다.
            self._baton, self._base_url, self._in_tx = None, None, False
            raise TursoError(
                f"Turso HTTP {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        self._baton = data.get("baton") if keep else None
        self._base_url = (data.get("base_url") or None) if keep else None
        results = data.get("results") or []
        for result in results:
            if result.get("type") == "error":
                message = (result.get("error") or {}).get("message", "알 수 없는 오류")
                if not keep:
                    self._in_tx = False
                raise TursoError(message)
        return results

    @staticmethod
    def _stmt(sql: str, parameters: Sequence[Any] = ()) -> dict[str, Any]:
        return {
            "type": "execute",
            "stmt": {
                "sql": sql,
                "args": [_encode(v) for v in parameters],
                "want_rows": True,
            },
        }

    # --- sqlite3 처럼 ---

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> Cursor:
        head = _code_of(sql).lstrip("(").split(" ", 1)[0].upper()
        requests: list[dict[str, Any]] = []
        if head in _WRITES and not self._in_tx:
            requests += [self._stmt("PRAGMA foreign_keys = ON"), self._stmt("BEGIN")]
            self._in_tx = True
        requests.append(self._stmt(sql, tuple(parameters)))
        # 트랜잭션 중이면 스트림을 이어 쓴다. 아니면 이 한 문장으로 열고 닫는다.
        results = self._pipeline(requests, keep=self._in_tx)
        last = results[len(requests) - 1]
        return Cursor((last.get("response") or {}).get("result"))

    def executescript(self, script: str) -> None:
        """여러 문장을 한 문장씩 보낸다. 저널 모드는 서버가 정한다."""
        for statement in split_statements(script):
            if _code_of(statement).upper().startswith("PRAGMA JOURNAL_MODE"):
                continue
            self.execute(statement)

    def commit(self) -> None:
        if self._in_tx:
            self._pipeline([self._stmt("COMMIT")], keep=False)
            self._in_tx = False

    def rollback(self) -> None:
        if self._in_tx:
            try:
                self._pipeline([self._stmt("ROLLBACK")], keep=False)
            finally:
                self._in_tx = False
                self._baton = self._base_url = None

    def close(self) -> None:
        self._baton = self._base_url = None
        self._in_tx = False
        self._client.close()


def connect(url: str, auth_token: str | None = None) -> Connection:
    started = time.perf_counter()
    try:
        return Connection(url, auth_token or "")
    finally:
        libsql_adapter._add("connect", started)
