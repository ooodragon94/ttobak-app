"""방 API — 오늘의 문제, 방별 순위표, 댓글.

보안에서 이 파일이 지키는 것
----------------------------

방 코드는 링크에 실려 카톡으로 돌아다닌다. 그래서 **코드를 아는 것과 회원인
것은 다르다**. 여기 있는 모든 방 관련 처리는 :func:`_member_room` 을 지나가고,
그 함수가 회원 여부를 확인한다.

회원이 아니면 **404** 를 준다. 403("권한 없음")이 아니다. 403 은 "그 방은
있는데 너는 못 들어간다"는 뜻이라, 코드를 찍어 보는 사람에게 **맞았다는 신호**
를 준다. 없는 것처럼 답해야 코드를 훑어도 아무것도 알아낼 수 없다.

댓글은 **오늘 문제를 끝낸 사람만** 쓰고 볼 수 있다. 이유는
:mod:`ttobak.game.comments` 에 적었다 — 한 줄이 그날 문제를 통째로 망친다.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ttobak.config import Settings
from ttobak.db import Player
from ttobak.db.repository import Database, Room
from ttobak.game.comments import (
    MAX_COMMENTS_PER_DAY,
    CommentError,
    clean_comment,
)
from ttobak.game.rooms import (
    MAX_MEMBERS,
    MAX_ROOMS_PER_PLAYER,
    RoomError,
    clean_room_name,
    is_valid_room_code,
    new_room_code,
    new_room_salt,
)
from ttobak.game.rounds import DAILY_SLOTS, daily_lengths, puzzle_for_day
from ttobak.game.rules import Mark, score_guess
from ttobak.game.service import HINT_AFTER_ATTEMPTS, InvalidGuessError
from ttobak.game.share import build_daily_share_text
from ttobak.hangul import decompose
from ttobak.web.deps import (
    CurrentPlayer,
    DatabaseDep,
    ServiceDep,
    SettingsDep,
    today,
)
from ttobak.web.schemas import (
    CommentRow,
    CommentsResponse,
    CreateRoomRequest,
    DailyGuessRequest,
    DailySlotRow,
    DailyStateResponse,
    NewCommentRequest,
    RoomPeekResponse,
    RoomRow,
    RoomsResponse,
    RoomSupportRequest,
    StandingRow,
)

router = APIRouter(prefix="/api/rooms", tags=["rooms"])

def _not_found() -> HTTPException:
    """방이 없거나, 있어도 내 방이 아닐 때.

    두 경우를 **같은 답**으로 처리하는 것이 핵심이다. 구분해서 답하면
    "이 코드는 존재한다"는 정보가 새어 나간다.
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="그런 방이 없어요."
    )


def _member_room(database: Database, room_id: str, player: Player) -> Room:
    """회원인 방을 가져온다. 아니면 404.

    **방을 건드리는 모든 요청이 여기를 지나야 한다.** 한 군데라도 빠뜨리면
    링크만 아는 사람이 남의 방 순위표를 읽을 수 있다.
    """
    # 형식부터 본다. 이상한 문자열이 DB 쿼리까지 가는 경로를 짧게 끊는다.
    if not is_valid_room_code(room_id):
        raise _not_found()
    room = database.get_room(room_id)
    if room is None or not database.is_member(room_id, player.id):
        raise _not_found()
    return room


def _room_row(room: Room, player: Player, daily_left: int = 0) -> RoomRow:
    return RoomRow(
        id=room.id,
        name=room.name,
        member_count=room.member_count,
        is_owner=room.owner_id == player.id,
        support_enabled=room.support_enabled,
        daily_left=daily_left,
    )


def _daily_left(database: Database, room_id: str, player_id: str, day) -> int:
    """오늘 이 방에서 그 사람이 **아직 안 끝낸** 문제 수.

    아직 안 연 문제도 센다. 화면은 이 값으로 "다음에 오늘의 문제를 열까,
    일반 판을 열까" 를 정한다 — 그날 처음 들어온 사람은 이 값이 최대이므로
    곧장 오늘의 문제로 간다.
    """
    started = database.dailies_of(room_id, day, player_id)
    return sum(
        1
        for slot in range(DAILY_SLOTS)
        if not (started.get(slot) and started[slot].is_finished)
    )


# ---------------------------------------------------------------------------
# 방 만들기 / 들어가기
# ---------------------------------------------------------------------------


