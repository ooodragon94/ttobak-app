"""신고함을 하이쿠와 함께 정리한다.

왜 필요한가
-----------

게임에서 "사전에 없는 단어" 가 뜨면 신고 단추로 "진짜 낱말인데요" 를 알릴 수
있다. 그런데 **받아만 두고 아무도 안 보고 있었다.** 판정하는 함수는 저장소에
있었지만 부르는 곳이 한 군데도 없었다. 그러면 신고는 빈 약속이다.

판정은 셋 중 하나
-----------------

- **반려**: 낱말이 아니다. 자모를 막 누른 것, 오타, 비속어, 사람 이름.
- **있는 단어**: 실제로 쓰는 말. 추측으로 받아 준다 → ``data/extra-allowed.txt``
- **출제할 단어**: 누구나 바로 아는 일상어. 정답으로도 낸다 → ``data/words-<n>.txt``

두 사전의 기준이 다른 이유는 ``tools/vet_words.py`` 첫머리에 적었다.

판정은 기본으로 **소넷**이 한다. 신고는 하루 몇 건뿐이라 비용이 거의 없는데,
"출제" 로 판정된 말은 매일 모두가 푸는 정답 목록에 들어간다. 하이쿠는 정답
목록 검토에서 개나리·독수리까지 흔하지 않다고 해서 이 자리를 맡기지 않는다.

쓰는 법::

    python tools/review_reports.py          # 미리보기. 판정만 보여 준다
    python tools/review_reports.py --yes    # 판정대로 기록하고 사전에 넣는다

믿지 않고 대조하는 것
---------------------

- **자모를 낱말로 읽는 일은 코드가 한다.** 처음에는 하이쿠에게 자모를 그대로
  보여 줬는데, 멀쩡한 'ㅂㅜㅇㅠㅎㅏㅁ'(부유함)을 "음절 구조가 틀렸다" 며
  반려했다. 지금은 읽을 수 있는 후보 낱말을 전부 만들어 주고, 모델은 그중에서
  고르기만 한다. 후보에 없는 말을 고르면 넣지 않고 다음에 다시 본다.
- **국어사전 표제어가 아닌 말은 출제로 올리지 않는다.** 첫 실제 판정에서 소넷이
  '부유함'(富裕) 을 '떠 있음'(浮遊) 으로 읽고 출제로 올렸다. 정답 목록은 매일
  모두가 마주하므로, 모델이 출제라고 해도 표제어가 아니면 있는 단어로만 받는다.
- 신고 내용이 자모가 아니면 모델에게 보여 주지도 않고 반려한다. 누가 신고
  칸에 문장을 밀어 넣어 판정을 조종하는 일을 막는다.

넣은 것이 있으면 ``var/restart.flag`` 를 놓는다. 서버는 시작할 때만 사전을
읽으므로, 5분 안에 감시 작업이 껐다 켜면서 반영된다. 하루 중간에 정답 목록이
바뀌어도 이미 누가 연 오늘의 문제는 그 사람 것을 따르므로 방 안에서 어긋나지
않는다.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DATA = ROOT / "data"
DEFAULT_DB = ROOT / "var" / "ttobak.sqlite3"
FLAG = ROOT / "var" / "restart.flag"

PROMPT = """너는 한국어 낱말 맞히기 게임의 신고함을 정리한다.
게임에서 "사전에 없는 단어" 로 거절된 입력을
사람들이 "진짜 낱말인데요" 라고 신고한 것들이다.
사람이 친 것은 자모라서 같은 입력이 여러 낱말로 읽힐 수 있다.
그래서 읽을 수 있는 후보 낱말을 / 로 나눠 주었다.
그중 사람이 뜻했을 낱말 하나를 골라 판정한다.

- 출제: 누구나 바로 뜻을 아는 일상 낱말. 정답으로 내도 된다.
- 있음: 실제로 쓰는 말이지만 정답으로 내기엔 흔하지 않은 말.
        추측으로만 받아 준다.
- 반려: 후보 중 어느 것도 낱말이 아니다. 오타, 비속어·혐오 표현,
        사람 이름, 문장 조각.
출제와 있음 사이에서 헷갈리면 있음으로 둔다.
있음과 반려 사이에서 헷갈리면 있음으로 둔다.

출력 규칙: 신고마다 한 줄, 아래 모양으로만 쓴다.
고른 낱말은 후보에 적힌 그대로 쓴다. 반려면 낱말 자리에 - 를 쓴다.
번호 | 낱말 | 출제·있음·반려 중 하나 | 짧은 이유

