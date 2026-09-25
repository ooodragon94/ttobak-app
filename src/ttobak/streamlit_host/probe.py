"""임시: 스트림릿 서버에서 Turso 지역마다 네트워크 왕복이 얼마인지 잰다.

Turso 를 어느 지역에 둘지 고르려고 넣은 것이다. 고르고 나면 지운다.
TCP 연결 한 번에 걸리는 시간이 곧 왕복 한 번이다. 다섯 번 재서 가장 짧은 것을 쓴다.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from urllib.parse import urlparse

REGIONS = {
    "aws-us-east-1 (버지니아)": "ec2.us-east-1.amazonaws.com",
    "aws-us-east-2 (오하이오)": "ec2.us-east-2.amazonaws.com",
    "aws-us-west-2 (오리건)": "ec2.us-west-2.amazonaws.com",
    "aws-eu-west-1 (아일랜드)": "ec2.eu-west-1.amazonaws.com",
    "aws-ap-northeast-1 (도쿄)": "ec2.ap-northeast-1.amazonaws.com",
    "aws-ap-south-1 (뭄바이)": "ec2.ap-south-1.amazonaws.com",
}

result: dict[str, float | str] = {}
_started = False
_lock = threading.Lock()


def _rtt(host: str) -> float | str:
    best = None
    for _ in range(5):
        started = time.perf_counter()
        try:
            with socket.create_connection((host, 443), timeout=5):
                pass
        except OSError as error:
            return f"실패: {error}"
        elapsed = (time.perf_counter() - started) * 1000
        best = elapsed if best is None else min(best, elapsed)
    return round(best, 1)


def _run() -> None:
    targets = dict(REGIONS)
    turso = urlparse(os.environ.get("TTOBAK_TURSO_URL", "")).hostname
    if turso:
        targets["지금 Turso"] = turso
    for name, host in targets.items():
        result[name] = _rtt(host)


def start() -> None:
    """한 번만, 뒤에서 잰다. 앱이 뜨는 것을 막지 않는다."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_run, daemon=True).start()