@router.get("", response_model=RoomsResponse)
def list_rooms(player: CurrentPlayer, database: DatabaseDep) -> RoomsResponse:
    """내가 속한 방들."""
    day = today()
    rooms = database.rooms_of(player.id)
    return RoomsResponse(
        rooms=[
            _room_row(r, player, _daily_left(database, r.id, player.id, day))
            for r in rooms
        ]
    )


@router.post("", response_model=RoomRow, status_code=status.HTTP_201_CREATED)
def create_room(
    payload: CreateRoomRequest, player: CurrentPlayer, database: DatabaseDep
) -> RoomRow:
    """방을 만든다. 만든 사람이 첫 회원이 된다."""
    try:
        name = clean_room_name(payload.name)
    except RoomError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    # 한 사람이 방을 무한히 만들면 DB 가 부풀고, 자동화하면 그것만으로
    # 서비스를 못 쓰게 만들 수 있다.
    if database.count_rooms_owned(player.id) >= MAX_ROOMS_PER_PLAYER:
        raise HTTPException(
            status_code=422,
            detail=f"방은 최대 {MAX_ROOMS_PER_PLAYER}개까지 만들 수 있어요.",
        )

    room = database.create_room(
        new_room_code(), name, player.id, new_room_salt()
    )
    return _room_row(room, player)


@router.post("/{room_id}/support", response_model=RoomRow)
def set_room_support(
    room_id: str,
    payload: RoomSupportRequest,
    player: CurrentPlayer,
    database: DatabaseDep,
) -> RoomRow:
    """이 방에서 응원하기를 보여 줄지 정한다. **방 주인만.**

    여기서는 403 이 맞다. 회원이라는 것까지는 이미 확인됐고, 알려 줘야 하는
    것은 "네 방이 아니다" 라는 사실이다. 404 로 숨기면 방금 목록에서 본 방이
    사라진 것처럼 보인다.
    """
    room = _member_room(database, room_id, player)
    if room.owner_id != player.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="방을 만든 사람만 바꿀 수 있어요.",
        )
    database.set_room_support(room.id, payload.enabled)
    updated = database.get_room(room.id)
    return _room_row(updated or room, player)


@router.get("/{room_id}/peek", response_model=RoomPeekResponse)
def peek_room(room_id: str, database: DatabaseDep) -> RoomPeekResponse:
    """초대 링크를 누른 사람에게 **방 이름만** 알려 준다.

    이 파일에서 로그인을 안 거치는 유일한 곳이다. 링크를 눌러 처음 온 사람은
    아직 닉네임이 없어서 :data:`CurrentPlayer` 를 통과할 수 없는데, 정작 그
    사람이 보는 화면이 "여기가 어디인지" 를 한 글자도 안 적고 있었다.

    로그인 없이 열어도 되는 이유는 **주는 것이 이름과 인원수뿐**이기
    때문이다. 회원 명단도, 순위표도, 오늘의 낱말도 안 준다. 그리고 코드를
    아는 사람은 어차피 :func:`join_room` 으로 들어올 수 있으므로, 이름을
    감추는 것은 아무것도 지켜 주지 않는다.

    틀린 코드에는 404 를 준다 — 파일 첫머리에 적은 이유와 같다.
    """
    if not is_valid_room_code(room_id):
        raise _not_found()
    room = database.get_room(room_id)
    if room is None:
        raise _not_found()
    return RoomPeekResponse(name=room.name, member_count=room.member_count)


@router.post("/{room_id}/join", response_model=RoomRow)
def join_room(
    room_id: str, player: CurrentPlayer, database: DatabaseDep
) -> RoomRow:
    """초대 링크로 방에 들어간다.

    여기만은 회원이 아닌 사람도 부를 수 있다(그래야 들어갈 수 있다). 대신
    **코드가 정확히 맞아야** 하고, 웹 계층의 요청 수 제한이 함께 걸린다.
    """
    if not is_valid_room_code(room_id):
        raise _not_found()
    room = database.get_room(room_id)
    if room is None:
        raise _not_found()

    # 이미 회원이면 그냥 통과시킨다. 링크를 두 번 눌렀을 뿐이다.
    if not database.is_member(room_id, player.id):
        # 링크가 밖으로 샜을 때 수천 명이 들어와 순위표를 못 쓰게 만드는 것을
        # 막는다. 친구들끼리 쓰는 물건이라 이 정도면 넉넉하다.
        if database.count_members(room_id) >= MAX_MEMBERS:
            raise HTTPException(
                status_code=422, detail=f"이 방은 정원({MAX_MEMBERS}명)이 찼어요."
            )
        database.join_room(room_id, player.id)

    refreshed = database.get_room(room_id)
    assert refreshed is not None
    return _room_row(refreshed, player)


