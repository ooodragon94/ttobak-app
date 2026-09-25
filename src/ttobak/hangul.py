"""한글 음절과 자모(낱자) 사이의 변환.

또박 계열 게임은 단어를 두벌식 키보드의 **기본 자모 24개** 단위로 쪼개어
한 칸에 하나씩 배치한다. 예를 들어 "고마움"은 다음 7칸이 된다::

    ㄱ ㅗ ㅁ ㅏ ㅇ ㅜ ㅁ

겹자모는 키보드에 없으므로 구성 요소로 더 쪼갠다. 쌍자음 ``ㄲ``은 ``ㄱㄱ``,
겹받침 ``ㄺ``은 ``ㄹㄱ``, 복합 모음 ``ㅐ``는 ``ㅏㅣ``가 된다.
"""

from __future__ import annotations

__all__ = [
    "BASIC_JAMOS",
    "BASIC_CONSONANTS",
    "BASIC_VOWELS",
    "decompose",
    "is_basic_jamo",
    "jamo_key",
    "syllable_count",
    "syllable_readings",
]

# 유니코드 한글 음절 영역 (U+AC00 '가' ~ U+D7A3 '힣')
_SYLLABLE_BASE = 0xAC00
_SYLLABLE_LAST = 0xD7A3
_JUNGSEONG_COUNT = 21
_JONGSEONG_COUNT = 28

# 음절 코드에서 인덱스로 역참조하는 표준 자모 표
_CHOSEONGS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNGSEONGS = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONGSEONGS = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"

#: 두벌식 자판에 실제로 존재하는 기본 자음 14개.
BASIC_CONSONANTS = "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"
#: 두벌식 자판에 실제로 존재하는 기본 모음 10개.
BASIC_VOWELS = "ㅏㅑㅓㅕㅗㅛㅜㅠㅡㅣ"
#: 게임에서 한 칸에 들어갈 수 있는 자모 24개.
BASIC_JAMOS = frozenset(BASIC_CONSONANTS + BASIC_VOWELS)

# 겹자모 -> 기본 자모 분해표. 세 종류를 하나로 합쳐 둔다.
_COMPOSITE_JAMOS: dict[str, str] = {
    # 쌍자음
    "ㄲ": "ㄱㄱ",
    "ㄸ": "ㄷㄷ",
    "ㅃ": "ㅂㅂ",
    "ㅆ": "ㅅㅅ",
    "ㅉ": "ㅈㅈ",
    # 겹받침
    "ㄳ": "ㄱㅅ",
    "ㄵ": "ㄴㅈ",
    "ㄶ": "ㄴㅎ",
    "ㄺ": "ㄹㄱ",
    "ㄻ": "ㄹㅁ",
    "ㄼ": "ㄹㅂ",
    "ㄽ": "ㄹㅅ",
    "ㄾ": "ㄹㅌ",
    "ㄿ": "ㄹㅍ",
    "ㅀ": "ㄹㅎ",
    "ㅄ": "ㅂㅅ",
    # 복합 모음
    "ㅐ": "ㅏㅣ",
    "ㅒ": "ㅑㅣ",
    "ㅔ": "ㅓㅣ",
    "ㅖ": "ㅕㅣ",
    "ㅘ": "ㅗㅏ",
    "ㅙ": "ㅗㅏㅣ",
    "ㅚ": "ㅗㅣ",
    "ㅝ": "ㅜㅓ",
    "ㅞ": "ㅜㅓㅣ",
    "ㅟ": "ㅜㅣ",
    "ㅢ": "ㅡㅣ",
}


def is_basic_jamo(char: str) -> bool:
    """``char``가 두벌식 자판의 기본 자모 24개 중 하나인지 판정한다."""
    return char in BASIC_JAMOS


def _split_composite(jamo: str) -> str:
    """겹자모를 기본 자모 문자열로 펼친다. 기본 자모면 그대로 돌려준다."""
    return _COMPOSITE_JAMOS.get(jamo, jamo)


