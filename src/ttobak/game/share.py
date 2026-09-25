"""공유 문구 만들기.

결과를 채팅방에 붙여 넣을 수 있는 짧은 글로 바꾼다.

**정답을 흘리지 않는 것이 핵심이다.** 자모는 빼고 색만 네모로 남긴다. 받은
사람은 몇 번 만에 맞혔는지, 얼마나 헤맸는지는 알 수 있지만 답은 알 수 없다.
그래서 아직 안 푼 사람에게 보내도 게임을 망치지 않는다.

문구를 짜는 원칙
----------------
채팅방에서는 스크롤이 빠르게 흐른다. 그래서 **위에서부터 중요한 순서로** 놓는다.

1. 첫 줄에 결과와 이름. 미리보기로 한 줄만 보이는 일이 잦다.
2. 그다음 격자. 눈길을 끄는 부분이고, 색만 봐도 얼마나 헤맸는지 보인다.
3. 마지막에 누적 기록과 주소. 관심 있는 사람만 읽으면 된다.

가운뎃점으로 이어 한 줄에 여러 값을 담는다. 줄이 늘어질수록 채팅방에서
자리를 많이 차지해 눈총을 받는다.

이 파일에는 입출력이 없다. 값을 받아 문자열을 돌려주는 순수 함수뿐이라 그대로
단위 테스트할 수 있다.
"""

from __future__ import annotations

from datetime import date

from ttobak.game.hard import get_difficulty
from ttobak.game.rules import Mark
from ttobak.game.themes import ShareTheme, get_theme
from ttobak.game.titles import rank_medal

__all__ = [
    "gave_up","build_share_text", "BADGES", "tier_badge"]

#: 누적 판수에 따라 붙는 배지. 오래 한 사람이 티가 나면 계속하게 된다.
#: (최소 판수, 배지) 를 큰 것부터 적어 두고 처음 걸리는 것을 쓴다.
BADGES: tuple[tuple[int, str], ...] = (
    (500, "👑"),
    (200, "🏆"),
    (100, "🌟"),
    (50, "🌳"),
    (10, "🌿"),
    (0, "🌱"),
)

#: 연속 성공을 자랑할 최소 횟수. 2연속부터는 자랑할 만하다.
_STREAK_THRESHOLD = 2


def tier_badge(played: int) -> str:
    """누적 판수에 맞는 배지 하나를 돌려준다."""
    for threshold, badge in BADGES:
        if played >= threshold:
            return badge
    return BADGES[-1][1]


def gave_up(status: str, attempts: int, max_attempts: int) -> bool:
    """졌는데 **기회가 남아 있었다면** 포기한 것이다.

    상태값을 따로 두지 않고 이렇게 판정한다. 정상적으로 진 판은 기회를 전부
    쓴 뒤에만 끝나므로, 남은 기회가 있는 패배는 포기밖에 없다. 스키마를
    건드리지 않고도 정확히 갈린다.

    구분해서 적는 이유: 여섯 번 다 틀린 것과 두 번 만에 손 든 것이 똑같이
    ``X/6`` 으로 보이면 공유 문구가 사실을 흐린다. 포기가 부끄러운 일은
    아니지만, 아닌 척할 일도 아니다.
    """
    return status == "lost" and 0 < attempts < max_attempts


def _grid(marks_per_row: list[list[str]], theme: ShareTheme) -> str:
    """채점 결과를 그림 격자로 바꾼다."""
    return "\n".join(
        "".join(theme.square(Mark(mark)) for mark in row) for row in marks_per_row
    )


def _headline(
    status: str,
    attempts: int,
    max_attempts: int,
    hints_used: int,
    theme: ShareTheme,
    difficulty: str = "normal",
) -> str:
    """첫 줄. 결과를 한눈에 보여 준다. 테마 그림으로 시작해 눈에 띄게 한다."""
    if status == "won":
        head = f"{theme.correct} 또박 {attempts}/{max_attempts}"
    elif gave_up(status, attempts, max_attempts):
        head = f"{theme.absent} 또박 🏳️ {attempts}/{max_attempts}"
    else:
        head = f"{theme.absent} 또박 X/{max_attempts}"
    # 난이도 표시. 서버가 규칙을 강제했을 때만 붙으므로 자랑해도 된다.
    badge = get_difficulty(difficulty).emoji
    if badge:
        head += f" {badge}"
    if hints_used > 0:
        head += f" 💡{hints_used}"
    return head


def _context(nickname: str, played_on: date, round_no: int, length: int) -> str:
    """누가, 언제, 몇 번째 문제를, 몇 칸으로 풀었는지."""
    stamp = f"{played_on.year}.{played_on.month:02d}.{played_on.day:02d}"
    return f"{nickname} · {stamp} · {round_no + 1}번째 · {length}칸"


