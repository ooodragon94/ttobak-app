"""화면 채점(app.js)과 서버 채점(rules.py)이 **같은 답**을 내는가.

채점 규칙이 두 군데에 있게 됐다. 화면이 그 자리에서 칠하고 서버가 나중에
저장하기 때문이다. 둘이 어긋나면 타일이 한 번 칠해졌다가 다른 색으로 바뀐다.
그래서 같은 입력을 양쪽에 넣어 대조한다. 같은 자모가 여러 번 나오는 경우가
어긋나기 가장 쉬워서 일부러 많이 섞는다.

브라우저(Edge)와 playwright 가 있어야 돈다. 없으면 건너뛴다.
"""

from __future__ import annotations

import base64
import random
import re
from pathlib import Path

import pytest

from ttobak.game.rules import keyboard_state, score_guess
from ttobak.game.sealed import seal

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "src" / "ttobak" / "static" / "js" / "app.js"


def _function_source(name: str) -> str:
    """app.js 에서 함수 하나의 소스를 꺼낸다(중괄호 짝을 세어 끝을 찾는다)."""
    text = APP_JS.read_text(encoding="utf-8")
    start = text.index(f"function {name}(")
    depth, i = 0, text.index("{", start)
    while True:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1


@pytest.fixture(scope="module")
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge", headless=True)
        except Exception as error:  # noqa: BLE001 - 브라우저가 없으면 건너뛴다
            pytest.skip(f"브라우저 없음: {error}")
        page = browser.new_page()
        source = APP_JS.read_text(encoding="utf-8")
        rank = re.search(r"const MARK_RANK = \{[^}]*\};", source)
        page.add_script_tag(
            content="\n".join(
                [
                    rank.group(0),
                    _function_source("scoreGuess"),
                    _function_source("mergeKeyboard"),
                    _function_source("unseal"),
                    "window.scoreGuess = scoreGuess;",
                    "window.mergeKeyboard = mergeKeyboard;",
                    "window.unseal = unseal;",
                ]
            )
        )
        yield page
        browser.close()


def test_채점이_서버와_같다(page):
    rng = random.Random(7)
    # 자모 종류를 일부러 적게 써서 중복이 많이 나오게 한다.
    pool = list("ㄱㄴㅏㅓㅇ")
    cases = []
    for _ in range(3000):
        length = rng.choice((5, 6, 7, 8))
        answer = [rng.choice(pool) for _ in range(length)]
        guess = [rng.choice(pool) for _ in range(length)]
        cases.append((guess, answer))
    got = page.evaluate("cases => cases.map(([g, a]) => scoreGuess(g, a))", cases)
    for (guess, answer), marks in zip(cases, got, strict=True):
        assert marks == [m.value for m in score_guess(guess, answer)], (guess, answer)


def test_키보드_색이_서버와_같다(page):
    rng = random.Random(11)
    pool = list("ㄱㄴㅏㅓㅇㅎ")
    for _ in range(300):
        answer = [rng.choice(pool) for _ in range(5)]
        rows = rng.randint(1, 6)
        guesses = [[rng.choice(pool) for _ in range(5)] for _ in range(rows)]
        marks = [score_guess(g, answer) for g in guesses]
        expected = {k: v.value for k, v in keyboard_state(guesses, marks).items()}
        got = page.evaluate(
            """([guesses, marks]) => guesses.reduce(
                (kb, g, i) => mergeKeyboard(kb, g, marks[i]), {})""",
            [guesses, [[m.value for m in row] for row in marks]],
        )
        assert got == expected


def test_감춘_정답을_화면이_똑같이_푼다(page):
    samples = ("ㅎㅏㄴㅡㄹ", "ㄱㅗㅇㅑㅇㅇㅣ", "ㄷㅗㅅㅓㄱㅗㅏㄴ", "ㅂㅣㅂㅣㅁㅂㅏㅂ")
    for jamos in samples:
        sealed = seal(jamos)
        assert page.evaluate("s => unseal(s)", sealed) == jamos
    assert page.evaluate("() => unseal(null)") is None
    broken = {"k": base64.b64encode(b"x").decode(), "v": "!!!"}
    assert page.evaluate("s => unseal(s)", broken) is None
