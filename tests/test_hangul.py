"""자모 분해 테스트."""

from __future__ import annotations

import pytest

from ttobak.hangul import BASIC_JAMOS, decompose, jamo_key, syllable_count


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("고마움", "ㄱㅗㅁㅏㅇㅜㅁ"),
        ("놀이터", "ㄴㅗㄹㅇㅣㅌㅓ"),
        ("동아리", "ㄷㅗㅇㅇㅏㄹㅣ"),
        ("고양이", "ㄱㅗㅇㅑㅇㅇㅣ"),
        ("컴퓨터", "ㅋㅓㅁㅍㅠㅌㅓ"),
    ],
)
def test_세글자_단어_분해(word: str, expected: str):
    assert jamo_key(word) == expected


def test_쌍자음은_같은_자모_둘로_쪼개진다():
    assert jamo_key("까치") == "ㄱㄱㅏㅊㅣ"


def test_겹받침은_두_자음으로_쪼개진다():
    assert jamo_key("값") == "ㄱㅏㅂㅅ"
    assert jamo_key("읽기") == "ㅇㅣㄹㄱㄱㅣ"


def test_복합모음은_기본모음으로_쪼개진다():
    assert jamo_key("왜") == "ㅇㅗㅏㅣ"
    assert jamo_key("의사") == "ㅇㅡㅣㅅㅏ"


def test_분해_결과는_모두_기본_자모다():
    for word in ["뷁", "괜찮아", "쌓였다", "닭볶음탕"]:
        assert all(jamo in BASIC_JAMOS for jamo in decompose(word))


def test_낱자로_적힌_입력도_통과한다():
    assert decompose("ㄱㅏ") == ["ㄱ", "ㅏ"]


def test_한글이_아니면_예외():
    with pytest.raises(ValueError):
        decompose("hello")
    with pytest.raises(ValueError):
        decompose("고양이!")


def test_음절수는_완성형_글자_수와_같다():
    assert syllable_count("고양이") == 3
    assert syllable_count("값") == 1
    # 복합 모음이 기본 모음 여럿으로 쪼개져도 음절 수는 하나다.
    assert syllable_count("왜") == 1



# --- 자모 나열 → 낱말 ---


@pytest.mark.parametrize(
    "word",
    [
        "부유함", "모임비", "고양이", "까치", "닭갈비",
        "의자", "왜가리", "값어치", "쇠고기",
    ],
)
def test_낱말을_자모로_풀었다_다시_읽으면_그_낱말이_후보에_있다(word: str):
    from ttobak.hangul import syllable_readings

    readings = syllable_readings(jamo_key(word))
    assert word in readings
    assert all(jamo_key(reading) == jamo_key(word) for reading in readings)


def test_같은_자모도_여러_낱말로_읽힌다():
    """쌍자음 키가 없어서 된소리와 받침이 갈린다. 하나만 고르면 틀린다."""
    from ttobak.hangul import syllable_readings

    assert set(syllable_readings("ㅇㅏㄱㄱㅏ")) == {"아까", "악가"}


def test_음절이_안_되는_나열은_읽을_방법이_없다():
    from ttobak.hangul import syllable_readings

    assert syllable_readings("ㄱ") == []
    assert syllable_readings("ㅏㄱ") == []
