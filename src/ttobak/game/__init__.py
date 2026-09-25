"""게임 규칙, 라운드별 문제 선정, 진행 서비스."""

from ttobak.game.rounds import Puzzle, puzzle_for_round
from ttobak.game.rules import Mark, keyboard_state, score_guess
from ttobak.game.service import GameService, GameView, InvalidGuessError
from ttobak.game.share import build_share_text, tier_badge
from ttobak.game.support import (
    SUPPORT_PROVIDERS,
    SUPPORT_TIERS,
    SupportProvider,
    SupportTier,
)
from ttobak.game.themes import DEFAULT_THEME, THEMES, get_theme, theme_choices
from ttobak.game.titles import assign_titles, rank_medal

__all__ = [
    "GameService",
    "GameView",
    "InvalidGuessError",
    "Mark",
    "Puzzle",
    "DEFAULT_THEME",
    "SUPPORT_PROVIDERS",
    "SUPPORT_TIERS",
    "THEMES",
    "assign_titles",
    "build_share_text",
    "get_theme",
    "rank_medal",
    "theme_choices",
    "tier_badge",
    "keyboard_state",
    "SupportProvider",
    "SupportTier",
    "puzzle_for_day",
    "puzzle_for_round",
    "score_guess",
]