def _record(
    played: int,
    win_rate: float,
    average_attempts: float | None,
    current_streak: int,
) -> str:
    """누적 기록 한 줄. 값이 없는 항목은 통째로 뺀다."""
    pieces = [f"{tier_badge(played)} {played}판", f"승률 {round(win_rate * 100)}%"]
    if average_attempts is not None:
        pieces.append(f"평균 {average_attempts:.1f}번")
    if current_streak >= _STREAK_THRESHOLD:
        pieces.append(f"🔥 {current_streak}연속")
    return " · ".join(pieces)


def build_share_text(
    *,
    nickname: str,
    played_on: date,
    round_no: int,
    status: str,
    max_attempts: int,
    marks_per_row: list[list[str]],
    played: int,
    win_rate: float,
    average_attempts: float | None,
    current_streak: int = 0,
    hints_used: int = 0,
    theme_key: str | None = None,
    url: str | None = None,
    difficulty: str = "normal",
) -> str:
    """공유용 문구를 만든다.

    :param nickname: 화면에 쓰는 닉네임. 여러 명이 같은 방에 올리면 누구 결과인지
        구분되어야 한다. 참가할 때 한글, 영문, 숫자, 공백만 통과시키므로 여기서
        따로 씻어 낼 것은 없다.
    :param status: ``won`` 이면 성공, 그 밖은 실패로 적는다.
    :param marks_per_row: 줄마다 칸별 채점 결과 문자열 목록.
    :param current_streak: 연속 성공 횟수. 2 이상일 때만 적는다.
    :param hints_used: 이 판에서 쓴 힌트 수. 0보다 크면 결과에 표시한다.
        도움을 받고도 안 받은 척하면 기록 비교가 의미를 잃는다.
    :param theme_key: 격자를 그릴 테마. 모르는 이름이면 기본 테마로 돌아간다.
    :param url: 붙여 넣을 접속 주소. 없으면 생략한다.
    :raises ValueError: 아직 끝나지 않은 판을 공유하려 할 때.
    """
    if status == "playing":
        raise ValueError("아직 진행 중인 판은 공유할 수 없습니다.")
    if not marks_per_row:
        raise ValueError("추측이 하나도 없는 판은 공유할 수 없습니다.")

    theme = get_theme(theme_key)
    length = len(marks_per_row[0])
    parts = [
        _headline(
            status, len(marks_per_row), max_attempts, hints_used, theme, difficulty
        ),
        _context(nickname, played_on, round_no, length),
        "",
        _grid(marks_per_row, theme),
        "",
        _record(played, win_rate, average_attempts, current_streak),
    ]
    if url:
        parts.append(f"👉 {url}")

    return "\n".join(parts)


def build_daily_share_text(
    *,
    nickname: str,
    room_name: str,
    played_on: date,
    status: str,
    max_attempts: int,
    marks_per_row: list[list[str]],
    rank: int,
    total: int,
    solved: int,
    theme_key: str | None = None,
    url: str | None = None,
) -> str:
    """방의 오늘의 문제 결과를 공유용 문구로 만든다.

    :raises ValueError: 아직 끝나지 않은 판을 공유하려 할 때.

    일반 게임 공유와 **일부러 다르게** 적는다. 그쪽은 "나 오늘 몇 판 했다"
    라는 개인 기록이지만, 이쪽은 **같은 문제를 푼 사람들 사이의 자리**다.
    그래서 승률 대신 등수를 적고, 링크에 방 코드를 실어 받은 사람이 같은
    방으로 바로 들어오게 한다.

    **링크에 방 코드가 들어간다는 뜻은 이 문구를 받은 사람은 누구나 그 방에
    들어올 수 있다는 뜻이다.** 초대 링크와 같은 성질이므로, 아무 데나 올리면
    모르는 사람이 들어온다. 친구 대화방에 올리는 것을 전제로 한 기능이다.
    """
    if status == "playing":
        raise ValueError("아직 진행 중인 판은 공유할 수 없습니다.")
    if not marks_per_row:
        raise ValueError("추측이 하나도 없는 판은 공유할 수 없습니다.")

    theme = get_theme(theme_key)
    attempts = len(marks_per_row)
    if status == "won":
        score = f"{attempts}/{max_attempts}"
    elif gave_up(status, attempts, max_attempts):
        score = f"🏳️ {attempts}/{max_attempts}"
    else:
        score = f"X/{max_attempts}"

    lines = [
        f"{theme.correct} 또박 · {room_name}",
        f"{nickname} · {played_on:%Y.%m.%d} · {score}",
        "",
        _grid(marks_per_row, theme),
        "",
    ]

    # 등수는 맞힌 사람만 의미가 있다. 못 맞힌 사람에게 "5명 중 5등" 을 보여
    # 주는 것은 알려 주는 것이 아니라 놀리는 것이다.
    if status == "won" and rank > 0:
        medal = rank_medal(rank)
        place = f"{medal} " if medal else ""
        lines.append(f"{place}{total}명 중 {rank}등")
    else:
        lines.append(f"오늘 {solved}/{total}명이 맞혔어요")

    if url:
        lines.append(f"👉 {url}")

    return "\n".join(lines)
