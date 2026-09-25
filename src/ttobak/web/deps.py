"""요청 단위 의존성: 설정, 저장소, 서비스, 그리고 현재 플레이어.

플레이어 식별은 서명된 쿠키 하나로 한다. 쿠키에는 플레이어 식별자만 들어가고
서명은 ``settings.secret_key``로 검증하므로, 브라우저에서 값을 고쳐 남의 기록에
접근할 수 없다.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeSerializer

from ttobak.clock import GAME_TIMEZONE
from ttobak.config import Settings, get_settings
from ttobak.db import Database, Player
from ttobak.game import GameService

__all__ = [
    "GAME_TIMEZONE",
    "CurrentPlayer",
    "ServiceDep",
    "SettingsDep",
    "DatabaseDep",
    "clean_nickname",
    "clear_player_cookie",
    "get_app_settings",
    "is_secure_request",
    "make_player_id",
    "set_player_cookie",
    "today",
]

#: 쿠키 안에서 서명 용도를 구분하는 값. 다른 용도의 토큰과 섞이지 않게 한다.
_COOKIE_SALT = "ttobak-player-cookie"

_NICKNAME_MIN = 1
_NICKNAME_MAX = 20
_ID_ALLOWED = re.compile(r"[^0-9a-z가-힣]+")
#: 표시용 닉네임에 허용하는 문자. 제어 문자와 방향 제어 문자를 배제한다.
_NICKNAME_ALLOWED = re.compile(r"[0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ _.\-]+")


def today() -> date:
    """게임 기준 시간대에서의 오늘 날짜."""
    return datetime.now(GAME_TIMEZONE).date()


def make_player_id(nickname: str) -> str:
    """닉네임을 저장소 키로 정규화한다.

    대소문자와 공백, 기호 차이를 무시해 ``민수``와 ``민수!``가 같은 사람이 되게
    한다. 한글은 결합 문자로 갈라져 있을 수 있으므로 NFC로 먼저 모은다.

    :raises ValueError: 정규화 결과가 비었을 때.
    """
    normalized = unicodedata.normalize("NFC", nickname).strip().lower()
    player_id = _ID_ALLOWED.sub("", normalized)
    if not player_id:
        raise ValueError("닉네임에 한글이나 영문, 숫자가 하나 이상 있어야 합니다.")
    return player_id[:_NICKNAME_MAX]


def clean_nickname(nickname: str) -> str:
    """화면에 보여 줄 닉네임을 다듬는다.

    허용 문자를 한글, 영문, 숫자, 공백, 그리고 흔한 기호 몇 개로 좁힌다.
    화면에 넣을 때 ``textContent``만 쓰므로 스크립트 주입은 이미 막혀 있지만,
    보이지 않는 제어 문자나 글자 방향을 뒤집는 문자로 순위표를 어지럽히는 장난을
    원천에서 차단한다.

    :raises ValueError: 길이가 범위를 벗어나거나 허용되지 않은 문자가 있을 때.
    """
    cleaned = " ".join(unicodedata.normalize("NFC", nickname).split())
    if not _NICKNAME_MIN <= len(cleaned) <= _NICKNAME_MAX:
        raise ValueError(f"닉네임은 {_NICKNAME_MIN}~{_NICKNAME_MAX}자여야 합니다.")
    if not _NICKNAME_ALLOWED.fullmatch(cleaned):
        raise ValueError("닉네임에는 한글, 영문, 숫자, 공백만 쓸 수 있습니다.")
    return cleaned


def _serializer(settings: Settings) -> URLSafeSerializer:
    return URLSafeSerializer(settings.secret_key, salt=_COOKIE_SALT)


def is_secure_request(request: Request) -> bool:
    """이 요청이 HTTPS로 들어왔는지 판정한다.

    Tailscale Funnel은 바깥에서 HTTPS로 받아 안쪽으로는 평문 HTTP로 넘긴다.
    그래서 ``request.url.scheme``만 보면 항상 http로 보인다. 프록시가 원래
    스킴을 알려 주는 ``X-Forwarded-Proto``를 먼저 본다.
    """
    forwarded = request.headers.get("x-forwarded-proto")
    if forwarded:
        return forwarded.split(",")[0].strip().lower() == "https"
    return request.url.scheme == "https"


def set_player_cookie(
    response: Response, player_id: str, settings: Settings, *, secure: bool
) -> None:
    """플레이어 쿠키를 서명해 응답에 심는다.

    ``secure``는 설정이 아니라 **요청 스킴**에서 온다. 설정으로 고정하면
    HTTPS 주소로 들어온 사람과 로컬 HTTP 주소로 들어온 사람 중 한쪽이 반드시
    로그인 상태를 잃는다. Secure 쿠키는 평문 HTTP로 전송되지 않기 때문이다.
    """
    response.set_cookie(
        key=settings.session_cookie,
        value=_serializer(settings).dumps(player_id),
        max_age=settings.session_max_age_days * 24 * 60 * 60,
        # 자바스크립트가 쿠키를 읽지 못하게 한다. 스크립트 주입이 생겨도
        # 세션을 훔쳐 갈 수 없다.
        httponly=True,
        # 다른 사이트에서 넘어온 요청에는 쿠키를 실어 보내지 않는다. CSRF 방어.
        samesite="lax",
        # HTTPS로 들어온 요청에만 붙인다. 붙이면 이후 평문 전송이 차단된다.
        secure=secure,
    )


def clear_player_cookie(response: Response, settings: Settings) -> None:
    """플레이어 쿠키를 지운다. 다른 사람으로 바꿔 플레이할 때 쓴다."""
    response.delete_cookie(settings.session_cookie)


def unsign_player_cookie(raw: str, settings: Settings) -> str:
    """서명된 쿠키 값에서 플레이어 식별자를 꺼낸다.

    :raises itsdangerous.BadSignature: 서명이 맞지 않으면.

    요청 객체가 아니라 **문자열을 받는다.** 레이트리밋 미들웨어가 이걸 쓰기
    때문이다 — 거기서 서명을 확인하지 않으면 쿠키는 그냥 공격자가 정하는
    문자열이고, 그걸 한도의 키로 삼는 것은 "제한하지 말아 달라"는 요청을
    그대로 들어주는 것과 같다.
    """
    return _serializer(settings).loads(raw)


def current_player_id(request: Request, settings: Settings) -> str | None:
    """쿠키에 든 플레이어 id. 서명이 깨졌으면 ``None``.

    참가 라우트가 "이미 나인 계정인가" 를 물을 때 쓴다. 그 확인이 없으면
    자기 닉네임으로 다시 들어올 때도 복구 코드를 요구하게 된다.
    """
    return _read_player_cookie(request, settings)


def _read_player_cookie(request: Request, settings: Settings) -> str | None:
    """쿠키에서 플레이어 식별자를 꺼낸다. 서명이 깨졌으면 ``None``."""
    raw = request.cookies.get(settings.session_cookie)
    if not raw:
        return None
    try:
        return unsign_player_cookie(raw, settings)
    except BadSignature:
        return None


# --- FastAPI 의존성 ---


def get_app_settings(request: Request) -> Settings:
    """이 앱이 실제로 기동된 설정.

    전역 ``get_settings()``를 그대로 쓰면 안 된다. 그것은 환경 변수와 ``.env``를
    읽어 캐싱한 단일 인스턴스라, ``create_app(settings)``로 다른 설정을 주입한
    앱과 어긋난다. 실제로 이 함수가 없을 때, 테스트 앱이 자기 비밀키로 쿠키를
    서명해 놓고 전역 설정의 비밀키로 검증하는 버그가 있었다.

    앱이 자기 설정을 ``state``에 넣어 두므로 여기서는 그것을 꺼내 쓰고,
    ``state``가 아직 비어 있을 때만 전역 설정으로 물러선다.
    """
    settings = getattr(request.app.state, "settings", None)
    return settings if settings is not None else get_settings()


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_service(request: Request) -> GameService:
    return request.app.state.service


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DatabaseDep = Annotated[Database, Depends(get_database)]
ServiceDep = Annotated[GameService, Depends(get_service)]


def get_optional_player(
    request: Request, settings: SettingsDep, database: DatabaseDep
) -> Player | None:
    """로그인한 플레이어. 쿠키가 없거나 기록이 지워졌으면 ``None``."""
    player_id = _read_player_cookie(request, settings)
    if player_id is None:
        return None
    return database.get_player(player_id)


def get_current_player(
    player: Annotated[Player | None, Depends(get_optional_player)],
) -> Player:
    """로그인한 플레이어. 없으면 401을 던진다."""
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="닉네임을 먼저 정해 주세요.",
        )
    return player


CurrentPlayer = Annotated[Player, Depends(get_current_player)]
OptionalPlayer = Annotated[Player | None, Depends(get_optional_player)]
