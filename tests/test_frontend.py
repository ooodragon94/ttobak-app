"""프런트엔드가 조용히 깨지지 않았는지.

**브라우저는 JS 문법 오류를 조용히 삼킨다.** 화면만 백지가 되고 서버 로그에도
파이썬 테스트에도 아무 흔적이 없다. 실제로 그 사고를 냈다 — 따옴표 하나가
깨져 페이지가 안 뜨는데 모든 테스트는 통과했다.

``$('#없는-id')`` 도 같은 종류다. null 을 돌려주고, 거기에 점을 찍는 순간
그 아래 코드가 통째로 멈춘다. 화면 절반이 조용히 죽는 흔한 원인이다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.check_js import check_file, scan  # noqa: E402

STATIC = ROOT / "src" / "ttobak" / "static" / "js"
TEMPLATE = ROOT / "src" / "ttobak" / "templates" / "index.html"


@pytest.mark.parametrize("path", sorted(STATIC.glob("*.js")), ids=lambda p: p.name)
def test_js가_구조적으로_멀쩡하다(path: Path) -> None:
    errors = check_file(path)
    assert not errors, f"{path.name}:\n  " + "\n  ".join(errors)


def test_검사기가_진짜로_동작한다() -> None:
    """늘 통과하는 빈 테스트가 되지 않게 검사기 자체를 확인한다."""
    assert scan('const a = "안 닫음;\nconst b = 1;')
    assert scan("function f() { return [1, 2; }")
    assert scan("const ok = (x) => `값: ${x}`;") == []


def test_JS가_찾는_id가_템플릿에_다_있다() -> None:
    """``$('#없는-id')`` 는 null 이고, 거기 점을 찍으면 그 아래가 통째로 멈춘다.

    두 가지는 빼고 본다.

    - **JS 가 직접 만드는 요소**(``el.id = "..."``). 템플릿에 없는 게 정상이다.
    - **``?.`` 로 접근하는 것.** 없어도 안전하게 넘어가도록 이미 쓴 것이다.

    이 예외를 안 두면 멀쩡한 코드를 계속 물어서 아무도 이 테스트를 안 믿게
    된다. 실제로 ``#share-preview`` 를 잡았는데 확인해 보니 오탐이었다.
    """
    html = TEMPLATE.read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))

    missing: list[str] = []
    for path in STATIC.glob("*.js"):
        js = path.read_text(encoding="utf-8")
        created = set(re.findall(r"""\.id\s*=\s*['"]([\w-]+)['"]""", js))
        for match in re.finditer(
            r"""getElementById\(['"]([\w-]+)['"]\)(\??)""", js
        ):
            found, optional = match.group(1), match.group(2)
            if optional or found in created or found in ids:
                continue
            missing.append(f"{path.name}: #{found}")
    assert not missing, "JS 가 찾는 id 가 템플릿에 없다: " + ", ".join(missing)


# ---------------------------------------------------------------------------
# CSS 변수
# ---------------------------------------------------------------------------


