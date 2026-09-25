"""라운드별 문제 선정.

플레이어는 한 문제를 끝내면 바로 다음 문제를 받는다. 하루 한 문제가 아니라
사람마다 자기 순서대로 계속 이어지는 방식이다.

난수는 저장하지 않는다. ``(소금값, 플레이어, 라운드 번호)``만으로 시드를 만들기
때문에, 서버를 재시작하거나 DB가 지워져도 같은 사람의 같은 라운드에서는 항상
같은 문제가 나온다. 진행 중이던 판을 새로고침해도 문제가 바뀌지 않는다는 뜻이다.

선정은 두 층으로 나뉜다.

**글자 수** 는 '주기(cycle)'로 고른다. 길이 후보가 5, 6, 7 세 개라면 세 라운드가
한 주기이고, 한 주기 안에서 각 길이가 정확히 한 번씩 나온다. 순서는 주기마다
새로 섞인다. 매번 독립적으로 뽑으면 5가 내리 네 번 나오는 일이 생기는데, 이
방식은 그런 쏠림 없이도 순서를 예측할 수 없게 만든다.

**단어** 는 길이별 사전을 한 번 섞어 놓고 앞에서부터 소진한다. 그래서 사전을 한
바퀴 돌기 전에는 같은 단어가 다시 나오지 않는다. 다 쓰면 다시 섞어 새 바퀴를
시작한다.

플레이어 식별자가 시드에 들어가므로 사람마다 출제 순서가 다르다. 옆 사람 답을
보고 맞히는 일이 생기지 않는다.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from ttobak.hangul import decompose
from ttobak.words import Lexicon

__all__ = ["Puzzle", "puzzle_for_round", "puzzle_for_day"]


@dataclass(frozen=True)
class Puzzle:
    """한 라운드의 정답과 그 형태."""

    round_no: int
    #: 정답 단어. 판이 끝나기 전에는 클라이언트로 보내지 않는다.
    answer: str
    #: 정답을 분해한 자모. 게임판의 칸 수가 곧 이 길이다.
    jamos: tuple[str, ...]

    @property
    def length(self) -> int:
        return len(self.jamos)

    @property
    def jamo_key(self) -> str:
        return "".join(self.jamos)


def _seeded_shuffle(items: list, *seed_parts: object) -> list:
    """``seed_parts``로 시드를 고정해 ``items``를 섞은 새 리스트를 돌려준다.

    ``hash()``를 쓰지 않는 이유는 파이썬의 문자열 해시가 프로세스마다 달라지기
    때문이다. 재시작해도 같은 결과를 얻으려면 sha256처럼 고정된 해시가 필요하다.
    """
    digest = hashlib.sha256("|".join(map(str, seed_parts)).encode("utf-8")).digest()
    shuffled = list(items)
    random.Random(digest).shuffle(shuffled)
    return shuffled


def puzzle_for_round(
    player_id: str,
    round_no: int,
    lexicon: Lexicon,
    *,
    lengths: tuple[int, ...] | None = None,
    salt: str = "ttobak-v1",
) -> Puzzle:
    """``player_id``의 ``round_no``번째 문제를 결정론적으로 계산한다.

    :param round_no: 0부터 시작하는 라운드 번호.
    :param lengths: 쓸 자모 길이 후보. 생략하면 사전에 있는 길이를 모두 쓴다.
    :param salt: 출제 순서를 결정하는 시드 문자열.
    :raises ValueError: 라운드 번호가 음수이거나 길이 후보가 비었을 때.
    """
    if round_no < 0:
        raise ValueError(f"라운드 번호는 0 이상이어야 합니다: {round_no}")

    # `or`를 쓰면 빈 튜플이 조용히 사전 전체로 대체된다. None만 기본값으로 본다.
    candidates = tuple(sorted(lexicon.lengths if lengths is None else lengths))
    if not candidates:
        raise ValueError("사용할 자모 길이 후보가 없습니다.")

    cycle, position = divmod(round_no, len(candidates))

    length_order = _seeded_shuffle(list(candidates), salt, "length", player_id, cycle)
    length = length_order[position]

    words = lexicon.for_length(length).words
    lap, index = divmod(cycle, len(words))
    word_order = _seeded_shuffle(list(words), salt, "word", player_id, length, lap)
    answer = word_order[index]

    return Puzzle(round_no=round_no, answer=answer, jamos=tuple(decompose(answer)))


#: 하루에 내는 오늘의 문제 수.
#:
#: 하나면 "3번에 맞췄다" 로 대화가 끝난다. 둘이면 "첫 번째는 쉬웠는데 두
#: 번째에서 막혔어" 가 되고, 그 차이가 방을 살아 있게 만든다. 이 기능은
#: 난이도가 아니라 **할 말을 만드는 것**이 목적이다.
#:
#: 셋 이상은 안 둔다. 하루에 풀 분량이 숙제처럼 느껴지는 순간 안 하게 된다.
DAILY_SLOTS = 2


def daily_lengths(slot: int, lengths: tuple[int, ...]) -> tuple[int, ...]:
    """``slot`` 번째 오늘의 문제에 쓸 길이 후보.

    - **첫 문제는 가장 짧은 길이로 고정한다**(보통 5자모).
    - 두 번째는 그 위에서 뽑되 **가장 긴 길이는 뺀다**(보통 6~7자모).

    왜 이렇게 정했나
    ----------------

    길이를 매일 무작위로 두었더니 첫 문제가 8자모로 나오는 날이 있었다.
    아침에 열자마자 여덟 칸을 마주하면 "오늘은 패스" 가 된다. 매일 같은
    자리에서 시작하는 편이 습관이 붙고, 그게 이 기능이 노리는 것이다.

    두 번째에서 가장 긴 길이를 빼는 이유도 같다. 둘 다 풀어야 하루치가
    끝나는데 두 번째가 매번 최대 난이도면 대부분 첫 문제만 풀고 만다.
    하나는 가볍게, 하나는 조금 더 — 그 정도가 매일 할 만하다.

    길이 후보가 하나뿐인 서버에서는 둘 다 그 길이를 쓴다.
    """
    ordered = tuple(sorted(lengths))
    if len(ordered) <= 1:
        return ordered
    if slot <= 0:
        return ordered[:1]
    # 가장 짧은 것과 가장 긴 것을 뺀 가운데. 셋 미만이면 뺄 것이 없으므로
    # 남은 것을 그대로 쓴다.
    middle = ordered[1:-1]
    return middle or ordered[1:]


def puzzle_for_day(
    scope: str,
    day: str,
    lexicon: Lexicon,
    *,
    lengths: tuple[int, ...] | None = None,
    salt: str = "ttobak-daily-v1",
    slot: int = 0,
) -> Puzzle:
    """``scope``에서 ``day``에 모두가 함께 푸는 문제.

    :func:`puzzle_for_round`와 결정적으로 다른 점은 **사람이 시드에 안 들어간다**
    는 것이다. 같은 방의 같은 날이면 누구에게나 같은 단어가 나온다.

    그게 이 기능의 존재 이유다. 사람마다 다른 문제를 풀면 "난 세 번 만에
    맞췄다"가 아무 의미가 없다. 시도 횟수를 비교할 수도, 풀이 과정을 보여 줄
    수도, "와 이걸 푸네"라고 말할 수도 없다. 카카오의 오늘의 단어가 이야깃거리가
    되는 이유는 난이도가 아니라 **모두가 같은 문제를 풀기 때문**이다.

    :param scope: 방 코드. 방마다 다른 문제가 나온다. 한 사람이 여러 방에
        속해도 각 방에서 각각 한 판씩 풀 수 있다.
    :param day: ``YYYY-MM-DD`` (한국 시간 기준). 문자열 그대로 시드에 들어간다.
    :param salt: :func:`puzzle_for_round`와 다른 값을 기본으로 둔다. 같은 값을
        쓰면 어떤 사람의 일반 라운드와 오늘의 문제가 같은 단어로 겹칠 수 있다.

    :param slot: 그날 몇 번째 문제인가. 시드에 들어가므로 슬롯마다 다른 단어가
        나온다. 이 값을 빼면 두 문제가 같은 단어가 된다.

    :raises ValueError: 길이 후보가 비었을 때.

    날짜별로 독립적으로 뽑으므로 같은 단어가 며칠 뒤 또 나올 수 있다. 사전이
    수백 개라 실제로는 드물고, 라운드 방식처럼 '소진'을 관리하려면 방마다
    상태를 들고 있어야 해서 그 복잡도를 지불할 값이 없다고 봤다.
    """
    candidates = tuple(sorted(lexicon.lengths if lengths is None else lengths))
    if not candidates:
        raise ValueError("사용할 자모 길이 후보가 없습니다.")

    length_order = _seeded_shuffle(
        list(candidates), salt, "length", scope, day, slot
    )
    length = length_order[0]

    words = lexicon.for_length(length).words
    word_order = _seeded_shuffle(
        list(words), salt, "word", scope, day, length, slot
    )
    answer = word_order[0]

    # round_no 자리에 슬롯 번호를 담는다. 오늘의 문제에는 라운드가 없고,
    # 화면과 저장소가 "그날 몇 번째 문제인가" 를 알아야 한다.
    return Puzzle(round_no=slot, answer=answer, jamos=tuple(decompose(answer)))
