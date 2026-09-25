"""JS 의 괄호·따옴표 균형을 검사한다. node 없이 도는 최소한의 방어.

**왜 필요한가**

브라우저는 JS 문법 오류를 조용히 삼킨다. 콘솔에만 한 줄 남기고 화면에는
아무것도 그리지 않는다. 그래서 따옴표 하나가 깨지면 **페이지가 통째로
백지**가 되고, 서버 로그에도 파이썬 테스트에도 아무 흔적이 없다. 실제로 그
사고를 냈고, 원인을 찾는 데 한참 걸렸다.

완전한 JS 파서는 아니다. 하지만 손으로 문자열을 다루다 나는 사고 —
안 닫힌 따옴표, 안 맞는 괄호 — 는 잡는다. 그게 실제로 났던 사고의 종류다.

    python tools/check_js.py src/media_organizer/static/app.js
"""

from __future__ import annotations

import sys
from pathlib import Path

_PAIRS = {")": "(", "]": "[", "}": "{"}


def scan(source: str) -> list[str]:
    """문제를 사람이 읽을 문장들로 돌려준다. 비어 있으면 통과다."""
    errors: list[str] = []
    stack: list[tuple[str, int]] = []
    index = 0
    line = 1
    quote: str | None = None

    while index < len(source):
        ch = source[index]
        nxt = source[index + 1] if index + 1 < len(source) else ""

        if ch == "\n":
            line += 1
            # 백틱(템플릿 리터럴)은 여러 줄에 걸쳐도 된다. 나머지는 아니다.
            if quote in ("'", '"'):
                errors.append(f"{line - 1}행: {quote} 따옴표가 줄 끝에서 안 닫혔다")
                quote = None
            index += 1
            continue

        if quote:
            if ch == "\\":  # 이스케이프는 다음 글자까지 통째로 건너뛴다
                index += 2
                continue
            if ch == quote:
                quote = None
            index += 1
            continue

        if ch == "/" and nxt == "/":
            while index < len(source) and source[index] != "\n":
                index += 1
            continue

        if ch == "/" and nxt == "*":
            end = source.find("*/", index + 2)
            if end < 0:
                errors.append(f"{line}행: /* 주석이 안 닫혔다")
                break
            line += source.count("\n", index, end)
            index = end + 2
            continue

        if ch in "'\"`":
            quote = ch
            index += 1
            continue

        if ch in "([{":
            stack.append((ch, line))
        elif ch in ")]}":
            if not stack:
                errors.append(f"{line}행: 여는 짝 없이 {ch}")
            elif stack[-1][0] != _PAIRS[ch]:
                opener, opened_at = stack.pop()
                errors.append(f"{line}행: {opener}({opened_at}행)와 {ch} 가 안 맞는다")
            else:
                stack.pop()
        index += 1

    if quote:
        errors.append(f"파일 끝: {quote} 따옴표가 안 닫혔다")
    for opener, opened_at in stack:
        errors.append(f"{opened_at}행: {opener} 가 안 닫혔다")
    return errors


def check_file(path: Path) -> list[str]:
    return scan(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    failed = 0
    for name in args:
        path = Path(name)
        errors = check_file(path)
        if errors:
            failed = 1
            print(f"{path}: {len(errors)}건")
            for e in errors:
                print(f"    {e}")
        else:
            print(f"{path}: 통과")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
