"""게임이 쓰는 시간 기준.

웹 계층과 게임 계층이 **같은 기준**으로 하루를 나눠야 해서 따로 둔다. 전에는
시간대가 ``web/deps.py`` 에만 있었는데, 게임 계층(``game/service.py``)도 "오늘
맞힌 수" 를 순위표와 같은 기준으로 세야 했다. 게임 계층이 웹 계층을 가져다
쓰면 의존 방향이 거꾸로라, 둘 다 여기서 가져간다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

__all__ = ["GAME_TIMEZONE", "day_bounds_utc"]

#: 하루가 바뀌는 기준 시간대. 참가자가 모두 한국에 있으므로 KST로 고정한다.
GAME_TIMEZONE = ZoneInfo("Asia/Seoul")


def day_bounds_utc(day: date) -> tuple[str, str]:
    """게임 시간대의 하루를 UTC 시각 두 개(시작은 포함, 끝은 제외)로 바꾼다.

    판을 끝낸 시각은 UTC 로 저장한다. "그날 끝낸 판" 을 고르려면 한국 시간
    자정부터 다음 자정까지를 UTC 로 바꿔 비교해야 한다. 저장된 값과 같은
    모양(ISO, 초 단위, ``+00:00``)이라 문자열로 비교해도 순서가 맞는다.
    """
    start = datetime.combine(day, time.min, tzinfo=GAME_TIMEZONE)
    end = start + timedelta(days=1)
    return start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()
