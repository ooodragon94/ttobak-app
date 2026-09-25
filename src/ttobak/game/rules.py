"""추측을 채점하고 키보드 상태를 계산하는 순수 함수들.

여기에는 입출력이 없다. 게임 규칙만 담고 있어 단위 테스트로 전부 검증된다.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from enum import StrEnum

__all__ = ["Mark", "score_guess", "keyboard_state"]


class Mark(StrEnum):
    """추측한 자모 한 칸의 채점 결과."""

    CORRECT = "correct"  # 초록: 자모와 위치가 모두 맞음
    PRESENT = "present"  # 노랑: 정답에 있지만 위치가 틀림
    ABSENT = "absent"  # 회색: 정답에 없음


#: 같은 자모에 여러 결과가 붙었을 때 키보드에 남길 우선순위 (높을수록 우선).
_MARK_PRIORITY = {Mark.ABSENT: 0, Mark.PRESENT: 1, Mark.CORRECT: 2}


def score_guess(guess: Sequence[str], answer: Sequence[str]) -> list[Mark]:
    """``guess``를 ``answer``와 비교해 칸별 채점 결과를 돌려준다.

    이 계열 낱말 맞히기의 표준 2단계 채점을 따른다.

    1. 먼저 같은 자리에 같은 자모가 있는 칸을 모두 초록으로 확정하고, 그만큼
       정답 쪽 자모 재고를 차감한다.
    2. 남은 칸을 왼쪽부터 훑으며 재고가 남아 있는 자모에만 노랑을 준다.
       재고가 바닥나면 회색이 된다.

    이 순서 덕분에 중복 자모가 정확히 처리된다. 정답에 ``ㄱ``이 하나뿐인데
    추측에 ``ㄱ``이 둘이고 그중 하나가 제자리라면, 제자리인 쪽만 초록이 되고
    나머지는 회색이 된다. 정답에 ``ㄱ``이 둘이고 추측의 ``ㄱ`` 하나는 제자리,
    하나는 다른 자리라면 각각 초록과 노랑이 된다.

    :raises ValueError: 추측과 정답의 길이가 다를 때.
    """
    if len(guess) != len(answer):
        raise ValueError(
            f"추측 길이 {len(guess)}가 정답 길이 {len(answer)}와 다릅니다."
        )

    marks = [Mark.ABSENT] * len(guess)

    # 1단계: 자리까지 맞은 칸을 초록으로 확정한다.
    remaining = Counter(answer)
    for index, (guessed, expected) in enumerate(zip(guess, answer, strict=True)):
        if guessed == expected:
            marks[index] = Mark.CORRECT
            remaining[guessed] -= 1

    # 2단계: 초록이 쓰고 남은 재고만큼 노랑을 나눠 준다.
    for index, guessed in enumerate(guess):
        if marks[index] is Mark.CORRECT:
            continue
        if remaining[guessed] > 0:
            marks[index] = Mark.PRESENT
            remaining[guessed] -= 1

    return marks


def keyboard_state(
    guesses: Sequence[Sequence[str]],
    marks_per_guess: Sequence[Sequence[Mark]],
) -> dict[str, Mark]:
    """지금까지의 추측을 합쳐 자모별 키보드 색을 계산한다.

    한 자모가 여러 결과를 받았다면 가장 좋은 결과를 남긴다. 초록이 노랑을,
    노랑이 회색을 덮어쓴다. 한 번 초록이었던 키가 뒤 추측 때문에 회색으로
    되돌아가는 일은 없다.
    """
    state: dict[str, Mark] = {}
    for guess, marks in zip(guesses, marks_per_guess, strict=True):
        for jamo, mark in zip(guess, marks, strict=True):
            current = state.get(jamo)
            if current is None or _MARK_PRIORITY[mark] > _MARK_PRIORITY[current]:
                state[jamo] = mark
    return state
