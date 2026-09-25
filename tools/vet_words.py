"""추측 허용 사전을 '다들 아는 말' 로 걸러 내는 도구.

왜 필요한가
-----------

허용 사전은 국어사전 표제어 36만 개에서 뽑았다. 그래서 '창서', '조갱이',
'니긴쇠' 같은 말이 전부 통과한다. 5자모 표본 40개를 보면 아는 말은 다섯
남짓이고 나머지는 아무도 모른다.

**그러면 "사전에 있는 말이어야 한다" 는 규칙이 사실상 없는 것과 같다.**
아무 자모나 눌러도 웬만하면 통과하니까, 낱말을 떠올려 맞힌다는 게임의 전제가
무너진다.

빈도표로는 못 거른다
--------------------

``korean-frequency.txt`` 는 자막 말뭉치의 **표면형** 목록이라 '칼국수',
'고드름' 같은 흔한 명사가 아예 없다. 그걸로 거르면 8자모 사전이 48,249개에서
715개로 줄고, 방금 손으로 채운 '탕비실' 도 도로 막힌다. 시험해 보고 버렸다.

그래서 사람(모델)이 읽고 판단한다
---------------------------------

이 도구는 판단을 **하지 않는다.** 낱말 목록을 덩어리로 잘라 주고, 판단 결과를
받아 다시 사전으로 굽는 일만 한다. 판단은 바깥에서(하이쿠 같은 모델이) 한다.

흐름::

    python tools/vet_words.py split --length 5 6 7 8   # 덩어리 파일로 자른다
    python tools/vet_words.py judge --length 5 6 7 8   # 하이쿠가 덩어리마다 판정
    python tools/vet_words.py check --length 5 6 7 8   # 미덥잖은 판정을 짚는다
    python tools/vet_words.py rescue --length 5 6 7 8  # 빠진 흔한 말을 소넷이 한 번 더
    python tools/vet_words.py apply --length 5 6 7 8   # 결과를 사전에 반영

    python tools/vet_words.py answers --length 5 6 7 8 --model sonnet
                                                       # 정답 사전 검토(반영은 사람이)

정답 검토에 하이쿠를 쓰지 않는 이유: 2026-09-11 에 돌려 보니 개나리·독수리·송아지·
지렁이까지 "흔하지 않다" 며 28개를 빼자고 했고, 정작 겨울눈은 놓쳤다. 정답은
몇백 개뿐이라 소넷으로 돌려도 비용이 거의 안 든다. 몇만 개인 허용 사전은 하이쿠로
충분했다 — 뺀 말이 대부분 활용형·조사 붙은 꼴·고유명사였다.

두 사전의 기준이 다르다
-----------------------

- **있는 단어**(``allowed``): 들어 본 적 있을 법한 실제 낱말이면 받는다.
  **헷갈리면 남긴다.** 멀쩡한 말을 빼면 사람이 제대로 친 답이 거절된다.
- **출제할 단어**(``words``): 누구나 바로 뜻을 아는 일상어만. **헷갈리면 뺀다.**
  어려운 말이 정답으로 나오면 그날 문제를 아무도 못 푼다.

틀리는 방향의 무게가 서로 반대라, 같은 기준으로 거르면 한쪽이 반드시 망가진다.

안전장치
--------

- **정답 후보는 절대 안 지운다.** 출제되는 말이 추측으로 거절되면 그 판은
  풀 수 없다. 구조적으로 못 일어나게 여기서 강제로 다시 넣는다.
- ``extra-allowed.txt`` 도 지키지 않는다면 손으로 채워 넣은 의미가 없다.
- 원본은 덮어쓰지 않는다. ``allowed-<n>.txt`` 를 갈아 끼우기 전에
  ``allowed-<n>.full.txt`` 로 남긴다 — 판단이 틀렸을 때 돌아갈 곳이 필요하다.
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DATA = PROJECT_ROOT / "data"
CHUNKS = DATA / "vet"

#: 한 덩어리에 담을 낱말 수.
#:
#: 모델 하나가 한 번에 읽고 판단하기에 무리 없는 크기로 잡는다. 너무 크면
#: 뒤쪽을 대충 보고, 너무 작으면 덩어리 수만 늘어난다.
CHUNK = 400


def read_lines(path: Path) -> list[str]:
    """주석과 빈 줄을 걷어내고 낱말만 읽는다.

    ``utf-8-sig`` 로 읽는 이유: 판단 결과 파일을 쓰는 쪽이 BOM 을 붙이는
    경우가 있다. 그러면 첫 낱말이 ``﻿가게`` 가 되어 조용히 사라진다 —
    첫 줄만 없어지므로 눈으로는 알아채기 어렵다.
    """
    if not path.exists():
        return []
    words: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.extend(line.split())
    return words


#: '다' 로 끝나지만 **명사**인 말들.
#:
#: 용언 기본형은 전부 '다' 로 끝나므로 그걸로 거르면 거의 다 잡힌다. 다만
#: 명사 중에도 '다' 로 끝나는 것이 있어서, 그건 손으로 지킨다. 목록이 짧은
#: 이유는 이 게임이 내는 길이(5~8자모)에서 그런 명사가 몇 개 안 되기 때문이다.
#: ('바다' 는 4자모라 아예 범위 밖이다.)
NOUNS_ENDING_IN_DA = frozenset({"과다", "판다", "사이다", "소다", "가다랑어"})


def is_verb_form(word: str) -> bool:
    """용언(동사·형용사) 기본형인가.

    **정답은 언제나 명사다.** 그런데 허용 사전에는 '먹다', '높다' 같은 기본형이
    섞여 있고, 거기에 '몌다', '뫃다', '믜다' 같은 고어까지 딸려 온다. 답으로는
    절대 안 나오는 말을 추측으로만 받아 주는 셈이라, 있어도 쓸 데가 없고
    게임만 헐거워진다.

    한국어 용언 기본형은 **예외 없이 '다' 로 끝난다.** 그래서 그 하나로 거의
    다 걸러진다. 명사 쪽 예외는 위 목록에서 지킨다.
    """
    return word.endswith("다") and word not in NOUNS_ENDING_IN_DA


def protected(length: int) -> set[str]:
    """무슨 일이 있어도 남겨야 하는 낱말들.

    정답 후보가 추측으로 거절되면 **그 판은 풀 수 없다.** 모델이 실수로
    빼더라도 여기서 되돌린다. 손으로 채운 목록도 같이 지킨다.
    """
    from ttobak.hangul import decompose

    keep = set(read_lines(DATA / f"words-{length}.txt"))
    for word in read_lines(DATA / "extra-allowed.txt"):
        try:
            if len(decompose(word)) == length:
                keep.add(word)
        except ValueError:
            continue
    return keep


def split(length: int) -> int:
    """허용 사전을 덩어리 파일로 자른다."""
    source = DATA / f"allowed-{length}.txt"
    words = read_lines(source)
    if not words:
        print(f"허용 사전이 비었습니다: {source}")
        return 1

    safe = protected(length)
    # 정답 후보는 판단할 필요가 없다. 어차피 남길 것이라 묻는 것이 낭비다.
    to_judge = [w for w in words if w not in safe]

    out = CHUNKS / str(length)
    out.mkdir(parents=True, exist_ok=True)
    # 판정 결과(.keep)도 같이 지운다. 덩어리만 새로 자르고 옛 판정을 남겨 두면
    # 번호가 같은 **다른 덩어리**에 옛 판정이 붙어서, apply 가 엉뚱한 낱말을
    # 남기거나 지운다.
    for old in [*out.glob("*.txt"), *out.glob("*.keep")]:
        old.unlink()

    count = 0
    for index in range(0, len(to_judge), CHUNK):
        piece = to_judge[index : index + CHUNK]
        (out / f"{index // CHUNK:04d}.txt").write_text(
            "\n".join(piece) + "\n", encoding="utf-8"
        )
        count += 1

    print(f"{length}자모: 전체 {len(words)}개")
    print(f"  지킬 것(정답 후보·손추가): {len(safe & set(words))}개")
    print(f"  판단할 것: {len(to_judge)}개 → 덩어리 {count}개 ({out})")
    return 0


def apply(length: int) -> int:
    """판단 결과를 모아 허용 사전을 다시 굽는다.

    덩어리마다 ``<번호>.keep`` 파일이 있어야 한다. 하나라도 없으면 멈춘다 —
    빠진 덩어리를 조용히 '전부 탈락' 으로 처리하면 사전이 통째로 사라진다.
    """
    out = CHUNKS / str(length)
    pieces = sorted(out.glob("*.txt"))
    if not pieces:
        print(f"덩어리가 없습니다. 먼저 split 하세요: {out}")
        return 1

    kept: set[str] = set()
    missing = []
    for piece in pieces:
        result = piece.with_suffix(".keep")
        if not result.exists():
            missing.append(piece.name)
            continue
        kept.update(read_lines(result))
    # rescue 로 되살린 말. 안 돌렸으면 파일이 없고 빈 목록이다.
    kept.update(read_lines(out / RESCUE_FILE))

    if missing:
        print(f"판단 결과가 없는 덩어리 {len(missing)}개: {', '.join(missing[:5])} …")
        print("전부 끝난 뒤에 다시 실행하세요.")
        return 1

    source = DATA / f"allowed-{length}.txt"
    original = read_lines(source)
    safe = protected(length)
    # 모델이 원본에 없는 말을 지어냈을 수 있다. 원본에 있는 것만 받는다.
    chosen = (kept & set(original)) | (safe & set(original))
    # 용언 기본형을 걷어낸다. 판단을 맡긴 쪽에 이 규칙을 말해 주지 못한
    # 경우가 있어서, **반영하는 자리에서 한 번 더** 거른다. 정답 후보는
    # safe 로 다시 들어오므로 여기서 지워도 잃지 않는다.
    verbs = {w for w in chosen if is_verb_form(w)}
    final = sorted((chosen - verbs) | (safe & set(original)))
    if verbs:
        print(f"  용언 기본형 제외: {len(verbs)}개")

    backup = DATA / f"allowed-{length}.full.txt"
    if not backup.exists():
        backup.write_text("\n".join(original) + "\n", encoding="utf-8")
        print(f"  원본 보관: {backup.name}")

    source.write_text("\n".join(final) + "\n", encoding="utf-8")
    print(
        f"{length}자모: {len(original)}개 → {len(final)}개 "
        f"({len(final) / len(original) * 100:.1f}% 남김)"
    )
    return 0


#: 그럴듯한 '남김 비율' 구간.
#:
#: 표본을 보면 허용 사전의 대부분이 아무도 모르는 말이라, 제대로 걸렀다면
#: 10~40% 쯤 남는다. 이 밖으로 벗어나면 판단을 제대로 안 한 것이다.
#:
#: - 너무 높으면: 거의 다 통과시켰다. 실제로 400개를 400개 그대로 남긴
#:   덩어리가 있었다.
#: - 너무 낮으면: 읽지도 않고 빈 파일을 썼다. '지도력', '지리학' 이 들어 있는
#:   덩어리를 통째로 비운 경우가 있었다.
PLAUSIBLE_LOW, PLAUSIBLE_HIGH = 0.03, 0.55



def check(length: int) -> int:
    """판단 결과가 미덥잖은 덩어리를 짚어 준다.

    **기계로 확실히 알 수 있는 것만 본다.**

    1. 원본에 없던 낱말을 지어냈는가
    2. 용언 기본형('다' 끝)이 남아 있는가 — 명사만 남기기로 했다
    3. 거의 다 통과시켰는가

    "흔한 낱말을 놓쳤는가" 도 재 보려 했지만 포기했다. 가진 빈도표가 자막
    말뭉치의 표면형이라 '가만·매우·몹시'(부사), '길고·도와·집어'(활용형),
    '레이·유진'(인명)이 잔뜩 들어 있다. 그걸로 재면 **제대로 버린 것까지
    놓쳤다고 잡는다.** 판정에 못 쓸 잣대를 들이대느니 없는 편이 낫다.

    남는 위험: 원본이 진짜로 부실한 덩어리와 게을러서 비운 덩어리를 이 검사로는
    못 가른다. 그건 표본을 눈으로 보는 수밖에 없다.
    """
    out = CHUNKS / str(length)
    todo, invented, verbs, high, ok = [], [], [], [], 0
    for src in sorted(out.glob("*.txt")):
        keep = src.with_suffix(".keep")
        if not keep.exists():
            todo.append(src.stem)
            continue
        words = read_lines(src)
        kept = read_lines(keep)
        source = set(words)
        bad_new = [w for w in kept if w not in source]
        bad_verb = [w for w in kept if is_verb_form(w)]
        ratio = len(kept) / len(words) if words else 0
        # 지어낸 낱말 자체는 apply 가 원본과 교집합을 취해 걸러 낸다. 그래서
        # 몇 개 섞인 것은 사전을 더럽히지 않는다. 문제는 **비율이 클 때**다 —
        # 절반이 지어낸 말이면 파일을 안 읽고 기억으로 쓴 것이고, 그러면
        # 남긴 나머지도 못 믿는다.
        invented_ratio = len(bad_new) / len(kept) if kept else 0
        if invented_ratio > 0.2:
            invented.append(f"{src.stem}({invented_ratio:.0%})")
        elif bad_verb:
            verbs.append(f"{src.stem}({','.join(bad_verb[:3])})")
        elif ratio > PLAUSIBLE_HIGH:
            high.append(src.stem)
        else:
            ok += 1

    print(
        f"{length}자모: 통과 {ok} · 안 함 {len(todo)}"
        f" · 지어냄 {len(invented)} · 용언남음 {len(verbs)} · 과다통과 {len(high)}"
    )
    labelled = (
        ("아직 안 함", todo),
        ("원본에 없는 낱말", invented),
        ("용언이 남음", verbs),
        ("너무 많이 남김", high),
    )
    for label, items in labelled:
        if items:
            print(f"  {label}: {' '.join(items)}")
    return 0 if not (todo or invented or verbs or high) else 1


# ---------------------------------------------------------------------------
# 하이쿠 판정
# ---------------------------------------------------------------------------

#: '있는 단어' 를 고를 때의 기준.
#:
#: **헷갈리면 남기라고 한다.** 예전 판정은 7자모 덩어리에서 400개 중 6~12개만
#: 남기면서 '개꿈', '스캐너', '가중치', '등기소' 까지 뺐다. 그러면 사람이 멀쩡한
#: 말을 쳐도 "사전에 없는 단어" 가 뜬다. 모르는 말을 남겨서 생기는 손해(게임이
#: 조금 헐거워짐)보다 훨씬 크다.
#:
#: 예시는 일부러 판정할 목록과 상관없는 말로 든다. 목록의 말을 예로 들면 모델이
#: 그 몇 개만 맞히고 기준은 안 배운다.
ALLOWED_PROMPT = """너는 한국어 낱말 맞히기 게임의 사전을 거르는 사람이다.
아래 목록에서 보통 한국 사람이 들어 본 적 있을 법한 실제 낱말을 모두 골라라.