@router.post("/{room_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_room(
    room_id: str, player: CurrentPlayer, database: DatabaseDep
) -> None:
    """방에서 나온다. 남긴 기록은 지우지 않는다."""
    _member_room(database, room_id, player)
    database.leave_room(room_id, player.id)


# ---------------------------------------------------------------------------
# 오늘의 문제
# ---------------------------------------------------------------------------


def daily_answer(room: Room, service, day, slot: int) -> str:
    """그 방의 그날 ``slot`` 번째 문제의 정답.

    길이는 슬롯마다 정해져 있다 — 1번은 가장 짧게(5자모), 2번은 그보다
    길게(6~7자모). 매일 첫 문제가 같은 크기라야 습관이 붙는다.
    """
    puzzle = puzzle_for_day(
        room.puzzle_salt,
        day.isoformat(),
        service.lexicon,
        lengths=daily_lengths(slot, service.lexicon.lengths),
        slot=slot,
    )
    return puzzle.answer


def room_answer(database: Database, room: Room, service, day, slot: int) -> str:
    """그 방 그날 문제의 정답. **먼저 연 사람이 있으면 그 사람 것을 따른다.**

    :func:`daily_answer` 는 지금 정답 목록으로 새로 계산한다. 목록이 하루 중간에
    바뀌면 같은 방 안에서도 먼저 연 사람과 나중에 연 사람의 낱말이 달라진다.
    판을 여는 곳과 칸 수를 미리 보여 주는 곳이 **둘 다** 이것을 거쳐야 한다 —
    한쪽만 거치면 "5칸이라더니 열어 보니 6칸" 이 된다.
    """
    opened = database.room_daily_answer(room.id, day, slot)
    return opened or daily_answer(room, service, day, slot)


def _open_slot(database: Database, room: Room, player: Player, service, day, slot: int):
    """그 슬롯의 판을 가져온다. 없으면 연다."""
    record = database.get_daily(room.id, day, player.id, slot)
    if record is None:
        answer = room_answer(database, room, service, day, slot)
        record = database.start_daily(room.id, day, player.id, answer, slot)
    return record


def _slot_rows(
    database: Database, room: Room, player: Player, service, day
) -> list[DailySlotRow]:
    """그날 문제들의 요약. 화면이 ①② 전환 단추를 그리는 데 쓴다."""
    started = database.dailies_of(room.id, day, player.id)
    rows = []
    for slot in range(DAILY_SLOTS):
        record = started.get(slot)
        if record is None:
            # 아직 안 연 문제. 길이는 미리 알 수 있으므로 칸 수는 보여 준다.
            answer = room_answer(database, room, service, day, slot)
            length = len(decompose(answer))
            rows.append(
                DailySlotRow(slot=slot, length=length, status="new", attempts=0)
            )
        else:
            rows.append(
                DailySlotRow(
                    slot=slot,
                    length=len(decompose(record.answer)),
                    status=record.status,
                    attempts=len(record.guesses),
                )
            )
    return rows


def _pick_slot(slots: list[DailySlotRow], wanted: int | None) -> int:
    """보여 줄 문제를 고른다.

    지정하지 않으면 **아직 안 끝낸 첫 문제**를 연다. 다 끝냈으면 마지막
    문제를 보여 준다 — 방금 푼 결과가 화면에 남아 있어야 자연스럽다.
    """
    if wanted is not None and 0 <= wanted < len(slots):
        return wanted
    for row in slots:
        if row.status in ("new", "playing"):
            return row.slot
    return slots[-1].slot if slots else 0


