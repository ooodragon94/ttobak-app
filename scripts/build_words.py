"""단어 목록을 자모 길이별 사전 파일로 굽는다.

사전을 코드가 아니라 데이터로 두기 위한 빌드 단계다. 두 종류를 만든다.

``data/words-<길이>.txt`` (정답 사전)
    ``data/candidates.txt``에서 뽑는다. 사람이 관리하는 목록이라 흔한 단어만
    들어 있고, 출제는 여기서만 한다. 국어사전 전체를 정답으로 쓰면 '각골지통'
    같은 말이 나와 아무도 못 맞힌다.

``data/allowed-<길이>.txt`` (입력 허용 사전)
    큰 단어 목록에서 뽑는다. 추측으로 받아 줄 단어라 넓을수록 좋다. 좁으면
    '원래' 같은 멀쩡한 단어가 거절되어 게임이 답답해진다.

사용법::

    python scripts/build_words.py --length 5 6 7
    python scripts/build_words.py --allowed-source data/my-wordlist.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ttobak.hangul import decompose, syllable_count  # noqa: E402

DEFAULT_CANDIDATES = PROJECT_ROOT / "data" / "candidates.txt"
DEFAULT_FREQUENCY = PROJECT_ROOT / "data" / "korean-frequency.txt"
DEFAULT_ALLOWED_SOURCE = PROJECT_ROOT / "data" / "korean-wordlist-raw.txt"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data"

#: 한 글자짜리는 게임판이 너무 쉬워져 제외한다.
MIN_SYLLABLES = 2

#: 완성형 한글로만 이루어진 단어만 받는다. 숫자, 로마자, 기호는 자판에 없다.
HANGUL_ONLY = re.compile(r"^[가-힣]+$")


def read_words(path: Path) -> list[str]:
    """주석과 빈 줄을 걷어내고 단어 목록을 읽는다. 공백 구분도 허용한다."""
    words: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        words.extend(line.split())
    return words


def filter_by_jamo_length(words: list[str], length: int) -> list[str]:
    """자모 길이가 정확히 ``length``이고 2음절 이상인 한글 단어만 남긴다."""
    selected: set[str] = set()
    for word in words:
        if not HANGUL_ONLY.fullmatch(word):
            continue
        if syllable_count(word) < MIN_SYLLABLES:
            continue
        try:
            jamos = decompose(word)
        except ValueError:
            continue
        if len(jamos) == length:
            selected.add(word)
    return sorted(selected)


def load_frequency(path: Path) -> dict[str, int]:
    """단어 -> 빈도 순위(0이 가장 흔함) 표를 읽는다. 파일이 없으면 빈 표."""
    if not path.exists():
        return {}
    ranks: dict[str, int] = {}
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        parts = line.split()
        if len(parts) == 2 and HANGUL_ONLY.fullmatch(parts[0]):
            ranks.setdefault(parts[0], index)
    return ranks


def audit_frequency(words: list[str], ranks: dict[str, int], threshold: int) -> None:
    """정답 후보 중 잘 안 쓰이는 단어를 짚어 준다.

    **정답 목록은 사람이 손으로 고른다.** 빈도만으로 자동 선정하면 자막 말뭉치
    특성상 '내가', '그냥', '진짜' 같은 조사와 부사가 상위를 채워 퍼즐로 쓸 수
    없다. 품사 분석기 없이는 걸러지지 않는다.

    그래서 빈도는 **선정이 아니라 검증**에 쓴다. 손으로 고른 목록에 너무 안
    쓰이는 말이 섞이지 않았는지 확인하는 용도다. 판단은 사람이 하되 근거는
    데이터로 남긴다.
    """
    if not ranks:
        return
    rare = [w for w in words if ranks.get(w, 10**9) > threshold]
    if not rare:
        return
    print(f"    빈도 낮음 {len(rare)}개(참고): {' '.join(rare[:20])}")


def write_dictionary(path: Path, words: list[str], label: str) -> None:
    """사전 파일 하나를 쓰고 결과를 한 줄로 보고한다."""
    path.write_text("\n".join(words) + "\n", encoding="utf-8")
    print(f"  {label}: {len(words):6d}개 -> {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=DEFAULT_CANDIDATES,
        help="정답 사전을 뽑아낼 후보 목록",
    )
    parser.add_argument(
        "--allowed-source",
        type=Path,
        default=DEFAULT_ALLOWED_SOURCE,
        help="입력 허용 사전을 뽑아낼 대용량 단어 목록",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="사전 출력 위치"
    )
    parser.add_argument(
        "--length", type=int, nargs="+", default=[5, 6, 7], help="뽑아낼 자모 길이"
    )
    parser.add_argument(
        "--frequency",
        type=Path,
        default=DEFAULT_FREQUENCY,
        help="빈도 순위 파일. 정답 후보 검증에만 쓴다",
    )
    parser.add_argument(
        "--rare-threshold",
        type=int,
        default=20000,
        help="이 순위보다 뒤면 '잘 안 쓰이는 말'로 보고한다",
    )
    args = parser.parse_args()

    candidates = read_words(args.candidates)
    print(f"정답 후보 {len(candidates)}개: {args.candidates.name}")

    allowed_pool: list[str] = []
    if args.allowed_source.exists():
        allowed_pool = read_words(args.allowed_source)
        print(f"허용 후보 {len(allowed_pool)}개: {args.allowed_source.name}")
    else:
        print(f"허용 사전 원본이 없어 건너뜁니다: {args.allowed_source.name}")

    ranks = load_frequency(args.frequency)
    if ranks:
        print(f"빈도표 {len(ranks)}개: {args.frequency.name} (검증용)")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for length in args.length:
        print(f"자모 {length}개")
        answers = filter_by_jamo_length(candidates, length)
        write_dictionary(args.output_dir / f"words-{length}.txt", answers, "정답")
        audit_frequency(answers, ranks, args.rare_threshold)
        if allowed_pool:
            write_dictionary(
                args.output_dir / f"allowed-{length}.txt",
                filter_by_jamo_length(allowed_pool, length),
                "허용",
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
