"""테스트 전역 픽스처.

모든 테스트는 임시 디렉터리에 만든 작은 사전과 빈 데이터베이스를 쓴다. 실제
``data/`` 사전이나 개발용 DB에 손대지 않으므로 순서와 무관하게 돌아간다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ttobak.config import Settings
from ttobak.db import Database
from ttobak.words import Lexicon, load_lexicon

#: 테스트용 미니 사전. 자모 길이별로 몇 개씩만 둔다.
SAMPLE_WORDS: dict[int, list[str]] = {
    # ㅎㅏㄴㅡㄹ / ㄱㅜㄹㅡㅁ / ㅂㅏㄹㅏㅁ / ㅅㅏㄹㅏㅁ
    5: ["하늘", "구름", "바람", "사람"],
    # ㄱㅓㄱㅈㅓㅇ / ㄱㅕㄴㄱㅏㅇ / ㅇㅕㄴㅍㅣㄹ
    6: ["걱정", "건강", "연필"],
    # ㄱㅗㅇㅑㅇㅇㅣ / ㄴㅗㄹㅇㅣㅌㅓ / ㅋㅓㅁㅍㅠㅌㅓ
    7: ["고양이", "놀이터", "컴퓨터"],
    # ㄷㅗㅅㅓㄱㅗㅏㄴ / ㅅㅓㅣㅌㅏㄱㄱㅣ / ㅂㅣㅂㅣㅁㅂㅏㅂ
    8: ["도서관", "세탁기", "비빔밥"],
}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """미니 사전 파일들이 들어 있는 임시 데이터 디렉터리."""
    directory = tmp_path / "data"
    directory.mkdir()
    for length, words in SAMPLE_WORDS.items():
        (directory / f"words-{length}.txt").write_text(
            "\n".join(words) + "\n", encoding="utf-8"
        )
    return directory


@pytest.fixture
def lexicon(data_dir: Path) -> Lexicon:
    return load_lexicon(data_dir, tuple(SAMPLE_WORDS))


@pytest.fixture
def settings(tmp_path: Path, data_dir: Path) -> Settings:
    """임시 경로를 가리키는 설정. 환경 변수의 영향을 받지 않는다."""
    return Settings(
        data_dir=data_dir,
        database_path=tmp_path / "test.sqlite3",
        puzzle_lengths=tuple(SAMPLE_WORDS),
        max_attempts=6,
        daily_salt="test-salt",
        secret_key="test-secret-key",
        # 테스트 중 실제 tailscale CLI를 부르지 않도록 없는 이름을 준다.
        tailscale_cli="tailscale-not-installed-for-tests",
        _env_file=None,
    )


@pytest.fixture
def claiming_client(settings: Settings):
    """**닉네임 잠금을 켠** 서버.

    기본값은 꺼짐이다. 카카오톡 인앱 브라우저가 쿠키를 안 남기는 경우가 있어
    켜 두면 본인까지 막히기 때문이다. 그래서 잠금 동작을 재는 시험은 여기서
    명시적으로 켠다 — 기본값이 무엇인지가 시험 코드에 드러나 있어야 한다.
    """
    from fastapi.testclient import TestClient

    from ttobak.web.app import create_app

    changed = settings.model_copy(update={"require_recovery_code": True})
    with TestClient(create_app(changed)) as test_client:
        yield test_client


@pytest.fixture
def database(settings: Settings) -> Database:
    db = Database(settings.database_path)
    db.initialize()
    return db


def join_player(client, nickname: str, *, code: str | None = None) -> str | None:
    """참가하고 **복구 코드를 돌려준다.**

    닉네임 선점이 생긴 뒤로, 같은 브라우저에서 닉네임을 바꿨다가 되돌아가려면
    복구 코드가 필요하다. 테스트가 그 흐름을 자주 쓰므로 헬퍼로 둔다.

    :param code: 이미 임자가 있는 닉네임으로 돌아갈 때 넣는다.
    :returns: 그 닉네임을 **처음 차지했을 때만** 코드. 아니면 ``None``.
    """
    body = {"nickname": nickname}
    if code:
        body["recovery_code"] = code
    response = client.post("/api/join", json=body)
    assert response.status_code == 200, response.text
    return response.json().get("recovery_code")


def detail_of(response) -> str:
    """오류 본문에서 **사람이 읽을 문구**만 꺼낸다.

    추측과 힌트의 거절은 문구만으로 부족해서 ``{"message", "code"}`` 로 온다.
    화면이 "사전에 없는 단어" 일 때만 신고 단추를 붙여야 하는데, 문장을
    문자열로 비교하게 두면 서버에서 말투를 한 번 다듬는 순간 조용히 깨지기
    때문이다. 나머지 오류는 아직 문자열 하나다.

    시험이 그 차이를 매번 신경 쓸 이유는 없으므로 여기서 흡수한다.
    """
    detail = response.json()["detail"]
    return detail["message"] if isinstance(detail, dict) else detail