def test_없는_CSS_변수를_쓰지_않는다() -> None:
    """**이건 조용히 틀리는 종류의 버그다.**

    ``var(--없는이름, #fff)`` 는 오류를 내지 않는다. 그냥 폴백으로 떨어지고
    아무도 안 알려 준다. 실제로 이 프로젝트에 없는 이름(``--surface``,
    ``--border`` 등)을 쓴 CSS 를 넣었더니, 다크 모드에서 방 카드가 흰색으로
    떠서 글자가 안 보였다. 눈으로 보기 전까지는 알 수 없었다.

    ``--tile-size`` 만 예외다. 그건 JS 가 화면 크기를 재서 넣어 주는 값이라
    스타일시트에 정의가 없는 것이 정상이고, 폴백도 일부러 두었다.
    """
    css = (ROOT / "src" / "ttobak" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    defined = set(re.findall(r"^\s+(--[a-z-]+):", css, re.M))
    used = set(re.findall(r"var\((--[a-z-]+)", css))
    runtime = {"--tile-size"}

    missing = sorted(used - defined - runtime)
    assert not missing, f"정의되지 않은 CSS 변수: {missing}"


def test_런타임_변수에는_폴백이_있다() -> None:
    """JS 가 값을 넣기 전에도 화면이 멀쩡해야 한다.

    폴백이 없으면 첫 그리기에서 칸 너비가 비어 판이 무너진다.
    """
    css = (ROOT / "src" / "ttobak" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    for use in re.findall(r"var\(--tile-size[^)]*\)", css):
        assert "," in use, f"폴백이 없다: {use}"


def test_HTML_이_쓰는_class_에_규칙이_있다() -> None:
    """**클래스를 붙였는데 CSS 규칙이 없으면 조용히 기본 모양으로 나온다.**

    실제로 그 사고를 냈다. ``.row`` 규칙이 ``.rooms__create .row`` 로만
    적혀 있어서, 같은 ``class="row"`` 를 쓴 한마디 폼은 스타일이 하나도
    안 붙었다. 입력칸은 쪼그라들고 버튼은 아래로 밀려났는데, 테스트는 전부
    통과했다 — 파이썬도 JS 도 CSS 를 안 보기 때문이다.

    여기서는 **레이아웃을 지시하는 이름**만 본다. 색이나 상태를 나타내는
    보조 클래스까지 강제하면 규칙이 잔소리가 된다.
    """
    css = (ROOT / "src" / "ttobak" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    html = TEMPLATE.read_text(encoding="utf-8")

    used: set[str] = set()
    for attr in re.findall(r'class="([^"]+)"', html):
        used.update(attr.split())

    missing = []
    for name in sorted(used):
        # 클래스 하나만으로 시작하는 규칙이 있는가. 조상 선택자 안에만
        # 있으면 다른 자리에서 못 쓴다 — 그게 이 시험이 잡으려는 것이다.
        if not re.search(rf"(?m)^\.{re.escape(name)}[\s,:{{]", css):
            missing.append(name)

    assert not missing, f"CSS 규칙이 없는 class: {missing}"


def test_게임_자판이_입력칸을_가로채지_않는다() -> None:
    """**전역 keydown 이 남의 입력칸에서 물러나야 한다.**

    실제로 낸 사고다. 자모 키에 ``preventDefault`` 를 걸고 게임판으로 보내는데,
    가드가 시트 두 개만 손으로 확인하고 있었다. 그래서 오늘의 문제 시트 위에서
    한마디를 치면 글자가 입력칸이 아니라 뒤의 게임판으로 갔다.

    시트를 새로 만들 때마다 같은 버그가 따라오는 구조였으므로, 여기서는
    **손으로 나열하지 않는 것**까지 확인한다.
    """
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "isTypingTarget(event.target)" in app, (
        "입력칸에 친 글자는 그 입력칸의 것이다. 게임이 가져가면 안 된다."
    )
    assert "anySheetOpen()" in app, "덮개 창은 class 로 세야 한다"
    assert "!el.sheet.hidden || !el.settings.hidden" not in app, (
        "시트를 손으로 나열하면 새 시트를 만들 때마다 조용히 깨진다"
    )


def test_모든_시트가_같은_class_를_쓴다() -> None:
    """``anySheetOpen()`` 이 class 로 세므로, 시트는 전부 그 class 를 달아야 한다.

    하나라도 빠지면 그 시트 위에서만 자판이 다시 게임판을 건드린다.
    """
    html = TEMPLATE.read_text(encoding="utf-8")
    # 화면을 덮는 창은 id 가 -sheet 로 끝나거나 알려진 이름을 쓴다.
    covers = re.findall(r'<div id="([^"]+)" class="([^"]*)"[^>]*hidden', html)
    known = {"sheet", "settings", "rooms", "daily-sheet", "hard-intro", "support"}
    for element_id, classes in covers:
        if element_id in known:
            assert "sheet" in classes.split(), f"{element_id} 에 sheet class 가 없다"


def test_그릴_판과_채점할_곳이_같이_바뀐다() -> None:
    """**둘이 어긋나면 다 채워도 거절당한다.**

    실제로 낸 사고다. 방의 오늘의 문제를 한 번 열면 ``dailyRoom`` 이 정해지고
    **그 뒤로 절대 안 지워졌다.** 그래서 일반 판(7칸)을 보면서 친 것이 계속
    방의 오늘의 문제(5칸)로 갔고, 화면에는 서버가 보낸 "자모 5개를 채워야
    합니다" 가 떴다.

    지금은 ``setGame`` 하나로만 바꾸므로 둘이 어긋날 수 없다.
    """
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "dailyRoom" not in app, (
        "판과 따로 도는 변수를 다시 만들면 같은 사고가 난다"
    )
    assert "function setGame(" in app, "판과 보낼 곳을 함께 바꾸는 자리가 있어야 한다"
    assert "Api.dailyGuess(state.room" in app, (
        "제출은 지금 그리고 있는 판을 따라가야 한다"
    )
    assert "function asBoard(" in app, (
        "오늘의 문제 응답을 일반 판 모양으로 맞추는 곳이 한 군데여야 한다"
    )


def test_난이도를_바꿀_때_확인을_받는다() -> None:
    """풀던 판이 포기로 기록되는 것은 되돌릴 수 없다.

    다만 **서버가 알려 준 값**으로만 판단해야 한다. 화면이 따로 세면
    서버와 어긋나서, 안 물어보고 판을 날리거나 잃을 것도 없는데 묻게 된다.
    """
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "costlyDifficulties" in app
    assert "costly_difficulties" in app, "서버 판단을 그대로 써야 한다"
    assert "confirm(ask)" in app


def test_놀이법_예시가_실제_채점과_같다() -> None:
    """**설명이 틀린 판을 보여 주면 규칙을 잘못 배운다.**

    실제로 그 사고를 냈다. '정답 하늘, 추측 사람' 예시가 앞의 ㅏ 를 노랑으로
    칠해 놓았는데, 진짜로 채점하면 그 자리는 **초록**(하늘의 둘째 자모가 ㅏ)
    이고 대신 ㄹ 이 노랑이었다. 처음 들어온 사람에게 규칙을 가르치는 화면이
    규칙과 어긋나 있었던 것이다.

    사람이 손으로 칠하는 한 또 틀린다. 그래서 ``aria-label`` 에 적어 둔
    ``정답 X, 추측 Y`` 를 읽어 **게임과 똑같은 함수로** 채점해 맞춰 본다.
    설명용 판을 새로 그려도 자동으로 검사된다.
    """
    from ttobak.game.rules import score_guess
    from ttobak.hangul import decompose

    html = TEMPLATE.read_text(encoding="utf-8")
    rows = re.findall(
        r'<div class="howto__row" aria-label="정답 (\S+?), 추측 (\S+?)">(.*?)</div>',
        html,
        re.S,
    )
    assert rows, "설명용 예시 판을 못 찾았다. aria-label 형식이 바뀌었나?"

    css_name = {"correct": "tile--correct", "present": "tile--present"}
    for answer, guess, body in rows:
        tiles = re.findall(r'<span class="tile tile--sm ([\w-]+)">(.)</span>', body)
        answer_jamos, guess_jamos = decompose(answer), decompose(guess)

        assert [jamo for _, jamo in tiles] == list(guess_jamos), (
            f"{answer}/{guess}: 칸에 적힌 자모가 '{guess}' 의 자모와 다르다"
        )
        expected = [
            css_name.get(mark.value, "tile--absent")
            for mark in score_guess(guess_jamos, answer_jamos)
        ]
        assert [css for css, _ in tiles] == expected, (
            f"정답 {answer} / 추측 {guess}: 색이 실제 채점과 다르다\n"
            f"  화면: {[css for css, _ in tiles]}\n"
            f"  실제: {expected}"
        )


def test_CSS_값의_괄호가_맞는다() -> None:
    """**괄호가 하나 어긋나면 그 선언만 조용히 버려진다.**

    실제로 그 사고를 냈다. ``.standing--me`` 의 배경이 이렇게 적혀 있었다.

        color-mix(in srgb, var(--color-accent) 16%, transparent))
                                                               ^ 하나 더

    브라우저는 오류를 내지 않는다. 그냥 그 줄을 못 본 척하고 넘어간다.
    그래서 순위표에서 **내 줄만 강조가 안 되는데** 아무 데도 흔적이 없었다.
    CSS 를 읽는 시험이 없으면 눈으로 볼 때까지 못 찾는 종류다.
    """
    css = (ROOT / "src" / "ttobak" / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    # 주석 안에는 짝이 안 맞는 괄호를 편하게 쓸 수 있어야 한다.
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    # ``@media (prefers-color-scheme: dark)`` 는 선언처럼 생겼지만 아니다.
    # 앞머리를 통째로 걷어내지 않으면 멀쩡한 규칙을 계속 물어서, 아무도
    # 이 시험을 안 믿게 된다.
    body = re.sub(r"@[a-z-]+[^{]*\{", "{", body)

    broken: list[str] = []
    for declaration in re.finditer(r"([-\w]+)\s*:\s*([^;{}]+)", body):
        value = declaration.group(2)
        if value.count("(") != value.count(")"):
            broken.append(f"{declaration.group(1)}: {value.strip()[:60]}")
    assert not broken, "괄호가 안 맞는 CSS 값: " + "; ".join(broken)


def test_거절당한_낱말을_신고할_수_있다() -> None:
    """**멀쩡한 낱말인데 사전에 없는 경우**를 알릴 길이 있어야 한다.

    사전이 표준국어대사전 계열이라 생활 합성어가 빠져 있는데('탕비실',
    '택시비', '방탄모'), 지금까지 그걸 아는 유일한 경로가 **친구가 카톡으로
    말해 주는 것**이었다. 말 안 하고 그냥 접는 사람이 훨씬 많다.

    붙는 조건도 확인한다. 난이도 규칙 위반이나 길이 오류에까지 신고 단추가
    붙으면 신고함이 쓰레기로 찬다. 그래서 서버가 준 ``unknown_word`` 일
    때만 붙인다 — 문장을 문자열로 비교하면 말투를 다듬는 순간 깨진다.
    """
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'error.code === "unknown_word"' in app, (
        "거절 사유는 서버가 준 이름으로 가른다. 문장 비교는 조용히 깨진다"
    )
    assert "function showRejection(" in app
    assert "Api.reportWord(" in app
    assert "Hangul.compose(jamos)" in app, (
        "친 것을 자모가 아니라 낱말로 보여 줘야 '내가 친 것' 으로 읽힌다"
    )


def test_거절_안내는_읽을_시간을_준다() -> None:
    """2.4초는 여덟 칸을 되짚기에 짧았다. 그리고 다음 낱말을 치기 시작하면
    볼 일이 끝났으므로 지운다 — 안 그러면 5초 내내 남아 거슬린다."""
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "REJECT_HOLD_MS = 5000" in app
    assert "if (!state.draft.length) showMessage" in app, (
        "새로 치기 시작하면 앞의 안내는 지워야 한다"
    )


def test_설정을_바꾸면_보고_있는_판을_다시_받는다() -> None:
    """**힌트를 끄면 단추가 그 자리에서 사라져야 한다.**

    단추를 그릴지는 서버가 판에 실어 보낸다. 그래서 설정만 저장하고 판을
    다시 안 받으면 화면이 옛 상태 그대로 남는다.

    예전에는 ``if (!state.room)`` 으로 **혼자 푸는 판만** 다시 받았다.
    오늘의 문제를 보는 중에 힌트를 끄면 단추가 계속 남아 있었고, 서버는
    이미 힌트를 막고 있었으므로 누르면 거절만 당했다.

    판을 받아 오는 곳이 둘(``Api.game`` / ``Api.daily``)이라 앞으로도 한쪽만
    챙기기 쉽다. 그래서 한곳으로 모아 두고, 그 함수를 쓰는지 여기서 지킨다.
    """
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "async function refreshCurrentGame()" in app
    assert "await refreshCurrentGame();" in app, (
        "설정을 저장한 뒤 보고 있는 판을 다시 받아야 한다"
    )
    # 그 함수가 두 갈래를 다 챙기는지.
    body = app[app.index("async function refreshCurrentGame()") :][:600]
    assert "Api.daily(" in body and "Api.game(" in body, (
        "오늘의 문제와 혼자 푸는 판을 모두 다시 받아야 한다"
    )
    assert "if (!state.room) setGame(await Api.game(), null);" not in app, (
        "혼자 푸는 판만 새로 받던 옛 코드가 남아 있다"
    )


def test_오늘의_문제_결과_창은_그_방의_순위를_보여_준다() -> None:
    """오늘의 문제를 맞힌 뒤 결과 창에 **같은 방 사람들의 순위**가 나와야 한다.

    예전에는 어느 판이든 혼자 풀기 순위를 불러 보여 줬다. 그날 아침 혼자 풀기를
    한 사람이 없으면, 방에서 문제를 막 맞힌 사람이 "아직 참가자가 없습니다" 를
    봤다. 방 화면과 같은 그리기 함수를 쓰는지까지 지킨다.
    """
    app = (STATIC / "app.js").read_text(encoding="utf-8")

    opener = app[app.index("async function openSheet(") :][:1500]
    assert "daily ? Promise.resolve(null) : Api.leaderboard()" in opener, (
        "오늘의 문제에서는 혼자 풀기 순위를 부르지 않아야 한다"
    )

    sheet = app[app.index("function buildSheet(") :][:3000]
    assert "fillStandings(box" in sheet, (
        "결과 창도 방 화면과 같은 순위 그리기를 써야 한다"
    )
    assert "function fillStandings(box, rows)" in app
    assert "fillStandings(el.dailyStandings, rows)" in app
