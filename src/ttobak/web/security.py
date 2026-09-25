"""공개 노출을 견디기 위한 방어 장치.

Tailscale Funnel로 인터넷에 열면 아무나 주소를 두드릴 수 있다. 게임 자체는
민감한 데이터를 다루지 않지만, 최소한 다음 세 가지는 막아야 한다.

1. 자동화된 요청 폭주로 서버와 디스크를 갉아먹는 것
2. 거대한 본문을 보내 메모리를 밀어 올리는 것
3. 닉네임에 스크립트를 심어 다른 사람 화면에서 실행시키는 것

세 번째는 프런트엔드가 모든 사용자 문자열을 ``textContent``로만 넣기 때문에
이미 구조적으로 막혀 있다. 여기서는 그 위에 콘텐츠 보안 정책을 한 겹 더 두어,
설령 어딘가에서 HTML 주입이 생기더라도 외부 스크립트가 실행되지 않게 한다.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

__all__ = [
    "PublicGZipMiddleware",
    "RateLimitMiddleware",
    "SecurityHeadersMiddleware",
    "BodySizeLimitMiddleware",
    "RateLimitRule",
]

#: 압축을 걸지 않을 경로. 앞에 붙는 것만 본다.
#:
#: **API 응답은 일부러 안 줄인다.** 압축은 크기로 내용을 흘린다(BREACH).
#: 응답 안에 비밀(복구 코드)과 공격자가 넣을 수 있는 값(닉네임)이 같이
#: 들어가면, 크기 변화를 반복해서 재어 비밀을 한 글자씩 알아낼 수 있다.
#: API 응답은 어차피 몇백 바이트라 줄여 봐야 얻는 것도 없다.
NO_COMPRESS_PREFIXES = ("/api",)

#: 이보다 작은 응답은 그냥 보낸다. 압축 헤더가 본문보다 커지는 구간이다.
MIN_COMPRESS_BYTES = 700


class PublicGZipMiddleware:
    """HTML·CSS·JS 처럼 **비밀이 없는 응답만** gzip 으로 줄인다.

    첫 방문에 102KB 를 그대로 내보내고 있었다. 카톡에 링크를 뿌려 사람이
    한꺼번에 몰리면 먼저 막히는 것이 서버가 아니라 회선이므로, 여기서
    네 배 넘게 줄여 두는 것이 가장 값싼 대비다.

    직접 압축하지 않고 Starlette 의 것을 감싸기만 한다. 압축은 스트리밍
    응답과 ``Accept-Encoding`` 협상을 제대로 다뤄야 해서 손으로 쓸 이유가
    없다. 여기서 하는 일은 **어디에 걸지 말지**를 정하는 것뿐이다.
    """

    def __init__(self, app: ASGIApp, minimum_size: int = MIN_COMPRESS_BYTES) -> None:
        self.app = app
        self._gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] == "http" and not scope["path"].startswith(
            NO_COMPRESS_PREFIXES
        ):
            await self._gzip(scope, receive, send)
            return
        await self.app(scope, receive, send)


#: 요청 본문 상한. 이 게임의 가장 큰 요청은 닉네임 20자짜리라 넉넉한 값이다.
MAX_BODY_BYTES = 8 * 1024


@dataclass(frozen=True)
class RateLimitRule:
    """``window_seconds`` 동안 허용할 최대 요청 수."""

    limit: int
    window_seconds: float
    #: 쿠키를 신원 키로 쓸지 여부.
    #:
    #: 보통은 쿠키가 가장 정확한 구분자다. 하지만 **신원을 새로 만드는 경로**
    #: 에서는 쓰면 안 된다. 매 요청마다 새 쿠키를 받아 키가 계속 바뀌므로 한도에
    #: 영원히 걸리지 않기 때문이다. 그런 경로는 접속 주소로만 센다.
    key_by_cookie: bool = True

    def __post_init__(self) -> None:
        if self.limit < 1 or self.window_seconds <= 0:
            raise ValueError("레이트리밋 값은 양수여야 합니다.")


#: 경로 접두사별 한도. 더 긴 접두사가 먼저 매칭되도록 순서대로 검사한다.
#: 추측 제출은 게임 흐름상 자주 일어나므로 여유를 두고, 참가(닉네임 생성)는
#: 계정을 무더기로 만들지 못하게 조인다.
#
#  한도는 넉넉하게 잡았다. Funnel 뒤에서 ``X-Forwarded-For``가 오지 않으면 외부
#  방문자 전원이 한 덩어리로 묶이는데, 그때 한도가 빡빡하면 친구들이 서로를
#  막아 버린다. 사람이 손으로 낼 수 있는 속도의 수십 배로 두어 정상 플레이는
#  절대 걸리지 않게 하고, 그 위의 자동화된 폭주만 잘라 낸다.
DEFAULT_RULES: tuple[tuple[str, RateLimitRule], ...] = (
    # 참가는 쿠키를 발급하는 경로라 쿠키로 세면 우회된다. 주소로만 센다.
    ("/api/join", RateLimitRule(limit=60, window_seconds=60, key_by_cookie=False)),
    ("/api/game/guess", RateLimitRule(limit=300, window_seconds=60)),
    ("/api/", RateLimitRule(limit=900, window_seconds=60)),
)

#: 전역 한도. **기본이 None(끔)이다.**
#:
#: 전에는 6000/분이었는데, 모든 방문자를 한 통에 세는 구조라 한 사람이
#: 초당 100회를 보내면 친구 전원이 429 를 받았다. 인증도 필요 없었다.
#: 막으려고 넣은 것이 서비스를 멈추는 가장 싼 방법이 되어 있었다.
#:
#: 켜고 싶으면 값을 주되, 정상 사용자 수 × 분당 요청 수보다 훨씬 크게 잡아라.
GLOBAL_RULE: RateLimitRule | None = None


class _SlidingWindow:
    """키별로 최근 요청 시각을 담아 두는 슬라이딩 윈도우 카운터.

    고정 창(fixed window) 방식은 창 경계에서 두 배까지 통과시키는 허점이 있다.
    요청 시각을 직접 들고 있으면 그 허점이 없고, 이 규모에서는 메모리도 문제가
    되지 않는다. 오래된 키는 접근할 때마다 정리한다.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, rule: RateLimitRule, now: float) -> bool:
        """``key``의 요청을 허용할지 판정하고, 허용하면 기록한다."""
        window = self._hits[key]
        cutoff = now - rule.window_seconds
        while window and window[0] <= cutoff:
            window.popleft()

        if len(window) >= rule.limit:
            return False
        window.append(now)
        return True

    def prune(self, now: float, max_window: float) -> None:
        """오래 쓰이지 않은 키를 버려 메모리가 계속 늘지 않게 한다."""
        cutoff = now - max_window
        stale = [
            key
            for key, window in self._hits.items()
            if not window or window[-1] <= cutoff
        ]
        for key in stale:
            del self._hits[key]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """경로별 요청 빈도를 제한한다.

    **키 선택이 이 미들웨어의 핵심이다.** Tailscale Funnel을 거치면 모든 요청이
    ``127.0.0.1``에서 오는 것처럼 보인다. 프록시가 tailscaled 프로세스이기
    때문이다. 그래서 접속 IP만 보고 제한하면 전 세계 방문자가 한 덩어리로 묶여,
    한 사람이 한도를 채우면 모두가 막힌다.

    그래서 다음 순서로 키를 고른다.

    1. **서명이 확인된** 플레이어 쿠키. 로그인한 사람은 이걸로 정확히 구분된다.
    2. ``CF-Connecting-IP``. Cloudflare 가 **덮어쓰는** 헤더라 위조가 안 된다.
    3. ``request.client.host``. 서버가 실제로 본 주소.

    **서명 검증이 빠져 있었고 그게 구멍이었다.** 쿠키를 문자열 그대로 키로
    쓰면 값을 매번 바꿔 보내는 것만으로 한도를 피할 수 있다. "전체 상한에서
    걸린다"고 적어 두었지만 그 전체 상한 자체가 남을 막는 무기였다.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        rules: tuple[tuple[str, RateLimitRule], ...] = DEFAULT_RULES,
        global_rule: RateLimitRule | None = GLOBAL_RULE,
        cookie_name: str = "ttobak_player",
        unsign: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__(app)
        self._rules = rules
        self._global_rule = global_rule
        self._cookie_name = cookie_name
        #: 쿠키 서명을 확인해 플레이어 id 를 꺼내는 함수. 없으면 쿠키를 안 믿는다.
        self._unsign = unsign
        self._windows = _SlidingWindow()
        self._last_prune = 0.0

    async def dispatch(self, request: Request, call_next):
        matched = self._rule_for(request.url.path)
        if matched is None:
            return await call_next(request)

        prefix, rule = matched
        now = time.monotonic()
        self._maybe_prune(now)

        # 규칙마다 창을 따로 둔다. 추측을 많이 했다고 참가가 막히면 안 된다.
        scoped_key = f"{prefix}|{self._identity(request, rule)}"

        # 전역 한도는 **기본으로 끈다.**
        #
        # 모든 방문자를 한 통에 세면 그 통이 공격 지렛대가 된다. 한 사람이
        # 초당 100회를 보내면 그 순간부터 친구 전원이 429 를 받는다. 인증도
        # 필요 없다. "최후의 안전판"으로 넣은 것이 오히려 서비스를 멈추는
        # 가장 싼 방법이었다.
        #
        # 정상 트래픽에도 걸린다. 1,000명이 분당 6회만 써도 6,000이다.
        #
        # 진짜 방어는 주체별 한도(위 scoped_key)와 Cloudflare 쪽 규칙이다.
        # 그쪽은 우리 서버에 닿기 전에 잘라 내므로 훨씬 싸다.
        if self._global_rule is not None and not self._windows.allow(
            "global", self._global_rule, now
        ):
            return _too_many_requests()
        if not self._windows.allow(scoped_key, rule, now):
            return _too_many_requests()

        return await call_next(request)

    def _rule_for(self, path: str) -> tuple[str, RateLimitRule] | None:
        """경로에 적용할 규칙. 정적 파일과 헬스체크는 제한하지 않는다."""
        for prefix, rule in self._rules:
            if path.startswith(prefix):
                return prefix, rule
        return None

    def _identity(self, request: Request, rule: RateLimitRule) -> str:
        """요청을 낼 주체를 최대한 정확히 가리키는 키.

        **여기가 틀리면 제한이 통째로 무의미해진다.** 키를 공격자가 마음대로
        바꿀 수 있으면 매 요청이 새 사람이 되어 한도에 걸리지 않는다.

        예전에는 두 가지를 그대로 믿었고 둘 다 위조 가능했다.

        1. ``X-Forwarded-For`` 의 **맨 앞** 항목. 프록시는 이 헤더를 지우지 않고
           **뒤에** 실제 주소를 덧붙인다. 즉 맨 앞은 클라이언트가 적어 보낸
           값이라 요청마다 아무 주소나 넣으면 그만이었다.
        2. **서명을 확인하지 않은 쿠키 문자열.** 쿠키를 매번 다르게 보내면
           역시 매번 새 키가 됐다.

        그래서 순서를 이렇게 바꾼다.

        - 쿠키는 **서명을 검증해서** 진짜 우리 것일 때만 쓴다. 위조한 쿠키는
          무시하고 주소로 떨어진다.
        - 주소는 Cloudflare 가 **항상 덮어쓰는** ``CF-Connecting-IP`` 를 먼저
          본다. 이 값은 클라이언트가 적어 보내도 프록시가 덮어쓴다.
        - 그다음이 ``request.client.host``. uvicorn 의 프록시 헤더 처리가
          XFF 를 오른쪽부터 훑어 넣어 준 값이라 원시 헤더보다 믿을 만하다.
        - 원시 ``X-Forwarded-For`` 는 **더 이상 읽지 않는다.**
        """
        if rule.key_by_cookie:
            player_id = self._verified_player(request)
            if player_id is not None:
                return f"p:{player_id[:64]}"

        # 프록시가 덮어쓰는 헤더만 믿는다. 클라이언트가 같은 이름으로 보내도
        # Cloudflare 가 자기 값으로 바꿔 버리므로 위조가 통하지 않는다.
        connecting = request.headers.get("cf-connecting-ip")
        if connecting:
            return f"i:{connecting.strip()[:64]}"

        client = request.client
        return f"i:{client.host if client else 'unknown'}"

    def _verified_player(self, request: Request) -> str | None:
        """쿠키에 든 플레이어 id. **서명이 맞을 때만** 돌려준다.

        서명을 확인하지 않으면 쿠키는 그냥 공격자가 정하는 문자열이고,
        그것을 한도의 키로 쓰는 것은 "제한을 걸지 말아 달라"는 요청을 그대로
        들어주는 것과 같다.
        """
        raw = request.cookies.get(self._cookie_name)
        if not raw or self._unsign is None:
            return None
        try:
            return self._unsign(raw)
        except Exception:  # noqa: BLE001 - 어떤 서명 오류든 '신원 없음'으로 본다
            return None

    def _maybe_prune(self, now: float) -> None:
        """1분에 한 번만 정리한다. 매 요청마다 훑으면 그 자체가 비용이다."""
        if now - self._last_prune < 60:
            return
        self._last_prune = now
        # 전역 규칙은 꺼져 있을 수 있다(기본값이 None). 있을 때만 함께 센다.
        windows = [rule.window_seconds for _, rule in self._rules]
        if self._global_rule is not None:
            windows.append(self._global_rule.window_seconds)
        self._windows.prune(now, max(windows) * 2)


async def _send_json(send, status: int, detail: str) -> None:
    """ASGI 수준에서 JSON 한 개를 직접 보낸다.

    ``BodySizeLimitMiddleware`` 는 순수 ASGI 라 ``JSONResponse`` 를 반환할
    자리가 없다. 응답을 손으로 조립한다.
    """
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _too_many_requests() -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요."},
        headers={"Retry-After": "30"},
    )


class BodySizeLimitMiddleware:
    """본문이 상한을 넘으면 거절한다. **실제로 흘러온 바이트를 센다.**

    왜 헤더만 보면 안 되나
    ----------------------

    전에는 ``Content-Length`` 만 봤다. 그런데 HTTP 는 그 헤더 없이도 본문을
    보낼 수 있다 — ``Transfer-Encoding: chunked`` 다. 그러면 이 검사를 그냥
    통과하고, 그 뒤에서 서버가 본문 전체를 메모리에 올린 다음 JSON 파싱을
    시도한다. 100MB 짜리를 동시에 여러 개 보내면 이 PC 의 메모리가 밀려
    올라가고, **같은 PC 에서 도는 다른 서비스까지** 함께 느려진다.

    "레이트리밋이 뒤에서 막아 준다"고 적어 뒀었는데, 레이트리밋은 요청 **수**
    를 세지 크기를 안 본다. 큰 요청 열 개는 한도에 안 걸린다.

    그래서 ASGI 수준으로 내려간다
    ------------------------------

    ``BaseHTTPMiddleware`` 는 본문을 이미 다 받은 뒤에야 손댈 수 있어서 이
    문제를 못 막는다. 여기서는 ``receive`` 를 감싸서 **덩어리가 도착할 때마다
    누적 크기를 세고**, 상한을 넘는 순간 더 읽지 않고 413 으로 끊는다.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_BODY_BYTES) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v for k, v in scope.get("headers", [])}
        declared = headers.get("content-length")
        if declared is not None:
            # 헤더가 있으면 본문을 한 바이트도 읽기 전에 끊을 수 있다. 제일 싸다.
            try:
                if int(declared) > self._max_bytes:
                    await _send_json(send, 413, "요청이 너무 큽니다.")
                    return
            except ValueError:
                await _send_json(send, 400, "잘못된 요청 헤더입니다.")
                return

        received = 0
        too_large = False

        async def limited_receive():
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    too_large = True
                    # 더 읽지 않는다. 본문을 끝까지 받아 주면 그 자체가 비용이다.
                    return {"type": "http.disconnect"}
            return message

        # 앱이 본문을 읽다가 끊기면 대개 "본문이 이상하다"며 400 을 낸다.
        # 그건 사실이 아니다 — 본문이 이상한 게 아니라 **너무 커서 우리가
        # 끊은 것**이다. 원인과 다른 코드를 주면 나중에 로그를 보고 엉뚱한
        # 곳을 뒤지게 되므로, 앱의 응답을 삼키고 413 으로 바꿔 보낸다.
        replaced = False

        async def guarded_send(message):
            nonlocal replaced
            if too_large:
                if message["type"] == "http.response.start" and not replaced:
                    replaced = True
                    await _send_json(send, 413, "요청이 너무 큽니다.")
                return  # 앱이 만든 응답은 버린다
            await send(message)

        await self._app(scope, limited_receive, guarded_send)
        if too_large and not replaced:
            await _send_json(send, 413, "요청이 너무 큽니다.")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """브라우저 쪽 방어선을 켜는 응답 헤더를 붙인다."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        https_only: bool = False,
        inline_script_hashes: tuple[str, ...] = (),
    ) -> None:
        super().__init__(app)
        self._https_only = https_only
        # 허용할 인라인 스크립트의 해시. 비워 두면 인라인은 전부 막힌다.
        self._script_src = " ".join(
            ("'self'", *(f"'{h}'" for h in inline_script_hashes))
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # 이 앱의 CSS와 JS는 전부 자기 출처의 파일이다. 인라인 스크립트가 하나도
        # 없으므로 'unsafe-inline' 없이 가장 엄격한 정책을 쓸 수 있다.
        response.headers["Content-Security-Policy"] = "; ".join(
            (
                "default-src 'self'",
                f"script-src {self._script_src}",
                "style-src 'self'",
                "img-src 'self' data:",
                "connect-src 'self'",
                "form-action 'self'",
                "frame-ancestors 'none'",
                "base-uri 'none'",
                "object-src 'none'",
            )
        )
        # 브라우저가 MIME 타입을 멋대로 추측하지 못하게 한다.
        response.headers["X-Content-Type-Options"] = "nosniff"
        # 다른 사이트가 이 페이지를 프레임에 넣어 클릭을 가로채지 못하게 한다.
        response.headers["X-Frame-Options"] = "DENY"
        # 외부로 나갈 때 전체 주소를 흘리지 않는다.
        response.headers["Referrer-Policy"] = "same-origin"
        # 쓰지 않는 브라우저 기능을 아예 꺼 둔다.
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        )
        if self._https_only:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response
