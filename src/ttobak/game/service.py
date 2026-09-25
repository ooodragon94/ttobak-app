"""게임 진행을 담당하는 서비스 계층.

라우터와 저장소 사이에 놓여 '지금 판을 불러온다', '추측을 제출한다', '다음
문제로 넘어간다' 같은 업무 단위를 제공한다. HTTP를 전혀 모르므로 그대로 단위
테스트할 수 있다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from ttobak.clock import day_bounds_utc
from ttobak.db import Database, GameRecord
from ttobak.game.hard import (
    DIFFICULTIES,
    Difficulty,
    HardModeError,
    check_difficulty,
    get_difficulty,
    relaxes,
)
from ttobak.game.rounds import Puzzle, puzzle_for_round
from ttobak.game.rules import Mark, keyboard_state, score_guess
from ttobak.game.share import build_share_text
from ttobak.hangul import BASIC_JAMOS, decompose
from ttobak.words import Lexicon

__all__ = ["GameService", "GameView", "InvalidGuessError", "HINT_AFTER_ATTEMPTS"]

#: 거절된 추측을 남기는 로거. 사전에 빠진 말을 찾는 것이 목적이다.
_log = logging.getLogger(__name__)

#: 힌트를 열어 주기 시작하는 시도 횟수. 세 번 틀린 뒤부터다.
HINT_AFTER_ATTEMPTS = 3

#: 정답에서 끝까지 남겨 둘 자모 수. 힌트로 다 열리면 게임이 아니다.
HINT_KEEP_HIDDEN = 2


class InvalidGuessError(Exception):
    """추측을 받아들일 수 없을 때 던진다.

    사람이 읽을 문구와, **화면이 분기할 수 있는 짧은 이름**을 같이 담는다.
    문구만 있으면 화면은 문장을 문자열로 비교해야 하는데, 서버에서 말투를
    한 번만 다듬어도 조용히 깨진다. 실제로 "사전에 없는 단어" 일 때만
    신고 단추를 붙여야 해서 그 구분이 필요해졌다.
    """

    def __init__(self, message: str, code: str = "invalid") -> None:
        super().__init__(message)
        self.message = message
        self.code = code

    def as_detail(self) -> dict[str, str]:
        """HTTP 오류 본문에 실을 모양.

        **여기 한 곳에서만 만든다.** 혼자 푸는 판과 오늘의 문제가 각자
        만들다가, 오늘의 문제 쪽만 ``str(error)`` 로 문자열을 보냈다.
        그러면 ``code`` 가 사라져서 화면이 "사전에 없는 단어" 를 알아보지
        못하고, 신고 단추가 안 붙었다.
        """
        return {"message": self.message, "code": self.code}


@dataclass(frozen=True)
class GameView:
    """클라이언트에 내려보낼 게임 상태 한 벌.

    진행 중에는 ``answer``가 ``None``이다. 정답은 판이 끝난 뒤에만 채워진다.
    브라우저 개발자 도구를 열어도 미리 볼 수 없다는 뜻이다.
    """

    round_no: int
    length: int
    max_attempts: int
    status: str
    rows: list[dict] = field(default_factory=list)
    keyboard: dict[str, str] = field(default_factory=dict)
    answer: str | None = None
    #: 오늘 이 사람이 맞힌 문제 수. 화면 상단에 보여 준다.
    solved_today: int = 0
    #: 끝난 판의 공유 문구. 진행 중이면 ``None``.
    share_text: str | None = None
    #: 힌트로 공개된 앞자리 자모들.
    hints: list[str] = field(default_factory=list)
    #: 지금 힌트를 더 받을 수 있는지.
    hint_available: bool = False
    #: 이 판의 난이도 열쇠. 화면이 표시와 안내에 쓴다.
    difficulty: str = "normal"
    #: 앞으로 더 받을 수 있는 힌트 수.
    hints_left: int = 0

    @property
    def attempts_used(self) -> int:
        return len(self.rows)

    @property
    def attempts_left(self) -> int:
        return self.max_attempts - self.attempts_used


class GameService:
    """문제 선정 규칙과 저장소를 엮어 라운드의 흐름을 관리한다."""

    def __init__(
        self,
        database: Database,
        lexicon: Lexicon,
        *,
        lengths: tuple[int, ...],
        max_attempts: int,
        salt: str,
        share_url: str = "",
        hints_offered: bool = True,
    ) -> None:
        self._database = database
        self._lexicon = lexicon
        self._lengths = lengths
        self._max_attempts = max_attempts
        self._salt = salt
        self._share_url = share_url
        self._hints_offered = hints_offered

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    @property
    def lexicon(self) -> Lexicon:
        """사전. 오늘의 문제(방)도 같은 사전으로 출제해야 한다.

        방 쪽에서 사전을 따로 읽으면 두 벌이 메모리에 뜨고, 더 나쁘게는
        사전을 갱신했을 때 한쪽만 바뀌어 '일반 게임에서는 되는데 오늘의
        문제에서는 사전에 없다는 단어'가 생긴다.
        """
        return self._lexicon

    def validate_guess(self, raw_guess: str, answer: str) -> str:
        """추측을 검증해 정규화된 자모 키로 돌려준다.

        :raises InvalidGuessError: 자판에 없는 글자, 길이 불일치, 사전에 없는
            단어일 때.

        :meth:`submit` 은 저장소까지 건드리지만 이 메서드는 **검증만** 한다.
        방의 오늘의 문제는 판을 다른 표에 저장하므로 검증 규칙만 필요하다.
        규칙을 그쪽에 복사하면 두 곳이 어긋나서, 같은 단어가 한쪽에서만
        받아들여지는 일이 생긴다.
        """
        return self._validate(raw_guess, answer)

    #: 시도 횟수로 고를 수 있는 범위.
    #:
    #: 기본(6)에서 두 번 줄이고 한 번 늘릴 수 있다. 아래로 더 내리면 운에
    #: 가까워지고(자모 8칸을 3번에 맞히는 것은 실력이 아니다), 위로 더 올리면
    #: 거의 다 맞혀서 순위표가 의미를 잃는다.
    ATTEMPT_CHOICES = (4, 5, 6, 7)

    @staticmethod
    def _hint_slots(
        record: GameRecord, answer_jamos: tuple[str, ...], rows: list[dict]
    ) -> list[str | None]:
        """힌트로 열린 자리들. 칸 수만큼의 목록이고, 안 열린 자리는 ``None``.

        **이미 맞힌 자리는 열지 않는다.**

        전에는 앞에서부터 그냥 ``정답[:쓴 개수]`` 를 줬다. 그래서 첫 글자를
        이미 초록으로 맞힌 사람이 힌트를 쓰면 **그 초록 글자를 다시 알려
        줬다.** 힌트를 쓰고도 아무것도 못 얻는 것이라, 실제로 "이미 맞춘 걸
        힌트로 준다" 는 항의를 받았다.

        지금은 **아직 못 맞힌 자리 중 가장 왼쪽**부터 연다. 위치를 함께
        돌려주므로 화면이 "몇 번째 칸이 무엇인지" 를 그대로 보여 줄 수 있다.
        """
        length = len(answer_jamos)
        # 지금까지 초록으로 확정한 자리.
        solved = {
            index
            for row in rows
            for index, mark in enumerate(row["marks"])
            if mark == Mark.CORRECT.value
        }
        # 아직 모르는 자리를 왼쪽부터. 여기서 앞의 몇 개를 연다.
        unknown = [index for index in range(length) if index not in solved]
        opened = set(unknown[: record.hints_used])
        return [
            answer_jamos[index] if index in opened else None
            for index in range(length)
        ]

    def hint_allowance_for(
        self, player_id: str, attempts: int, length: int
    ) -> int:
        """시도 횟수와 칸 수만으로 힌트 상한을 낸다.

        일반 라운드와 오늘의 문제가 **같은 규칙**을 써야 한다. 규칙이 두 벌이
        되면 "여기선 되는데 저기선 안 되네" 가 되고, 그게 왜인지 아무도 설명
        못 한다. 그래서 판의 종류에 안 매인 형태로 뽑아 둔다.
        """
        if not self._hints_offered or not self._player_wants_hints(player_id):
            return 0
        earned = max(0, attempts - HINT_AFTER_ATTEMPTS + 1)
        ceiling = max(0, length - HINT_KEEP_HIDDEN)
        return min(earned, ceiling)

    @staticmethod
    def hint_slots_for(
        hints_used: int, answer_jamos: tuple[str, ...], rows: list[dict]
    ) -> list[str | None]:
        """힌트로 열린 자리들. 판 종류를 안 가린다.

        **이미 맞힌 자리는 열지 않는다** — 초록으로 맞힌 글자를 힌트로 다시
        알려 주면 힌트를 쓰고도 아무것도 못 얻는다(실제로 항의를 받았다).
        """
        length = len(answer_jamos)
        solved = {
            index
            for row in rows
            for index, mark in enumerate(row["marks"])
            if mark == Mark.CORRECT.value
        }
        unknown = [index for index in range(length) if index not in solved]
        opened = set(unknown[:hints_used])
        return [
            answer_jamos[index] if index in opened else None
            for index in range(length)
        ]

    def _record_attempts(self, record: GameRecord) -> int:
        """이 **판**에 적용되는 시도 횟수.

        판이 열릴 때 박아 둔 값을 쓴다. 없으면(이 기능 이전의 옛 판) 서버
        기본값이다. 지금 설정을 보지 않는 것이 핵심이다 — 풀던 판의 규칙이
        중간에 바뀌면 안 된다.
        """
        return record.max_attempts or self._max_attempts

    def _difficulty_for(self, player_id: str) -> Difficulty:
        """이 사람이 고른 난이도. 고른 적이 없으면 기본 난이도."""
        player = self._database.get_player(player_id)
        return get_difficulty(player.difficulty if player else None)

    def _attempts_for(self, player_id: str) -> int:
        """이 사람이 쓸 시도 횟수. 고른 것이 없으면 서버 기본값."""
        player = self._database.get_player(player_id)
        chosen = player.max_attempts if player else None
        if chosen in self.ATTEMPT_CHOICES:
            return chosen
        return self._max_attempts

    def _lengths_for(self, player_id: str) -> tuple[int, ...]:
        """이 사람이 풀기로 한 자모 길이들.

        고른 것이 없거나(설정을 건드린 적 없음) 사전에 없는 값만 골랐다면
        서버 기본값 전부를 쓴다. **빈 목록을 그대로 쓰면 낼 문제가 없어
        게임이 멈춘다.**
        """
        player = self._database.get_player(player_id)
        chosen = player.puzzle_lengths if player else None
        if not chosen:
            return self._lengths
        usable = tuple(n for n in chosen if n in self._lengths)
        return usable or self._lengths

    def puzzle(self, player_id: str, round_no: int) -> Puzzle:
        """``player_id``의 ``round_no``번째 문제. 항상 같은 값이 나온다.

        길이 후보가 사람마다 다를 수 있다. 후보가 바뀌면 그 뒤의 출제 순서도
        바뀌지만, **진행 중이던 판은 정답을 이미 저장해 두었으므로 영향을
        받지 않는다.** 설정을 바꿨다고 풀던 문제가 갈리면 안 된다.
        """
        return puzzle_for_round(
            player_id,
            round_no,
            self._lexicon,
            lengths=self._lengths_for(player_id),
            salt=self._salt,
        )

    def load(self, player_id: str, today: date) -> GameView:
        """지금 풀고 있는 판을 불러온다.

        한 판도 시작한 적이 없으면 0번 라운드를 연다. 마지막 판이 아직 끝나지
        않았다면 그 판을 그대로 이어서 준다. 여기서 자동으로 다음 문제를 열지
        않는 이유는, 끝난 판의 결과 화면을 사용자가 확인할 시간이 필요하기
        때문이다. 다음 문제는 ``advance``로 명시적으로 넘어간다.
        """
        record = self._database.latest_game(player_id)
        if record is None:
            record = self._open_round(player_id, 0, today)
        return self._to_view(player_id, record, today)

    def round_at_risk(self, player_id: str) -> bool:
        """지금 난이도를 바꾸면 풀던 판을 잃는가.

        한 번이라도 친 진행 중인 판이 있을 때만 참이다. 화면은 이때만 확인을
        받는다 — 잃을 것이 없는데 매번 물으면 잔소리가 되고, 잔소리는 읽히지
        않아서 정작 중요한 순간에도 그냥 눌러 버리게 만든다.

        **내리는 쪽은 위험하지 않다.** 규칙을 빼기만 하는 변경은 판을 그대로
        두고 난이도만 갈아 주므로 잃을 것이 없다. 여기서 그 경우까지 참으로
        내면, 아무 일도 안 일어나는데 "판을 잃는다" 고 겁을 주게 된다.
        """
        return bool(self.costly_difficulties(player_id))

    def costly_difficulties(self, player_id: str) -> tuple[str, ...]:
        """지금 고르면 **풀던 판을 잃는** 난이도들.

        화면은 "바꾸시겠습니까" 를 누르기 **전에** 물어야 하므로, 참/거짓
        하나로는 모자란다. 어느 쪽으로 바꾸느냐에 따라 답이 다르기 때문이다.
        불닭에서 보통으로 내리는 것은 공짜고, 보통에서 불닭으로 올리는 것은
        판을 잃는다. 그래서 **목록**으로 답한다.

        판정을 서버에 두는 이유: 화면이 같은 규칙을 한 벌 더 갖게 되면
        언젠가 한쪽만 고쳐진다. 그러면 안 물어보고 판을 날리거나, 잃을 것도
        없는데 겁을 주게 된다.
        """
        record = self._database.latest_game(player_id)
        if not (record and not record.is_finished and record.guesses):
            return ()
        now = get_difficulty(record.difficulty)
        return tuple(d.key for d in DIFFICULTIES if not relaxes(d, now))

    def apply_difficulty(self, player_id: str, today: date) -> GameView:
        """난이도를 바꾼 뒤의 판 상태를 돌려준다. 필요하면 판을 새로 연다.

        판에는 시작할 때의 난이도가 박혀 있어서, 설정만 바꾸면 **진행 중인
        판은 그대로 옛 난이도로 남는다.** 그건 다 풀고 나서 난이도를 올려
        자랑하는 것을 막기 위한 장치인데, 반대 방향으로는 덫이 된다 —
        불닭모드로 시작했다가 노말로 되돌려도 그 판은 계속 불닭이다.

        더 나쁜 경우도 있다. 불닭모드는 초록 자리 고정과 노랑 자모 포함을
        동시에 요구해서, **조건을 만족하는 단어가 사전에 하나도 없는 상태**가
        될 수 있다. 그러면 무엇을 쳐도 거절당하고, 거절당하니 시도 횟수도
        안 줄어서 **지지도 못한 채 그 판에 갇힌다.**

        그래서 난이도를 바꾸면 판을 정리해 준다.

        - 아직 한 번도 안 쳤으면 **그 판의 난이도만 바꾼다.** 잃을 것이 없다.
        - 이미 쳤으면 그 판을 **패배로 적고 새 단어로 새 판을 연다.**

        친 뒤에 패배로 적는 이유는 그러지 않으면 어려운 단어를 만날 때마다
        난이도를 껐다 켜서 넘길 수 있기 때문이다. 같은 단어를 두고 판만
        비우는 것도 안 된다 — 알아낸 것을 그대로 다시 치면 시도 횟수가
        사실상 무한이 된다.
        """
        record = self._database.latest_game(player_id)
        wanted = self._difficulty_for(player_id)

        if record is None:
            return self.load(player_id, today)
        if record.difficulty == wanted.key:
            return self._to_view(player_id, record, today)

        if record.is_finished:
            # 끝난 판은 건드리지 않는다. 기록이고, 다음 판부터 적용된다.
            return self._to_view(player_id, record, today)

        # 판을 그대로 두고 난이도만 갈아 주는 두 경우.
        #
        #  - 아직 한 번도 안 쳤다. 잃을 것이 없다.
        #  - **규칙을 빼기만 한다**(불닭 → 보통 등). 느슨해지는 쪽으로는
        #    자랑거리가 안 생긴다. 판에 박히는 난이도도 같이 낮아지므로
        #    공유 문구가 "불닭으로 풀었다" 고 거짓말하지 않는다.
        #
        # 두 번째를 안 두었다가 항의를 받았다. 불닭모드에서 사전에 후보가
        # 하나도 없어 갇혔는데, 빠져나오려고 난이도를 내리니 풀던 판까지
        # 없어졌다. 게다가 그 사람은 불닭을 **고른 적이 없었다** — 옛
        # 켬/끔 하드모드가 자동으로 불닭으로 옮겨진 계정이었다.
        relaxed = relaxes(wanted, get_difficulty(record.difficulty))
        if not record.guesses or relaxed:
            updated = self._database.set_game_difficulty(
                player_id, record.round_no, wanted.key,
                # 느슨해지는 쪽이면 이미 친 판이어도 갈아 준다.
                require_untouched=not relaxed,
            )
            return self._to_view(player_id, updated or record, today)

        return self._abandon_and_open(player_id, record, today)

    def _abandon_and_open(
        self, player_id: str, record: GameRecord, today: date
    ) -> GameView:
        """풀던 판을 패배로 닫고 다음 판을 연다.

        난이도를 바꿀 때와 직접 포기할 때가 같은 일을 한다. 두 벌로 두면
        한쪽만 고쳐져서 "난이도로 넘길 때는 기록에 남는데 포기로 넘길 때는
        안 남는" 식의 어긋남이 생긴다.
        """
        self._database.abandon_round(player_id, record.round_no)
        fresh = self._open_round(player_id, record.round_no + 1, today)
        return self._to_view(player_id, fresh, today)

    def resign(self, player_id: str, today: date) -> GameView:
        """지금 판을 포기한다. **끝난 판 그대로**를 돌려준다.

        여기서 다음 문제를 바로 열지 않는 것이 중요하다. 포기한 사람이 제일
        먼저 궁금한 것은 **정답이 뭐였나**이고, 새 판을 바로 띄우면 그걸 볼
        기회가 사라진다. 진 판을 그대로 보여 주면 정답과 공유 문구가 함께
        나오고, 평소처럼 "다음 문제" 를 눌러 넘어가면 된다 — 화면 흐름이
        졌을 때와 똑같아서 따로 배울 것도 없다.

        **패배로 적는다.** 그러지 않으면 어려운 단어를 만날 때마다 포기해서
        쉬운 것만 골라 풀 수 있고, 그러면 승률과 평균 시도 횟수가 아무 뜻도
        없는 숫자가 된다. 순위표를 걸어 둔 게임에서는 특히 그렇다.

        그래도 포기할 길은 있어야 한다. 막힌 판에 갇혀 있으면 그날 게임을
        아예 안 하게 되는데, 그건 패배 한 번보다 훨씬 나쁘다.
        """
        record = self._database.latest_game(player_id)
        if record is None:
            return self.load(player_id, today)
        if record.is_finished:
            # 이미 끝난 판이면 포기할 것이 없다. 그대로 보여 준다.
            return self._to_view(player_id, record, today)
        given_up = self._database.abandon_round(player_id, record.round_no)
        return self._to_view(player_id, given_up or record, today)

    def advance(self, player_id: str, today: date) -> GameView:
        """다음 문제를 연다.

        아직 진행 중인 판이 있으면 넘어가지 않고 그 판을 돌려준다. 어려운 문제를
        건너뛰어 통계를 부풀리는 일을 막기 위해서다.
        """
        record = self._database.latest_game(player_id)
        if record is None:
            record = self._open_round(player_id, 0, today)
        elif record.is_finished:
            record = self._open_round(player_id, record.round_no + 1, today)
        return self._to_view(player_id, record, today)

    def submit(self, player_id: str, raw_guess: str, today: date) -> GameView:
        """추측 하나를 채점해 저장하고, 갱신된 상태를 돌려준다.

        :raises InvalidGuessError: 판이 끝났거나, 길이가 맞지 않거나, 쓸 수 없는
            자모가 섞였거나, 사전에 없는 단어일 때.
        """
        record = self._database.latest_game(player_id)
        if record is None:
            record = self._open_round(player_id, 0, today)

        if record.is_finished:
            raise InvalidGuessError("이미 끝난 판입니다. 다음 문제로 넘어가세요.")
        allowed = self._record_attempts(record)
        if record.attempts >= allowed:
            raise InvalidGuessError("남은 기회가 없습니다.")

        guess = self._validate(raw_guess, record.answer)

        # 난이도에 따라 지금까지의 단서를 반드시 써야 한다. **판에 박아 둔
        # 값**을 보는 것이 중요하다 — 지금 설정을 보면 도중에 낮출 수 있다.
        try:
            check_difficulty(
                get_difficulty(record.difficulty),
                tuple(guess),
                [tuple(past) for past in record.guesses],
                _jamos(record.answer),
            )
        except HardModeError as error:
            raise InvalidGuessError(str(error)) from error

        guesses = (*record.guesses, guess)
        status = self._next_status(guesses, record.answer, allowed)

        updated = self._database.save_progress(
            player_id, record.round_no, guesses, status
        )
        return self._to_view(player_id, updated, today)

    def reveal_hint(self, player_id: str, today: date) -> GameView:
        """힌트를 하나 더 연다.

        :raises InvalidGuessError: 아직 조건이 안 됐거나 더 열 것이 없을 때.
        """
        if not self._hints_offered:
            raise InvalidGuessError("힌트 기능이 꺼져 있습니다.")
        if not self._player_wants_hints(player_id):
            raise InvalidGuessError("설정에서 힌트를 켜야 쓸 수 있습니다.")

        record = self._database.latest_game(player_id)
        if record is None or record.is_finished:
            raise InvalidGuessError("진행 중인 판이 없습니다.")
        difficulty = get_difficulty(record.difficulty)
        if difficulty.restricted:
            # 이 난이도들의 값어치는 "아무 도움 없이 풀었다" 는 데 있다.
            # 힌트를 허용하면 공유 문구의 난이도 표시가 의미를 잃는다.
            raise InvalidGuessError(
                f"{difficulty.label}모드에서는 힌트를 쓸 수 없어요."
            )

        allowance = self._hint_allowance(player_id, record)
        if record.attempts < HINT_AFTER_ATTEMPTS:
            remaining = HINT_AFTER_ATTEMPTS - record.attempts
            raise InvalidGuessError(f"{remaining}번 더 시도하면 힌트를 쓸 수 있습니다.")
        if record.hints_used >= allowance:
            raise InvalidGuessError("지금은 더 열 수 있는 힌트가 없습니다.")

        # 상한을 SQL 조건으로 넘긴다. 여기서 검사만 하고 넘기면 요청이 동시에
        # 올 때 전부 통과해 정답이 통째로 열린다(실제로 그랬다).
        updated = self._database.use_hint(player_id, record.round_no, allowance)
        if updated is None:
            raise InvalidGuessError("지금은 더 열 수 있는 힌트가 없습니다.")
        return self._to_view(player_id, updated, today)

    # --- 내부 구현 ---

    def _player_wants_hints(self, player_id: str) -> bool:
        """이 사람이 설정에서 힌트를 켰는지. 기본은 꺼짐이다."""
        player = self._database.get_player(player_id)
        return bool(player and player.hints_enabled)

    def _hint_allowance(self, player_id: str, record: GameRecord) -> int:
        """지금까지의 시도로 열 수 있는 힌트의 최대 개수.

        시도가 늘수록 하나씩 더 열린다. 세 번 틀리면 하나, 네 번이면 둘이다.
        헤맨 만큼만 도와주므로 처음부터 힌트로 밀고 가는 일이 생기지 않는다.

        다만 정답 길이에서 ``HINT_KEEP_HIDDEN`` 개는 끝까지 남긴다. 앞자리를
        전부 열어 버리면 맞히는 것이 아니라 받아 적는 것이 된다.
        """
        if not self._hints_offered or not self._player_wants_hints(player_id):
            return 0
        # 기본 난이도가 아니면 아예 0이다. 여기서 막아야 화면의 "남은 힌트"
        # 숫자도 0으로 나온다 — 못 쓰는 힌트가 몇 개 남았다고 적혀 있으면
        # 눌러 보고 거절당한다.
        if get_difficulty(record.difficulty).restricted:
            return 0
        earned = max(0, record.attempts - HINT_AFTER_ATTEMPTS + 1)
        ceiling = max(0, len(_jamos(record.answer)) - HINT_KEEP_HIDDEN)
        return min(earned, ceiling)

    def _open_round(self, player_id: str, round_no: int, today: date) -> GameRecord:
        """라운드를 열고 저장소에 기록한다."""
        puzzle = self.puzzle(player_id, round_no)
        return self._database.start_round(
            player_id,
            round_no,
            puzzle.answer,
            today,
            # 판을 여는 시점의 값을 박아 둔다. 이후에 설정을 바꿔도 이 판의
            # 규칙은 안 바뀐다 — 줄이면 그 자리에서 패배가 되기 때문이다.
            max_attempts=self._attempts_for(player_id),
            # 난이도도 판에 박아 둔다. 다 풀고 나서 설정을 올려
            # "불닭모드로 풀었다" 고 자랑하는 것을 막는다.
            difficulty=self._difficulty_for(player_id).key,
        )

    def _validate(self, raw_guess: str, answer: str) -> str:
        """추측 문자열을 검증해 정규화된 자모 키로 돌려준다."""
        guess = "".join(raw_guess.split())
        answer_length = len(_jamos(answer))

        unknown = {char for char in guess if char not in BASIC_JAMOS}
        if unknown:
            raise InvalidGuessError(
                "자판에 없는 글자가 있습니다: " + " ".join(sorted(unknown))
            )
        if len(guess) != answer_length:
            raise InvalidGuessError(f"자모 {answer_length}개를 채워야 합니다.")

        # 사전에 그대로 있거나, 알려진 조각으로 만들어진 말이면 받는다.
        # ('친구들', '택시비' 처럼 사전이 표제어로 안 싣는 말들.)
        #
        # **이 판의 정답은 사전과 상관없이 받는다.** 판은 시작할 때 정답을
        # 따로 저장해 두는데, 사전은 그 뒤에 바뀔 수 있다. 정답 목록을 손질하다
        # 그 낱말이 사전에서 빠지면, 풀던 사람이 정답을 정확히 쳐도 "사전에 없는
        # 단어" 로 거절돼 **그 판을 영영 못 끝낸다.** 정답과 같은 추측은 어차피
        # 맞힌 것이라, 받아 준다고 새어 나가는 것은 없다.
        is_answer = guess == "".join(_jamos(answer))
        if not is_answer and not self._lexicon.accepts(guess, answer_length):
            # 거절한 말을 남겨 둔다.
            #
            # 사전은 공개 목록에서 가져온 것이라 멀쩡한 말이 빠져 있다
            # ('휴게실' 은 있는데 '탕비실' 은 없었다). 그런데 지금까지는
            # **친구가 카톡으로 말해 줘야만** 알 수 있었다. 말 안 하고 그냥
            # 게임을 접은 사람은 셀 수도 없다.
            #
            # 자모 그대로 남긴다. 사람이 친 것이 자모라서 원래 어떤 글자를
            # 의도했는지는 서버가 알 수 없다 — 되짚는 것은 사람 몫이다.
            # 정답은 남기지 않는다. 로그를 보는 것만으로 그날 답이 새면 안 된다.
            _log.info("사전에 없어서 거절: %s (자모 %d개)", guess, answer_length)
            raise InvalidGuessError("사전에 없는 단어입니다.", code="unknown_word")
        return guess

    def _next_status(
        self, guesses: tuple[str, ...], answer: str, allowed: int
    ) -> str:
        """마지막 추측까지 반영한 게임 상태를 판정한다."""
        if guesses[-1] == "".join(_jamos(answer)):
            return "won"
        if len(guesses) >= allowed:
            return "lost"
        return "playing"

    def board(
        self, guesses: tuple[str, ...], answer: str
    ) -> tuple[list[dict], dict[str, str]]:
        """추측들을 화면이 그릴 수 있는 (줄 목록, 키보드 색)으로 바꾼다.

        일반 게임과 방의 오늘의 문제가 **이 함수를 같이 쓴다.** 판을 그리는
        규칙(칸 색, 키보드 색, 단어 이름표)을 두 벌로 두면 한쪽만 고쳐져
        어긋난다 — 같은 자모가 두 화면에서 다른 색으로 보이는 종류의 버그는
        원인을 찾기 어렵다.
        """
        answer_jamos = _jamos(answer)
        split = [list(guess) for guess in guesses]
        marks = [score_guess(guess, answer_jamos) for guess in split]

        rows = [
            {
                "jamos": guess,
                "marks": [mark.value for mark in row_marks],
                "word": self._word_label(guess),
            }
            for guess, row_marks in zip(split, marks, strict=True)
        ]
        keyboard = {
            jamo: mark.value for jamo, mark in keyboard_state(split, marks).items()
        }
        return rows, keyboard

    def _to_view(self, player_id: str, record: GameRecord, today: date) -> GameView:
        """저장된 판을 채점 결과까지 붙여 화면용 구조로 바꾼다."""
        answer_jamos = _jamos(record.answer)
        rows, keyboard = self.board(record.guesses, record.answer)
        allowance = self._hint_allowance(player_id, record)

        return GameView(
            round_no=record.round_no,
            length=len(answer_jamos),
            # 지금 설정이 아니라 **이 판**의 값이다. 화면의 줄 수와 "남은 기회"
            # 가 실제 판정과 어긋나면 안 된다.
            max_attempts=self._record_attempts(record),
            status=record.status,
            rows=rows,
            keyboard=keyboard,
            answer=record.answer if record.is_finished else None,
            solved_today=self._solved_today(player_id, today),
            share_text=self._share_text(player_id, record, rows),
            hints=self._hint_slots(record, answer_jamos, rows),
            difficulty=record.difficulty,
            # ``allowance`` 가 이미 난이도를 반영하므로 여기서 또 보지 않는다.
            # 같은 조건을 두 군데 적으면 한쪽만 고쳐져 어긋난다.
            hint_available=(
                not record.is_finished and record.hints_used < allowance
            ),
            hints_left=max(0, allowance - record.hints_used),
        )

    def _share_text(
        self, player_id: str, record: GameRecord, rows: list[dict]
    ) -> str | None:
        """끝난 판이면 채팅방에 붙여 넣을 문구를 만든다.

        진행 중에는 만들지 않는다. 아직 안 끝난 판의 색 격자를 보내면 남은 줄
        수가 드러나 힌트가 된다.

        **한 번도 안 치고 포기한 판은 공유할 격자가 없다.** 그때
        ``build_share_text`` 는 예외를 던진다(빈 격자를 지어내는 것보다 낫다).
        그런데 이 함수는 판을 보여 주는 길목에 있어서, 예외가 그대로
        올라가면 **그 판 전체가 500 이 된다.** 포기는 이미 기록된 뒤라
        그 사람은 다시 들어와도 계속 500 을 받는다 — 영영 갇힌다.

        실제로 그 사고를 냈다. 친구가 "포기했더니 아무것도 안 된다" 고
        말해 주기 전까지, 서버 로그에 ``GET /api/game 500`` 이 계속 찍히고
        있었다. 오늘의 문제 쪽은 같은 이유로 이미 막아 뒀는데 일반 판을
        빠뜨렸다.

        공유 문구가 없는 것은 아쉬운 일이고, 판을 못 보는 것은 못 쓰는 일이다.
        """
        if not record.is_finished or not rows:
            return None

        player = self._database.get_player(player_id)
        stats = self._database.player_stats(player_id)
        return build_share_text(
            nickname=player.display_name if player else player_id,
            played_on=record.played_on,
            round_no=record.round_no,
            status=record.status,
            max_attempts=self._record_attempts(record),
            marks_per_row=[row["marks"] for row in rows],
            difficulty=record.difficulty,
            played=stats.played,
            win_rate=stats.win_rate,
            average_attempts=stats.average_attempts,
            current_streak=stats.current_streak,
            hints_used=record.hints_used,
            theme_key=player.share_theme if player else None,
            url=self._share_url or None,
        )

    def _solved_today(self, player_id: str, today: date) -> int:
        """오늘 이 사람이 맞힌 문제 수.

        순위표와 같은 기준(그날 **끝낸** 판)으로 센다.
        """
        player = self._database.get_player(player_id)
        if player is None:
            return 0
        for entry in self._database.leaderboard(*day_bounds_utc(today)):
            if entry.display_name == player.display_name:
                return entry.solved
        return 0

    def _word_label(self, guess: list[str]) -> str:
        """추측한 자모 나열에 대응하는 단어. 여러 개면 첫 번째를 쓴다."""
        words = self._lexicon.for_length(len(guess)).words_for("".join(guess))
        return words[0] if words else ""


def _jamos(word: str) -> tuple[str, ...]:
    """단어를 자모 튜플로 분해한다. 서비스 안에서만 쓰는 얇은 헬퍼."""
    return tuple(decompose(word))


#: 프런트엔드가 색 이름을 문자열로 받으므로, 가능한 값을 한곳에 모아 둔다.
MARK_VALUES = tuple(mark.value for mark in Mark)
