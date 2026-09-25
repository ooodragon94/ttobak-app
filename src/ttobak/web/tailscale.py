"""접속자의 Tailscale 신원 조회.

``tailscale whois <IP>``를 호출해 어느 기기에서 들어왔는지 알아낸다. 이 정보는
인증 수단이 아니라 편의 기능이다. 한 사람이 여러 기기를 쓰거나 여러 사람이 같은
Tailscale 계정을 공유할 수 있으므로, 실제 플레이어 구분은 닉네임으로 한다.
여기서 얻은 기기명은 처음 접속했을 때 닉네임 입력란을 채워 주는 데만 쓴다.

CLI가 없거나 실패해도 게임은 그대로 돌아가야 하므로 모든 오류는 ``None``으로
흡수한다.
"""

from __future__ import annotations

import ipaddress
import logging
import shutil
import subprocess
from dataclasses import dataclass

__all__ = ["TailscaleIdentity", "whois"]

logger = logging.getLogger(__name__)

#: whois 호출이 이 시간을 넘기면 포기한다. 페이지 로딩을 막지 않기 위함이다.
_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class TailscaleIdentity:
    """``tailscale whois``가 알려 준 접속자 정보."""

    #: 기기 이름. 예: ``dizioh-macbookpro``
    node: str | None
    #: Tailscale 계정. 예: ``someone@example.com``
    user: str | None

    @property
    def suggested_nickname(self) -> str | None:
        """닉네임 입력란에 미리 채워 넣을 만한 이름."""
        return self.node


def whois(client_ip: str, *, cli: str = "tailscale") -> TailscaleIdentity | None:
    """``client_ip``의 Tailscale 신원을 조회한다. 알 수 없으면 ``None``.

    :param client_ip: 접속자 IP. Tailscale 대역(100.x)이 아니면 조회에 실패한다.
    :param cli: ``tailscale`` 실행 파일 경로 또는 이름.
    """
    if not _is_tailnet_address(client_ip):
        # Funnel로 들어온 외부 접속은 tailnet 주소가 아니다. 조회해 봐야 실패할
        # 뿐이므로 프로세스를 띄우지 않는다. 외부에서 들어온 문자열을 하위
        # 프로세스로 넘기지 않는다는 뜻이기도 하다.
        return None

    executable = shutil.which(cli)
    if executable is None:
        logger.debug("tailscale CLI를 찾을 수 없어 whois를 건너뜁니다: %s", cli)
        return None

    try:
        completed = subprocess.run(
            [executable, "whois", client_ip],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        logger.debug("tailscale whois 실행 실패: %s", error)
        return None

    if completed.returncode != 0:
        return None
    return _parse_whois(completed.stdout)


def _is_tailnet_address(client_ip: str) -> bool:
    """``client_ip``가 Tailscale이 쓰는 대역인지 확인한다.

    Tailscale은 IPv4는 ``100.64.0.0/10``(CGNAT 대역), IPv6는 ``fd7a:115c:a1e0::/48``을
    쓴다. 이 검사를 통과한 문자열만 ``tailscale whois``에 넘긴다.

    명령은 리스트로 실행하므로 셸을 거치지 않아 명령어 주입 자체가 불가능하지만,
    외부 입력을 하위 프로세스 근처에 두지 않는 편이 안전하다. 파싱에 실패하는
    문자열도 여기서 걸러진다.
    """
    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv4Address):
        return address in ipaddress.ip_network("100.64.0.0/10")
    return address in ipaddress.ip_network("fd7a:115c:a1e0::/48")


def _parse_whois(output: str) -> TailscaleIdentity | None:
    """``tailscale whois``의 텍스트 출력을 파싱한다.

    출력은 다음과 같은 두 블록으로 이루어진다::

        Machine:
          Name:          my-laptop.tailnet.ts.net
          ...
        User:
          Name:     someone@example.com

    두 블록 모두 ``Name:``을 쓰므로 현재 어느 블록에 있는지를 추적해야 한다.
    """
    section: str | None = None
    node: str | None = None
    user: str | None = None

    for raw_line in output.splitlines():
        stripped = raw_line.strip()
        if stripped in ("Machine:", "User:", "Node:"):
            section = stripped.rstrip(":")
            continue
        if not stripped.startswith("Name:"):
            continue

        value = stripped.removeprefix("Name:").strip()
        if section == "User":
            user = value or None
        elif section in ("Machine", "Node"):
            # 전체 도메인 이름 중 첫 마디만 남겨 짧게 쓴다.
            node = value.split(".")[0] or None

    if node is None and user is None:
        return None
    return TailscaleIdentity(node=node, user=user)
