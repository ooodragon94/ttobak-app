"""공유 문구에 쓰는 그림 테마.

같은 결과라도 채팅방에 올라오는 모양이 사람마다 다르면 훨씬 재미있다. 그래서
네모 세 종류를 무엇으로 그릴지 고를 수 있게 했다.

테마를 데이터로 둔 이유
-----------------------
그림을 코드 여기저기에 흩어 두면 하나 추가할 때마다 여러 파일을 고쳐야 한다.
여기 딕셔너리에 한 줄 더하면 설정 화면과 공유 문구에 동시에 나타난다.

고를 때 지킨 것
---------------
- 세 그림이 **한눈에 구분**되어야 한다. 비슷한 색끼리 묶으면 격자가 안 읽힌다.
- 어두운 채팅방과 밝은 채팅방 양쪽에서 보여야 한다.
- ``cvd`` 테마는 재미가 아니라 필요해서 넣었다. 초록과 빨강을 구분하기 어려운
  사람에게 기본 테마는 읽기 힘들다. 파랑과 주황은 색각 이상에서도 가장 잘
  구분되는 조합이라 표준처럼 쓰인다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ttobak.game.rules import Mark

__all__ = ["ShareTheme", "THEMES", "DEFAULT_THEME", "get_theme", "theme_choices"]


@dataclass(frozen=True)
class ShareTheme:
    """격자를 그릴 그림 한 벌."""

    key: str
    label: str
    correct: str
    present: str
    absent: str

    def square(self, mark: Mark) -> str:
        """채점 결과 하나를 그림으로 바꾼다."""
        return {
            Mark.CORRECT: self.correct,
            Mark.PRESENT: self.present,
            Mark.ABSENT: self.absent,
        }[mark]

    @property
    def preview(self) -> str:
        """설정 화면에 보여 줄 맛보기. 정답, 자리 틀림, 없음 순서다."""
        return f"{self.correct}{self.present}{self.absent}"


#: 고를 수 있는 테마들. 여기에 한 줄 더하면 설정 화면에 바로 나타난다.
#: 딕셔너리 순서가 곧 화면에 보이는 순서다.
THEMES: dict[str, ShareTheme] = {
    theme.key: theme
    for theme in (
        ShareTheme("classic", "기본", "🟩", "🟨", "⬛"),
        ShareTheme("heart", "하트", "💚", "💛", "🖤"),
        ShareTheme("circle", "동그라미", "🟢", "🟡", "⚫"),
        ShareTheme("fruit", "과일", "🍏", "🍋", "🍇"),
        ShareTheme("moon", "달", "🌕", "🌗", "🌑"),
        ShareTheme("cvd", "색약 친화", "🟦", "🟧", "⬜"),
    )
}

#: 아무것도 고르지 않았을 때 쓰는 테마.
DEFAULT_THEME = "classic"


def get_theme(key: str | None) -> ShareTheme:
    """테마를 찾는다. 모르는 이름이면 조용히 기본값으로 돌아간다.

    저장된 설정이 나중에 없어진 테마를 가리킬 수 있다. 그때 예외를 던지면
    공유 버튼이 통째로 죽는다. 모양이 달라지는 것과 기능이 죽는 것 중에는
    전자가 훨씬 낫다.
    """
    return THEMES.get(key or DEFAULT_THEME, THEMES[DEFAULT_THEME])


def theme_choices() -> list[dict[str, str]]:
    """설정 화면에 내려보낼 테마 목록."""
    return [
        {"key": theme.key, "label": theme.label, "preview": theme.preview}
        for theme in THEMES.values()
    ]
