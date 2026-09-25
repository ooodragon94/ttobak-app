-- 꼬들 서버 스키마.
-- 마이그레이션 도구 없이 기동 시 한 번 실행되므로 모든 문장이 멱등해야 한다.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 플레이어. Tailscale 계정은 기기마다 동일할 수 있으므로 사람 구분은 닉네임으로 한다.
CREATE TABLE IF NOT EXISTS players (
    id              TEXT PRIMARY KEY,           -- 닉네임을 정규화한 식별자
    display_name    TEXT NOT NULL,              -- 화면에 보여 줄 원본 닉네임
    created_at      TEXT NOT NULL,              -- ISO-8601 UTC
    last_seen_at    TEXT NOT NULL,
    tailscale_node  TEXT,                       -- 마지막 접속 기기명 (참고용)
    tailscale_user  TEXT,                       -- 마지막 접속 Tailscale 계정 (참고용)
    -- 개인 설정. 사람마다 다르게 두므로 게임이 아니라 플레이어에 붙는다.
    hints_enabled   INTEGER NOT NULL DEFAULT 0, -- 힌트 사용 여부 (기본 꺼짐)
    share_theme     TEXT NOT NULL DEFAULT 'classic', -- 공유 격자 그림 테마
    -- 방 주인과 어떤 사이인지. 선택 입력이라 빈 문자열이 정상이다.
    -- 순위표에 닉네임 옆에 붙어서, 서로 모르는 사람들끼리도 맥락이 생긴다.
    relation        TEXT NOT NULL DEFAULT ''
);

-- 게임 한 판. 플레이어마다 0번 라운드부터 끝없이 이어진다.
CREATE TABLE IF NOT EXISTS games (
    player_id       TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    round_no        INTEGER NOT NULL,           -- 0부터 시작하는 라운드 번호
    answer          TEXT NOT NULL,              -- 판을 시작한 시점의 정답 스냅샷
    status          TEXT NOT NULL DEFAULT 'playing'
                    CHECK (status IN ('playing', 'won', 'lost')),
    guesses         TEXT NOT NULL DEFAULT '[]', -- 자모 문자열의 JSON 배열
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    -- 순위표를 '오늘' 기준으로 끊기 위한 한국 시간 날짜. 시작 시점에 박아 둔다.
    played_on       TEXT NOT NULL,              -- YYYY-MM-DD (KST)
    -- 이 판에서 쓴 힌트 수. 앞에서부터 그만큼의 자모가 공개된다.
    hints_used      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, round_no)
);

-- 순위표는 '오늘 끝난 판'을 훑으므로 그 조합에 인덱스를 둔다.
CREATE INDEX IF NOT EXISTS idx_games_played_on
    ON games (played_on, status);

-- 다음 라운드 번호를 찾을 때 플레이어별 역순 조회를 쓴다.
CREATE INDEX IF NOT EXISTS idx_games_player_round
    ON games (player_id, round_no DESC);

-- ---------------------------------------------------------------------------
-- 방 — 친구끼리만 보이는 순위표와 '오늘의 문제'
-- ---------------------------------------------------------------------------

