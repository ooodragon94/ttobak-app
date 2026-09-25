"""단어 사전 로딩과 조회.

사전은 두 갈래로 나뉜다. 낱말 맞히기 게임이 공통으로 쓰는 구조다.

**정답 사전** (``data/words-<길이>.txt``)
    출제될 수 있는 단어. 사람이 골라 관리하는 목록이라 누구나 아는 말만 들어
    있다. 여기에 사전 전체를 넣으면 '각골지통' 같은 단어가 정답으로 나와
    아무도 못 맞힌다.

**입력 허용 사전** (``data/allowed-<길이>.txt``)
    추측으로 받아 줄 단어. 훨씬 넓다. 이게 좁으면 '원래'처럼 멀쩡한 단어를
    쳤는데 "사전에 없는 단어"라고 거절당해 게임이 망가진다.

**사용자 추가 사전** (``data/extra-allowed.txt``)
    공개 단어 목록에 빠진 말을 손으로 채워 넣는 곳. '타다키' 같은 외래어나
    신조어는 국어사전 기반 목록에 없다. 사전을 다시 빌드해도 이 파일은
    덮어쓰이지 않으므로, 플레이하다 막힌 단어를 여기 적어 두면 된다.
    길이는 자동으로 판별하므로 한 파일에 몰아 적으면 된다.

정답 사전은 허용 사전에 자동으로 합쳐지므로, 정답이 거절되는 일은 구조적으로
생기지 않는다.

게임은 자모 나열만 다루므로 조회 키는 단어를 분해해 이어붙인 자모 문자열이다.
서로 다른 단어가 같은 자모 나열을 가질 수 있어 키 하나에 여러 단어가 매달린다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ttobak.hangul import decompose, jamo_key

__all__ = [
    "Lexicon",
    "WordList",
    "load_lexicon",
    "normalize_guess",
]


def _read_words(path: Path) -> list[str]:
    """주석과 빈 줄을 걷어내고 단어 목록을 읽는다."""
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


@dataclass(frozen=True)
class WordList:
    """자모 길이가 같은 단어들의 사전."""

    length: int
    #: 출제 후보. 사전 순으로 고정해 두어 출제 순서를 재현할 수 있다.
    words: tuple[str, ...]
    #: 추측으로 받아 줄 자모 키 전체. 정답 사전도 여기 포함된다.
    allowed_keys: frozenset[str]
    #: 자모 키 -> 그 나열을 갖는 단어들. 화면에 단어를 되짚어 보여 줄 때 쓴다.
    by_key: dict[str, tuple[str, ...]]

    @classmethod
    def load(
        cls,
        length: int,
        answers_path: Path,
        allowed_path: Path | None,
        extra_path: Path | None = None,
    ) -> WordList:
        """정답 사전과 허용 사전을 읽어 ``WordList``를 만든다.

        :param allowed_path: 없거나 파일이 존재하지 않으면 정답 사전만 허용한다.
        :param extra_path: 사용자가 손으로 추가한 단어 파일. 길이가 다른 단어가
            섞여 있어도 되며, 맞는 것만 걸러 쓴다.
        :raises ValueError: 정답 사전이 비었거나 길이가 다른 단어가 섞였을 때.
        """
        answers = sorted(set(_read_words(answers_path)))
        if not answers:
            raise ValueError(f"정답 사전이 비어 있습니다: {answers_path}")

        by_key: dict[str, list[str]] = {}

        def add(word: str, source: Path) -> str:
            jamos = decompose(word)
            if len(jamos) != length:
                raise ValueError(
                    f"{source.name} 안에 길이가 섞여 있습니다: "
                    f"{word}는 {len(jamos)}자모인데 {length}자모 사전입니다."
                )
            key = "".join(jamos)
            by_key.setdefault(key, []).append(word)
            return key

        answer_keys = {add(word, answers_path) for word in answers}

        allowed_keys = set(answer_keys)
        for source in (allowed_path, extra_path):
            if source is None or not source.exists():
                continue
            for word in _read_words(source):
                try:
                    allowed_keys.add(add(word, source))
                except ValueError:
                    # 허용 사전은 외부에서 받아 온 큰 목록이고, 사용자 추가
                    # 사전에는 길이가 다른 단어가 섞여 있는 것이 정상이다.
                    # 한 줄 때문에 서버가 못 뜨면 곤란하므로 조용히 건너뛴다.
                    continue

        return cls(
            length=length,
            words=tuple(answers),
            allowed_keys=frozenset(allowed_keys),
            by_key={key: tuple(dict.fromkeys(value)) for key, value in by_key.items()},
        )

    def contains(self, jamos: str) -> bool:
        """``jamos`` 나열을 추측으로 받아 줄지 확인한다."""
        return jamos in self.allowed_keys

    def words_for(self, jamos: str) -> tuple[str, ...]:
        """``jamos`` 나열에 해당하는 단어들. 없으면 빈 튜플."""
        return self.by_key.get(jamos, ())

    def __len__(self) -> int:
        return len(self.words)


#: 규칙으로 붙여 주는 뒷가지들.
#:
#: 국어사전은 이런 말을 표제어로 싣지 않는다. **규칙으로 만들어지기 때문**이다 —
#: '친구들' 을 싣기 시작하면 모든 명사의 복수형을 실어야 한다. 그래서 아무리 큰
#: 사전을 가져와도 이 부류는 영원히 빠져 있고, 목록에 한 개씩 더하는 방식으로는
#: 절대 못 따라잡는다. 실제로 36만 단어짜리 사전을 쓰는데도 '친구들', '택시비',
#: '치킨집' 이 전부 없었다.


@dataclass(frozen=True)
class Lexicon:
    """길이별 사전을 한데 묶은 컨테이너."""

    by_length: dict[int, WordList]

    @property
    def lengths(self) -> tuple[int, ...]:
        return tuple(sorted(self.by_length))

    def accepts(self, jamos: str, length: int) -> bool:
        """이 자모 나열을 추측으로 받아 줄지. **사전에 있는 말만 받는다.**

        한때 규칙으로 넓혔다가 되돌렸다
        --------------------------------

        사전에 없는 멀쩡한 말이 꽤 있었다('탕비실', '택시비'). 한국어는 말을
        붙여 새로 만들고 국어사전은 그런 파생형을 표제어로 안 싣기 때문이다.
        그래서 "알려진 말 + 뒷가지" 를 규칙으로 받아 주게 했었다.

        **두 번 다 실패했다.**

        - '알려진 말 둘을 이어 붙이면 통과' 는 '칼두'(칼+두)를 받아 줬다.
          무작위 자모로 잰 오탐율은 0.04% 였는데, 사람은 무작위 자모를 치지
          않고 그럴듯한 음절을 친다. 시험이 현실과 달랐다.
        - 뒷가지를 열넷 두니 '정차기'(정차+기), '방가마' 가 통과했다.
          플레이하던 친구들이 바로 알아챘다.
        - 마지막에 '들' 하나만 남겼는데, 그것도 원조 게임이 받아 주지 않을
          가능성이 크다. '친구들' 은 한국어로는 맞지만 낱말 맞히기의 답으로는
          어색하다.

        규칙으로 경계를 그리려는 시도 자체가 틀렸다. **무엇이 낱말인지는
        규칙이 아니라 사전이 안다.** 빠진 말은 거절 로그
        (``tools/missing_words.py``)로 찾아 ``extra-allowed.txt`` 에 적는다.
        손이 더 가지만, 없는 말을 통과시키는 것보다 낫다.
        """
        return self.for_length(length).contains(jamos)

    def for_length(self, length: int) -> WordList:
        """``length`` 자모 사전을 돌려준다.

        :raises KeyError: 해당 길이의 사전이 없을 때.
        """
        try:
            return self.by_length[length]
        except KeyError as exc:
            available = ", ".join(str(n) for n in self.lengths)
            raise KeyError(
                f"자모 {length}개 사전이 없습니다. 사용 가능한 길이: {available}"
            ) from exc


def load_lexicon(data_dir: Path, lengths: tuple[int, ...]) -> Lexicon:
    """``data_dir``에서 요청한 길이들의 사전을 읽어 들인다.

    :raises FileNotFoundError: 정답 사전이 없을 때. ``scripts/build_words.py``로
        먼저 생성해야 한다.
    """
    by_length: dict[int, WordList] = {}
    for length in lengths:
        answers_path = data_dir / f"words-{length}.txt"
        if not answers_path.exists():
            raise FileNotFoundError(
                f"정답 사전이 없습니다: {answers_path}\n"
                f"`python scripts/build_words.py --length {length}`로 만들어 주세요."
            )
        by_length[length] = WordList.load(
            length,
            answers_path,
            data_dir / f"allowed-{length}.txt",
            data_dir / "extra-allowed.txt",
        )
    return Lexicon(by_length=by_length)


def normalize_guess(text: str) -> str:
    """사용자 입력을 자모 키로 정규화한다. 완성형/낱자 입력을 모두 받는다."""
    return jamo_key(text)