남긴다:
- 일상에서 쓰는 명사와 흔한 합성어·파생어 (예: 칫솔, 가습기, 우산꽂이, 노트북)
- 뉴스·교과서·생활에서 접하는 한자어와 외래어
- 헷갈리면 남긴다. 멀쩡한 말을 빼면 사람이 제대로 친 답이 거절된다.

뺀다:
- 대부분이 뜻을 모르는 옛말·방언·희귀 한자어·좁은 전문 용어
- 사람 이름 같은 고유명사
- '다' 로 끝나는 동사·형용사 기본형

출력 규칙: 목록에 있는 낱말만, 한 줄에 하나씩. 번호·설명·머리말 없이.
남길 것이 하나도 없으면 NONE 한 줄만 쓴다.

목록:
{words}
"""

#: '출제할 단어' 를 검토할 때의 기준. 있는 단어와 반대로 **헷갈리면 뺀다.**
ANSWER_PROMPT = """너는 한국어 낱말 맞히기 게임의 정답 목록을 검토한다.
정답은 친구들이 매일 함께 푸는 문제라서, 누구나 바로 뜻을 아는 일상 낱말이어야 한다.

각 낱말을 판정한다.
- 유지: 누구나 알고 일상에서 흔히 쓰는 말
- 제외: 실제 낱말이어도 흔하지 않은 말(듣고 "그런 말이 있어?" 할 만한 말),
        또는 표준 표기가 아닌 말
