"""화면이 그 자리에서 채점할 수 있게 내려보내는 것들.

- 진행 중인 판에는 감춘 정답(``sealed``)이 실리고, 끝난 판에는 없다.
- 감춘 정답은 풀면 정확히 그 판의 정답 자모 나열이다(화면 채점이 틀리지 않게).
- 응답 어디에도 정답이 **그대로** 보이지는 않는다(우연히 보이는 것까지만 막는다).
- 사전 목록은 정답을 포함하고, 같은 판이면 다시 보내지 않는다.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ttobak.config import Settings
from ttobak.game.sealed import seal, unseal
from ttobak.hangul import jamo_key
from ttobak.web.app import create_app


def test_감추고_풀면_그대로다():
    for jamos in ("ㅎㅏㄴㅡㄹ", "ㄱㅗㅇㅑㅇㅇㅣ", "ㄷㅗㅅㅓㄱㅗㅏㄴ"):
        sealed = seal(jamos)
        assert unseal(sealed) == jamos
        assert jamos not in json.dumps(sealed, ensure_ascii=False)


def test_열쇠는_매번_새로_뽑는다():
    assert seal("ㅎㅏㄴㅡㄹ") != seal("ㅎㅏㄴㅡㄹ")


def test_혼자_풀기_판에_감춘_정답이_실린다(settings: Settings):
    with TestClient(create_app(settings)) as client:
        client.post("/api/join", json={"nickname": "채점"})
        game = client.get("/api/game").json()
        assert game["status"] == "playing"
        key = unseal(game["sealed"])
        assert len(key) == game["length"]
        # 정답이 응답에 그대로 보이면 안 된다.
        assert game["answer"] is None
        assert key not in json.dumps(game, ensure_ascii=False)

        # 감춘 정답으로 치면 맞힌다 — 화면 채점과 서버 채점이 같은 정답을 본다.
        won = client.post("/api/game/guess", json={"guess": key}).json()
        assert won["status"] == "won"
        assert won["sealed"] is None
        assert jamo_key(won["answer"]) == key


def test_오늘의_문제_판에도_실린다(settings: Settings):
    with TestClient(create_app(settings)) as client:
        client.post("/api/join", json={"nickname": "방장"})
        code = client.post("/api/rooms", json={"name": "방"}).json()["id"]
        daily = client.get(f"/api/rooms/{code}/daily").json()
        key = unseal(daily["sealed"])
        assert len(key) == daily["length"]
        done = client.post(
            f"/api/rooms/{code}/daily/guess", json={"guess": key, "slot": daily["slot"]}
        ).json()
        assert done["status"] == "won" and done["sealed"] is None


def test_사전_목록에_정답이_다_들어_있고_같으면_다시_안_보낸다(settings: Settings):
    with TestClient(create_app(settings)) as client:
        first = client.get("/api/lexicon").json()
        assert first["keys"]
        known = {key for keys in first["keys"].values() for key in keys.split()}
        assert jamo_key("하늘") in known and jamo_key("고양이") in known

        again = client.get("/api/lexicon", params={"v": first["version"]}).json()
        assert again["unchanged"] is True and again["keys"] == {}

        stale = client.get("/api/lexicon", params={"v": "옛것"}).json()
        assert stale["unchanged"] is False and stale["keys"]
