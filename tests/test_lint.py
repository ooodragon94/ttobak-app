"""코드 검사(ruff)를 시험으로 묶는다.

2026-10-06 "AI 가 만든 티가 나는 코드" 를 잡는 규칙을 늘렸다(pyproject.toml 의
``[tool.ruff.lint]``). 규칙은 켜 두기만 하면 아무도 안 돌린다. 시험에 넣어 두면
사람이 고치든 AI 가 고치든 ``pytest`` 한 번에 같이 걸린다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_코드_검사를_통과한다() -> None:
    pytest.importorskip("ruff")
    done = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--output-format", "concise", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert done.returncode == 0, "ruff 가 지적한 것:\n" + done.stdout[-3000:]
