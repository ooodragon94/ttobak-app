"""HTTP 요청/응답 본문 스키마.

라우터가 주고받는 JSON 모양을 한곳에 모아 두어, 프런트엔드와의 계약이
코드에서 바로 읽히게 한다.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

__all__ = [
    "GuessRequest",
    "GuessRow",
    "GameStateResponse",
    "JoinRequest",
    "LeaderboardResponse",
    "MeResponse",
    "StatsResponse",
]


class WordReportRequest(BaseModel):
    """"이건 진짜 단어인데요" 신고.

    **자모 나열을 그대로 받는다.** 사람이 친 것이 자모라서, 글자로 되돌리는
    것은 서버가 함부로 할 일이 아니다 — 받침 하나 차이로 '옷차림' 이
    '옻차림' 이 된다.
    """

    guess: str = Field(min_length=2, max_length=40, description="거절당한 자모 나열")


class RecoveryResponse(BaseModel):
    """복구 코드를 새로 만들어 **한 번만** 내려보낸다.

    서버는 해시만 갖고 있어 기존 코드를 다시 알려 줄 방법이 없다. 그래서
    "보여 주기" 가 아니라 "새로 만들기" 다. 새로 만들면 **전에 적어 둔 코드는
    못 쓴다** — 화면이 그 사실을 반드시 알려야 한다.
    """

    recovery_code: str = Field(description="새 복구 코드. 다시는 볼 수 없다")


class JoinRequest(BaseModel):
    """닉네임을 정해 게임에 참가한다."""

    nickname: str = Field(min_length=1, max_length=20, description="표시할 닉네임")
    #: 이미 임자가 있는 닉네임으로 들어올 때만 필요하다.
    #:
    #: 평소에는 안 쓴다 — 쿠키가 1년이라 기기를 바꾸거나 브라우저를 지웠을
    #: 때만 넣게 된다.
    recovery_code: str | None = Field(
        default=None, max_length=40, description="복구 코드 (기기를 바꿨을 때)"
    )
    #: 방 주인과 어떤 사이인지. **선택**이다 — 안 적어도 그냥 넘어간다.
    #: 순위표에 닉네임 옆에 붙어서, 서로 모르는 사람들끼리 맥락이 생긴다.
    relation: str = Field(default="", max_length=12)


class MeResponse(BaseModel):
    """현재 접속자 정보."""

    player_id: str | None = Field(default=None, description="로그인했다면 식별자")
    display_name: str | None = Field(default=None, description="표시 이름")
    suggested_nickname: str | None = Field(
        default=None, description="Tailscale 기기명에서 뽑은 닉네임 후보"
    )
    #: 닉네임을 처음 차지했을 때 **딱 한 번** 내려간다.
    #:
    #: 서버는 해시만 갖고 있어서 다시는 알려 줄 수 없다. 화면은 이 값이
    #: 오면 반드시 사용자가 적어 둘 수 있게 크게 보여 줘야 한다.
    recovery_code: str | None = Field(
        default=None, description="처음 가입했을 때만. 다시는 볼 수 없다"
    )


class GuessRequest(BaseModel):
    """추측 제출."""

    guess: str = Field(
        min_length=1,
        max_length=32,
        description="자모를 이어 붙인 문자열. 예: 'ㄱㅗㅇㅑㅇㅇㅣ'",
    )


class GuessRow(BaseModel):
    """제출이 끝난 추측 한 줄."""

    jamos: list[str] = Field(description="칸마다 하나씩 들어간 자모")
    marks: list[str] = Field(description="칸별 채점: correct / present / absent")
    word: str = Field(default="", description="그 자모 나열에 해당하는 단어")


class GameStateResponse(BaseModel):
    """게임판 전체 상태. 정답은 판이 끝난 뒤에만 채워진다."""

    round_no: int = Field(description="0부터 시작하는 라운드 번호")
    length: int = Field(description="이번 판의 자모 칸 수")
    max_attempts: int
    status: str = Field(description="playing / won / lost")
    rows: list[GuessRow]
    keyboard: dict[str, str] = Field(description="자모별 키보드 색")
    answer: str | None = Field(default=None, description="끝난 판의 정답")
    solved_today: int = Field(default=0, description="오늘 맞힌 문제 수")
    share_text: str | None = Field(
        default=None, description="끝난 판의 공유 문구. 정답은 들어 있지 않다"
    )
    hints: list[str | None] = Field(
        default_factory=list,
        description="칸 수만큼의 목록. 힌트로 열린 자리만 자모, 나머지는 null",
    )
    hint_available: bool = Field(default=False, description="힌트를 더 받을 수 있는지")
    #: 이 판의 난이도 열쇠. 화면이 표시를 띄우는 데 쓴다.
    difficulty: str = Field(default="normal")
    hints_left: int = Field(default=0, description="더 받을 수 있는 힌트 수")


class LeaderboardRow(BaseModel):
    """순위표 한 줄. 오늘 몇 개를 맞혔는지가 기준이다."""

    rank: int
    display_name: str
    #: 방 주인과 어떤 사이인지. 선택 입력이라 빈 값이 정상이다.
    relation: str = Field(default="")
    solved: int = Field(description="오늘 맞힌 문제 수")
    played: int = Field(description="오늘 끝낸 문제 수")
    average_attempts: float | None = Field(
        default=None, description="맞힌 판들의 평균 시도 횟수"
    )
    best_attempts: int | None = Field(
        default=None, description="맞힌 판 중 최소 시도 횟수"
    )
    medal: str = Field(default="", description="1~3등 메달. 그 아래는 빈 문자열")
    title: str = Field(default="", description="칭호 이름. 없으면 빈 문자열")
    title_emoji: str = Field(default="", description="칭호 그림")
    is_me: bool = Field(default=False, description="내 줄인지")
    #: 후원해 준 사람. 확인은 못 하지만 본인이 눌러 준 것을 믿는다.
    supporter: bool = Field(default=False, description="후원자 배지")


class LeaderboardResponse(BaseModel):
    played_on: date
    entries: list[LeaderboardRow]


class StatsResponse(BaseModel):
    """개인 통계."""

    played: int
    wins: int
    win_rate: float
    current_streak: int
    max_streak: int
    guess_distribution: dict[int, int]
    average_attempts: float | None = Field(
        default=None, description="맞힌 판들의 평균 시도 횟수"
    )
    badge: str = Field(default="🌱", description="누적 판수에 따른 배지")


class ThemeChoice(BaseModel):
    key: str
    label: str
    preview: str


class DifficultyChoice(BaseModel):
    """고를 수 있는 난이도 하나.

    규칙 두 개를 참/거짓으로 함께 내려보내는 이유: 화면이 "맞힌 자리는 그대로"
    옆에 초록 칸을, "나온 자모는 꼭" 옆에 노란 칸을 그린다. 문구만 주면
    어느 색을 붙일지 화면이 이름으로 짐작해야 하고, 그러면 난이도를 하나
    더 넣을 때 조용히 틀린 색이 붙는다.
    """

    key: str
    label: str
    emoji: str
    note: str
    keep_correct: bool = Field(description="맞힌 자리를 그대로 둬야 하는지")
    require_present: bool = Field(description="나온 자모를 반드시 넣어야 하는지")


class SettingsResponse(BaseModel):
    """플레이어 개인 설정."""

    hints_enabled: bool = Field(description="힌트를 쓸지 여부")
    hints_offered: bool = Field(
        description="서버가 힌트 기능을 제공하는지. 꺼져 있으면 설정 자체가 안 보인다"
    )
    share_theme: str = Field(description="공유 격자 그림 테마")
    themes: list[ThemeChoice] = Field(
        default_factory=list, description="고를 수 있는 테마 목록"
    )
    #: 이 사람이 풀기로 한 자모 길이. 서버가 내는 길이 중에서만 고를 수 있다.
    puzzle_lengths: list[int] = Field(
        default_factory=list, description="지금 고른 길이들"
    )
    #: 고를 수 있는 전체 길이. 화면이 이걸로 선택지를 그린다.
    available_lengths: list[int] = Field(default_factory=list)
    #: 이 사람이 고른 시도 횟수.
    max_attempts: int = Field(default=6, description="지금 고른 시도 횟수")
    #: 고를 수 있는 시도 횟수들.
    attempt_choices: list[int] = Field(default_factory=list)
    #: 지금 고른 난이도 열쇠.
    difficulty: str = Field(default="normal", description="난이도")
    #: 고를 수 있는 난이도들. 화면이 이걸로 선택지와 설명을 그린다.
    difficulty_choices: list[DifficultyChoice] = Field(default_factory=list)
    #: 지금 난이도를 바꾸면 **풀던 판이 포기로 기록되는가.**
    #:
    #: 화면이 확인을 받을지 판단하는 데 쓴다. 아직 한 번도 안 친 판이면
    #: 잃을 것이 없으므로 묻지 않는다 — 매번 물으면 잔소리가 된다.
    #: 지금 고르면 **풀던 판을 잃는** 난이도들. 참/거짓 하나로는 모자라다 —
    #: 내리는 것은 공짜고 올리는 것만 판을 잃기 때문이다.
    costly_difficulties: list[str] = Field(default_factory=list)
    #: 지금 적어 둔 "방장과의 사이".
    relation: str = Field(default="")


class SupportProviderRow(BaseModel):
    """송금 수단 하나. 설정된 것만 내려간다."""

    key: str
    label: str
    emoji: str
    #: 누르면 갈 곳.
    url: str = Field(default="", description="이 수단의 송금 주소")


class SupportResponse(BaseModel):
    """후원 안내.

    ``url`` 이 비어 있으면 화면은 후원 버튼을 **아예 안 그린다.** 링크를 안
    정했는데 버튼만 있으면 눌렀을 때 아무 데도 안 가고, 그건 후원을 못 받는
    것보다 나쁘다.
    """

    url: str = Field(default="", description="후원 페이지. 비면 기능 자체가 꺼진다")
    #: 설정된 송금 수단들. 비어 있으면 화면은 수단 선택을 안 그린다.
    providers: list[SupportProviderRow] = Field(default_factory=list)


class SettingsRequest(BaseModel):
    """바꿀 설정. 준 항목만 반영한다."""

    hints_enabled: bool | None = Field(default=None, description="힌트 사용 여부")
    share_theme: str | None = Field(default=None, description="공유 격자 테마")
    #: 방 주인과 어떤 사이인지. 빈 문자열을 주면 지운다.
    relation: str | None = Field(default=None, max_length=12)
    #: 풀고 싶은 자모 길이들. 빈 목록을 주면 "전부" 로 되돌린다.
    puzzle_lengths: list[int] | None = Field(
        default=None, description="풀 자모 길이 (빈 목록이면 전부)"
    )
    #: 시도 횟수. 다음 문제부터 적용된다.
    max_attempts: int | None = Field(default=None, description="시도 횟수")
    #: 난이도. 다음 문제부터 적용된다.
    difficulty: str | None = Field(default=None, description="난이도")


# ---------------------------------------------------------------------------
# 방 / 오늘의 문제 / 댓글
# ---------------------------------------------------------------------------


class RoomRow(BaseModel):
    """방 하나. 목록과 상세에 함께 쓴다."""

    id: str = Field(description="초대 코드. 링크에 그대로 들어간다")
    name: str = Field(description="방 이름")
    member_count: int = Field(description="지금 인원")
    is_owner: bool = Field(description="내가 만든 방인지")
    #: 이 방에서 응원하기를 보여 줄지. 주인만 바꿀 수 있다.
    support_enabled: bool = Field(default=True, description="응원하기 노출")
    #: 오늘 이 방에서 **내가 아직 안 끝낸** 문제 수.
    #:
    #: 화면이 "다음에 무엇을 열까" 를 정하는 데 쓴다. 이 값이 없으면
    #: 화면이 방마다 오늘의 문제를 따로 물어봐야 해서 왕복이 늘고,
    #: 그 사이에 일반 판이 잠깐 보였다 바뀐다.
    daily_left: int = Field(default=0, description="오늘 남은 문제 수")


class RoomPeekResponse(BaseModel):
    """초대 링크를 누른 사람에게 보여 줄 최소한의 정보.

    **아직 아무도 아닌 사람이 받는 응답이다.** 그래서 이름과 인원수만 담는다.
    회원 명단도, 순위표도, 오늘의 낱말도 여기 실리지 않는다.
    """

    name: str = Field(description="방 이름")
    member_count: int = Field(description="지금 인원")


class RoomSupportRequest(BaseModel):
    enabled: bool = Field(description="응원하기를 보여 줄지")


class RoomsResponse(BaseModel):
    rooms: list[RoomRow] = Field(default_factory=list)


class CreateRoomRequest(BaseModel):
    #: 길이 상한을 여기서도 건다. 서버가 잘라 주긴 하지만, 요청 본문 자체를
    #: 작게 유지해야 거대한 문자열이 파싱 단계에서 메모리를 먹지 않는다.
    name: str = Field(max_length=200, description="방 이름")


class StandingRow(BaseModel):
    """오늘의 순위 한 줄."""

    display_name: str
    #: 방 주인과 어떤 사이인지. 선택 입력이라 빈 값이 정상이다.
    relation: str = Field(default="")
    status: str = Field(description="won | lost | playing | none(아직 안 함)")
    attempts: int = Field(description="이 문제에 쓴 시도 횟수")
    is_me: bool = Field(description="나인지. 화면에서 내 줄을 강조한다")
    supporter: bool = Field(default=False, description="후원자 배지")


class DailySlotRow(BaseModel):
    """그날 문제 하나의 요약. 화면이 전환 단추를 그리는 데 쓴다."""

    slot: int = Field(description="0부터")
    length: int = Field(description="자모 칸 수")
    status: str = Field(description="won | lost | playing | new")
    attempts: int = Field(default=0)


class DailyStateResponse(BaseModel):
    """방의 오늘의 문제 상태.

    **정답은 판이 끝난 뒤에만 채워진다.** 진행 중에는 ``null`` 이다 —
    응답에 담아 두고 화면에서 안 보여 주는 방식은 개발자 도구를 열면
    끝이라 방어가 아니다.
    """

    room: RoomRow
    play_date: str = Field(description="YYYY-MM-DD (KST)")
    length: int = Field(description="자모 칸 수")
    max_attempts: int
    status: str = Field(description="won | lost | playing")
    # 판을 그리는 부분은 일반 게임과 **같은 모양**으로 준다. 화면에서 판을
    # 그리는 코드가 이미 있고, 모양이 다르면 그 코드를 한 벌 더 쓰게 된다.
    # 두 벌이 되면 색칠 규칙 같은 것이 한쪽만 고쳐져 어긋난다.
    rows: list[GuessRow] = Field(default_factory=list)
    keyboard: dict[str, str] = Field(
        default_factory=dict, description="자모별 키보드 색"
    )
    answer: str | None = Field(default=None, description="끝난 뒤에만 준다")
    standings: list[StandingRow] = Field(default_factory=list)
    solved_count: int = Field(default=0, description="오늘 맞힌 사람 수")
    #: 칸 수만큼의 목록. 힌트로 열린 자리만 자모, 나머지는 null.
    hints: list[str | None] = Field(default_factory=list)
    hint_available: bool = Field(default=False, description="힌트를 더 받을 수 있는지")
    hints_left: int = Field(default=0, description="더 받을 수 있는 힌트 수")
    #: 지금 보고 있는 문제 번호.
    slot: int = Field(default=0)
    #: 그날 문제들의 요약. 화면이 ①② 전환 단추를 그린다.
    slots: list[DailySlotRow] = Field(default_factory=list)
    total_count: int = Field(default=0, description="오늘 시작한 사람 수")
    #: 끝난 뒤에만 채워지는 공유 문구. **정답은 들어 있지 않다.**
    #:
    #: 링크에 방 코드가 실려 있어 받은 사람이 같은 방으로 바로 들어온다.
    #: 그게 이 기능의 목적이다 — 같은 문제를 푼 사람끼리 비교하는 것.
    share_text: str | None = Field(default=None)


class DailyGuessRequest(BaseModel):
    guess: str = Field(max_length=100, description="자모 문자열")
    #: 어느 문제인가. 서버가 짐작하면 화면이 2번을 보고 있는데 1번에
    #: 채점이 들어가는 일이 생긴다.
    slot: int = Field(default=0, ge=0, le=9, description="그날 몇 번째 문제")


class CommentRow(BaseModel):
    id: int
    display_name: str
    body: str
    is_me: bool


class CommentsResponse(BaseModel):
    comments: list[CommentRow] = Field(default_factory=list)
    remaining: int = Field(description="오늘 더 쓸 수 있는 개수")


class NewCommentRequest(BaseModel):
    body: str = Field(max_length=500, description="남길 한 줄")


class ThanksResponse(BaseModel):
    """후원 신고를 받은 뒤 감사 화면에 쓸 값."""

    count: int = Field(description="이 사람이 지금까지 보낸 횟수")
