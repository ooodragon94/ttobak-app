"""JSON API 라우터.

라우터는 얇게 유지한다. 검증과 게임 규칙은 ``GameService``가, 저장은
``Database``가 맡고, 여기서는 HTTP 관심사만 다룬다.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ttobak.clock import day_bounds_utc
from ttobak.config import Settings
from ttobak.db import Player
from ttobak.db.repository import ConcurrentGuessError
from ttobak.game import (
    SUPPORT_PROVIDERS,
    THEMES,
    InvalidGuessError,
    assign_titles,
    rank_medal,
    theme_choices,
    tier_badge,
)
from ttobak.game.claim import (
    hash_recovery_code,
    new_recovery_code,
    verify_recovery_code,
)
from ttobak.game.hard import DIFFICULTIES, get_difficulty
from ttobak.game.service import GameService
from ttobak.game.support import SupportProvider
from ttobak.hangul import BASIC_JAMOS
from ttobak.web.deps import (
    CurrentPlayer,
    DatabaseDep,
    OptionalPlayer,
    ServiceDep,
    SettingsDep,
    clean_nickname,
    clear_player_cookie,
    current_player_id,
    is_secure_request,
    make_player_id,
    set_player_cookie,
    today,
)
from ttobak.web.schemas import (
    DifficultyChoice,
    GameStateResponse,
    GuessRequest,
    JoinRequest,
    LeaderboardResponse,
    LeaderboardRow,
    MeResponse,
    RecoveryResponse,
    SettingsRequest,
    SettingsResponse,
    StatsResponse,
    SupportProviderRow,
    SupportResponse,
    ThanksResponse,
    ThemeChoice,
    WordReportRequest,
)
from ttobak.web.tailscale import whois

#: 저장을 받아 줄 난이도 열쇠들. 모르는 값은 400 으로 막는다 — 아무 문자열이나
#: 넣게 두면 읽을 때 조용히 기본 난이도로 떨어져서, 설정은 저장됐다는데
#: 게임은 안 바뀌는 상태가 된다.
_DIFFICULTY_KEYS = frozenset(choice.key for choice in DIFFICULTIES)

router = APIRouter(prefix="/api", tags=["game"])

logger = logging.getLogger(__name__)


@router.get("/me", response_model=MeResponse)
def read_me(
    request: Request,
    settings: SettingsDep,
    database: DatabaseDep,
    player: OptionalPlayer,
) -> MeResponse:
    """현재 접속자 정보. 아직 참가 전이면 닉네임 후보를 함께 준다.

    **여기서도 닉네임을 선점한다.** 선점을 참가(``/api/join``)에서만 하면
    이미 쿠키를 갖고 다니는 사람은 영영 선점이 안 된다 — 그들은 join 을
    부르지 않기 때문이다. 그 사이에 누가 그 닉네임을 먼저 차지하면 원래
    주인이 기기를 바꿨을 때 못 돌아온다.

    쿠키가 있다는 것은 이미 서명을 통과했다는 뜻이므로, 이 사람이 그
    계정의 주인인 것은 확실하다. 그래서 조용히 임자로 못 박고 복구 코드를
    한 번 보여 준다.
    """
    if player is not None:
        code = None
        _, stored = database.recovery_hash_of(player.id)
        if stored is None:
            code = new_recovery_code()
            database.set_recovery_hash(player.id, hash_recovery_code(code))
        return MeResponse(
            player_id=player.id,
            display_name=player.display_name,
            recovery_code=code,
        )

    suggestion = None
    if request.client is not None:
        identity = whois(request.client.host, cli=settings.tailscale_cli)
        if identity is not None:
            suggestion = identity.suggested_nickname
    return MeResponse(suggested_nickname=suggestion)


@router.post("/join", response_model=MeResponse)
def join(
    payload: JoinRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    database: DatabaseDep,
) -> MeResponse:
    """닉네임을 정하고 플레이어 쿠키를 받는다.

    같은 닉네임으로 다시 들어오면 기존 기록을 이어서 플레이한다.
    """
    try:
        display_name = clean_nickname(payload.nickname)
        player_id = make_player_id(display_name)
    except ValueError as error:
        # starlette 버전마다 422 상수 이름이 달라 숫자를 그대로 쓴다.
        raise HTTPException(status_code=422, detail=str(error)) from error

    # --- 닉네임 선점 ---
    #
    # 이 게임은 비밀번호가 없다. 그러면 **닉네임을 아는 사람이 곧 그 사람**
    # 이 되는데, 지인끼리 쓰는 물건에서는 그게 제일 큰 구멍이다(서로 이름을
    # 안다). 남의 진행 중인 판을 보고 기회를 대신 소모시킬 수 있었다.
    #
    # 그래서 "먼저 쓴 사람이 임자" 로 바꾼다. 이미 있는 닉네임인데 그 계정의
    # 복구 코드가 없으면 거절한다.
    exists, stored_hash = database.recovery_hash_of(player_id)
    already_me = current_player_id(request, settings) == player_id
    recovery_code: str | None = None

    # 임자가 있는 닉네임이면 코드가 맞아야 들어온다.
    claimed_by_other = exists and stored_hash and not already_me
    code_ok = bool(payload.recovery_code) and verify_recovery_code(
        payload.recovery_code or "", stored_hash or ""
    )
    # 설정이 꺼져 있으면 막지 않는다. 자세한 이유는 Settings 쪽에 적었다 —
    # 요약하면 **쿠키를 못 들고 있는 본인까지 막히기 때문**이다.
    if settings.require_recovery_code and claimed_by_other and not code_ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "이미 쓰고 있는 닉네임이에요. "
                "본인이라면 복구 코드를 넣고, 아니면 다른 이름을 써 주세요."
            ),
        )

    identity = None
    if request.client is not None:
        identity = whois(request.client.host, cli=settings.tailscale_cli)

    player = database.upsert_player(
        player_id,
        display_name,
        tailscale_node=identity.node if identity else None,
        tailscale_user=identity.user if identity else None,
    )

    # 방 주인과 어떤 사이인지. **선택 입력**이라 안 적으면 그냥 넘어간다.
    # 적었을 때만 저장한다 — 빈 값으로 덮어쓰면, 기기를 바꿔 다시 들어온
    # 사람의 기존 소개가 지워진다.
    if payload.relation.strip():
        player = database.update_preferences(
            player.id, relation=payload.relation.strip()
        ) or player

    if settings.require_recovery_code and stored_hash is None:
        # 아직 임자가 없는 닉네임(새 계정이거나 이 기능 이전의 옛 계정)이다.
        # 지금 들어온 사람을 임자로 못 박고 코드를 **한 번만** 보여 준다.
        #
        # 기능이 꺼져 있을 때는 발급하지 않는다. 아무 힘도 없는 코드를 적어
        # 두라고 하면, 그걸 믿은 사람이 나중에 배신당한다.
        recovery_code = new_recovery_code()
        database.set_recovery_hash(player_id, hash_recovery_code(recovery_code))

    set_player_cookie(response, player.id, settings, secure=is_secure_request(request))
    return MeResponse(
        player_id=player.id,
        display_name=player.display_name,
        recovery_code=recovery_code,
    )


def _guess_error(error: InvalidGuessError) -> dict[str, str]:
    """거절 사유를 화면이 쓸 수 있는 모양으로.

    ``message`` 는 그대로 보여 줄 문구, ``code`` 는 화면이 분기할 이름이다.
    문장을 문자열로 비교하게 두면 말투를 다듬는 순간 화면이 조용히 깨진다.
    """
    return error.as_detail()


@router.post("/words/report", status_code=status.HTTP_204_NO_CONTENT)
def report_word(
    payload: WordReportRequest,
    player: CurrentPlayer,
    database: DatabaseDep,
    service: ServiceDep,
) -> None:
    """거절당한 말을 "이건 진짜 단어" 라고 신고한다.

    받아만 두고 **아무것도 바로 반영하지 않는다.** 신고를 그대로 믿고 사전에
    넣으면, 아무 자모나 눌러서 사전을 오염시킬 수 있다. 판정은 나중에
    따로 한다(``tools/review_words.py``).

    이 기능이 필요한 이유: 사전이 표준국어대사전 계열이라 생활 합성어가
    빠져 있는데, 지금까지 그걸 아는 유일한 경로가 **친구가 카톡으로 말해
    주는 것**이었다. 말 안 하고 그냥 접는 사람이 훨씬 많다.
    """
    guess = "".join(payload.guess.split())
    unknown = {ch for ch in guess if ch not in BASIC_JAMOS}
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="자판에 없는 글자가 있습니다: " + " ".join(sorted(unknown)),
        )
    if len(guess) not in service.lexicon.lengths:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이 서버가 내지 않는 길이예요.",
        )
    # 이미 받아 주는 말이면 신고할 것이 없다. 사전이 갱신된 뒤 늦게 눌린
    # 경우라 오류로 다룰 일은 아니다.
    if service.lexicon.accepts(guess, len(guess)):
        return
    database.report_word(guess, len(guess), player.id)


@router.post("/recovery", response_model=RecoveryResponse)
def reissue_recovery_code(
    player: CurrentPlayer, database: DatabaseDep, settings: SettingsDep
) -> RecoveryResponse:
    """복구 코드를 새로 만든다. **쿠키가 있는 본인만.**

    기존 코드를 다시 보여 주지 않는 이유는 서버가 해시만 갖고 있어서다.
    그래서 이 기능은 "보여 주기" 가 아니라 "새로 만들기" 이고, 부르는 순간
    전에 적어 둔 코드는 못 쓰게 된다.

    이게 필요한 이유: 처음 만들어진 코드를 화면이 안 보여 주던 시기가 있었다.
    그때 닉네임을 차지한 사람들은 코드를 가진 적이 없어서, 기기를 바꾸면
    자기 닉네임을 되찾을 방법이 없다. 지금 쿠키가 살아 있는 동안 여기서
    새로 받아 두면 그 상태를 벗어난다.
    """
    if not settings.require_recovery_code:
        # 꺼져 있으면 코드가 아무 일도 안 한다. 그런 값을 내주면 사용자는
        # 적어 두고 안심하는데 실제로는 지켜 주는 것이 없다.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="지금은 닉네임 잠금이 꺼져 있어서 복구 코드가 필요 없어요.",
        )

    code = new_recovery_code()
    # 덮어쓰는 쪽을 쓴다. set_recovery_hash 는 이미 임자가 있으면 아무것도
    # 안 하므로, 여기서 그걸 쓰면 **동작하지 않는 코드를 내주게 된다** —
    # 사용자는 적어 두고 안심하는데 정작 그 코드로는 못 들어온다.
    database.replace_recovery_hash(player.id, hash_recovery_code(code))
    return RecoveryResponse(recovery_code=code)


@router.post("/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave(response: Response, settings: SettingsDep) -> None:
    """쿠키를 지워 다른 사람으로 바꿔 앉을 수 있게 한다. 기록은 남는다."""
    clear_player_cookie(response, settings)


def _settings_response(
    player: Player, settings: Settings, service: GameService | None = None
) -> SettingsResponse:
    """설정 응답을 한곳에서 만든다. 읽기와 쓰기가 같은 모양을 내려보내야 한다."""
    return SettingsResponse(
        hints_enabled=player.hints_enabled,
        relation=player.relation,
        hints_offered=settings.hints_offered,
        share_theme=player.share_theme,
        themes=[ThemeChoice(**choice) for choice in theme_choices()],
        # 고른 것이 없으면 "전부" 로 보여 준다. 화면에서 아무것도 체크가
        # 안 된 상태로 두면 사용자가 고장 난 줄 안다.
        puzzle_lengths=list(player.puzzle_lengths or settings.puzzle_lengths),
        available_lengths=list(settings.puzzle_lengths),
        max_attempts=player.max_attempts or settings.max_attempts,
        attempt_choices=list(GameService.ATTEMPT_CHOICES),
        # 지금 난이도를 바꾸면 풀던 판을 잃는지. 화면은 이 값이 참일 때만
        # 확인을 받는다 — 잃을 것이 없는데 매번 물으면 잔소리가 된다.
        costly_difficulties=(
            list(service.costly_difficulties(player.id))
            if service is not None
            else []
        ),
        # 모르는 열쇠가 저장돼 있어도 화면이 빈칸이 되지 않게 한 번 거른다.
        difficulty=get_difficulty(player.difficulty).key,
        difficulty_choices=[
            DifficultyChoice(
                key=choice.key,
                label=choice.label,
                emoji=choice.emoji,
                note=choice.note,
                keep_correct=choice.keep_correct,
                require_present=choice.require_present,
            )
            for choice in DIFFICULTIES
        ],
    )


@router.get("/settings", response_model=SettingsResponse)
def read_settings(
    player: CurrentPlayer, settings: SettingsDep, service: ServiceDep
) -> SettingsResponse:
    """내 개인 설정."""
    return _settings_response(player, settings, service)


@router.put("/settings", response_model=SettingsResponse)
def update_settings(
    payload: SettingsRequest,
    player: CurrentPlayer,
    settings: SettingsDep,
    database: DatabaseDep,
    service: ServiceDep,
) -> SettingsResponse:
    """개인 설정을 바꾼다. 준 항목만 반영한다."""
    if payload.hints_enabled and not settings.hints_offered:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이 서버는 힌트 기능을 제공하지 않습니다.",
        )
    if payload.share_theme is not None and payload.share_theme not in THEMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"없는 테마입니다: {payload.share_theme}",
        )

    if payload.difficulty is not None and payload.difficulty not in _DIFFICULTY_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"없는 난이도입니다: {payload.difficulty}",
        )

    if payload.max_attempts is not None and (
        payload.max_attempts not in GameService.ATTEMPT_CHOICES
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"고를 수 있는 값이 아닙니다: {payload.max_attempts}",
        )

    if payload.puzzle_lengths is not None:
        unknown = set(payload.puzzle_lengths) - set(settings.puzzle_lengths)
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"이 서버가 내지 않는 길이입니다: {sorted(unknown)}",
            )

    updated = database.update_preferences(
        player.id,
        hints_enabled=payload.hints_enabled,
        share_theme=payload.share_theme,
        puzzle_lengths=(
            tuple(payload.puzzle_lengths)
            if payload.puzzle_lengths is not None
            else None
        ),
        max_attempts=payload.max_attempts,
        difficulty=payload.difficulty,
        relation=(payload.relation.strip() if payload.relation is not None else None),
    )
    if payload.difficulty is not None:
        # 판에는 시작할 때의 난이도가 박혀 있다. 정리해 주지 않으면 노말로
        # 되돌려도 풀던 판은 계속 불닭이고, 불닭은 조건을 만족하는 단어가
        # 없으면 **지지도 못한 채 갇히는** 상태가 된다.
        service.apply_difficulty(player.id, today())
    return _settings_response(updated, settings, service)


@router.get("/support", response_model=SupportResponse)
def read_support(
    settings: SettingsDep, player: OptionalPlayer, database: DatabaseDep
) -> SupportResponse:
    """후원 안내. 링크를 안 정했으면 빈 목록을 준다.

    단계 목록까지 서버가 주는 이유: 금액과 문구를 화면에 박아 두면 고치려고
    할 때마다 프런트를 건드려야 한다. 값을 한곳(``game/support.py``)에 두면
    나중에 "메가커피가 2,500원 됐다" 같은 것을 한 줄로 고칠 수 있다.

    **끈 방의 회원에게는 빈 응답을 준다.** 화면에서만 버튼을 감추지 않는
    이유는, 감추는 것과 없는 것이 다르기 때문이다. 빈 응답이면 버튼이 안
    뜨는 것은 물론이고 창 자체가 열리지 않는다 — 주소를 직접 치거나
    개발자 도구로 함수를 불러도 보여 줄 것이 없다.
    """
    if player is not None and not database.support_open_for(player.id):
        return SupportResponse()

    # 설정된 수단만 모은다. 하나도 없으면 기능 자체가 꺼진다.
    configured = [
        (provider, getattr(settings, f"support_{provider.key}", ""))
        for provider in SUPPORT_PROVIDERS
    ]
    configured = [(provider, url) for provider, url in configured if url]

    # 기타 주소(토스도 카카오도 아닌 것)는 "other" 라는 수단으로 취급한다.
    if settings.support_url:
        other = SupportProvider("other", "후원하기", "💛")
        configured.append((other, settings.support_url))

    if not configured:
        return SupportResponse()

    return SupportResponse(
        url=configured[0][1],
        providers=[
            SupportProviderRow(key=p.key, label=p.label, emoji=p.emoji, url=url)
            for p, url in configured
        ],
    )


class ThanksRequest(BaseModel):
    amount: int = Field(ge=0, le=1_000_000, description="보낸 금액")


@router.post("/support/thanks", response_model=ThanksResponse)
def say_thanks(
    payload: ThanksRequest, player: CurrentPlayer, database: DatabaseDep
) -> ThanksResponse:
    """"보냈어요" 를 눌렀을 때. 감사 화면에 쓸 값을 돌려준다.

    **확인하지 않는다.** 카카오페이는 우리 서버에 아무것도 알려 주지 않으므로
    확인할 방법이 자체가 없다. 거짓으로 얻는 것이 배지 하나뿐이라 그렇게까지
    막을 값어치가 없다.
    """
    count = database.add_supporter(player.id, payload.amount)
    return ThanksResponse(count=count)


@router.get("/game", response_model=GameStateResponse)
def read_game(player: CurrentPlayer, service: ServiceDep) -> GameStateResponse:
    """지금 풀고 있는 판. 처음이면 첫 문제가 열린다."""
    return GameStateResponse(**asdict(service.load(player.id, today())))


@router.post("/game/next", response_model=GameStateResponse)
def next_round(player: CurrentPlayer, service: ServiceDep) -> GameStateResponse:
    """다음 문제로 넘어간다. 진행 중인 판이 있으면 그대로 둔다."""
    return GameStateResponse(**asdict(service.advance(player.id, today())))


@router.post("/game/resign", response_model=GameStateResponse)
def resign_round(player: CurrentPlayer, service: ServiceDep) -> GameStateResponse:
    """지금 판을 포기하고 다음 문제를 연다. **패배로 기록된다.**"""
    return GameStateResponse(**asdict(service.resign(player.id, today())))


@router.post("/game/hint", response_model=GameStateResponse)
def reveal_hint(player: CurrentPlayer, service: ServiceDep) -> GameStateResponse:
    """앞에서부터 자모를 하나 더 공개한다."""
    try:
        view = service.reveal_hint(player.id, today())
    except InvalidGuessError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=_guess_error(error)
        ) from error
    return GameStateResponse(**asdict(view))


@router.post("/game/guess", response_model=GameStateResponse)
def submit_guess(
    payload: GuessRequest, player: CurrentPlayer, service: ServiceDep
) -> GameStateResponse:
    """추측을 제출하고 채점된 게임판을 돌려받는다."""
    try:
        view = service.submit(player.id, payload.guess, today())
    except InvalidGuessError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=_guess_error(error)
        ) from error
    except ConcurrentGuessError as error:
        # 같은 판에 다른 추측이 먼저 반영됐다. 여러 개를 동시에 보내 한 번의
        # 기회로 여러 단어를 채점받는 것을 막는다.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    return GameStateResponse(**asdict(view))


@router.get("/leaderboard", response_model=LeaderboardResponse)
def read_leaderboard(
    database: DatabaseDep,
    player: CurrentPlayer,
    played_on: date | None = None,
) -> LeaderboardResponse:
    """그날 참가자들의 순위. **참가한 사람만 볼 수 있다.**

    전에는 로그인 없이도 볼 수 있었는데, 그러면 인터넷의 아무나 이 목록을
    긁어 **닉네임 전부를 얻는다.** 이 게임은 닉네임만 입력하면 그 사람이
    되므로, 닉네임 목록은 곧 "아무나 될 수 있는 사람들의 명단"이다.
    공개할 이유가 없다.

    등수만 있으면 1등 말고는 볼 이유가 없다. 그래서 메달과 칭호를 붙이고,
    보는 사람의 줄을 따로 표시해 자기 자리를 바로 찾게 한다.
    """
    target = played_on or today()
    # 그날 **끝낸** 판으로 센다. 판을 연 날로 세면, 전날 열어 둔 판을 오늘 맞혀도
    # 전날 순위에 들어가서 방금 맞힌 사람이 오늘 순위에 안 보인다. 실제로 끝난
    # 판 171개 중 11개가 그렇게 다른 날에 세어져 있었다.
    raw = database.leaderboard(*day_bounds_utc(target))
    titles = assign_titles(raw)
    my_name = player.display_name if player else None
    # 한 번에 읽어 메모리에서 맞춘다. 줄마다 물으면 30명이면 질의가 30번이다.
    supporters = database.supporter_names()

    entries = [
        LeaderboardRow(
            rank=index,
            display_name=entry.display_name,
            relation=entry.relation,
            solved=entry.solved,
            played=entry.played,
            average_attempts=entry.average_attempts,
            best_attempts=entry.best_attempts,
            medal=rank_medal(index),
            supporter=entry.display_name in supporters,
            title=(
                titles[entry.display_name].label if entry.display_name in titles else ""
            ),
            title_emoji=(
                titles[entry.display_name].emoji if entry.display_name in titles else ""
            ),
            is_me=entry.display_name == my_name,
        )
        for index, entry in enumerate(raw, start=1)
    ]
    return LeaderboardResponse(played_on=target, entries=entries)


@router.get("/stats", response_model=StatsResponse)
def read_stats(player: CurrentPlayer, database: DatabaseDep) -> StatsResponse:
    """내 누적 전적."""
    stats = database.player_stats(player.id)
    return StatsResponse(
        played=stats.played,
        wins=stats.wins,
        win_rate=round(stats.win_rate, 4),
        current_streak=stats.current_streak,
        max_streak=stats.max_streak,
        guess_distribution=stats.guess_distribution,
        average_attempts=(
            round(stats.average_attempts, 1)
            if stats.average_attempts is not None
            else None
        ),
        badge=tier_badge(stats.played),
    )
