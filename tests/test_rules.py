"""채점 규칙 테스트.

중복 자모 처리가 이 게임에서 가장 틀리기 쉬운 부분이라 집중적으로 검증한다.
"""

from __future__ import annotations

import pytest

from ttobak.game.rules import Mark, keyboard_state, score_guess

CORRECT, PRESENT, ABSENT = Mark.CORRECT, Mark.PRESENT, Mark.ABSENT


def marks(pattern: str) -> list[Mark]:
    """``"GYX"`` 같은 축약 표기를 ``Mark`` 리스트로 바꾼다."""
    table = {"G": CORRECT, "Y": PRESENT, "X": ABSENT}
    return [table[char] for char in pattern]


def test_모두_맞으면_전부_초록():
    answer = list("ㄱㅗㅇㅑㅇㅇㅣ")
    assert score_guess(answer, answer) == marks("GGGGGGG")


def test_자리만_틀린_자모는_노랑():
    assert score_guess(list("ㅏㄱ"), list("ㄱㅏ")) == marks("YY")


def test_정답에_없는_자모는_회색():
    assert score_guess(list("ㄴㅜ"), list("ㄱㅏ")) == marks("XX")


def test_중복_자모_하나는_초록_하나는_노랑():
    """정답에 ㄱ이 둘이고 추측의 ㄱ 하나만 제자리라면 나머지는 노랑이 된다."""
    answer = list("ㄱㅏㄱㅜ")  # ㄱ 두 개
    guess = list("ㄱㅜㅏㄱ")  # 0번 ㄱ은 제자리, 3번 ㄱ은 자리가 틀림
    assert score_guess(guess, answer) == marks("GYYY")


def test_정답보다_많이_적은_중복은_회색():
    """정답의 ㄱ이 하나뿐이면, 추측의 ㄱ 둘 중 하나만 색이 붙는다."""
    answer = list("ㄱㅏㄴㅜ")  # ㄱ 한 개
    guess = list("ㄱㅏㄱㅜ")  # ㄱ 두 개, 앞쪽이 제자리
    assert score_guess(guess, answer) == marks("GGXG")


def test_제자리_중복이_노랑보다_먼저_배정된다():
    """앞쪽 ㄱ이 자리가 틀리고 뒤쪽 ㄱ이 제자리면, 초록이 재고를 먼저 가져간다."""
    answer = list("ㅏㅏㄱ")  # ㄱ 한 개, 마지막 자리
    guess = list("ㄱㅏㄱ")  # 0번은 자리 틀림, 2번은 제자리
    assert score_guess(guess, answer) == marks("XGG")


def test_길이가_다르면_예외():
    with pytest.raises(ValueError):
        score_guess(list("ㄱㅏ"), list("ㄱㅏㄴ"))


def test_키보드는_가장_좋은_결과를_남긴다():
    """뒤에 회색이 나와도 앞서 받은 초록이 지워지지 않는다."""
    guesses = [list("ㄱㅏ"), list("ㄱㅜ")]
    scored = [marks("GY"), marks("GX")]
    assert keyboard_state(guesses, scored) == {
        "ㄱ": CORRECT,
        "ㅏ": PRESENT,
        "ㅜ": ABSENT,
    }


def test_키보드는_노랑을_초록으로_승격한다():
    guesses = [list("ㅏㄱ"), list("ㄱㅏ")]
    scored = [marks("YY"), marks("GG")]
    assert keyboard_state(guesses, scored) == {"ㄱ": CORRECT, "ㅏ": CORRECT}