헷갈리면 제외한다. 정답이 어려우면 그날 문제를 아무도 못 푼다.

출력 규칙: 목록의 모든 낱말을 빠짐없이, 한 줄에 하나씩 아래 모양으로만 쓴다.
낱말 | 유지
낱말 | 제외 | 짧은 이유

목록:
{words}
"""

_HANGUL_WORD = re.compile(r"[가-힣]+")
_VERDICT_LINE = re.compile(
    r"^\s*([가-힣]+)\s*[|\t:,-]?\s*(유지|제외)\s*[|\t:,-]?\s*(.*)$"
)


def parse_kept(text: str, words: list[str]) -> list[str]:
    """하이쿠의 답에서 남긴 낱말만 뽑는다.

    **원본 덩어리에 있는 낱말만 받는다.** 번호나 설명을 붙여 답해도 거기 섞인
    말은 목록에 없으면 버려지고, 목록에 없는 말을 지어내도 들어오지 않는다.
    용언 기본형도 여기서 한 번 더 거른다 — 모델이 규칙을 놓칠 수 있다.
    """
    source = set(words)
    kept: list[str] = []
    for token in _HANGUL_WORD.findall(text):
        if token in source and token not in kept and not is_verb_form(token):
            kept.append(token)
    return kept


def plausible(kept: list[str], words: list[str]) -> bool:
    ratio = len(kept) / len(words) if words else 0
    return PLAUSIBLE_LOW <= ratio <= PLAUSIBLE_HIGH


def judge(length: int, workers: int, redo: bool, model: str) -> int:
    """덩어리마다 하이쿠에게 '있는 단어' 를 고르게 해 keep 파일로 남긴다.

    **이미 판정한 덩어리는 건너뛴다**(``--redo`` 가 아니면). 한도에 걸리거나
    중간에 끊겨도 같은 명령을 다시 돌리면 남은 것만 한다.

    비율이 그럴듯한 구간을 벗어나면 한 번 더 묻는다. 두 번째도 벗어나면 그대로
    쓰되 표시해 둔다 — 원본이 정말 부실한 덩어리일 수도 있어서, 기계가 버리지
    않고 사람이 보게 한다.
    """
    from haiku import HaikuError, ask

    out = CHUNKS / str(length)
    pieces = sorted(out.glob("*.txt"))
    if not pieces:
        print(f"덩어리가 없습니다. 먼저 split 하세요: {out}")
        return 1
    todo = [p for p in pieces if redo or not p.with_suffix(".keep").exists()]
    print(f"{length}자모: 덩어리 {len(pieces)}개 중 {len(todo)}개 판정", flush=True)

    def work(piece: Path) -> str:
        words = read_lines(piece)
        prompt = ALLOWED_PROMPT.replace("{words}", "\n".join(words))
        kept: list[str] | None = None
        last_error = ""
        for _ in range(2):
            try:
                kept = parse_kept(ask(prompt, model=model), words)
            except HaikuError as error:
                last_error = str(error)
                continue
            if plausible(kept, words):
                break
        if kept is None:
            return f"실패: {last_error}"
        piece.with_suffix(".keep").write_text(
            "".join(f"{w}\n" for w in kept), encoding="utf-8"
        )
        mark = "" if plausible(kept, words) else "  ← 비율이 이상함, 눈으로 볼 것"
        return f"{len(words)} → {len(kept)} ({len(kept) / len(words):.0%}){mark}"

    failed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, piece): piece for piece in todo}
        for done, future in enumerate(as_completed(futures), 1):
            result = future.result()
            failed += result.startswith("실패")
            stem = futures[future].stem
            print(f"  [{done}/{len(todo)}] {length}/{stem}: {result}", flush=True)
    if failed:
        print(f"{length}자모: 실패 {failed}개. 같은 명령을 다시 돌리면 그것만 합니다.")
    return 1 if failed else 0


def judge_answers(length: int, model: str) -> int:
    """정답 사전을 하이쿠에게 검토받아 ``vet/answers-<n>.review`` 로 남긴다.

    **사전을 직접 고치지 않는다.** 정답은 매일 사람들이 마주하는 말이라, 뺄지
    말지는 결과를 사람이 한 번 보고 정한다. 여기서는 판정과 이유만 적는다.

    답에서 빠뜨린 낱말은 그것만 모아 한 번 더 묻는다. 긴 목록을 한 번에 주면
    모델이 뒤쪽 몇 개를 조용히 건너뛰곤 한다.
    """
    from haiku import HaikuError, ask

    words = read_lines(DATA / f"words-{length}.txt")
    verdicts: dict[str, tuple[str, str]] = {}
    pending = list(words)
    for _ in range(3):
        if not pending:
            break
        try:
            prompt = ANSWER_PROMPT.replace("{words}", "\n".join(pending))
            reply = ask(prompt, model=model)
        except HaikuError as error:
            print(f"{length}자모 정답 검토 실패: {error}")
            continue
        for line in reply.splitlines():
            match = _VERDICT_LINE.match(line)
            if match and match.group(1) in pending:
                verdicts[match.group(1)] = (match.group(2), match.group(3).strip(" |"))
        pending = [w for w in words if w not in verdicts]

    CHUNKS.mkdir(parents=True, exist_ok=True)
    out = CHUNKS / f"answers-{length}.review"
    lines = []
    for word in words:
        verdict, reason = verdicts.get(word, ("판정없음", ""))
        lines.append(f"{word}\t{verdict}\t{reason}".rstrip())
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    dropped = [w for w in words if verdicts.get(w, ("",))[0] == "제외"]
    print(
        f"{length}자모 정답 {len(words)}개: 제외 제안 {len(dropped)}개,"
        f" 판정없음 {len(pending)}개 → {out.name}"
    )
    for word in dropped:
        print(f"  - {word}: {verdicts[word][1]}")
    return 1 if pending else 0


#: 1차 판정에서 빠졌지만 빈도표(실제 대화)에 나오는 말을 한 번 더 볼 때의 기준.
#:
#: 하이쿠 1차 판정은 대체로 옳게 뺐지만(조사 붙은 꼴·고유명사·용언·욕설), 8자모에서
#: '다이어트', '사기꾼', '시멘트', '속임수' 같은 흔한 명사도 뺐다. 이런 말이 빠지면
#: 사람이 멀쩡한 말을 쳐도 거절된다. 그래서 **빠진 말 중 실제로 쓰이는 것만** 추려
#: 소넷에게 한 번 더 묻는다. 몇만 개 전체가 아니라 수백 개라 비용이 작다.
#:
#: 예시는 판정할 목록과 상관없는 말로 든다.
RESCUE_PROMPT = """너는 한국어 낱말 맞히기 게임의 사전을 검토한다.
아래는 1차 판정에서 빠졌지만 실제 대화에 자주 나오는 말들이다.
이 중 추측으로 받아 줘야 할 낱말만 골라라.