def _daily_state(
    database: Database,
    room: Room,
    player: Player,
    service,
    settings: Settings,
    slot: int | None = None,
) -> DailyStateResponse:
    """오늘 판의 상태를 화면이 쓸 모양으로 만든다.

    **끝나기 전에는 정답을 절대 내보내지 않는다.** 판정 결과(색깔)만 준다.
    """
    day = today()
    slots = _slot_rows(database, room, player, service, day)
    slot = _pick_slot(slots, slot)
    record = _open_slot(database, room, player, service, day, slot)
    # 판을 연 뒤라 요약이 바뀌었을 수 있다. 다시 만들어야 화면과 어긋나지 않는다.
    slots = _slot_rows(database, room, player, service, day)

    # 판을 그리는 부분은 일반 게임과 **같은 코드**로 만든다. 색칠 규칙이
    # 두 벌이 되면 한쪽만 고쳐져 같은 자모가 화면마다 다른 색이 된다.
    rows, keyboard = service.board(record.guesses, record.answer)

    answer_jamos = tuple(decompose(record.answer))
    allowance = service.hint_allowance_for(
        player.id, len(record.guesses), len(answer_jamos)
    )
    hints = service.hint_slots_for(record.hints_used, answer_jamos, rows)

    # 순위는 **지금 보고 있는 문제**의 것이다. 1번과 2번은 다른 낱말이라
    # 합쳐서 줄 세울 수 없다.
    standings = database.daily_standings(room.id, day, slot)
    supporters = database.supporter_ids()

    # 맞힌 사람들 사이에서의 등수. 못 맞힌 사람은 0(등수 없음)이다.
    winners = [s for s in standings if s.status == "won"]
    # 공유 문구의 "n명 중" 은 **푼 사람** 수다. 방에 있기만 한 사람까지 세면
    # 등수가 실제보다 대단해 보인다.
    players = [s for s in standings if s.status != "none"]
    my_rank = next(
        (i for i, s in enumerate(winners, 1) if s.player_id == player.id), 0
    )

    share_text = None
    # 한 번도 안 치고 포기한 판은 공유할 격자가 없다. 그대로 만들려고 하면
    # 500 이 난다 — 실제로 그랬다. 공유 버튼이 안 뜨는 것이 맞는 동작이고,
    # 보여 줄 것이 없는데 굳이 빈 격자를 지어낼 이유도 없다.
    if record.is_finished and rows:
        base = (settings.share_url or "").rstrip("/")
        share_text = build_daily_share_text(
            nickname=player.display_name,
            room_name=room.name,
            played_on=day,
            status=record.status,
            max_attempts=service.max_attempts,
            marks_per_row=[row["marks"] for row in rows],
            rank=my_rank,
            total=len(players),
            solved=len(winners),
            theme_key=player.share_theme,
            # 방 코드를 실어야 받은 사람이 **같은 방**으로 들어온다.
            # 코드가 없으면 그냥 앱만 열려서 비교가 안 된다.
            url=f"{base}/?room={room.id}" if base else None,
        )
    return DailyStateResponse(
        room=_room_row(room, player),
        play_date=day.isoformat(),
        length=len(decompose(record.answer)),
        max_attempts=service.max_attempts,
        status=record.status,
        rows=rows,
        keyboard=keyboard,
        # 끝난 뒤에만 정답을 준다.
        answer=record.answer if record.is_finished else None,
        standings=[
            StandingRow(
                display_name=s.display_name,
                relation=s.relation,
                status=s.status,
                attempts=s.attempts,
                is_me=s.player_id == player.id,
                supporter=s.player_id in supporters,
            )
            for s in standings
        ],
        solved_count=len(winners),
        total_count=len(players),
        share_text=share_text,
        hints=hints,
        hint_available=(
            not record.is_finished
            and len(record.guesses) >= HINT_AFTER_ATTEMPTS
            and record.hints_used < allowance
        ),
        hints_left=max(0, allowance - record.hints_used),
        slot=slot,
        slots=slots,
    )


@router.get("/{room_id}/daily", response_model=DailyStateResponse)
def read_daily(
    room_id: str,
    player: CurrentPlayer,
    database: DatabaseDep,
    service: ServiceDep,
    settings: SettingsDep,
    slot: int | None = None,
) -> DailyStateResponse:
    """오늘의 문제 상태. ``slot`` 을 안 주면 아직 안 끝낸 첫 문제를 연다."""
    room = _member_room(database, room_id, player)
    return _daily_state(database, room, player, service, settings, slot)


