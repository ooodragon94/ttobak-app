"""오늘의 문제에 남기는 한 줄.

"와 이걸 푸네" 같은 말을 같은 방 사람들끼리 주고받게 하는 것이 목적이다.
찌르기(알림만 보내는 것)보다 이쪽이 나은 이유는 **남길 것이 생기기 때문**이다.
크리스마스 트리에 글을 남기던 것과 같은 종류의 재미다.

푼 사람만 쓰고, 푼 사람만 본다
------------------------------

이게 이 기능에서 가장 중요한 규칙이고, 재미보다 먼저다.

아직 못 푼 사람에게 댓글을 보여 주면 **"ㄱ으로 시작함"** 한 줄로 그날 문제가
끝난다. 악의가 없어도 그렇게 된다 — "받침이 어려웠다"만 해도 힌트다. 그래서
막을 방법이 규칙밖에 없다. 문구를 검사해서 걸러내는 것은 불가능하다(어떤 말이
힌트인지 기계가 알 수 없다).

그래서 **오늘 그 방의 문제를 끝낸 사람에게만** 목록을 준다. 이기고 끝냈든
지고 끝냈든 상관없다. 이미 답을 아는 사람에게는 스포일러가 없다.

부수 효과로 남용도 줄어든다. 아무나 들어와서 댓글만 쏟아붓지 못하고,
쓰려면 먼저 오늘 문제를 풀어야 한다.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "MAX_COMMENTS_PER_DAY",
    "MAX_LENGTH",
    "CommentError",
    "clean_comment",
]

#: 한 줄 길이 상한(글자 수).
#:
#: 짧게 둔다. 이건 대화방이 아니라 한마디를 남기는 자리다. 길어지면 화면을
#: 차지하고, 길게 쓸수록 스포일러가 섞일 여지도 커진다.
MAX_LENGTH = 80

#: 한 사람이 하루에 한 방에 남길 수 있는 수.
#:
#: 대화를 막으려는 것이 아니라 도배를 막는 것이다. 다섯이면 주고받기에는
#: 충분하고, 화면을 채우기에는 모자라다.
MAX_COMMENTS_PER_DAY = 5

_INVISIBLE = {"Cc", "Cf", "Cs", "Co", "Cn"}


class CommentError(Exception):
    """댓글이 규칙에 안 맞을 때. 사람이 읽을 문구를 담는다."""


def clean_comment(body: str) -> str:
    """댓글을 다듬는다. 저장할 문자열을 돌려준다.

    :raises CommentError: 비었거나 규칙에 안 맞으면.

    **HTML 을 지우지 않는다.** 화면에 넣을 때 ``textContent`` 로만 넣으므로
    ``<script>`` 는 태그가 아니라 그냥 글자로 보인다. 여기서 태그를 지우려
    들면 두 가지가 나빠진다. 멀쩡한 말("a < b")이 깨지고, 어설픈 필터를
    우회하는 방법을 찾는 쪽이 이긴다. **막는 곳은 출력하는 곳 한 군데**여야
    한다.

    지우는 것은 눈에 안 보이는 글자뿐이다. 제어 문자와 서식 문자는 화면을
    망가뜨리거나(U+202E 는 글자를 거꾸로 보이게 한다) 빈 댓글을 안 빈 것처럼
    보이게 만든다.
    """
    cleaned = _strip_invisible(body or "")
    # 줄바꿈을 공백으로 접는다. 한 줄짜리 자리이고, 여러 줄을 허용하면
    # 한 사람이 화면을 통째로 차지할 수 있다.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        raise CommentError("한마디 적어 주세요.")
    if len(cleaned) > MAX_LENGTH:
        raise CommentError(f"{MAX_LENGTH}자까지 쓸 수 있어요.")
    return cleaned


def _strip_invisible(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) not in _INVISIBLE)
