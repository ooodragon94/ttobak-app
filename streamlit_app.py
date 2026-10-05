"""스트림릿 클라우드가 실행하는 파일.

스트림릿 클라우드는 저장소 맨 위의 ``streamlit_app.py`` 를 찾아 돌린다. 여기서는
``src`` 를 경로에 올리고 다리(:mod:`ttobak.streamlit_host.host`)를 부르기만 한다.

코드를 올리면 새 코드로 다시 읽는다
-----------------------------------

**배포하고 재 보니:** 새 주소(``/api/lexicon``)를 넣어 올렸는데 화면 코드만 새것이고
서버는 404 를 냈다. 스트림릿은 새 커밋을 받아 이 파일은 매번 새로 읽지만,
**이미 한 번 읽은 파이썬 모듈은 프로세스에 그대로 남는다.** 그래서 앱을 새로
만들어도(캐시 열쇠가 바뀌어도) 옛 모듈로 만들어졌다. 앱을 재부팅해야만 반영되던
이유가 이것이었다.

그래서 여기서 코드·화면·사전의 지문을 재고, 지난번과 다르면 ``ttobak`` 모듈을
전부 메모리에서 내린 뒤 다시 읽는다. 이 파일은 그 대상이 아니라서(매번 디스크에서
새로 읽힌다) 이 일을 맡길 수 있다. 지문은 ``host.py`` 도 캐시 열쇠로 쓴다.
"""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def code_version() -> str:
    """앱의 동작을 바꾸는 파일 전부의 지문.

    - 파이썬 코드(``src/ttobak/**/*.py``)
    - 화면(``static``, ``templates``) — 앱이 켜질 때 한 번 읽어 화면에 붙인다
    - 사전(게임이 읽는 것만). 로컬에만 있는 큰 원본은 안 본다.
    """
    package = SRC / "ttobak"
    files = sorted(
        path
        for pattern in ("*.py", "*.js", "*.css", "*.html", "*.sql")
        for path in package.rglob(pattern)
    ) + sorted(
        path
        for pattern in ("words-*.txt", "allowed-?.txt", "extra-allowed.txt")
        for path in (ROOT / "data").glob(pattern)
    )
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


_version = code_version()
if getattr(sys, "_ttobak_code_version", None) != _version:
    for name in [m for m in sys.modules if m == "ttobak" or m.startswith("ttobak.")]:
        del sys.modules[name]
    sys._ttobak_code_version = _version

from ttobak.streamlit_host.host import main  # noqa: E402

main()