@router.post("/{room_id}/daily/guess", response_model=DailyStateResponse)
def guess_daily(
    room_id: str,
    payload: DailyGuessRequest,
    player: CurrentPlayer,
    database: DatabaseDep,
    service: ServiceDep,
    settings: SettingsDep,
) -> DailyStateResponse:
    """오늘의 문제에 한 번 추측한다.

    어느 문제인지(``slot``)를 반드시 받는다. 서버가 짐작하면 화면이 2번을
    보고 있는데 1번에 채점이 들어가는 일이 생긴다.
    """
    room = _member_room(database, room_id, player)
    day = today()
    slot = payload.slot or 0
    if not 0 <= slot < DAILY_SLOTS:
        raise HTTPException(status_code=422, detail="없는 문제 번호예요.")

    record = _open_slot(database, room, player, service, day, slot)
    if record.is_finished:
        raise HTTPException(status_code=409, detail="오늘 문제는 이미 끝났어요.")

    answer_jamos = tuple(decompose(record.answer))
    try:
        word = service.validate_guess(payload.guess, record.answer)
    except InvalidGuessError as error:
        # **혼자 푸는 판과 똑같은 모양으로 돌려준다.** 예전에는 여기만
        # ``str(error)`` 로 문자열을 보내서 ``code`` 가 사라졌다. 그래서
        # 오늘의 문제에서는 사전에 없는 낱말을 쳐도 신고 단추가 안 붙었다.
        # 화면 코드는 하나인데 서버가 두 모양으로 답하고 있었던 것이다.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=error.as_detail()
        ) from error

    guesses = (*record.guesses, word)
    marks = score_guess(tuple(decompose(word)), answer_jamos)
    if all(m is Mark.CORRECT for m in marks):
        new_status = "won"
    elif len(guesses) >= service.max_attempts:
        new_status = "lost"
    else:
        new_status = "playing"

    # 낙관적 잠금. 읽었을 때의 개수가 그대로 남아 있을 때만 저장한다.
    # 없으면 추측 여섯 개를 동시에 보내 한 번의 기회로 여섯 단어의 색을
    # 전부 알아낼 수 있다(응답은 다 채점돼 오고 저장만 하나 남는다).
    saved = database.save_daily(
        room.id,
        day,
        player.id,
        guesses,
        new_status,
        expect_attempts=len(record.guesses),
        slot=slot,
    )
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="방금 다른 추측이 먼저 반영됐어요. 다시 시도해 주세요.",
        )
    return _daily_state(database, room, player, service, settings, slot)


# ---------------------------------------------------------------------------
# 댓글 — 푼 사람만
# ---------------------------------------------------------------------------


def _require_finished(database: Database, room: Room, player: Player):
    """오늘 문제를 끝냈는지 확인한다. 안 끝냈으면 403.

    여기서는 403 이 맞다. 방이 있다는 것도, 내가 회원이라는 것도 이미 아는
    상태이고, 알려 줘야 하는 것은 "먼저 풀어라"라는 **행동 안내**이기 때문이다.
    404 로 숨기면 사용자가 무엇을 해야 할지 알 수 없다.
    """
    started = database.dailies_of(room.id, today(), player.id)
    # **전부** 끝내야 한다. 1번만 끝낸 사람에게 댓글을 보여 주면 2번에 대한
    # 이야기가 그대로 스포일러가 된다.
    done = [
        started.get(slot) for slot in range(DAILY_SLOTS)
    ]
    if any(record is None or not record.is_finished for record in done):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="오늘 문제를 다 풀어야 볼 수 있어요. (스포일러 방지)",
        )
    return done[-1]


@router.post("/{room_id}/daily/resign", response_model=DailyStateResponse)
def resign_daily(
    room_id: str,
    player: CurrentPlayer,
    database: DatabaseDep,
    service: ServiceDep,
    settings: SettingsDep,
    slot: int | None = None,
) -> DailyStateResponse:
    """오늘의 문제를 포기한다. 패배로 적고 **정답을 보여 준다.**

    오늘의 문제는 하루에 한 번뿐이라 "다음 문제" 가 없다. 그래서 막히면
    빠져나갈 방법이 아예 없었다 — 지지도 못한 채 그 판에 갇힌다. 포기한
    사람이 제일 먼저 궁금한 것은 정답이므로, 진 판을 그대로 보여 준다.
    """
    room = _member_room(database, room_id, player)
    day = today()
    slots = _slot_rows(database, room, player, service, day)
    chosen = _pick_slot(slots, slot)
    record = database.get_daily(room.id, day, player.id, chosen)
    if record is None:
        raise HTTPException(status_code=404, detail="아직 시작하지 않은 문제예요.")
    if not record.is_finished:
        database.abandon_daily(room.id, day, player.id, chosen)
    return _daily_state(database, room, player, service, settings, chosen)


