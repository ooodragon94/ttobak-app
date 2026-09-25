"""공유 문구 테스트.

가장 중요한 성질은 **정답이 새지 않는 것**이다. 아직 안 푼 사람에게 보내도
게임을 망치지 않아야 채팅방에 올릴 수 있다.
"""

from __future__ import annotations

from datetime import date

import pytest

from ttobak.game.share import BADGES, build_share_text, tier_badge

WON_ROWS = [
    ["absent", "correct", "absent", "absent", "absent", "absent"],
    ["present", "correct", "absent", "correct", "absent", "absent"],
    ["present", "correct", "present", "correct", "absent", "present"],
    ["correct", "correct", "correct", "correct", "correct", "correct"],
]


def sample(**overrides) -> str:
    kwargs = {
        "nickname": "지오",
        "played_on": date(2026, 9, 4),
        "round_no": 3,
        "status": "won",
        "max_attempts": 6,
        "marks_per_row": WON_ROWS,
        "played": 4,
        "win_rate": 0.75,
        "average_attempts": 4.3,
    }
    kwargs.update(overrides)
    return build_share_text(**kwargs)


def test_격자가_채점_결과와_일치한다():
    text = sample()
    assert "⬛🟩⬛⬛⬛⬛" in text
    assert "🟨🟩⬛🟩⬛⬛" in text
    assert "🟩🟩🟩🟩🟩🟩" in text


SQUARES = {"⬛", "🟨", "🟩"}


def grid_lines(text: str) -> list[str]:
    """네모만으로 이루어진 줄. 첫 줄의 장식 이모지와 구분하기 위한 기준이다."""
    return [line for line in text.splitlines() if line and set(line) <= SQUARES]


def test_격자에_글자가_새지_않는다():
    """안내 문구에는 한글이 있어도 되지만, 격자에는 네모만 있어야 한다."""
    for line in grid_lines(sample()):
        for char in line:
            assert not ("가" <= char <= "힣"), f"격자에 글자가 샜습니다: {line}"
            assert not ("ㄱ" <= char <= "ㅣ"), f"격자에 자모가 샜습니다: {line}"


def test_정답_단어가_어디에도_없다():
    """받은 사람이 아직 안 풀었어도 답을 알 수 없어야 한다."""
    # build_share_text 는 애초에 정답을 인자로 받지 않는다. 그 설계를 못박는다.
    import inspect

    parameters = inspect.signature(build_share_text).parameters
    assert "answer" not in parameters
    assert "느낌" not in sample()


def test_격자_줄_수가_시도_횟수와_같다():
    assert len(grid_lines(sample())) == len(WON_ROWS)


def test_격자_각_줄이_칸_수만큼이다():
    for line in grid_lines(sample()):
        assert len(line) == len(WON_ROWS[0])


def test_성공하면_시도_횟수가_보인다():
    assert sample().splitlines()[0] == "🟩 또박 4/6"


def test_실패하면_다르게_적는다():
    """**기회를 다 쓰고 진 판**이라야 X 다.

    정상적으로 지는 판은 기회를 전부 쓴 뒤에만 끝난다. 그래서 시도 횟수는
    언제나 최대치와 같다 — 3/6 로 진 판은 게임 흐름상 나올 수 없고,
    그건 포기한 판이다(아래 시험 참고).
    """
    text = sample(status="lost", marks_per_row=WON_ROWS[:1] * 6)
    assert text.splitlines()[0] == "⬛ 또박 X/6"


def test_포기는_기회가_남은_패배다():
    """여섯 번 다 틀린 것과 두 번 만에 손 든 것이 같아 보이면 안 된다.

    상태값을 따로 두지 않고 **남은 기회**로 가른다. 정상 패배는 기회를 전부
    쓰므로, 기회가 남은 패배는 포기밖에 없다.
    """
    text = sample(status="lost", marks_per_row=WON_ROWS[:2])
    assert text.splitlines()[0] == "⬛ 또박 🏳️ 2/6"


def test_날짜와_라운드와_칸수가_들어간다():
    text = sample()
    assert "2026.09.04" in text
    assert "4번째" in text  # round_no 3 은 4번째다
    assert "6칸" in text


def test_닉네임이_위쪽에_있다():
    """채팅방 미리보기가 앞 몇 줄만 보여 주는 일이 잦다."""
    assert sample(nickname="영희").splitlines()[1].startswith("영희 · ")


def test_통계가_들어간다():
    text = sample()
    assert "🌱 4판" in text
    assert "승률 75%" in text
    assert "평균 4.3번" in text


def test_연속_성공은_두_번부터_자랑한다():
    assert "연속" not in sample(current_streak=1)
    assert "🔥 3연속" in sample(current_streak=3)


def test_평균이_없으면_그_항목을_빼먹는다():
    """한 판도 못 맞혔으면 평균이 없다. 빈 값을 적는 것보다 낫다."""
    assert "평균" not in sample(average_attempts=None)


def test_주소를_붙일_수_있다():
    text = sample(url="https://example.ts.net:8443")
    assert text.rstrip().endswith("👉 https://example.ts.net:8443")


def test_추측이_없으면_공유할_수_없다():
    with pytest.raises(ValueError, match="추측이 하나도"):
        sample(marks_per_row=[])


def test_주소가_없으면_붙지_않는다():
    assert "http" not in sample()


def test_진행_중인_판은_공유할_수_없다():
    """남은 줄 수가 드러나면 힌트가 된다."""
    with pytest.raises(ValueError, match="진행 중"):
        sample(status="playing")


@pytest.mark.parametrize(
    ("played", "badge"),
    [
        (0, "🌱"),
        (9, "🌱"),
        (10, "🌿"),
        (49, "🌿"),
        (50, "🌳"),
        (100, "🌟"),
        (999, "👑"),
    ],
)
def test_배지가_누적_판수를_따라간다(played: int, badge: str):
    assert tier_badge(played) == badge


def test_배지_표가_내림차순이다():
    """앞에서부터 훑어 처음 걸리는 것을 쓰므로 순서가 뒤집히면 잘못 나온다."""
    thresholds = [threshold for threshold, _ in BADGES]
    assert thresholds == sorted(thresholds, reverse=True)
    assert thresholds[-1] == 0  # 0판도 배지를 받아야 한다
