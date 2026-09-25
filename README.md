# 또박 (ttobak)

한글 **자모**로 낱말을 맞히는 놀이. 친구들끼리 방을 만들고, 매일 같은 문제를
풀어 순위를 겨룬다.

- 정답을 두벌식 자판의 **기본 자모 24개**로 쪼개 한 칸에 하나씩 놓는다.
  "고양이"는 `ㄱ ㅗ ㅇ ㅑ ㅇ ㅇ ㅣ` 일곱 칸이 된다. 쌍자음·겹받침·겹모음도 낱자로
  쪼갠다(`ㄲ` → `ㄱㄱ`, `ㅘ` → `ㅗㅏ`).
- 칸 수는 문제마다 다르다(자모 5~8개).
- 채점은 색 세 가지다. **초록**은 자리까지 정답, **노랑**은 정답에 있지만 자리가
  틀림, **회색**은 정답에 없음. 같은 자모가 여러 번 나오면 초록을 먼저 정하고
  남은 개수만큼만 노랑을 준다.
- **방**: 초대 링크(`?room=코드`)로 들어온다. 같은 방 같은 날은 모두 같은 문제를
  풀고, 방 순위와 댓글(다 푼 사람만)이 있다.
- **혼자 풀기**: 문제가 끝없이 이어지고, 그날 순위에 오른다.
- 난이도(단서 강제), 시도 횟수, 문제 길이, 힌트, 공유 문구 테마를 고를 수 있다.
- 사전에 없는 낱말은 거절하고, "진짜 낱말인데요" 신고를 받는다.

## 구조

```
src/ttobak/
  hangul.py          자모 분해·조립
  words.py           사전 읽기
  game/              규칙·출제·채점·난이도·공유 문구 (웹과 무관)
  db/                저장소 (SQLite, 또는 Turso/libSQL)
  web/               FastAPI 서버 + 화면(templates, static)
  streamlit_host/    스트림릿 위에 같은 화면·서버를 올리는 다리
streamlit_app.py     스트림릿 클라우드 진입점
data/                words-<n>.txt(출제), allowed-<n>.txt·extra-allowed.txt(추측 허용)
tools/               사전 거르기, 신고 정리, 백업 등 관리 도구
```

게임 규칙과 화면은 하나다. 돌리는 방식만 두 가지다.

### 1) FastAPI 로 직접

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # 윈도우
.venv/Scripts/python -m ttobak --port 8790
```

기록은 `var/ttobak.sqlite3` 에 쌓인다. 설정은 `.env.example` 을 `.env` 로
복사해서 바꾼다.

### 2) 스트림릿 클라우드 + Turso (무료)

스트림릿 클라우드는 디스크가 남지 않으므로 기록은 Turso(원격 libSQL)에 둔다.

- 화면: 스트림릿 컴포넌트(v2)가 `src/ttobak/static` 의 HTML/CSS/JS 를 **그대로**
  페이지에 올린다.
- 서버: 화면의 요청을 컴포넌트 신호로 받아, 같은 프로세스 안의 FastAPI 앱에
  그대로 전한다. 그래서 규칙·검증·요청 제한이 1)과 같은 코드다.
- 로그인: 쿠키 대신 서명된 열쇠를 브라우저 저장소에 둔다.

스트림릿 앱 설정의 **Secrets** 에 넣는 값:

```toml
TTOBAK_TURSO_URL = "libsql://…turso.io"
TTOBAK_TURSO_TOKEN = "…"
TTOBAK_SECRET_KEY = "…"   # 열쇠 서명용. 아무 긴 무작위 문자열
TTOBAK_DAILY_SALT = "…"   # 출제 순서 시드. 바꾸면 순서가 새로 섞인다
TTOBAK_PUBLIC = "true"
TTOBAK_SHARE_URL = "https://….streamlit.app/"
```

기존 SQLite 기록을 Turso 로 옮길 때는 `tools/copy_to_turso.py` 를 쓴다.

**비밀값은 이 저장소에 없다.** 출제 시드와 서명 키가 스트림릿 설정에만 있어서,
코드가 공개돼 있어도 그날 정답을 미리 알 수는 없다.

## 개발

```bash
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check .
```

`TTOBAK_DB_DRIVER=libsql` 을 주면 같은 시험이 libSQL(로컬 파일) 위에서 돈다.
