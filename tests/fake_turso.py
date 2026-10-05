"""시험용 가짜 Turso — Hrana HTTP 파이프라인을 로컬 SQLite 파일로 흉내 낸다.

``turso_http`` 어댑터를 진짜 Turso 없이 시험하려고 만든다. 스트림(baton)마다
SQLite 커넥션을 하나 두고, 요청이 오면 그 커넥션에서 문장을 실행해 Hrana 모양으로
답한다. 트랜잭션은 어댑터가 보내는 BEGIN/COMMIT/ROLLBACK 을 그대로 실행한다.

``TTOBAK_TEST_FAKE_TURSO=1`` 로 테스트를 돌리면(conftest) 모든 저장이 이 길로 간다.
"""

from __future__ import annotations

import base64
import itertools
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx


def _decode(value: dict[str, Any]) -> Any:
    kind = value["type"]
    if kind == "null":
        return None
    if kind == "integer":
        return int(value["value"])
    if kind == "float":
        return float(value["value"])
    if kind == "blob":
        return base64.b64decode(value["base64"])
    return value["value"]


def _encode(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode()}
    return {"type": "text", "value": str(value)}


class FakeTurso:
    """한 데이터베이스 파일을 Hrana 처럼 내놓는다."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.streams: dict[str, sqlite3.Connection] = {}
        self._ids = itertools.count(1)
        self.requests = 0

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path, timeout=5.0, isolation_level=None, check_same_thread=False
        )
        return conn

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        assert request.url.path.endswith("/v2/pipeline"), request.url
        body = json.loads(request.content)
        baton = body.get("baton")
        if baton is None:
            conn = self._open()
            baton = f"b{next(self._ids)}"
            self.streams[baton] = conn
        elif baton not in self.streams:
            return httpx.Response(400, text="stream expired")
        else:
            conn = self.streams[baton]

        results = []
        closed = False
        for item in body["requests"]:
            if item["type"] == "close":
                conn.close()
                self.streams.pop(baton, None)
                closed = True
                results.append({"type": "ok", "response": {"type": "close"}})
                continue
            stmt = item["stmt"]
            try:
                cur = conn.execute(
                    stmt["sql"], [_decode(a) for a in stmt.get("args", [])]
                )
                rows = cur.fetchall() if cur.description else []
                results.append(
                    {
                        "type": "ok",
                        "response": {
                            "type": "execute",
                            "result": {
                                "cols": [
                                    {"name": d[0]} for d in (cur.description or [])
                                ],
                                "rows": [[_encode(v) for v in row] for row in rows],
                                "affected_row_count": cur.rowcount
                                if cur.rowcount > 0
                                else 0,
                                "last_insert_rowid": str(cur.lastrowid)
                                if cur.lastrowid
                                else None,
                            },
                        },
                    }
                )
            except sqlite3.Error as error:
                results.append({"type": "error", "error": {"message": str(error)}})
        return httpx.Response(
            200,
            json={
                "baton": None if closed else baton,
                "base_url": None,
                "results": results,
            },
        )