def _decompose_syllable(char: str) -> str:
    """완성형 음절 하나를 기본 자모 문자열로 분해한다."""
    offset = ord(char) - _SYLLABLE_BASE
    jongseong_index = offset % _JONGSEONG_COUNT
    jungseong_index = (offset // _JONGSEONG_COUNT) % _JUNGSEONG_COUNT
    choseong_index = offset // (_JONGSEONG_COUNT * _JUNGSEONG_COUNT)

    parts = [
        _split_composite(_CHOSEONGS[choseong_index]),
        _split_composite(_JUNGSEONGS[jungseong_index]),
    ]
    if jongseong_index:
        parts.append(_split_composite(_JONGSEONGS[jongseong_index]))
    return "".join(parts)


def decompose(text: str) -> list[str]:
    """``text``를 기본 자모 리스트로 분해한다.

    완성형 음절은 초성/중성/종성으로 쪼갠 뒤 겹자모까지 펼친다. 이미 낱자로
    적힌 자모는 그대로(겹자모라면 펼쳐서) 통과시킨다. 그 밖의 문자는 게임판에
    올릴 수 없으므로 ``ValueError``를 던진다.

    >>> decompose("고마움")
    ['ㄱ', 'ㅗ', 'ㅁ', 'ㅏ', 'ㅇ', 'ㅜ', 'ㅁ']
    >>> decompose("값")
    ['ㄱ', 'ㅏ', 'ㅂ', 'ㅅ']
    """
    jamos: list[str] = []
    for char in text:
        if _SYLLABLE_BASE <= ord(char) <= _SYLLABLE_LAST:
            jamos.extend(_decompose_syllable(char))
        elif char in _COMPOSITE_JAMOS or is_basic_jamo(char):
            jamos.extend(_split_composite(char))
        else:
            raise ValueError(f"한글 자모로 분해할 수 없는 문자입니다: {char!r}")
    return jamos


def jamo_key(text: str) -> str:
    """단어를 사전 조회용 자모 문자열 키로 정규화한다."""
    return "".join(decompose(text))


def syllable_count(text: str) -> int:
    """``text``에 들어 있는 완성형 음절 수를 센다.

    자모 쪽에서 모음을 세면 안 된다. "왜"처럼 복합 모음이 있는 글자는 기본
    모음 여러 개로 쪼개지므로 한 음절을 여럿으로 잘못 세게 된다.
    """
    return sum(1 for char in text if _SYLLABLE_BASE <= ord(char) <= _SYLLABLE_LAST)


# ---------------------------------------------------------------------------
# 자모 나열 → 낱말 (읽는 방법이 여럿일 수 있다)
# ---------------------------------------------------------------------------


def _units(table: str) -> dict[str, str]:
    """표준 자모 표를 '기본 자모 나열 → 그 자모' 로 뒤집는다."""
    return {_COMPOSITE_JAMOS.get(j, j): j for j in table if j.strip()}


_CHO_UNITS = _units(_CHOSEONGS)
_JUNG_UNITS = _units(_JUNGSEONGS)
# 받침 표의 첫 칸은 "받침 없음" 이라 공백이다. _units 가 공백을 건너뛴다.
_JONG_UNITS = _units(_JONGSEONGS)


def syllable_readings(jamos: str, limit: int = 16) -> list[str]:
    """기본 자모 나열을 **완성된 음절로만** 읽는 모든 방법.

    :func:`decompose` 의 반대인데 답이 하나가 아니다. 게임은 겹자모를 낱자로
    풀어서 받으므로 같은 나열이 여러 낱말이 된다. ``ㅇㅏㄱㄱㅏ`` 는 '아까' 도
    되고 '악가' 도 된다. 그래서 하나를 고르지 않고 가능한 읽기를 전부 준다.
    낱자가 남는 읽기(받침만 덩그러니 남는 것)는 넣지 않는다 — 한 낱말이 아니다.

    왜 필요한가
    -----------

    신고는 사람이 친 자모만 남는다. 그걸 하이쿠에게 그대로 보여 줬더니 멀쩡한
    'ㅂㅜㅇㅠㅎㅏㅁ'(부유함)을 "음절 구조가 틀렸다" 며 반려했다. 규칙으로
    정해지는 일은 코드가 하고, 모델에게는 후보 낱말만 보여 준다.

    입력기처럼 앞에서부터 한 가지로 조립하지 않는 이유도 같다. 입력기 규칙으로는
    'ㅌㅗㄱㄱㅣ' 가 '토끼' 가 아니라 '톡기' 가 된다 — 자판에 쌍자음 키가 없는
    이 게임에서는 된소리와 받침을 가를 방법이 없다.
    """
    size = len(jamos)
    memo: dict[int, list[str]] = {}

    def read_from(start: int) -> list[str]:
        if start == size:
            return [""]
        if start in memo:
            return memo[start]
        found: list[str] = []
        for cho_key, cho in _CHO_UNITS.items():
            if not jamos.startswith(cho_key, start):
                continue
            after_cho = start + len(cho_key)
            for jung_key, jung in _JUNG_UNITS.items():
                if not jamos.startswith(jung_key, after_cho):
                    continue
                after_jung = after_cho + len(jung_key)
                index = _CHOSEONGS.find(cho) * _JUNGSEONG_COUNT + _JUNGSEONGS.find(jung)
                base = _SYLLABLE_BASE + index * _JONGSEONG_COUNT
                # 받침 없이 끝나는 읽기
                found.extend(chr(base) + rest for rest in read_from(after_jung))
                # 받침을 붙이는 읽기
                for jong_key, jong in _JONG_UNITS.items():
                    if jamos.startswith(jong_key, after_jung):
                        syllable = chr(base + _JONGSEONGS.find(jong))
                        tail = read_from(after_jung + len(jong_key))
                        found.extend(syllable + rest for rest in tail)
        memo[start] = found
        return found

    return read_from(0)[:limit]