남긴다: 일상 명사, 흔한 합성어·파생어, 널리 쓰는 외래어 (예: 칫솔, 가습기, 노트북)
뺀다:
- 조사나 어미가 붙은 꼴 (예: 무엇의, 사람도, 한다는, 빠르게)
- 동사·형용사, 부사, 감탄사
- 사람 이름·땅 이름 같은 고유명사
- 욕설·비속어

출력 규칙: 목록에 있는 낱말만, 한 줄에 하나씩. 번호·설명·머리말 없이.
남길 것이 하나도 없으면 NONE 한 줄만 쓴다.

목록:
{words}
"""

#: 되살린 말을 모아 두는 파일. 덩어리(*.txt)로 읽히지 않게 확장자를 .keep 으로 둔다.
RESCUE_FILE = "rescued.keep"

#: 한 번에 묻는 낱말 수.
RESCUE_BATCH = 300


def frequency_words() -> set[str]:
    """빈도표(자막 말뭉치)에 나오는 말. 첫 칸이 낱말이다."""
    path = DATA / "korean-frequency.txt"
    if not path.exists():
        return set()
    lines = path.read_text(encoding="utf-8").splitlines()
    return {line.split()[0] for line in lines if line.strip()}


def rescue(length: int, model: str) -> int:
    """1차 판정에서 빠졌지만 빈도표에 있는 말을 한 번 더 묻는다.

    **1차 판정이 전부 끝나야 돈다.** 끝나지 않은 덩어리가 있으면 빠진 말을
    제대로 셀 수 없다. 묶음 하나라도 실패하면 되살린 목록을 쓰지 않는다 —
    반쯤 되살린 목록으로 apply 하면 어느 말이 빠졌는지 알 수 없게 된다.
    """
    from haiku import HaikuError, ask

    out = CHUNKS / str(length)
    pieces = sorted(out.glob("*.txt"))
    unfinished = [p for p in pieces if not p.with_suffix(".keep").exists()]
    if not pieces or unfinished:
        left = len(unfinished)
        print(f"{length}자모: 1차 판정이 안 끝났습니다 (남은 덩어리 {left}개).")
        return 1

    common = frequency_words()
    candidates: list[str] = []
    for piece in pieces:
        kept = set(read_lines(piece.with_suffix(".keep")))
        for word in read_lines(piece):
            if word not in kept and word in common and not is_verb_form(word):
                candidates.append(word)
    print(
        f"{length}자모: 빠졌지만 빈도표에 있는 말 {len(candidates)}개를"
        f" {model} 에게 다시 묻습니다.",
        flush=True,
    )

    rescued: list[str] = []
    for start in range(0, len(candidates), RESCUE_BATCH):
        part = candidates[start : start + RESCUE_BATCH]
        prompt = RESCUE_PROMPT.replace("{words}", "\n".join(part))
        try:
            reply = ask(prompt, model=model)
        except HaikuError as error:
            print(f"{length}자모: 실패해서 되살린 목록을 쓰지 않습니다 — {error}")
            return 1
        got = parse_kept(reply, part)
        rescued.extend(got)
        number = start // RESCUE_BATCH + 1
        sample = " ".join(got[:15])
        print(f"  [{number}] {len(part)} → {len(got)}: {sample}", flush=True)

    (out / RESCUE_FILE).write_text("".join(f"{w}\n" for w in rescued), encoding="utf-8")
    print(f"{length}자모: {len(rescued)}개 되살림 → {RESCUE_FILE}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["split", "apply", "check", "judge", "answers", "rescue"],
    )
    parser.add_argument("--length", type=int, nargs="+", required=True)
    parser.add_argument(
        "--workers", type=int, default=4, help="judge: 동시에 부를 하이쿠 수"
    )
    parser.add_argument(
        "--redo", action="store_true", help="judge: 판정한 덩어리도 다시"
    )
    parser.add_argument(
        "--model",
        default=None,
        help="모델. 기본은 judge=haiku, answers·rescue=sonnet",
    )
    args = parser.parse_args()

    worst = 0
    for length in args.length:
        if args.command == "judge":
            code = judge(length, args.workers, args.redo, args.model or "haiku")
        elif args.command == "answers":
            code = judge_answers(length, args.model or "sonnet")
        elif args.command == "rescue":
            code = rescue(length, args.model or "sonnet")
        else:
            simple = {"split": split, "apply": apply, "check": check}
            code = simple[args.command](length)
        worst = max(worst, code)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
