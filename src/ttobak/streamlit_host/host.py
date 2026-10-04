"""스트림릿 쪽 다리: 화면의 요청을 FastAPI 앱에 전하고 답을 돌려준다.

요청은 네트워크를 타지 않는다. :class:`fastapi.testclient.TestClient` 로 **같은
프로세스 안의** 앱을 부른다. 이름은 "시험용" 이지만 하는 일은 ASGI 앱을 직접
호출하는 것뿐이라, 라우트·검증·미들웨어(요청 제한 포함)가 실제와 똑같이 돈다.

사람 한 명 = 스트림릿 세션 하나 = 클라이언트 하나
---------------------------------------------------

쿠키는 클라이언트마다 따로 담긴다. 세션마다 클라이언트를 하나씩 두면 브라우저
하나가 쿠키 통을 하나 가진 것과 같다. 새로고침하면 세션이 새로 생기므로, 쿠키
값(서명된 신원 열쇠)을 브라우저 저장소에 따로 남겼다가 다시 넣어 준다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import streamlit as st
from fastapi.testclient import TestClient

logger = logging.getLogger(__name__)

#: 앱 안쪽 주소. 실제로 연결하는 곳은 아니고, 쿠키가 붙는 도메인 역할만 한다.
#: https 로 두어야 ``Secure`` 표시가 붙은 쿠키도 돌려보낸다.
BASE_URL = "https://ttobak.local"
COOKIE_DOMAIN = "ttobak.local"

#: 컴포넌트 열쇠. 세션 상태에 이 이름으로 컴포넌트 값이 담긴다.
COMPONENT_KEY = "ttobak"

#: 다리가 넘겨 줄 수 있는 요청. 화면은 api/ 아래만 부른다. 다른 주소(문서,
#: 정적 파일)는 넘길 이유가 없으므로 아예 막는다.
ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "DELETE"})

#: 처리한 요청을 기억해 둘 개수. 같은 번호가 다시 오면 다시 실행하지 않고
#: 기억해 둔 답을 준다(제출 같은 요청이 두 번 들어가면 안 된다).
REMEMBER = 64

_COMPONENT_JS = (Path(__file__).with_name("component.js")).read_text(encoding="utf-8")


def _secrets() -> dict[str, str]:
    """스트림릿 비밀값(``st.secrets``) 중 ``TTOBAK_`` 로 시작하는 것.

    비밀값이 아예 없으면 스트림릿이 예외를 던진다. 그때는 빈 사전이다.
    """
    try:
        items = dict(st.secrets)
    except Exception:
        return {}
    return {k: str(v) for k, v in items.items() if k.startswith("TTOBAK_")}


def _fingerprint(values: dict[str, str]) -> str:
    """비밀값 묶음의 지문. 값이 하나라도 바뀌면 지문이 바뀐다(값 자체는 안 남긴다)."""
    blob = json.dumps(values, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def backend() -> tuple[Any, Any, dict[str, Any]]:
    """지금 비밀값에 맞는 앱을 돌려준다. 비밀값이 바뀌면 새로 만든다.

    **처음 배포 때 실제로 터진 일**: 비밀값을 넣기 전에 앱이 한 번 켜져서,
    Turso 주소 없이 임시 DB 로 앱이 만들어졌다. 그 뒤 비밀값을 넣었지만
    스트림릿은 앱을 다시 켜지 않고 값만 바꿔 준다. 앱은 캐시돼 있었으므로 계속
    임시 DB 를 썼다 — 친구들이 푼 기록이 Turso 에 하나도 안 들어갔다.

    그래서 캐시 열쇠에 비밀값의 **지문**을 넣는다. 값이 바뀌면 지문이 바뀌고,
    그러면 새 값으로 앱을 새로 만든다.
    """
    values = _secrets()
    return _backend_for(_fingerprint(values) + _code_version(), values)


def _code_version() -> str:
    """또박 코드의 지문. 코드를 고쳐 올리면 바뀐다.

    **배포하고 재 보니:** DB 코드를 고쳐 올렸는데 속도가 그대로였다. 스트림릿은
    바뀐 파일을 다시 읽지만, 캐시해 둔 앱은 **옛 코드로 만든 그대로** 남는다.
    열쇠가 비밀값뿐이라 바뀐 게 없다고 본 것이다. 코드 지문을 열쇠에 더하면
    올릴 때마다 새 코드로 앱을 다시 만든다.
    """
    package = Path(__file__).resolve().parent.parent
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*.py")):
        digest.update(path.relative_to(package).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


@st.cache_resource(show_spinner=False, max_entries=2)
def _backend_for(
    fingerprint: str, _values: dict[str, str]
) -> tuple[Any, Any, dict[str, Any]]:
    """앱과 화면 조각을 비밀값 묶음마다 **한 번만** 만든다.

    앱이 시작할 때 사전을 읽고 DB 를 준비한다. 요청마다 새로 하면 느리고
    쓸데없으므로 캐시한다. 기동(lifespan)은 여기서 한 번 돌리고, 세션별
    클라이언트는 기동 없이 같은 앱을 부른다.

    ``_values`` 앞의 밑줄은 스트림릿에게 "이건 캐시 열쇠로 쓰지 마라" 는 뜻이다.
    열쇠는 ``fingerprint`` 하나로 충분하고, 비밀값을 캐시 열쇠에 두지 않는다.
    """
    # 비밀값이 환경 변수보다 이긴다. 스트림릿에서는 설정이 비밀값으로만 오고,
    # 바뀐 값이 반영되어야 하기 때문이다.
    os.environ.update(_values)
    from ttobak.config import Settings
    from ttobak.web.app import create_app

    # get_settings() 는 프로세스 전체에서 한 번 만든 설정을 계속 돌려준다
    # (캐시). 비밀값이 바뀌어도 옛 설정이 남으므로 여기서는 새로 읽는다.
    settings = Settings()
    app = create_app(settings)
    boot = TestClient(app, base_url=BASE_URL)
    boot.__enter__()  # 기동을 돌리고 계속 열어 둔다
    return app, settings, _assets(boot)


def _assets(client: TestClient) -> dict[str, Any]:
    """화면 조각을 앱에서 그대로 받아 온다.

    파일을 따로 읽지 않고 앱에 물어보는 이유: 앱이 실제로 내보내는 것과
    **똑같은 것**이어야 한다. 템플릿이 채우는 값(예: 공유 주소)까지 같아진다.
    """
    html = client.get("/").text
    start = html.index("<body>") + len("<body>")
    end = html.index("</body>")
    # 스크립트는 따로 순서대로 붙이므로 본문에서는 뺀다.
    body = re.sub(r"<script\b[^>]*>.*?</script>", "", html[start:end], flags=re.S)
    css = client.get("/static/css/style.css").text
    scripts = [
        client.get(f"/static/js/{name}").text
        for name in ("hangul.js", "api.js", "app.js")
    ]
    return {"body": body, "css": css, "scripts": scripts}


def _client(app: Any) -> TestClient:
    """이 세션(사람 한 명)의 클라이언트. 쿠키 통이 여기에 붙어 있다.

    비밀값이 바뀌어 앱이 새로 만들어졌으면, 옛 앱에 붙은 클라이언트는 버리고
    새로 만든다. 쿠키(신원 열쇠)는 브라우저 저장소에서 다시 들어온다.
    """
    client = st.session_state.get("ttobak_client")
    if client is not None and st.session_state.get("ttobak_client_app") is not app:
        client = None
    if client is None:
        client = TestClient(
            app,
            base_url=BASE_URL,
            # 서버 쪽 예외를 파이썬 예외로 던지지 않고 500 응답으로 받는다.
            # 던지면 스트림릿 화면에 파이썬 오류가 통째로 뜬다.
            raise_server_exceptions=False,
            headers=_client_headers(),
        )
        st.session_state.ttobak_client = client
        st.session_state.ttobak_client_app = app
    return client


def _client_headers() -> dict[str, str]:
    """요청에 실을 머리말. 요청 제한이 사람을 구분할 수 있게 실제 주소를 넘긴다.

    앱 안쪽 호출이라 그냥 두면 모두 같은 주소("testclient")로 보인다. 그러면
    요청 제한이 모든 사람을 한 사람으로 센다. 또박의 요청 제한은 앞단이 넣어
    주는 ``CF-Connecting-IP`` 를 믿으므로, 스트림릿이 아는 실제 주소를 여기에
    싣는다. 브라우저가 이 머리말을 지어낼 수는 없다 — 파이썬이 붙이는 것이다.
    """
    address = getattr(st.context, "ip_address", None)
    return {"CF-Connecting-IP": address} if address else {}


def _forward(client: TestClient, request: dict[str, Any]) -> dict[str, Any]:
    """요청 하나를 앱에 전하고 ``{id, status, payload}`` 로 돌려준다."""
    rid = request.get("id")
    method = str(request.get("method", "GET")).upper()
    path = str(request.get("path", ""))
    if method not in ALLOWED_METHODS or not path.startswith("api/"):
        return {"id": rid, "status": 400, "payload": {"detail": "잘못된 요청입니다."}}
    from ttobak.db import libsql_adapter

    before, started = libsql_adapter.stats(), time.perf_counter()
    try:
        response = client.request(method, "/" + path, json=request.get("body"))
    except Exception:
        logger.exception("다리에서 요청을 전하다 실패: %s %s", method, path)
        detail = "서버에서 문제가 생겼어요. 잠시 뒤 다시 시도해 주세요."
        return {"id": rid, "status": 0, "payload": {"detail": detail}}
    payload = None
    if response.status_code != 204 and response.content:
        try:
            payload = response.json()
        except ValueError:
            payload = None
    return {
        "id": rid,
        "status": response.status_code,
        "payload": payload,
        "timing": _timing(before, started),
    }


def _timing(before: dict[str, float], started: float) -> dict[str, float]:
    """요청 하나에 걸린 시간과 그중 DB 몫. 화면이 모아 두었다가 보여 준다.

    브라우저가 잰 왕복 시간에서 이 ``total_ms`` 를 빼면 스트림릿이 신호를 나르고
    다시 그리는 데 쓴 시간이 나온다.
    """
    from ttobak.db import libsql_adapter

    after = libsql_adapter.stats()
    timing = {key: round(after[key] - before[key], 1) for key in after}
    timing["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return timing


def _component_value(name: str) -> Any:
    state = st.session_state.get(COMPONENT_KEY)
    if state is None:
        return None
    try:
        return state[name]
    except (KeyError, TypeError, AttributeError):
        return getattr(state, name, None)


def _on_requests() -> None:
    """화면이 보낸 요청 묶음을 처리한다. 스트림릿이 다시 그리기 **전에** 불린다."""
    batch = _component_value("requests")
    if not isinstance(batch, dict):
        return
    app, settings, _ = backend()
    client = _client(app)

    # 새로 열린 세션이면 쿠키 통이 비어 있다. 브라우저에 남겨 둔 열쇠를 넣는다.
    cookie = settings.session_cookie
    token = batch.get("token")
    if token and not client.cookies.get(cookie):
        client.cookies.set(cookie, str(token), domain=COOKIE_DOMAIN)

    done: dict[Any, dict[str, Any]] = st.session_state.setdefault("ttobak_done", {})
    replies = []
    for request in batch.get("requests") or []:
        if not isinstance(request, dict):
            continue
        rid = request.get("id")
        if rid not in done:
            done[rid] = _forward(client, request)
        replies.append(done[rid])
    # 오래된 기억은 버린다. 번호는 계속 늘어나므로 작은 번호부터 버리면 된다.
    for rid in sorted(done, key=lambda key: (key is None, key))[:-REMEMBER]:
        done.pop(rid, None)

    st.session_state.ttobak_replies = replies
    # 서버가 쿠키를 새로 주거나(참가) 지웠으면(나가기) 브라우저에도 반영한다.
    st.session_state.ttobak_token = client.cookies.get(cookie)
    st.session_state.ttobak_token_known = True


_bridge = st.components.v2.component("ttobak_bridge", js=_COMPONENT_JS)


def main() -> None:
    """스트림릿 앱 본문. 매번 다시 그릴 때마다 처음부터 돈다."""
    st.set_page_config(
        page_title="또박",
        page_icon="🟩",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _, _, assets = backend()

    data: dict[str, Any] = {"replies": st.session_state.get("ttobak_replies", [])}
    if st.session_state.get("ttobak_token_known"):
        data["token"] = st.session_state.get("ttobak_token")
    if not _component_value("ready"):
        # 화면을 아직 안 붙였을 때만 무거운 조각을 보낸다.
        data["assets"] = assets

    _bridge(
        key=COMPONENT_KEY,
        data=data,
        on_requests_change=_on_requests,
        on_ready_change=lambda: None,
    )