신고:
{reports}
"""

_LINE = re.compile(
    r"^\s*(\d+)\s*[|.)]\s*([가-힣]+|-)\s*\|"
    r"\s*(출제|있음|반려)\s*\|?\s*(.*)$"
)

LABELS = {
    "출제": "출제할 단어",
    "있음": "있는 단어",
    "반려": "반려",
    "이미": "이미 사전에 있음",
}

Verdict = tuple[str, "str | None", str]


@cache
def headwords() -> frozenset[str]:
    """국어사전 표제어 전체. 읽기 후보 중 진짜 낱말을 앞에 세우는 데 쓴다."""
    path = DATA / "korean-wordlist-raw.txt"
    if not path.exists():
        return frozenset()
    return frozenset(path.read_text(encoding="utf-8").split())


def judge(reports: list[dict], model: str) -> dict[int, Verdict]:
    """신고마다 (판정, 낱말, 이유) 를 낸다. 열쇠는 신고 번호."""
    from haiku import HaikuError, ask

    from ttobak.hangul import is_basic_jamo, syllable_readings

    verdicts: dict[int, Verdict] = {}
    to_ask: list[tuple[dict, list[str]]] = []
    for report in reports:
        jamos = report["jamos"]
        if not jamos or not all(is_basic_jamo(c) for c in jamos):
            verdicts[report["id"]] = ("반려", None, "자모가 아닌 글자가 섞임")
            continue
        readings = syllable_readings(jamos)
        if not readings:
            # 어떻게 읽어도 낱자가 남는다. 모델에게 물을 것도 없이 낱말이 아니다.
            verdicts[report["id"]] = ("반려", None, "음절로 읽히지 않음")
            continue
        # 사전 표제어인 읽기를 앞에 둔다. 모델이 엉뚱한 읽기를 고르는 일이 준다.
        readings.sort(key=lambda word: word not in headwords())
        to_ask.append((report, readings[:6]))
    if not to_ask:
        return verdicts

    listing = "\n".join(f"{r['id']} | {' / '.join(w)}" for r, w in to_ask)
    try:
        reply = ask(PROMPT.replace("{reports}", listing), model=model)
    except HaikuError as error:
        print(f"하이쿠 판정 실패: {error}")
        return verdicts

    by_id = {report["id"]: (report, words) for report, words in to_ask}
    for line in reply.splitlines():
        match = _LINE.match(line)
        if not match or int(match.group(1)) not in by_id:
            continue
        report, words = by_id[int(match.group(1))]
        word, verdict = match.group(2), match.group(3)
        reason = match.group(4).strip()
        if verdict == "반려":
            verdicts[report["id"]] = ("반려", None, reason)
        elif word not in words:
            # 후보에 없는 말을 골랐다. 사람이 친 것과 다른 말을 넣을 수는 없다.
            note = f"후보에 없는 낱말({word}), 다음에 다시 봄"
            verdicts[report["id"]] = ("보류", None, note)
        elif verdict == "출제" and word not in headwords():
            # 정답 목록은 매일 모두가 마주한다. 모델 판정만으로는 넣지 않는다.
            note = f"{reason} (표제어가 아니라 출제 대신 있는 단어로)".strip()
            verdicts[report["id"]] = ("있음", word, note)
        else:
            verdicts[report["id"]] = (verdict, word, reason)
    return verdicts


def append_word(path: Path, word: str, header: str) -> bool:
    """사전 파일 끝에 낱말을 더한다. 이미 있으면 안 더한다.

    줄바꿈은 파일이 원래 쓰던 모양을 따른다. 그냥 쓰면 윈도우가 CRLF 를
    섞어 넣어서, 한 파일 안에 줄바꿈이 두 가지가 된다.
    """
    raw = path.read_bytes() if path.exists() else b""
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    existing = {line.strip() for line in text.splitlines()}
    if word in existing:
        return False
    if header not in existing:
        text = text.rstrip("\n") + f"\n\n{header}\n"
    elif not text.endswith("\n"):
        text += "\n"
    newline = "\r\n" if crlf else "\n"
    with path.open("w", encoding="utf-8", newline=newline) as handle:
        handle.write(text + f"{word}\n")
    return True


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--yes", action="store_true", help="판정대로 기록하고 사전에 넣는다"
    )
    parser.add_argument(
        "--model", default="sonnet", help="판정할 모델 (기본 sonnet)"
    )
    args = parser.parse_args()

    from ttobak.db.repository import Database
    from ttobak.words import load_lexicon

    database = Database(args.db)
    reports = database.pending_word_reports(limit=200)
    if not reports:
        print("판정할 신고가 없습니다.")
        return 0

    lengths = tuple(
        sorted(int(p.stem.split("-")[1]) for p in DATA.glob("words-*.txt"))
    )
    lexicon = load_lexicon(DATA, lengths)

    verdicts: dict[int, Verdict] = {}
    fresh = []
    for report in reports:
        length, jamos = report["length"], report["jamos"]
        if length not in lengths:
            verdicts[report["id"]] = ("반려", None, f"자모 {length}개 문제는 없음")
        elif lexicon.accepts(jamos, length):
            # 이미 사전에 들어간 말은 모델에게 묻지 않는다. 손으로 먼저 넣은 경우다.
            known = lexicon.for_length(length).words_for(jamos)
            verdicts[report["id"]] = ("이미", known[0] if known else None, "")
        else:
            fresh.append(report)
    verdicts.update(judge(fresh, args.model))

    print(f"대기 중인 신고 {len(reports)}건\n")
    for report in reports:
        verdict, word, reason = verdicts.get(report["id"], ("보류", None, "판정 없음"))
        label = LABELS.get(verdict, verdict)
        print(
            f"  #{report['id']:<4} {report['jamos']:<12} 표{report['votes']:<3}"
            f" {label:<10} {word or '-':<8} {reason}"
        )

    if not args.yes:
        print("\n미리보기입니다. 반영하려면 --yes 를 붙이세요.")
        return 0

    today = date.today().isoformat()
    header = f"# --- 신고 반영 {today} (tools/review_reports.py) ---"
    changed = False
    for report in reports:
        verdict, word, reason = verdicts.get(report["id"], ("보류", None, ""))
        if verdict == "보류":
            continue  # 다음에 다시 본다
        if verdict == "출제" and word:
            target = DATA / f"words-{report['length']}.txt"
            changed |= append_word(target, word, header)
        elif verdict == "있음" and word:
            changed |= append_word(DATA / "extra-allowed.txt", word, header)
        status = "rejected" if verdict == "반려" else "added"
        note = f"[{LABELS[verdict]}] {reason}".strip()
        database.resolve_word_report(report["id"], status, word, note)

    if changed:
        FLAG.touch()
        print("\n사전을 바꿨습니다. 재시작 깃발을 놓았으니 5분 안에 반영됩니다.")
    else:
        print("\n판정만 기록했습니다. 사전은 바뀌지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
