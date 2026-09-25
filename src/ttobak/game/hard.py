"""난이도 — 밝혀진 단서를 얼마나 강제할 것인가.

왜 "시도 횟수를 줄이는 것" 이 난이도가 아닌가
----------------------------------------------

기회를 줄이는 것은 **어려운 설정**이지 다른 게임이 아니다. 8칸을 4번에
맞히는 것은 실력이라기보다 운이고, 그걸로 자랑하면 받는 쪽도 시큰둥하다.

진짜로 다른 것은 **전략을 막는 것**이다. 지금은 단서를 무시하고 아직 안 나온
자모만 잔뜩 넣어 정보를 캐는 수가 있다. 5번째 줄에서 처음으로 진짜 후보를
쓰는 식이다. 그게 사실 가장 효율적인 풀이인데 재미는 없다.

세 단계로 나눈 이유
-------------------

규칙이 둘인데 **조이는 정도가 다르다.**

- **자리 고정**(초록은 그대로)은 이미 아는 것을 유지하라는 것뿐이라 부담이
  적다. 남은 칸은 여전히 마음대로 쓸 수 있다.
- **자모 필수**(노랑은 반드시 포함)가 훨씬 세다. 노랑이 셋이면 다섯 칸 중
  셋이 정해져 버려서 탐색할 자리가 거의 없다.

그래서 하나씩 켤 수 있게 나눴다. 둘 다 켜면 **매 추측이 지금까지 나온 단서를
전부 만족하는 진짜 후보**여야 한다. 이 계열 게임에서 흔히 하드 모드라고 부르는
상태가 그것이다.

서버가 강제해야 하는 이유
-------------------------

공유 문구에 난이도 표시가 붙기 때문이다. 화면에서만 막으면 아무나 그 표시를
달 수 있고, 그러면 표시 자체가 무의미해진다. 그래서 판정은 전부 서버에서 하고,
어느 난이도였는지도 **판을 열 때 박아 둔다** — 다 풀고 나서 설정을 켜서
자랑하는 것을 막기 위해서다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ttobak.game.rules import Mark, score_guess

__all__ = [
    "DIFFICULTIES",
    "Difficulty",
    "HardModeError",
    "check_difficulty",
    "get_difficulty",
    "relaxes",
]


class HardModeError(Exception):
    """난이도 규칙을 어긴 추측. 사람이 읽을 문구를 담는다."""


@dataclass(frozen=True)
class Difficulty:
    """난이도 하나."""

    key: str
    label: str
    emoji: str
    #: 한 줄 설명. 설정 화면과 첫 안내에 그대로 쓴다.
    note: str
    #: 초록으로 맞힌 자리를 그대로 둬야 하는가.
    keep_correct: bool = False
    #: 노랑으로 나온 자모를 반드시 넣어야 하는가.
    require_present: bool = False

    @property
    def restricted(self) -> bool:
        """기본 난이도가 아닌가. 힌트를 막을지 판단하는 데 쓴다."""
        return self.keep_correct or self.require_present


#: 고를 수 있는 난이도. 순서가 곧 강도다.
#:
#: 힌트는 기본 난이도에서만 쓸 수 있다. 나머지의 값어치는 "아무 도움 없이
#: 풀었다" 는 데 있어서, 힌트를 허용하면 표시가 의미를 잃는다.
DIFFICULTIES: tuple[Difficulty, ...] = (
    Difficulty(
        key="normal",
        label="보통",
        emoji="",
        note="자유롭게 풀어요. 힌트도 쓸 수 있어요.",
    ),
    Difficulty(
        key="hard",
        label="하드",
        emoji="🔒",
        note="맞힌 자리는 그대로 둬야 해요.",
        keep_correct=True,
    ),
    Difficulty(
        key="hell",
        label="헬",
        # 🔥 는 쓸 수 없다. 공유 문구에서 이미 **연속 성공**을 뜻한다
        # ("🔥 5연속"). 같은 그림이 두 뜻을 가지면 자랑이 안 통한다.
        emoji="😈",
        note="나온 자모는 반드시 넣어야 해요.",
        require_present=True,
    ),
    Difficulty(
        key="buldak",
        label="불닭",
        emoji="🌶️",
        note="둘 다. 매 추측이 진짜 후보여야 해요.",
        keep_correct=True,
        require_present=True,
    ),
)

_BY_KEY = {d.key: d for d in DIFFICULTIES}


def get_difficulty(key: str | None) -> Difficulty:
    """열쇠로 난이도를 찾는다. 모르는 값이면 기본 난이도.

    모르는 값에 예외를 던지지 않는 이유: 나중에 난이도를 지우거나 이름을
    바꿨을 때, 그 값을 저장해 둔 사람의 게임이 통째로 안 열리면 안 된다.
    """
    return _BY_KEY.get(key or "", DIFFICULTIES[0])


def check_difficulty(
    difficulty: Difficulty,
    guess: tuple[str, ...],
    previous: list[tuple[str, ...]],
    answer: tuple[str, ...],
) -> None:
    """난이도 규칙을 어겼으면 예외를 던진다.

    :param guess: 이번에 낸 추측(자모 목록).
    :param previous: 지금까지 낸 추측들.
    :param answer: 정답. 이전 추측을 다시 채점하는 데만 쓴다.
    :raises HardModeError: 규칙을 어겼을 때.

    노랑의 **자리** 는 어느 난이도에서도 강제하지 않는다. 노랑은 "여기는
    아니다" 라는 뜻이라 어디로 가야 할지는 여전히 모르는 상태이고, 자리까지
    강제하면 풀 수 없는 판이 생긴다.
    """
    if not difficulty.restricted or not previous:
        return

    # 초록으로 확정된 자리들.
    fixed: dict[int, str] = {}
    # 지금까지 확인된 "이 자모가 최소 몇 개는 있다".
    required: dict[str, int] = {}

    for past in previous:
        marks = score_guess(past, answer)
        counts: dict[str, int] = {}
        for index, (jamo, mark) in enumerate(zip(past, marks, strict=True)):
            if mark is Mark.CORRECT:
                fixed[index] = jamo
            if mark in (Mark.CORRECT, Mark.PRESENT):
                counts[jamo] = counts.get(jamo, 0) + 1
        # 여러 줄에 걸쳐 얻은 정보는 **가장 많이 본 쪽**이 맞다.
        for jamo, count in counts.items():
            required[jamo] = max(required.get(jamo, 0), count)

    if difficulty.keep_correct:
        for index, jamo in sorted(fixed.items()):
            if index >= len(guess) or guess[index] != jamo:
                raise HardModeError(
                    f"{index + 1}번째 칸은 '{jamo}' 로 맞혔어요. 그대로 두세요."
                )

    if difficulty.require_present:
        for jamo, count in required.items():
            if guess.count(jamo) < count:
                more = "" if count == 1 else f" {count}개"
                raise HardModeError(f"'{jamo}'{more}를 꼭 넣어야 해요.")


def relaxes(new: Difficulty, old: Difficulty) -> bool:
    """``new`` 가 ``old`` 보다 **느슨하기만** 한가.

    규칙을 하나도 더하지 않으면 참이다. 불닭 → 보통, 불닭 → 하드가 여기
    해당하고, 하드 → 헬은 아니다(자리 고정을 빼는 대신 자모 필수를 더한다).

    이걸 왜 따로 재는가
    -------------------

    풀던 판의 난이도를 바꾸면 그 판을 포기로 적고 새 문제를 연다.
    **올릴 때는 그래야 한다.** 안 그러면 쉬운 규칙으로 절반을 풀어 놓고
    불닭으로 올려서 불닭으로 푼 척할 수 있다.

    그런데 같은 처분을 **내릴 때**도 하고 있었다. 그건 근거가 없다.
    느슨해지는 쪽으로는 자랑할 것이 안 생기고 — 판에 박히는 난이도도 같이
    낮아지므로 공유 문구가 정직하게 나온다 — 오히려 반대로 덫이었다.
    불닭모드는 두 규칙을 동시에 걸어서 **조건을 만족하는 낱말이 사전에
    하나도 없는 상태**가 될 수 있는데, 거기서 빠져나오려고 난이도를
    내리면 풀던 판까지 잃었다.

    실제로 그 항의를 받았다. 옛 켬/끔 시절의 하드모드가 자동으로 불닭으로
    옮겨졌기 때문에, **고른 적도 없는 난이도**에서 그 일을 당한 것이다.
    """
    return not (
        (new.keep_correct and not old.keep_correct)
        or (new.require_present and not old.require_present)
    )
