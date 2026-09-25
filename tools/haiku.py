"""하이쿠(판단이 중요하면 소넷)에게 짧은 판단을 맡기는 얇은 창구.

왜 API 가 아니라 ``claude -p`` 인가
-----------------------------------

사전 거르기나 신고 판정은 **가끔 한 번씩** 도는 일이라, 그것 때문에 API 키를
새로 발급해 어딘가에 보관하는 것이 오히려 위험을 늘린다. 개발자 PC 에 이미
로그인돼 있는 Claude Code 를 그대로 쓴다.

누가 부르나
-----------

**개발자 PC 에서만 부른다.** 게임 서버에는 Claude 로그인이 없고, 있어서도 안
된다 — 게임 서버가 뚫렸을 때 딸려 가는 것이 늘어난다. 그래서 이 파일은
``tools/`` 에만 있고 서버 코드(``src/``)는 이것을 모른다.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


class HaikuError(RuntimeError):
    """하이쿠를 부르지 못했거나, 부른 쪽이 실패를 알렸을 때."""


def _claude_exe() -> str:
    """``claude`` 실행 파일 위치.

    작업 스케줄러처럼 PATH 가 짧은 곳에서 불리면 ``which`` 가 못 찾는다.
    설치 기본 위치를 한 번 더 본다.
    """
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "claude.exe"
    if fallback.exists():
        return str(fallback)
    raise HaikuError(
        "claude 실행 파일을 찾을 수 없습니다. Claude Code 가 설치돼 있어야 합니다."
    )


def ask(prompt: str, *, model: str = "haiku", timeout: int = 300) -> str:
    """프롬프트 하나를 보내고 답을 글자 그대로 받는다.

    작업 폴더를 **임시 폴더**로 둔다. 프로젝트 폴더에서 부르면 그 폴더의
    설정·기억이 같이 실려서, 낱말을 고르라는 짧은 부탁에 엉뚱한 맥락이 섞인다.
    """
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            # MCP 연결(메일·캘린더 같은 것)은 안 띄운다. 낱말 고르기에는 필요 없고,
            # 몇백 번 부르는 일이라 매번 붙는 시간이 쌓인다.
            [_claude_exe(), "-p", "--model", model, "--strict-mcp-config"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=tempfile.gettempdir(),
            creationflags=flags,
        )
    except subprocess.TimeoutExpired as error:
        raise HaikuError(f"{timeout}초 안에 답이 없었습니다.") from error
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        code = proc.returncode
        raise HaikuError(f"claude 가 실패를 알렸습니다 (코드 {code}): {detail}")
    return proc.stdout
