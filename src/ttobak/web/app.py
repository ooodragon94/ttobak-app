"""FastAPI 애플리케이션 조립.

앱 생성은 팩토리 함수로 감싼다. 테스트가 임시 데이터베이스를 가리키는 설정으로
독립된 앱 인스턴스를 만들 수 있어야 하기 때문이다.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from ttobak import __version__
from ttobak.config import Settings, get_settings
from ttobak.db import Database
from ttobak.game import GameService
from ttobak.web.deps import today, unsign_player_cookie
from ttobak.web.routes.api import router as api_router
from ttobak.web.routes.rooms import router as rooms_router
from ttobak.web.security import (
    BodySizeLimitMiddleware,
    PublicGZipMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from ttobak.words import load_lexicon

__all__ = ["create_app"]

#: 페이지 맨 앞에서 한 번 도는 아주 작은 스크립트.
#:
#: 이 앱은 루트(`/`)에도 붙고 하위 경로(`/ttobak/`)에도 붙는다. 그런데 페이지
#: 안의 주소가 상대경로라, 끝에 슬래시가 없는 `/ttobak` 로 들어오면 브라우저가
#: `static/...` 을 `/static/...` 으로 풀어 엉뚱한 곳을 찾는다. 그러면 CSS 와 JS 가
#: 통째로 404 가 나서 **빈 화면**만 보인다.
#:
#: 서버는 자기가 어느 경로에 걸려 있는지 알 수 없다. Tailscale Funnel 이 접두사를
#: 떼고 넘기면서 그 사실을 알려 주는 헤더를 붙이지 않기 때문이다. 직접 확인했다.
#: 그래서 브라우저가 스스로 고치게 한다. 주소 끝에 슬래시를 붙여 다시 부른다.
#:
#: `replace` 를 쓰는 이유는 방문 기록을 남기지 않기 위해서다. 뒤로 가기를 눌렀을 때
#: 슬래시 없는 주소로 돌아가 무한히 튕기는 일이 없다.
BOOTSTRAP_SCRIPT = (
    "if(location.pathname!=='/'&&!location.pathname.endsWith('/'))"
    "location.replace(location.pathname+'/'+location.search+location.hash);"
)

#: 위 스크립트의 SHA-256. 콘텐츠 보안 정책에 이 값을 넣어야 실행이 허용된다.
#:
#: 인라인 스크립트를 열어 주는 가장 좁은 방법이다. `'unsafe-inline'` 을 쓰면 어떤
#: 인라인 스크립트든 다 돌아가지만, 해시를 쓰면 **정확히 이 한 줄만** 허용된다.
#: 코드를 고치면 해시가 자동으로 따라 바뀌므로 둘이 어긋날 일도 없다.
BOOTSTRAP_SCRIPT_HASH = "sha256-" + base64.b64encode(
    hashlib.sha256(BOOTSTRAP_SCRIPT.encode("utf-8")).digest()
).decode("ascii")

logger = logging.getLogger(__name__)


def _prune_if_new_day(app: FastAPI) -> None:
    """오늘 아직 안 했으면 오래된 기록을 정리한다. 실패해도 게임은 계속 돈다."""
    day = today()
    if getattr(app.state, "pruned_on", None) == day:
        return
    # 먼저 적어 둔다. 여러 요청이 동시에 들어와도 한 번만 돌게 하고, 정리가
    # 실패해도 그날 요청마다 다시 시도하느라 느려지지 않게 한다.
    app.state.pruned_on = day
    settings = app.state.settings
    try:
        counts = app.state.database.prune(
            today=day,
            keep_days=settings.retention_days,
            dormant_days=settings.dormant_days,
        )
    except Exception:
        logger.exception("오래된 기록 정리에 실패했다")
        return
    removed = {name: count for name, count in counts.items() if count}
    if removed:
        logger.info("오래된 기록 정리: %s", removed)


def create_app(settings: Settings | None = None) -> FastAPI:
    """설정을 받아 완성된 FastAPI 앱을 만든다."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """기동 시 사전과 데이터베이스를 한 번만 준비한다."""
        database = Database(settings.database_path)
        database.initialize()
        lexicon = load_lexicon(settings.data_dir, settings.puzzle_lengths)

        app.state.settings = settings
        app.state.database = database
        app.state.service = GameService(
            database,
            lexicon,
            lengths=settings.puzzle_lengths,
            max_attempts=settings.max_attempts,
            salt=settings.daily_salt,
            share_url=settings.share_url,
            hints_offered=settings.hints_offered,
        )
        # 켜질 때 한 번 정리한다. 스트림릿 무료 배포는 잠들었다 깨며 자주 다시
        # 켜지므로 대개 이것으로 충분하고, 오래 켜져 있으면 아래 미들웨어가
        # 하루 한 번 더 한다.
        _prune_if_new_day(app)
        logger.info(
            "또박 준비 완료: 사전 %s, DB %s, 공개=%s",
            {length: len(lexicon.for_length(length)) for length in lexicon.lengths},
            database.path,
            settings.public,
        )
        yield

    app = FastAPI(
        title="또박",
        description="한글 자모 낱말 맞히기. 문제가 끝없이 이어진다.",
        version=__version__,
        lifespan=lifespan,
        # 공개 배포에서는 API 문서를 닫아 둔다. 공격에 필요한 정보를 그대로
        # 알려 줄 이유가 없다. 로컬 개발에서는 TTOBAK_ENABLE_DOCS=true로 켠다.
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )

    # 미들웨어는 나중에 추가한 것이 바깥쪽에서 먼저 실행된다. 그래서 가장 싼
    # 검사인 본문 크기 제한을 마지막에 붙여 가장 먼저 걸리게 한다.
    app.add_middleware(
        SecurityHeadersMiddleware,
        https_only=settings.public,
        inline_script_hashes=(BOOTSTRAP_SCRIPT_HASH,),
    )
    # 쿠키 서명을 확인하는 함수를 넘긴다. 이게 없으면 미들웨어는 쿠키를
    # 안 믿고 주소로만 세는데, 그러면 같은 집(NAT) 사람들이 서로를 막는다.
    app.add_middleware(
        RateLimitMiddleware,
        cookie_name=settings.session_cookie,
        unsign=lambda raw: unsign_player_cookie(raw, settings),
    )
    app.add_middleware(BodySizeLimitMiddleware)

    @app.middleware("http")
    async def prune_daily(request: Request, call_next):
        """**하루의 첫 요청**에서 오래된 기록을 정리한다.

        예약 작업(cron)이 없는 곳(스트림릿 무료 배포)에서도 돌게 하려고 요청에
        얹었다. 날짜만 비교하므로 평소 요청에는 비용이 거의 없다. 지우는 일은
        스레드로 넘겨 다른 요청을 막지 않는다.
        """
        if getattr(app.state, "pruned_on", None) != today():
            await run_in_threadpool(_prune_if_new_day, app)
        return await call_next(request)

    # 압축은 가장 바깥에 둔다. 안쪽에서 무엇이 나오든(정적 파일, 템플릿,
    # 오류 화면) 마지막에 한 번만 줄이면 되기 때문이다.
    app.add_middleware(PublicGZipMiddleware)

    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
    templates = Jinja2Templates(directory=settings.templates_dir)
    app.include_router(api_router)
    # 방/오늘의 문제/댓글. /api 아래라 요청 수 제한과 쿠키 검사가
    # 그대로 적용된다(라우터를 나눴다고 보호에서 빠지지 않는다).
    app.include_router(rooms_router)

    # 정적 파일 주소에 붙일 버전. 브라우저가 옛 CSS/JS를 계속 쓰는 것을 막는다.
    # 기동 시각을 섞어 두어 코드를 고치고 재시작하면 자동으로 값이 바뀐다.
    asset_version = f"{__version__}-{int(time.time())}"

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index(request: Request) -> HTMLResponse:
        """게임 화면. 상태는 모두 API로 받아 오는 단일 페이지다.

        **이 페이지는 절대 캐시하지 않는다.** CSS 와 JS 는 주소에 버전이 붙어
        있어 바뀌면 새로 받아 가지만, 그 버전을 알려 주는 것이 바로 이 HTML 이다.
        HTML 이 캐시되면 낡은 버전 번호를 계속 물고 있어 고친 내용이 영영
        반영되지 않는다. 실제로 휴대폰에서 깨진 화면이 계속 나오는 사고가 있었다.
        """
        # 링크 미리보기용 절대 주소.
        #
        # **상대 경로면 카톡이 이미지를 못 받아 간다.** 미리보기를 만드는
        # 쪽은 우리 페이지 밖에서 이미지를 따로 요청하므로 "static/og.png"
        # 만으로는 어디를 가리키는지 알 수 없다.
        #
        # 설정에 공유 주소가 있으면 그것을 쓰고(도메인이 생기면 그 값이
        # 들어간다), 없으면 지금 들어온 요청의 주소에서 만든다. 후자는
        # 프록시 뒤에서 http 로 보일 수 있어 정확하지 않을 수 있다.
        base = (settings.share_url or str(request.base_url)).rstrip("/")
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "asset_version": asset_version,
                "bootstrap_script": BOOTSTRAP_SCRIPT,
                "og_title": "또박 · 한글 자모 단어 맞히기",
                "og_description": "친구들과 매일 같은 문제를 풀고 겨뤄요 🏆",
                "og_url": base + "/",
                "og_image": f"{base}/static/og.png?v={asset_version}",
            },
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        """기동 확인용 엔드포인트."""
        return {"status": "ok", "version": __version__}

    return app
