"""방 — 친구끼리만 보이는 순위표와 오늘의 문제.

전에는 순위표가 하나뿐이라 링크를 아는 사람이 전부 한 화면에 섞였다. 방을
두면 회사 사람들 방과 친구들 방을 따로 둘 수 있고, 무엇보다 **같은 방 사람은
같은 문제를 푼다**(:func:`~.rounds.puzzle_for_day`). 그래야 "난 세 번 만에
맞췄다"가 말이 된다.

보안에서 지키는 것
------------------

방 코드는 **그 자체가 열쇠**다. 링크를 아는 사람이 곧 들어올 수 있는 사람이라
로그인 절차가 없다(친구들이 못 들어오면 안 된다는 요구가 먼저다). 그래서
코드가 새거나 추측되면 그것으로 끝이다. 세 가지로 막는다.

1. **추측할 수 없게 만든다.** :func:`new_room_code` 는 암호학적 난수
   72비트를 쓴다. 순번이나 시각에서 만들지 않는다 — 그러면 옆 방 코드를
   더하고 빼서 알아낼 수 있다.
2. **없는 척한다.** 회원이 아닌 사람에게는 "권한 없음"이 아니라 "그런 방
   없음"으로 답한다. 403 은 "코드는 맞았다"는 정보를 준다.
3. **두드리는 속도를 제한한다.** 72비트를 다 훑을 수는 없지만, 참가 시도
   자체에 상한을 두면 자동화된 시도가 의미를 잃는다(웹 계층에서 건다).

크기 상한도 보안이다. 방을 무한히 만들거나 한 방에 무한히 들어올 수 있으면
디스크와 화면을 채워 서비스를 못 쓰게 만들 수 있다.
"""

from __future__ import annotations

import re
import secrets
import unicodedata

__all__ = [
    "MAX_MEMBERS",
    "MAX_ROOMS_PER_PLAYER",
    "ROOM_CODE_LENGTH",
    "RoomError",
    "clean_room_name",
    "is_valid_room_code",
    "new_room_code",
    "new_room_salt",
]

#: 방 코드에 쓸 글자.
#:
#: 헷갈리는 글자(0/O, 1/l/I)를 뺐다. 코드는 카톡으로 옮겨 적히거나 말로
#: 불러 주게 되는데, 그때 "영이야 오야?"를 묻게 만들면 안 된다.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

#: 코드 길이. 31글자 알파벳 14자리면 약 69비트다.
#:
#: 이 숫자가 곧 보안 강도다. 초당 백만 번을 물어봐도 평균 1조 년이 걸린다.
#: 짧게 만들고 싶은 유혹이 있지만(옮겨 적기 편하니까), 코드는 링크에 담겨
#: 전달되므로 사람이 외울 필요가 없다. 편의를 위해 강도를 깎을 이유가 없다.
ROOM_CODE_LENGTH = 14

#: 한 방의 최대 인원.
#:
#: 친구들끼리 쓰는 물건이라 이 정도면 넉넉하다. 상한이 없으면 링크가 밖으로
#: 샜을 때 수천 명이 들어와 순위표가 못 쓰게 된다.
MAX_MEMBERS = 100

#: 한 사람이 만들 수 있는 방 수. 자동화된 방 생성으로 DB 를 채우는 것을 막는다.
MAX_ROOMS_PER_PLAYER = 20

#: 방 이름 길이 상한(글자 수).
MAX_ROOM_NAME = 20

_CODE_PATTERN = re.compile(f"^[{_ALPHABET}]{{{ROOM_CODE_LENGTH}}}$")

#: 화면을 망가뜨리는 글자들. 이름과 댓글 양쪽에서 지운다.
#:
#: 제어 문자(Cc)는 눈에 안 보이면서 줄바꿈이나 커서 이동을 일으키고,
#: 서식 문자(Cf)에는 글자 방향을 뒤집는 것(U+202E)이 있어 이름을 거꾸로
#: 보이게 만들 수 있다. 둘 다 재미로 쓰기에는 남을 속이기 너무 쉽다.
_INVISIBLE = {"Cc", "Cf", "Cs", "Co", "Cn"}


class RoomError(Exception):
    """방 관련 요청이 규칙에 안 맞을 때. 사람이 읽을 문구를 담는다."""


def new_room_code() -> str:
    """추측할 수 없는 방 코드.

    ``secrets`` 를 쓴다. ``random`` 은 재현 가능한 난수라 시드를 알면 다음
    값을 계산할 수 있다 — 출제 순서를 고정하는 데는 그게 장점이지만
    열쇠를 만드는 데 쓰면 열쇠가 아니게 된다.
    """
    return "".join(secrets.choice(_ALPHABET) for _ in range(ROOM_CODE_LENGTH))


def new_room_salt() -> str:
    """방마다 다른 출제 시드.

    코드를 그대로 시드로 쓰지 않는 이유: 코드는 링크에 실려 돌아다닌다.
    그것만으로 오늘의 정답을 미리 계산할 수 있으면 안 된다. 소금값은 서버
    밖으로 나가지 않는다.
    """
    return secrets.token_hex(16)


def is_valid_room_code(code: str) -> bool:
    """형식만 본다. 존재 여부는 저장소가 답한다.

    형식 검사를 먼저 하는 이유는 DB 를 아끼려는 것이 아니라, 이상한 문자열이
    쿼리 파라미터로 들어가는 경로를 짧게 끊기 위해서다.
    """
    return bool(_CODE_PATTERN.match(code or ""))


def _strip_invisible(text: str) -> str:
    """눈에 안 보이거나 화면을 뒤집는 글자를 지운다."""
    return "".join(ch for ch in text if unicodedata.category(ch) not in _INVISIBLE)


def clean_room_name(name: str) -> str:
    """방 이름을 다듬는다.

    :raises RoomError: 다듬고 나서 아무것도 안 남으면.

    HTML 을 지우거나 바꾸지 **않는다.** 화면에서 문자열을 그대로 텍스트로만
    넣기 때문이다(``textContent``). 여기서 어설프게 태그를 지우려 들면
    "<3" 같은 멀쩡한 이름이 깨지고, 정작 우회는 막지 못한다. 이스케이프는
    출력하는 쪽에서 하는 것이 원칙이다.
    """
    cleaned = _strip_invisible(name or "")
    # 줄바꿈과 탭은 한 줄짜리 이름에 들어올 자리가 없다. 공백 하나로 접는다.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        raise RoomError("방 이름을 입력해 주세요.")
    if len(cleaned) > MAX_ROOM_NAME:
        cleaned = cleaned[:MAX_ROOM_NAME]
    return cleaned
