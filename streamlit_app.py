"""스트림릿 클라우드가 실행하는 파일.

스트림릿 클라우드는 저장소 맨 위의 ``streamlit_app.py`` 를 찾아 돌린다. 여기서는
``src`` 를 경로에 올리고 다리(:mod:`ttobak.streamlit_host.host`)를 부르기만 한다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from ttobak.streamlit_host.host import main  # noqa: E402

main()
