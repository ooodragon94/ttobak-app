"""명령줄 진입점.

``python -m ttobak`` 또는 설치 후 ``ttobak``로 서버를 띄운다. 기본값은 모든
인터페이스에 바인딩하므로, Tailscale 주소로 들어오는 접속을 그대로 받는다.
"""

from __future__ import annotations

import argparse
import logging

import uvicorn

from ttobak.config import get_settings


def main() -> int:
    settings = get_settings()

    parser = argparse.ArgumentParser(prog="ttobak", description=__doc__)
    parser.add_argument("--host", default=settings.host, help="바인딩 주소")
    parser.add_argument("--port", type=int, default=settings.port, help="바인딩 포트")
    parser.add_argument(
        "--reload", action="store_true", help="코드 변경 시 자동 재시작 (개발용)"
    )
    parser.add_argument(
        "--log-level", default="info", help="uvicorn 로그 수준 (debug/info/warning)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )

    uvicorn.run(
        "ttobak.web.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
