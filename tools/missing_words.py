"""서버 로그에서 "사전에 없다" 고 거절한 말을 모아 보여 준다.

왜 필요한가
-----------

사전은 공개 국어사전 목록에서 만든 것이라 멀쩡한 말이 빠져 있다. 실제로
'휴게실' 은 있는데 '탕비실' 은 없었다. 문제는 **그걸 알아내는 유일한 경로가
친구의 카톡** 이었다는 것이다. 말해 주는 사람은 극소수이고, 대부분은 그냥
"이 게임 이상하네" 하고 접는다.

그래서 거절한 말을 로그에 남기고, 이 도구로 모아 본다. 자주 거절된 순으로
보여 주므로 위에서부터 훑으면서 멀쩡한 말을 골라내면 된다.

쓰는 법
-------

::

    python tools/missing_words.py                 # 기본 로그에서 읽는다
    python tools/missing_words.py var/server.log  # 파일을 지정한다
    python tools/missing_words.py --min 2         # 두 번 이상 거절된 것만

골라낸 말은 ``data/extra-allowed.txt`` 에 적고 서버를 재시작하면 반영된다.

자모를 글자로 되돌리지 않는 이유
--------------------------------

사람이 친 것은 자모라서, 같은 자모 나열이 여러 글자가 될 수 있다. 서버가
멋대로 되돌리면 틀린 말을 사전에 넣게 된다. 여기서는 **자모를 그대로 보여
주고**, 무엇을 의도한 말인지는 사람이 판단한다.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG = ROOT / "var" / "server.log"

#: 서비스 계층이 남기는 줄. 문구가 바뀌면 여기도 같이 고쳐야 한다.
LINE = re.compile(r"사전에 없어서 거절: (\S+) \(자모 (\d+)개\)")


def collect(text: str) -> Counter[tuple[str, int]]:
    """로그 본문에서 (자모 나열, 길이) 별 거절 횟수를 센다."""
    return Counter(
        (jamos, int(length)) for jamos, length in LINE.findall(text)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "logs",
        nargs="*",
        type=Path,
        default=None,
        help="읽을 로그 파일들. 없으면 var/server.log",
    )
    parser.add_argument(
        "--min",
        type=int,
        default=1,
        help="이 횟수 이상 거절된 것만 보여 준다 (기본 1)",
    )
    args = parser.parse_args()

    # 회전된 로그(server.log.1 등)도 함께 본다. 하나만 보면 어제 것을 놓친다.
    paths = args.logs or sorted(DEFAULT_LOG.parent.glob(DEFAULT_LOG.name + "*"))
    if not paths:
        print(f"로그가 없습니다: {DEFAULT_LOG}")
        return 1

    counts: Counter[tuple[str, int]] = Counter()
    for path in paths:
        if not path.exists():
            continue
        counts.update(collect(path.read_text(encoding="utf-8", errors="replace")))

    rows = [
        (n, jamos, length)
        for (jamos, length), n in counts.items()
        if n >= args.min
    ]
    if not rows:
        print("거절된 말이 없습니다. (아직 로그가 안 쌓였을 수도 있습니다)")
        return 0

    # 자주 거절된 것이 위로. 같은 횟수면 짧은 것부터 — 짧을수록 흔한 말이다.
    rows.sort(key=lambda row: (-row[0], row[2], row[1]))

    print(f"{'횟수':>4}  {'자모':<14} 길이")
    print("-" * 30)
    for n, jamos, length in rows:
        print(f"{n:>4}  {jamos:<14} {length}")
    print()
    print(f"총 {len(rows)}종. 멀쩡한 말은 data/extra-allowed.txt 에 적으세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