-- 방 코드가 곧 열쇠다. 링크를 아는 사람이 들어올 수 있는 사람이므로
-- 코드는 추측할 수 없어야 한다(game/rooms.py 의 new_room_code 참고).
CREATE TABLE IF NOT EXISTS rooms (
    id          TEXT PRIMARY KEY,           -- 초대 코드. 순번이 아니라 난수다.
    name        TEXT NOT NULL,
    owner_id    TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    -- 출제 시드. 코드와 따로 두는 이유: 코드는 링크에 실려 밖으로 나간다.
    -- 코드만으로 오늘의 정답을 계산할 수 있으면 안 된다.
    puzzle_salt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS room_members (
    room_id     TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    player_id   TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    joined_at   TEXT NOT NULL,
    PRIMARY KEY (room_id, player_id)
);

-- 한 사람이 속한 방을 훑는 조회가 잦다(내 방 목록).
CREATE INDEX IF NOT EXISTS idx_room_members_player
    ON room_members (player_id);

-- 오늘의 문제 한 판. 방 × 날짜 × 사람마다 하나뿐이라 그대로 기본키가 된다.
-- 이 제약이 곧 "하루 한 번" 규칙이다. 코드로 세지 않아도 DB 가 막아 준다.
CREATE TABLE IF NOT EXISTS daily_games (
    room_id     TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    play_date   TEXT NOT NULL,              -- YYYY-MM-DD (KST)
    player_id   TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    answer      TEXT NOT NULL,              -- 시작 시점 정답 스냅샷
    status      TEXT NOT NULL DEFAULT 'playing'
                CHECK (status IN ('playing', 'won', 'lost')),
    guesses     TEXT NOT NULL DEFAULT '[]',
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    hints_used  INTEGER NOT NULL DEFAULT 0,
    -- 그날 몇 번째 문제인가. 하루에 여러 개를 내므로 열쇠의 일부다.
    slot        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (room_id, play_date, slot, player_id)
);

-- 방의 오늘 순위표를 그리는 조회.
CREATE INDEX IF NOT EXISTS idx_daily_room_date
    ON daily_games (room_id, play_date, status);

-- 오늘의 문제에 남기는 한 줄. **푼 사람만 쓰고 푼 사람만 본다**
-- (game/comments.py 참고 — 안 그러면 댓글 한 줄이 그날 문제를 끝낸다).
CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id     TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    play_date   TEXT NOT NULL,
    player_id   TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_comments_room_date
    ON comments (room_id, play_date, id);

-- 닉네임 선점을 위한 복구 코드 해시.
--
-- 이 게임은 비밀번호가 없다(친구들이 쉽게 들어와야 한다). 그런데 그러면
-- 닉네임을 아는 사람이 곧 그 사람이 된다 — 지인끼리 쓰는 물건에서는 이게
-- 제일 큰 구멍이다. 남의 진행 중인 판을 보고 기회를 대신 소모시킬 수 있다.
--
-- 그래서 "먼저 쓴 사람이 임자" 로 바꾸고, 기기를 바꿀 때만 쓰는 복구 코드를
-- 준다. 코드 자체는 저장하지 않고 해시만 둔다 — DB 가 유출돼도 남의 계정을
-- 되찾을 수는 없어야 한다.
-- (실제 추가는 repository._migrate 가 한다. 이 파일은 매 기동 실행되므로
--  ALTER TABLE 을 두면 두 번째 기동에서 '중복 컬럼' 으로 죽는다.)

-- 후원해 준 사람.
--
-- **자동으로는 알 수 없다.** 카카오페이 QR 은 우리 서버에 아무것도 알려 주지
-- 않는다(웹훅도 API 도 없다). 그래서 본인이 "보냈어요" 를 누른 것을 그대로
-- 믿는다. 친구들끼리 쓰는 물건이고, 거짓말해서 얻는 것이 배지 하나뿐이라
-- 검증에 드는 복잡도가 값어치보다 크다.
--
-- 필요하면 주인이 카카오페이 내역과 대조해 ``confirmed`` 를 채우면 된다.
CREATE TABLE IF NOT EXISTS supporters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    amount      INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    -- 주인이 실제 입금을 확인했는가. 0 이어도 배지는 붙는다.
    confirmed   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_supporters_player ON supporters (player_id);


-- 친구들이 "이건 진짜 단어인데요" 라고 신고한 자모 나열.
--
-- 사전이 표준국어대사전 계열이라 생활 합성어가 통째로 빠져 있다('휴게실' 은
-- 있는데 '탕비실' 은 없었다). 그런데 그걸 알아내는 유일한 경로가 카톡으로
-- 말해 주는 것이었고, 말 안 하고 그냥 접는 사람이 훨씬 많다.
--
-- **글자가 아니라 자모로 저장한다.** 사람이 친 것이 자모라서 서버는 어떤
-- 글자를 의도했는지 모른다('ㅇㅗㅊㅊㅏㄹㅣㅁ' 은 '옷차림' 이 아니라
-- '옻차림' 이었다). 되짚는 것은 나중에 사람이나 모델이 하고, 그 결과가
-- 원래 자모와 맞는지는 코드가 검산한다.
CREATE TABLE IF NOT EXISTS word_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    jamos       TEXT NOT NULL,              -- 신고된 자모 나열
    length      INTEGER NOT NULL,
    player_id   TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    -- pending: 아직 안 봄 / added: 사전에 넣음 / rejected: 낱말이 아님
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'added', 'rejected')),
    -- 판정 결과 낱말. 넣기로 했을 때만 채워진다.
    word        TEXT,
    -- 왜 그렇게 판정했는지. 사람이 나중에 다시 볼 수 있게 남긴다.
    note        TEXT,
    reviewed_at TEXT,
    -- 같은 자모를 여러 명이 신고할 수 있다. 그때는 한 줄로 세고 횟수를 올린다.
    votes       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (jamos)
);

CREATE INDEX IF NOT EXISTS idx_word_reports_status
    ON word_reports (status, votes DESC);
