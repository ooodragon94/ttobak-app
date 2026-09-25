"""라운드별 문제 선정 테스트."""

from __future__ import annotations

from collections import Counter

import pytest

from ttobak.game.rounds import puzzle_for_round
from ttobak.words import Lexicon

LENGTHS = (5, 6, 7)


def test_같은_라운드는_항상_같은_문제(lexicon: Lexicon):
    first = puzzle_for_round("민수", 3, lexicon, lengths=LENGTHS, salt="s")
    second = puzzle_for_round("민수", 3, lexicon, lengths=LENGTHS, salt="s")
    assert first == second


def test_사람마다_출제_순서가_다르다(lexicon: Lexicon):
    """옆 사람 화면을 봐도 답을 알 수 없어야 한다."""
    mine = [
        puzzle_for_round("민수", n, lexicon, lengths=LENGTHS, salt="s").answer
        for n in range(9)
    ]
    theirs = [
        puzzle_for_round("영희", n, lexicon, lengths=LENGTHS, salt="s").answer
        for n in range(9)
    ]
    assert mine != theirs


def test_소금값이_다르면_출제가_달라진다(lexicon: Lexicon):
    a = [
        puzzle_for_round("민수", n, lexicon, lengths=LENGTHS, salt="a").answer
        for n in range(9)
    ]
    b = [
        puzzle_for_round("민수", n, lexicon, lengths=LENGTHS, salt="b").answer
        for n in range(9)
    ]
    assert a != b


def test_정답_길이는_후보_중_하나(lexicon: Lexicon):
    for n in range(30):
        puzzle = puzzle_for_round("민수", n, lexicon, lengths=LENGTHS, salt="s")
        assert puzzle.length in LENGTHS
        assert len(puzzle.jamos) == puzzle.length


def test_한_주기_안에_모든_길이가_한_번씩_나온다(lexicon: Lexicon):
    """길이 후보가 3개면 연속한 3라운드에 5, 6, 7이 한 번씩 등장한다."""
    counts = Counter(
        puzzle_for_round("민수", n, lexicon, lengths=LENGTHS, salt="s").length
        for n in range(30)
    )
    assert counts == {5: 10, 6: 10, 7: 10}

    # 주기 단위로도 쏠림이 없어야 한다.
    for cycle in range(10):
        window = {
            puzzle_for_round("민수", n, lexicon, lengths=LENGTHS, salt="s").length
            for n in range(cycle * 3, cycle * 3 + 3)
        }
        assert window == set(LENGTHS)


def test_사전을_한_바퀴_돌기_전에는_중복이_없다(lexicon: Lexicon):
    """길이 5 사전에 단어가 4개면, 그 길이의 앞선 4번 출제는 서로 달라야 한다."""
    words = lexicon.for_length(5).words
    picks = []
    n = 0
    while len(picks) < len(words):
        puzzle = puzzle_for_round("민수", n, lexicon, lengths=LENGTHS, salt="s")
        if puzzle.length == 5:
            picks.append(puzzle.answer)
        n += 1
    assert len(set(picks)) == len(picks)


def test_라운드가_아무리_커도_문제가_나온다(lexicon: Lexicon):
    """사전을 여러 바퀴 돌아도 예외 없이 계속 출제되어야 한다."""
    puzzle = puzzle_for_round("민수", 5000, lexicon, lengths=LENGTHS, salt="s")
    assert puzzle.length in LENGTHS


def test_잘못된_입력은_예외(lexicon: Lexicon):
    with pytest.raises(ValueError):
        puzzle_for_round("민수", -1, lexicon, lengths=LENGTHS, salt="s")
    with pytest.raises(ValueError):
        puzzle_for_round("민수", 0, lexicon, lengths=(), salt="s")