@router.post("/{room_id}/daily/hint", response_model=DailyStateResponse)
def hint_daily(
    room_id: str,
    player: CurrentPlayer,
    database: DatabaseDep,
    service: ServiceDep,
    settings: SettingsDep,
    slot: int | None = None,
) -> DailyStateResponse:
    """오늘의 문제에서 힌트를 하나 연다.

    일반 라운드와 **같은 규칙**이다 — 세 번 틀린 뒤부터, 시도가 늘 때마다
    하나씩, 끝의 두 자모는 끝까지 남긴다.

    쓴 힌트 수는 순위표에 반영된다. 같은 세 번이라도 힌트 없이 푼 쪽이 위로
    간다. 그러지 않으면 모두 같은 단어를 푸는 의미가 없어진다.
    """
    room = _member_room(database, room_id, player)
    day = today()
    slots = _slot_rows(database, room, player, service, day)
    chosen = _pick_slot(slots, slot)
    record = _open_slot(database, room, player, service, day, chosen)
    if record.is_finished:
        raise HTTPException(status_code=400, detail="이미 끝난 문제예요.")

    if not settings.hints_offered:
        raise HTTPException(status_code=400, detail="힌트 기능이 꺼져 있습니다.")
    if not player.hints_enabled:
        raise HTTPException(
            status_code=400, detail="설정에서 힌트를 켜야 쓸 수 있어요."
        )
    if len(record.guesses) < HINT_AFTER_ATTEMPTS:
        left = HINT_AFTER_ATTEMPTS - len(record.guesses)
        raise HTTPException(
            status_code=400, detail=f"{left}번 더 시도하면 힌트를 쓸 수 있어요."
        )

    allowance = service.hint_allowance_for(
        player.id, len(record.guesses), len(decompose(record.answer))
    )
    # 상한을 SQL 조건으로 넘긴다. 여기서 검사만 하고 넘기면 요청이 동시에
    # 올 때 전부 통과해 정답이 통째로 열린다.
    if database.use_daily_hint(room.id, day, player.id, chosen, allowance) is None:
        raise HTTPException(
            status_code=400, detail="지금은 더 열 수 있는 힌트가 없어요."
        )
    return _daily_state(database, room, player, service, settings, chosen)


@router.get("/{room_id}/comments", response_model=CommentsResponse)
def read_comments(
    room_id: str, player: CurrentPlayer, database: DatabaseDep
) -> CommentsResponse:
    """오늘의 댓글. **오늘 문제를 끝낸 사람만 볼 수 있다.**"""
    room = _member_room(database, room_id, player)
    _require_finished(database, room, player)
    rows = database.comments(room.id, today())
    return CommentsResponse(
        comments=[
            CommentRow(
                id=c.id,
                display_name=c.display_name,
                body=c.body,
                is_me=c.player_id == player.id,
            )
            for c in rows
        ],
        remaining=MAX_COMMENTS_PER_DAY
        - database.count_comments_today(room.id, today(), player.id),
    )


@router.post("/{room_id}/comments", response_model=CommentsResponse)
def write_comment(
    room_id: str,
    payload: NewCommentRequest,
    player: CurrentPlayer,
    database: DatabaseDep,
) -> CommentsResponse:
    """한 줄 남긴다. **오늘 문제를 끝낸 사람만.**"""
    room = _member_room(database, room_id, player)
    _require_finished(database, room, player)

    try:
        body = clean_comment(payload.body)
    except CommentError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    day = today()
    # 도배 방지. 대화를 막으려는 것이 아니라 한 사람이 화면을 통째로 차지하는
    # 것을 막는다.
    if database.count_comments_today(room.id, day, player.id) >= MAX_COMMENTS_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail=f"오늘은 {MAX_COMMENTS_PER_DAY}개까지 쓸 수 있어요.",
        )

    database.add_comment(room.id, day, player.id, body)
    return read_comments(room_id, player, database)
