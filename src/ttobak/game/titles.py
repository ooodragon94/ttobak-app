"""리더보드 칭호.

등수만 있으면 1등 말고는 볼 이유가 없다. 그래서 **각자 잘한 구석을 하나씩**
찾아 이름을 붙인다. 오늘 가장 많이 푼 사람, 가장 적은 시도로 맞힌 사람,
한 번에 맞힌 사람처럼 기준이 여럿이면 아래쪽 사람도 가져갈 것이 생긴다.

한 사람이 여러 칭호를 독식하지 않게, 위에서부터 훑으며 **아직 칭호가 없는
사람에게만** 준다. 그래야 이름표가 골고루 퍼진다.

입출력이 없는 순수 함수라 그대로 단위 테스트할 수 있다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ttobak.db import LeaderboardEntry

__all__ = ["Title", "TITLE_RULES", "assign_titles", "rank_medal"]

#: 1~3등에 붙는 메달. 그 아래는 숫자로만 표시한다.
_MEDALS = ("🥇", "🥈", "🥉")

#: 칭호를 주기 위한 최소 표본. 한 판 풀고 "정확도" 칭호를 가져가면 시시하다.
_MIN_SOLVED_FOR_ACCURACY = 2


@dataclass(frozen=True)
class Title:
    """칭호 하나의 정의."""

    key: str
    label: str
    emoji: str
    #: 이 칭호의 후보인지 판정한다.
    eligible: Callable[[LeaderboardEntry], bool]
    #: 후보 중 누가 가져갈지 정하는 정렬 기준. 작을수록 먼저다.
    rank_by: Callable[[LeaderboardEntry], tuple]


def _has_solved(entry: LeaderboardEntry) -> bool:
    return entry.solved > 0


#: 칭호 목록. 위에 있는 것부터 주인을 찾는다. 순서가 곧 우선순위다.
TITLE_RULES: tuple[Title, ...] = (
    Title(
        key="one_shot",
        label="한 방",
        emoji="🎯",
        # 첫 줄에 맞힌 사람. 운이든 실력이든 이건 자랑할 만하다.
        eligible=lambda e: e.best_attempts == 1,
        rank_by=lambda e: (-e.solved,),
    ),
    Title(
        key="grinder",
        label="다작왕",
        emoji="🔥",
        eligible=lambda e: e.solved >= 3,
        rank_by=lambda e: (-e.solved,),
    ),
    Title(
        key="sniper",
        label="저격수",
        emoji="🏹",
        # 적은 시도로 꾸준히 맞힌 사람.
        eligible=lambda e: (
            e.solved >= _MIN_SOLVED_FOR_ACCURACY and e.average_attempts is not None
        ),
        rank_by=lambda e: (e.average_attempts or 99,),
    ),
    Title(
        key="steady",
        label="개근",
        emoji="🌱",
        # 많이 붙어 있었던 사람. 성적과 무관하게 참여를 알아준다.
        eligible=lambda e: e.played >= 3,
        rank_by=lambda e: (-e.played,),
    ),
    Title(
        key="clutch",
        label="벼랑 끝",
        emoji="🧗",
        # 마지막 기회에 맞힌 사람. 졸였다가 살아난 이야기는 늘 재밌다.
        eligible=lambda e: e.best_attempts is not None and e.best_attempts >= 6,
        rank_by=lambda e: (-(e.best_attempts or 0),),
    ),
    Title(
        key="marathon",
        label="장문가",
        emoji="📏",
        # 많이 풀었는데 시도도 많이 쓴 사람. 오래 붙잡고 있었다는 뜻이다.
        eligible=lambda e: (
            e.solved >= 2 and e.average_attempts is not None and e.average_attempts >= 4
        ),
        rank_by=lambda e: (-(e.average_attempts or 0),),
    ),
    Title(
        key="first_blood",
        label="첫 정답",
        emoji="⚡",
        eligible=_has_solved,
        rank_by=lambda e: (e.average_attempts or 99,),
    ),
    # --- 여기부터는 **못 맞힌 사람들 몫** ---
    #
    # 순위표에 아무것도 없는 줄이 있으면 그 사람은 다음에 안 들어온다.
    # 놀리는 것과 알아주는 것 사이가 중요해서, 문구는 전부 "그래도 왔다" 는
    # 쪽으로 적었다. 비웃는 말은 하나도 안 넣었다.
    Title(
        key="so_close",
        label="아까비",
        emoji="😩",
        # 여러 판 했는데 하나도 못 맞힌 사람. 제일 억울한 자리다.
        eligible=lambda e: e.solved == 0 and e.played >= 3,
        rank_by=lambda e: (-e.played,),
    ),
    Title(
        key="explorer",
        label="탐험가",
        emoji="🧭",
        # 못 맞혔어도 두 판 이상 시도한 사람.
        eligible=lambda e: e.solved == 0 and e.played >= 2,
        rank_by=lambda e: (-e.played,),
    ),
    Title(
        key="brave",
        label="용기상",
        emoji="🫡",
        # 한 판 하고 못 맞힌 사람. 그래도 온 것을 알아준다.
        eligible=lambda e: e.solved == 0 and e.played >= 1,
        rank_by=lambda e: (-e.played,),
    ),
    Title(
        key="showed_up",
        label="출석",
        emoji="🚪",
        # 마지막 그물. 위 어디에도 안 걸린 사람은 여기서 받는다.
        # **빈 줄을 만들지 않는 것**이 이 칭호의 유일한 목적이다.
        #
        # 그래도 한 판은 해야 한다. 아무것도 안 한 사람에게 "출석" 을 주면
        # 그 말이 거짓이 되고, 칭호 전체가 가벼워진다.
        eligible=lambda e: e.played >= 1,
        rank_by=lambda e: (-e.played,),
    ),
)


def rank_medal(rank: int) -> str:
    """등수에 붙는 메달. 4등부터는 빈 문자열."""
    return _MEDALS[rank - 1] if 1 <= rank <= len(_MEDALS) else ""


def assign_titles(entries: Sequence[LeaderboardEntry]) -> dict[str, Title]:
    """참가자마다 칭호를 하나씩 배정한다.

    :returns: 표시 이름 -> 칭호. 칭호를 못 받은 사람은 빠진다.
    """
    taken: dict[str, Title] = {}
    for rule in TITLE_RULES:
        candidates = [
            entry
            for entry in entries
            if entry.display_name not in taken and rule.eligible(entry)
        ]
        if not candidates:
            continue
        winner = min(candidates, key=rule.rank_by)
        taken[winner.display_name] = rule
    return taken
