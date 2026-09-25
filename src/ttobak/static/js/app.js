/**
 * 화면 조립과 입력 처리.
 *
 * 서버가 보내 준 게임 상태(`state.game`)가 유일한 진실이고, 화면은 그 상태를
 * 그대로 그린다. 아직 제출하지 않은 입력만 `state.draft`에 따로 담는다.
 */
(() => {
  "use strict";

  const MARK_CLASS = {
    correct: "correct",
    present: "present",
    absent: "absent",
  };

  const state = {
    /** @type {object|null} 서버가 보낸 게임 상태 */
    game: null,
    /**
     * @type {string|null} 지금 그리고 있는 판이 어느 방의 오늘의 문제인가.
     * ``null`` 이면 혼자 푸는 일반 판이다.
     *
     * **화면에 그린 판과 채점을 보낼 곳은 반드시 같이 바뀌어야 한다.**
     * 예전에는 이 값이 모듈 변수로 따로 있었고 한 번 정해지면 안 지워졌다.
     * 그래서 방의 오늘의 문제를 한 번이라도 열면, 그 뒤로 일반 판을 보면서
     * 친 것까지 계속 방으로 갔다 — 7칸을 다 채웠는데 "자모 5개를 채워야
     * 합니다" 가 뜨는 상태였다. 화면은 일반 판(7칸), 채점은 방의 오늘의
     * 문제(5칸)를 보고 있었기 때문이다.
     *
     * 그래서 둘을 같은 객체에 두고 ``setGame`` 으로만 바꾼다.
     */
    room: null,
    /** @type {string[]} 아직 제출하지 않은 자모 */
    draft: [],
    /** 잠금 중에는 입력을 받지 않는다. 제출 연출이 끝날 때까지. */
    locked: false,
  };

  /**
   * 그릴 판과 채점을 보낼 곳을 **한 번에** 바꾼다.
   *
   * 이 함수를 거치지 않고 ``state.game`` 만 갈아끼우면 둘이 어긋난다.
   * 판을 바꾸는 곳은 전부 여기를 지나가야 한다.
   *
   * @param {object} view 서버가 준 판 상태
   * @param {string|null} room 방의 오늘의 문제면 그 방 코드, 아니면 null
   */
  /**
   * 오늘의 문제 응답을 일반 판과 같은 모양으로 맞춘다.
   *
   * 서버가 주는 모양이 조금 다르다. 일반 판에만 있는 값(round_no,
   * solved_today)이 없어서, 그대로 그리면 화면에 "NaN번째 문제 ·
   * 오늘 undefined개" 가 뜬다.
   *
   * 예전에는 시트를 **열 때만** 이 손질을 했다. 그래서 열자마자는 멀쩡한데
   * 한 번 치는 순간(추측 응답이 그대로 들어가면서) 깨졌다. 손질하는 곳이
   * 하나여야 그런 구멍이 안 생긴다.
   */
  function asBoard(daily) {
    return {
      ...daily,
      rows: daily.rows || [],
      solved_today: daily.solved_count,
      // 힌트도 서버가 계산해서 준다. 여기서 억지로 끄면 오늘의 문제에서만
      // 힌트가 안 되는데, 그 이유를 화면 어디에도 적을 수 없다.
      // 쓴 횟수는 순위에 반영되므로 공정성은 그쪽에서 지켜진다.
      hints: daily.hints ?? [],
      hint_available: daily.hint_available ?? false,
      // round_no 자리에 문제 번호를 담는다. 화면이 "① 5칸" 처럼 적는다.
      round_no: daily.slot ?? 0,
    };
  }

  function setGame(view, room = null) {
    state.game = view;
    state.room = room;
    state.draft = [];
  }

  const el = {
    loading: document.getElementById("loading"),
    loadingFailed: document.getElementById("loading-failed"),
    loadingError: document.getElementById("loading-error"),
    loadingRetry: document.getElementById("loading-retry"),
    join: document.getElementById("join"),
    joinForm: document.getElementById("join-form"),
    nickname: document.getElementById("nickname"),
    joinError: document.getElementById("join-error"),
    joinRoom: document.getElementById("join-room"),
    joinRelation: document.getElementById("join-relation"),
    joinRecovery: document.getElementById("join-recovery"),
    recovery: document.getElementById("recovery"),
    recoveryCode: document.getElementById("recovery-code"),
    recoveryCopy: document.getElementById("recovery-copy"),
    recoveryStatus: document.getElementById("recovery-status"),
    recoveryOk: document.getElementById("recovery-ok"),
    howto: document.getElementById("howto"),
    howtoOk: document.getElementById("howto-ok"),
    settingsHowto: document.getElementById("settings-howto"),
    settingsResign: document.getElementById("settings-resign"),
    settingsRecovery: document.getElementById("settings-recovery"),
    game: document.getElementById("game"),
    boardMeta: document.getElementById("board-meta"),
    board: document.getElementById("board"),
    boardArea: document.getElementById("board-area"),
    message: document.getElementById("message"),
    keyboard: document.getElementById("keyboard"),
    submit: document.getElementById("submit"),
    next: document.getElementById("next"),
    hint: document.getElementById("hint"),
    hintLine: document.getElementById("hint-line"),
    statsButton: document.getElementById("stats-button"),
    menuButton: document.getElementById("menu-button"),
    sheet: document.getElementById("sheet"),
    sheetTitle: document.getElementById("sheet-title"),
    sheetBody: document.getElementById("sheet-body"),
    sheetClose: document.getElementById("sheet-close"),
    sheetNext: document.getElementById("sheet-next"),
    sheetShare: document.getElementById("sheet-share"),
    settings: document.getElementById("settings"),
    settingsClose: document.getElementById("settings-close"),
    settingsHintRow: document.getElementById("settings-hint-row"),
    settingsHints: document.getElementById("settings-hints"),
    settingsRelation: document.getElementById("settings-relation"),
    settingsStatus: document.getElementById("settings-status"),
    settingsRename: document.getElementById("settings-rename"),
    settingsSupport: document.getElementById("settings-support"),
    roomsButton: document.getElementById("rooms-button"),
    rooms: document.getElementById("rooms"),
    roomsClose: document.getElementById("rooms-close"),
    roomsList: document.getElementById("rooms-list"),
    roomsStatus: document.getElementById("rooms-status"),
    roomName: document.getElementById("room-name"),
    roomCreate: document.getElementById("room-create"),
    roomForm: document.getElementById("room-form"),
    dailySheet: document.getElementById("daily-sheet"),
    dailyClose: document.getElementById("daily-close"),
    dailySummary: document.getElementById("daily-summary"),
    dailySlots: document.getElementById("daily-slots"),
    dailyShare: document.getElementById("daily-share"),
    dailyStandings: document.getElementById("daily-standings"),
    commentsLocked: document.getElementById("comments-locked"),
    commentsList: document.getElementById("comments-list"),
    commentsForm: document.getElementById("comments-form"),
    commentBody: document.getElementById("comment-body"),
    commentSend: document.getElementById("comment-send"),
    commentsStatus: document.getElementById("comments-status"),
    support: document.getElementById("support"),
    supportClose: document.getElementById("support-close"),
    supportTiers: document.getElementById("support-tiers"),
    supportProviders: document.getElementById("support-providers"),
    supportStatus: document.getElementById("support-status"),
    thanks: document.getElementById("thanks"),
    thanksLine: document.getElementById("thanks-line"),
    settingsThemes: document.getElementById("settings-themes"),
    settingsLengths: document.getElementById("settings-lengths"),
    settingsAttempts: document.getElementById("settings-attempts"),
    settingsDifficulty: document.getElementById("settings-difficulty"),
    difficultyNote: document.getElementById("difficulty-note"),
    hardIntro: document.getElementById("hard-intro"),
    hardIntroTitle: document.getElementById("hard-intro-title"),
    hardIntroRules: document.getElementById("hard-intro-rules"),
    hardIntroBadge: document.getElementById("hard-intro-badge"),
    hardIntroOk: document.getElementById("hard-intro-ok"),
  };

  // --- 화면 그리기 ---

  /** 게임판을 다시 그린다. 제출된 줄, 입력 중인 줄, 빈 줄 순서로 채운다. */
  function renderBoard() {
    const { game, draft } = state;
    if (!game) return;

    el.board.replaceChildren();
    el.board.style.setProperty("--length", String(game.length));

    for (let rowIndex = 0; rowIndex < game.max_attempts; rowIndex += 1) {
      const row = document.createElement("div");
      row.className = "board__row";
      row.style.gridTemplateColumns = `repeat(${game.length}, 1fr)`;
      row.dataset.row = String(rowIndex);

      const submitted = game.rows[rowIndex];
      const isActiveRow = !submitted && rowIndex === game.rows.length;

      for (let column = 0; column < game.length; column += 1) {
        const tile = document.createElement("div");
        tile.className = "tile";
        tile.setAttribute("role", "gridcell");

        if (submitted) {
          tile.textContent = submitted.jamos[column];
          tile.classList.add(`tile--${MARK_CLASS[submitted.marks[column]]}`);
        } else if (isActiveRow) {
          const jamo = draft[column] ?? "";
          tile.textContent = jamo;
          tile.classList.add("tile--active");
          if (jamo) tile.classList.add("tile--filled");
        } else {
          tile.classList.add("tile--pending");
        }
        row.append(tile);
      }
      el.board.append(row);
    }
  }

  /** 키보드를 그리고 지금까지 밝혀진 자모 색을 입힌다. */
  function renderKeyboard() {
    const colors = state.game?.keyboard ?? {};
    el.keyboard.replaceChildren();

    Hangul.KEYBOARD_ROWS.forEach((jamos, index) => {
      const row = document.createElement("div");
      row.className = "keyboard__row";

      jamos.forEach((jamo) => {
        const key = document.createElement("button");
        key.type = "button";
        key.className = "key";
        key.textContent = jamo;
        key.dataset.jamo = jamo;
        const mark = colors[jamo];
        if (mark) key.classList.add(`key--${MARK_CLASS[mark]}`);
        row.append(key);
      });

      // 첫 줄 끝에 지우기 키를 붙여 한 손으로 닿게 한다.
      if (index === 0) {
        const backspace = document.createElement("button");
        backspace.type = "button";
        backspace.className = "key key--wide";
        backspace.textContent = "←";
        backspace.dataset.action = "backspace";
        backspace.setAttribute("aria-label", "지우기");
        row.append(backspace);
      }
      el.keyboard.append(row);
    });
  }

  /** 남은 기회, 글자 수, 오늘 성적을 알려 주고 하단 버튼을 전환한다. */
  function renderMeta() {
    const { game } = state;
    if (!game) return;

    const playing = game.status === "playing";
    const left = game.max_attempts - game.rows.length;
    const solved = `오늘 ${game.solved_today}개`;

    // 오늘의 문제는 하루에 하나뿐이라 "몇 번째" 가 없다. 방을 보고 있으면
    // 그렇게 적어 준다 — 지금 무엇을 풀고 있는지가 화면에 있어야 한다.
    const which = state.room ? "오늘의 문제" : `${game.round_no + 1}번째 문제`;
    el.boardMeta.textContent = playing
      ? `${which} · 자모 ${game.length}칸 · 남은 기회 ${left}번 · ${solved}`
      : `${which} · ${game.status === "won" ? "정답" : "실패"} · ${solved}`;

    // 판이 끝나면 제출 버튼을 감추고 다음 문제 버튼을 띄운다. 같은 자리에서
    // 버튼만 바뀌므로 손가락을 옮기지 않고 계속 풀 수 있다.
    el.submit.hidden = !playing;
    el.next.hidden = playing;
    el.submit.disabled = !playing;

    renderHints();
  }

  /**
   * 힌트로 열린 자리를 보여 준다.
   *
   * **자리를 그대로 보여 주는 것이 핵심이다.** 예전에는 열린 자모만 앞에
   * 나열했는데, 그러면 그게 몇 번째 칸인지 알 수 없었다. 지금은 칸 수만큼
   * 그리고 열린 자리에만 글자를 넣는다 — ``_ _ ㄴ _ _`` 처럼.
   */
  function renderHints() {
    const game = state.game;
    if (!game) return;

    const slots = game.hints ?? [];
    const opened = slots.filter(Boolean).length;

    if (opened === 0) {
      el.hintLine.hidden = true;
    } else {
      el.hintLine.replaceChildren();
      const label = document.createElement("span");
      label.className = "hint-line__label";
      label.textContent = "힌트";
      const body = document.createElement("span");
      body.className = "hint-line__body";
      body.textContent = slots.map((jamo) => jamo ?? "_").join(" ");
      el.hintLine.append(label, body);
      el.hintLine.hidden = false;
    }

    const playing = game.status === "playing";
    el.hint.hidden = !(playing && game.hint_available);
    el.hint.textContent =
      game.hints_left > 1 ? `힌트 보기 (${game.hints_left})` : "힌트 보기";
  }

  async function revealHint() {
    if (state.locked || state.game?.status !== "playing") return;
    state.locked = true;
    try {
      // 지금 보고 있는 판으로 보낸다. 방을 보고 있는데 일반 판에 힌트를
      // 쓰면 엉뚱한 판의 기회가 줄어든다.
      state.game = state.room
        ? asBoard(await Api.hintDaily(state.room, state.game?.slot ?? 0))
        : await Api.hint();
      render();
      // 열린 자리가 몇 번째인지 알려 준다. "앞자리" 라고만 하면 이미 맞힌
      // 칸을 건너뛰고 연다는 사실이 화면에 안 드러난다.
      const opened = (state.game.hints ?? [])
        .map((jamo, index) => (jamo ? index + 1 : null))
        .filter((index) => index !== null);
      showMessage(
        opened.length
          ? `${opened.join(", ")}번째 칸이 열렸어요`
          : "열 수 있는 힌트가 없어요",
      );
    } catch (error) {
      showMessage(error.message, true);
    } finally {
      state.locked = false;
    }
  }

  /** 칸 크기를 가로·세로 **양쪽**에 맞춘다.
   *
   * 예전에는 판이 가로를 꽉 채우고 칸 높이가 거기서 나왔다. 그래서 자모
   * 7칸짜리 문제에서는 6줄이 세로를 넘쳐 **제출 버튼이 화면 밖으로 나갔다.**
   * 카톡 인앱 브라우저처럼 주소창과 툴바가 화면을 많이 먹는 곳에서 특히 심했다.
   *
   * 두 한계 중 **작은 쪽**을 쓴다. 가로로 들어갈 수 있는 크기와 세로로
   * 들어갈 수 있는 크기 중 작은 것이 실제로 들어가는 크기다.
   *
   * 상한(64px)을 두는 이유: 넓은 PC 화면에서 칸이 우스꽝스럽게 커진다.
   * 하한(24px)은 그 아래로는 글자가 안 읽히기 때문이다 — 그 경우에는
   * 차라리 넘치게 두고 사용자가 스크롤하는 편이 낫다.
   */
  function fitBoard() {
    const game = state.game;
    if (!game || !el.boardArea) return;

    const gap = 6;
    const area = el.boardArea.getBoundingClientRect();
    const meta = el.boardMeta?.getBoundingClientRect().height ?? 0;
    // board-area 의 위아래 여백(8px씩)과 요소 사이 간격(10px)을 뺀다.
    const usableHeight = area.height - meta - 36;
    const usableWidth = area.width - 24;

    const cols = game.length;
    const rows = game.max_attempts;
    const byWidth = (usableWidth - gap * (cols - 1)) / cols;
    // 칸의 세로:가로 = 1.12 이므로 높이 한계를 가로 크기로 되돌린다.
    const byHeight = (usableHeight - gap * (rows - 1)) / rows / 1.12;

    const size = Math.max(24, Math.min(byWidth, byHeight, 64));
    el.board.style.setProperty("--tile-size", `${Math.floor(size)}px`);
  }

  function render() {
    renderBoard();
    renderKeyboard();
    renderMeta();
    fitBoard();
  }

  /** 잠시 뒤에 한 번 더 맞춘다.
   *
   * **인앱 브라우저는 돌아오는 순간의 높이가 최종 높이가 아니다.** 주소창과
   * 툴바가 접혔다 펴지는 동안 화면 높이가 계속 바뀌는데, 그 중간에 재면
   * 실제보다 큰 값이 나와 판이 넘친다. 후원하고 돌아왔을 때 판이 헤더를
   * 덮은 것이 정확히 그 경우였다.
   *
   * 두 번 재는 값이 한 번 재고 틀리는 값보다 싸다.
   */
  function fitBoardSoon() {
    fitBoard();
    setTimeout(fitBoard, 150);
    setTimeout(fitBoard, 600);
  }

  // 화면이 바뀌면 다시 맞춘다.
  //
  // visualViewport 를 함께 듣는 이유: 폰에서 키보드가 올라오면 보이는 높이가
  // 줄어드는데 window 의 resize 는 안 오는 브라우저가 있다. 그때 다시 안
  // 맞추면 판이 키보드에 가린다.
  window.addEventListener("resize", fitBoard);
  window.visualViewport?.addEventListener("resize", fitBoard);
  // 다른 앱에 갔다 돌아온 경우. 이때가 높이가 제일 안 믿기는 순간이다.
  window.addEventListener("pageshow", fitBoardSoon);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) fitBoardSoon();
  });

  /** 짧은 안내 문구. `isError`면 붉게 보이고 잠시 뒤 사라진다. */
  let messageTimer = null;
  function showMessage(text, isError = false, holdMs = 2400) {
    el.message.textContent = text;
    el.message.classList.toggle("message--error", isError);
    clearTimeout(messageTimer);
    if (text) messageTimer = setTimeout(() => showMessage(""), holdMs);
  }

  /**
   * 사전에 없다고 거절당했을 때. **친 낱말과 신고 단추를 같이 보여 준다.**
   *
   * 그냥 "사전에 없는 단어입니다" 만 2.4초 띄웠더니 세 가지가 안 됐다.
   *
   *  - 무엇을 쳤는지 안 보인다. 자모 여덟 개를 눈으로 되짚어야 했다.
   *  - 읽기 전에 사라진다. 그래서 5초로 늘렸다.
   *  - **멀쩡한 낱말인데 사전에 없는 경우**를 알릴 방법이 없었다. 지금까지
   *    그걸 아는 유일한 경로가 친구가 카톡으로 말해 주는 것이었는데,
   *    말 안 하고 그냥 접는 사람이 훨씬 많다.
   *
   * 자모를 도로 글자로 합쳐 보여 준다. `ㅂㅏㅇㅌㅏㄴㅁㅗ` 보다 `방탄모` 가
   * "내가 친 것" 으로 읽힌다.
   */
  const REJECT_HOLD_MS = 5000;

  function showRejection(jamos) {
    clearTimeout(messageTimer);
    el.message.textContent = "";
    el.message.classList.add("message--error");

    const word = Hangul.compose(jamos) || jamos;
    const said = document.createElement("span");
    said.textContent = `'${word}' 은(는) 사전에 없어요`;

    const report = document.createElement("button");
    report.type = "button";
    report.className = "message__report";
    report.textContent = "신고";
    report.title = "진짜 있는 낱말인데 거절당했다면 알려 주세요";
    report.addEventListener("click", async () => {
      // 두 번 누르지 못하게 즉시 잠근다. 눌렀는지 아닌지가 안 보이면
      // 사람은 한 번 더 누른다.
      report.disabled = true;
      try {
        await Api.reportWord(jamos);
        showMessage(`'${word}' 신고했어요. 고맙습니다 🙏`, false, REJECT_HOLD_MS);
      } catch (error) {
        showMessage(error.message, true, REJECT_HOLD_MS);
      }
    });

    el.message.append(said, report);
    messageTimer = setTimeout(() => showMessage(""), REJECT_HOLD_MS);
  }

  /** 입력 중인 줄을 흔들어 거절을 알린다. */
  function shakeActiveRow() {
    const row = el.board.querySelector(`[data-row="${state.game.rows.length}"]`);
    if (!row) return;
    row.classList.remove("board__row--shake");
    void row.offsetWidth; // 애니메이션을 다시 시작시키기 위한 강제 리플로
    row.classList.add("board__row--shake");
  }

  /** 방금 제출된 줄의 칸을 순서대로 뒤집는다. */
  function animateLastRow() {
    const index = state.game.rows.length - 1;
    const row = el.board.querySelector(`[data-row="${index}"]`);
    if (!row) return;
    [...row.children].forEach((tile, column) => {
      tile.style.animationDelay = `${column * 90}ms`;
      tile.classList.add("tile--flip");
    });
  }

  /** 맞혔을 때 정답 줄이 왼쪽부터 차례로 튀어오른다.
   *
   * 뒤집기가 **다 끝난 뒤에** 시작해야 한다. 겹치면 두 변형이 서로를 덮어써서
   * 칸이 덜컥거린다. 그래서 뒤집기 시간(칸수 × 90ms + 한 칸 분량)만큼 기다린다.
   */
  function animateWin() {
    const index = state.game.rows.length - 1;
    const row = el.board.querySelector(`[data-row="${index}"]`);
    if (!row) return;
    const after = state.game.length * 90 + 400;
    setTimeout(() => {
      [...row.children].forEach((tile, column) => {
        tile.style.animationDelay = `${column * 80}ms`;
        tile.classList.add("tile--win");
      });
    }, after);
  }

  /** 졌을 때 판 전체가 한 번 가라앉는다.
   *
   * 흔들기(오답)와 다른 몸짓이어야 한다. 같은 연출을 쓰면 "단어가 틀렸다"와
   * "판이 끝났다"가 구분되지 않는다.
   */
  function animateLose() {
    const after = state.game.length * 90 + 400;
    setTimeout(() => {
      el.board.classList.remove("board--lose");
      // 리플로를 강제해 애니메이션을 다시 태운다. 안 하면 두 번째부터 안 돈다.
      void el.board.offsetWidth;
      el.board.classList.add("board--lose");
    }, after);
  }

  // --- 입력 처리 ---

  function pushJamo(jamo) {
    if (state.locked || state.game?.status !== "playing") return;
    if (state.draft.length >= state.game.length) return;
    // 다음 낱말을 치기 시작했으면 앞의 안내는 볼 일이 끝났다. 거절 안내를
    // 5초나 띄우기 때문에, 안 지우면 새로 치는 동안 계속 남아 거슬린다.
    if (!state.draft.length) showMessage("");
    state.draft.push(jamo);
    renderBoard();
  }

  function popJamo() {
    if (state.locked || state.game?.status !== "playing") return;
    state.draft.pop();
    renderBoard();
  }

  async function submitDraft() {
    if (state.locked) return;
    if (state.game?.status !== "playing") {
      openSheet();
      return;
    }
    if (state.draft.length !== state.game.length) {
      shakeActiveRow();
      showMessage(`자모 ${state.game.length}개를 채워 주세요.`, true);
      return;
    }

    state.locked = true;
    el.submit.disabled = true;
    // try 밖에 둔다. 거절당했을 때 catch 에서 **무엇을 쳤는지** 알아야
    // 신고 단추를 붙일 수 있는데, try 안에서 선언하면 catch 에서 안 보인다.
    const answer = state.draft.join("");
    try {
      // 방의 오늘의 문제를 푸는 중이면 그쪽으로 보낸다. 저장되는 표가
      // 다르기 때문이다(일반 라운드와 오늘의 문제는 별개의 판이다).
      // 그리고 있는 판과 같은 곳으로 보낸다. state.room 이 판과 함께
      // 바뀌므로 둘이 어긋날 수 없다.
      state.game = state.room
        ? asBoard(
            await Api.dailyGuess(state.room, answer, state.game?.slot ?? 0),
          )
        : await Api.guess(answer);
      state.draft = [];
      render();
      animateLastRow();
      const word = state.game.rows.at(-1)?.word;
      if (word) showMessage(word);
      if (state.game.status === "won") {
        animateWin();
        // 연출을 다 보고 나서 결과창이 뜨게 한다. 바로 덮으면 방금 맞힌
        // 순간을 못 본다 — 그게 이 게임에서 제일 기분 좋은 지점이다.
        setTimeout(openSheet, state.game.length * 90 + 1200);
      } else if (state.game.status === "lost") {
        animateLose();
        setTimeout(openSheet, state.game.length * 90 + 1000);
      }
    } catch (error) {
      shakeActiveRow();
      // 사전에 없다는 거절만 신고 단추를 붙인다. 난이도 규칙 위반이나
      // 길이 오류에까지 붙이면 신고함이 쓰레기로 찬다.
      if (error.code === "unknown_word") showRejection(answer);
      else showMessage(error.message, true);
    } finally {
      state.locked = false;
      renderMeta();
    }
  }

  /** 다음 문제를 연다. 서버가 진행 중인 판을 지켜 주므로 건너뛰기는 불가능하다. */
  /**
   * 지금 보고 있는 오늘의 문제에서 **아직 안 끝낸 다음 칸**을 찾는다.
   * 없으면 null.
   */
  function nextUnfinishedSlot(game) {
    const slots = game?.slots ?? [];
    const here = game?.round_no ?? 0;
    // 지금 칸 다음부터 한 바퀴 돌며 찾는다. 1번을 나중에 풀었어도
    // 2번이 남아 있으면 잡힌다.
    for (let i = 1; i <= slots.length; i += 1) {
      const row = slots[(here + i) % slots.length];
      if (row && row.status !== "won" && row.status !== "lost") return row.slot;
    }
    return null;
  }

  /**
   * "다음 문제" 를 누르면 무엇을 열까.
   *
   * **오늘의 문제가 남아 있으면 그것이 먼저다.** 예전에는 무조건 일반 판을
   * 열었다. 그래서 1번을 맞히고 다음을 눌렀는데 2번이 아니라 엉뚱한 문제가
   * 나왔고, 친구들과 겨루려고 들어온 사람이 혼자 푸는 판에 떨어졌다.
   * 오늘의 문제는 **다 같이 같은 낱말**을 푸는 것이라 그게 이 게임의 중심이다.
   */
  async function goNextRound() {
    if (state.locked) return;
    state.locked = true;
    try {
      const slot = state.room ? nextUnfinishedSlot(state.game) : null;
      if (state.room && slot !== null) {
        closeSheet();
        showMessage("");
        await openDaily(state.room, slot);
        return;
      }
      // 남은 오늘의 문제가 없을 때만 일반 판으로 간다. 방을 비우지 않으면
      // 방금 보던 오늘의 문제로 채점이 계속 간다.
      setGame(await Api.nextRound(), null);
      closeSheet();
      render();
      showMessage("");
    } catch (error) {
      showMessage(error.message, true);
    } finally {
      state.locked = false;
    }
  }

  // --- 결과 시트 ---

  async function openSheet() {
    el.sheet.hidden = false;
    const finished = state.game?.status !== "playing";
    el.sheetNext.hidden = !finished;
    el.sheetShare.hidden = !finished || !state.game?.share_text;
    // 오늘의 문제를 보고 있으면 이 창의 주인공은 **그 방의 순위**다.
    const daily = Boolean(state.room);
    el.sheetTitle.textContent = daily ? "오늘의 문제" : "내 전적";
    el.sheetBody.replaceChildren(paragraph("불러오는 중...", "muted"));
    try {
      // 방 순위는 판에 이미 실려 온다. 오늘의 문제에서는 혼자 풀기 순위를
      // 부르지 않는다 — 불러 봐야 보여 줄 자리가 없다.
      const [stats, board] = await Promise.all([
        Api.stats(),
        daily ? Promise.resolve(null) : Api.leaderboard(),
      ]);
      el.sheetBody.replaceChildren(...buildSheet(stats, board));
    } catch (error) {
      el.sheetBody.replaceChildren(paragraph(error.message, "muted"));
    }
  }

  function closeSheet() {
    el.sheet.hidden = true;
    document.getElementById("share-preview")?.remove();
  }

  function buildSheet(stats, board) {
    const nodes = [];
    const game = state.game;

    if (game && game.status !== "playing") {
      const result = document.createElement("div");
      result.className = "result";
      result.append(
        paragraph(game.status === "won" ? "정답입니다" : "오늘은 아쉽네요", "muted")
      );
      const answer = document.createElement("div");
      answer.className = "result__answer";
      answer.textContent = game.answer ?? "";
      result.append(answer);
      nodes.push(result);
    }

    if (state.room) {
      // **오늘의 문제를 끝냈으면 같은 방 사람들과의 순위가 먼저다.** 예전에는
      // 여기서도 혼자 풀기 순위를 보여 줘서, 방에서 문제를 막 맞힌 사람이
      // "아직 참가자가 없습니다" 를 봤다. 그날 아침 혼자 풀기를 한 사람이 아무도
      // 없었을 뿐인데, 보는 쪽에서는 방에 아무도 없는 것처럼 읽힌다.
      const slot = (game?.slot ?? 0) + 1;
      nodes.push(sectionTitle(`오늘의 순위 · ${game?.room?.name ?? "방"} ${slot}번`));
      const box = document.createElement("div");
      box.className = "standings";
      fillStandings(box, game?.standings ?? []);
      nodes.push(box);
      nodes.push(sectionTitle("혼자 풀기 전적"));
    }

    nodes.push(
      statGrid([
        ["플레이", stats.played],
        ["승률", `${Math.round(stats.win_rate * 100)}%`],
        ["연속", stats.current_streak],
        ["최고 연속", stats.max_streak],
      ])
    );

    nodes.push(sectionTitle("시도 횟수 분포"));
    // 막대에 불을 켜는 것은 **방금 끝낸 판이 이 분포에 들어 있을 때만**이다.
    // 오늘의 문제는 혼자 풀기 전적에 안 들어가므로 켜면 엉뚱한 막대가 켜진다.
    const justPlayed = state.room ? 0 : game?.rows?.length ?? 0;
    nodes.push(distribution(stats.guess_distribution, justPlayed));

    if (board) {
      nodes.push(sectionTitle("오늘의 순위"));
      nodes.push(rankList(board.entries));
    }
    return nodes;
  }

  function statGrid(pairs) {
    const grid = document.createElement("div");
    grid.className = "stat-grid";
    pairs.forEach(([label, value]) => {
      const cell = document.createElement("div");
      const valueNode = document.createElement("div");
      valueNode.className = "stat__value";
      valueNode.textContent = String(value);
      const labelNode = document.createElement("div");
      labelNode.className = "stat__label";
      labelNode.textContent = label;
      cell.append(valueNode, labelNode);
      grid.append(cell);
    });
    return grid;
  }

  function distribution(dist, highlight) {
    const wrapper = document.createElement("div");
    const counts = Object.entries(dist).map(([k, v]) => [Number(k), v]);
    const max = Math.max(1, ...counts.map(([, v]) => v));
    const attempts = state.game?.max_attempts ?? 6;

    for (let n = 1; n <= attempts; n += 1) {
      const count = dist[n] ?? 0;
      const row = document.createElement("div");
      row.className = "dist__row";

      const label = document.createElement("span");
      label.textContent = String(n);

      const bar = document.createElement("span");
      bar.className = "dist__bar";
      if (count > 0 && n === highlight && state.game?.status === "won") {
        bar.classList.add("dist__bar--best");
      }
      bar.style.width = `${Math.max(8, (count / max) * 100)}%`;
      bar.textContent = String(count);

      row.append(label, bar);
      wrapper.append(row);
    }
    return wrapper;
  }

  /**
   * 순위표를 그린다.
   *
   * 등수만 늘어놓으면 1등 말고는 볼 이유가 없다. 그래서 메달과 칭호를 붙이고,
   * 보는 사람의 줄은 배경을 다르게 해 자기 자리를 바로 찾게 한다.
   */
  /**
   * 닉네임 옆에 붙는 "방장과의 사이". 안 적은 사람이 대부분이라
   * **빈 값이면 아무것도 안 만든다** — 빈 칸이 줄줄이 생기면 오히려
   * 안 적은 것이 눈에 띈다.
   */
  function relationTag(text) {
    const value = (text ?? "").trim();
    if (!value) return null;
    const tag = document.createElement("span");
    tag.className = "relation-tag";
    tag.textContent = value;
    return tag;
  }

  function rankList(entries) {
    if (entries.length === 0) return paragraph("아직 참가자가 없습니다.", "muted");
    const list = document.createElement("ul");
    list.className = "rank-list";

    entries.forEach((entry) => {
      const item = document.createElement("li");
      item.className = "rank-list__item";
      if (entry.is_me) item.classList.add("rank-list__item--me");

      const rank = document.createElement("span");
      rank.className = "rank-list__rank";
      rank.textContent = entry.medal || String(entry.rank);

      const who = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = entry.display_name;
      who.append(name);

      const rel = relationTag(entry.relation);
      if (rel) who.append(rel);

      if (entry.title) {
        const badge = document.createElement("span");
        badge.className = "rank-list__title";
        badge.textContent = `${entry.title_emoji} ${entry.title}`;
        who.append(badge);
      }

      const sub = document.createElement("span");
      sub.className = "rank-list__sub";
      sub.textContent = subtitleFor(entry);
      who.append(sub);

      const score = document.createElement("span");
      score.className = "rank-list__score";
      score.textContent = `${entry.solved}개`;

      item.append(rank, who, score);
      list.append(item);
    });
    return list;
  }

  /** 순위표 두 번째 줄. 값이 없는 항목은 통째로 뺀다. */
  function subtitleFor(entry) {
    const bits = [`${entry.played}판`];
    if (entry.average_attempts != null) bits.push(`평균 ${entry.average_attempts}번`);
    if (entry.best_attempts != null) bits.push(`최고 ${entry.best_attempts}번`);
    return bits.join(" · ");
  }

  function paragraph(text, className = "") {
    const node = document.createElement("p");
    if (className) node.className = className;
    node.textContent = text;
    return node;
  }

  function sectionTitle(text) {
    const node = document.createElement("h3");
    node.className = "section-title";
    node.textContent = text;
    return node;
  }

  /**
   * 결과를 공유한다.
   *
   * 휴대폰에서는 운영체제의 공유 시트를 띄운다. 카카오톡, 메시지, 어디로든
   * 바로 보낼 수 있어 가장 자연스럽다. 데스크톱 브라우저는 대개 이 기능이
   * 없으므로 클립보드에 복사한다.
   *
   * 둘 다 막힌 경우(권한 거부, 안전하지 않은 출처)를 대비해 마지막에는 글을
   * 화면에 펼쳐 전체 선택해 둔다. 사용자가 직접 긁어 갈 수 있다.
   */
  async function shareResult() {
    const text = state.game?.share_text;
    if (!text) return;

    if (navigator.share) {
      try {
        await navigator.share({ text });
        return;
      } catch (error) {
        // 사용자가 공유 시트를 닫은 것이면 아무 일도 없었던 셈이다.
        if (error?.name === "AbortError") return;
      }
    }

    try {
      await navigator.clipboard.writeText(text);
      flashShareButton("복사했습니다");
      return;
    } catch {
      showSharePreview(text);
    }
  }

  /** 버튼 글자를 잠시 바꿔 성공을 알린다. 알림창보다 덜 거슬린다. */
  function flashShareButton(message) {
    const original = el.sheetShare.textContent;
    el.sheetShare.textContent = message;
    setTimeout(() => {
      el.sheetShare.textContent = original;
    }, 1600);
  }

  /** 복사가 막혔을 때 글을 펼쳐 직접 긁어 가게 한다. */
  function showSharePreview(text) {
    let box = document.getElementById("share-preview");
    if (!box) {
      box = document.createElement("textarea");
      box.id = "share-preview";
      box.className = "share-preview";
      box.readOnly = true;
      box.rows = text.split("\n").length;
      el.sheetShare.insertAdjacentElement("afterend", box);
    }
    box.value = text;
    box.select();
    flashShareButton("아래 글을 복사하세요");
  }

  // --- 설정 ---

  /**
   * 설정 창을 연다.
   *
   * 설정은 서버가 사람마다 따로 들고 있다. 브라우저에 저장하면 기기를 바꿀 때
   * 잃어버리고, 같은 닉네임으로 다른 기기에서 들어왔을 때 설정이 달라진다.
   */
  async function openSettings() {
    el.settings.hidden = false;
    setSettingsStatus("");
    try {
      const settings = await Api.settings();
      // 서버가 힌트 기능을 아예 안 주면 항목 자체를 감춘다. 켤 수 없는 스위치를
      // 보여 주는 것은 사용자를 헷갈리게 할 뿐이다.
      el.settingsHintRow.hidden = !settings.hints_offered;
      el.settingsHints.checked = settings.hints_enabled;
      updateSwitchLabel();
      el.settingsRelation.value = settings.relation ?? "";
      renderThemes(settings.themes, settings.share_theme);
      renderLengths(settings.available_lengths, settings.puzzle_lengths);
      renderAttempts(settings.attempt_choices, settings.max_attempts);
      costlyDifficulties = settings.costly_difficulties ?? [];
      renderDifficulties(settings.difficulty_choices, settings.difficulty);
    } catch (error) {
      setSettingsStatus(error.message);
    }
  }

  /* ---------------- 난이도 ----------------
   *
   * 스위치가 아니라 칸 고르기인 이유: 난이도가 셋이 되면서 켬/끔으로는
   * 표현이 안 된다. 시도 횟수와 같은 모양으로 두어 "하나만 고르는 것"
   * 이라는 게 보이게 한다.
   *
   * 규칙을 모르고 올리면 "왜 자꾸 거부당하지" 가 된다. 그래서 **그 난이도를
   * 처음 고를 때 한 번만** 설명을 띄운다. 매번 띄우면 잔소리가 되고, 아예 안
   * 띄우면 규칙을 알 방법이 없다.
   *
   * 본 적 있는지는 난이도마다 따로 기억한다. 하드모드를 봤다고 불닭모드
   * 규칙까지 아는 것은 아니다.
   */
  const INTRO_SEEN_PREFIX = "ttobak_intro_seen_";

  /**
   * 지금 고르면 **풀던 판을 잃는** 난이도 열쇠들. 설정을 열 때 서버가 준다.
   *
   * 참/거짓 하나였다가 목록으로 바꿨다. 어느 쪽으로 바꾸느냐에 따라 답이
   * 다르기 때문이다 — 불닭에서 보통으로 내리는 것은 공짜인데, 예전에는
   * 그때도 판을 포기로 적고 "새 문제가 나옵니다" 라고 겁을 줬다.
   */
  let costlyDifficulties = [];

  /** 난이도 고르기. 하나만 고른다. */
  function renderDifficulties(choices, selected) {
    const box = el.settingsDifficulty;
    box.textContent = "";
    (choices ?? []).forEach((choice) => {
      const on = choice.key === selected;
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = on ? "length-chip length-chip--on" : "length-chip";
      // 이모지를 앞에 붙여 공유 문구에 뭐가 찍히는지 미리 보이게 한다.
      chip.textContent = choice.emoji
        ? `${choice.emoji} ${choice.label}`
        : choice.label;
      chip.setAttribute("aria-pressed", String(on));
      chip.addEventListener("click", async () => {
        if (on) return;
        // 규칙을 **더하는** 쪽으로 바꿀 때만 풀던 판을 잃는다. 되돌릴 수
        // 없으니 그때만 묻는다.
        //
        // 어느 난이도가 그런지는 서버가 정해 준다(costly_difficulties).
        // 화면이 같은 규칙을 한 벌 더 가지면 언젠가 한쪽만 고쳐져서,
        // 안 물어보고 판을 날리거나 잃을 것도 없는데 겁을 주게 된다.
        if (costlyDifficulties.includes(choice.key)) {
          const ask =
            "지금 풀던 판은 포기로 기록되고 새 문제가 나옵니다." +
            " (난이도를 내리는 쪽은 풀던 판 그대로 갑니다.) 바꿀까요?";
          if (!confirm(ask)) return;
        }
        try {
          const saved = await Api.saveSettings({ difficulty: choice.key });
          renderDifficulties(saved.difficulty_choices, saved.difficulty);
          costlyDifficulties = saved.costly_difficulties ?? [];
          setSettingsStatus("저장했어요.");
          maybeShowIntro(choice);
          // 판이 바뀌었을 수 있다. 화면을 서버 상태로 다시 맞춘다 —
          // 안 하면 이미 없어진 판을 계속 그리고 있게 된다.
          await refreshCurrentGame();
        } catch (error) {
          setSettingsStatus(error.message);
        }
      });
      box.appendChild(chip);
    });

    // 고른 난이도의 설명을 칸 아래에 항상 띄워 둔다. 설명 창은 한 번만
    // 뜨므로, 나중에 "이게 뭐였더라" 를 확인할 곳이 필요하다.
    const current = (choices ?? []).find((choice) => choice.key === selected);
    el.difficultyNote.textContent = current ? current.note : "";
  }

  /** 이 난이도의 규칙 설명을 처음 한 번만 띄운다. */
  function maybeShowIntro(choice) {
    // 기본 난이도는 강제하는 게 없으니 설명할 것도 없다.
    if (!choice.keep_correct && !choice.require_present) return;

    const key = INTRO_SEEN_PREFIX + choice.key;
    let seen = false;
    try {
      seen = localStorage.getItem(key) === "1";
    } catch {
      // 저장소가 막혔으면 매번 보여 준다. 안 보여 주는 것보다 낫다.
    }
    if (seen) return;

    el.hardIntroTitle.textContent = `${choice.emoji} ${choice.label}모드`;
    el.hardIntroRules.textContent = "";
    // 서버가 준 규칙 그대로 그린다. 화면에 규칙을 또 적어 두면 서버와
    // 어긋났을 때 알아챌 방법이 없다.
    if (choice.keep_correct) {
      addRule("correct", "맞힌 자리는 ", "그대로", " 두기");
    }
    if (choice.require_present) {
      addRule("present", "나온 자모는 ", "꼭 넣기", "");
    }
    addRule("none", "힌트 ", "사용 불가", "", "✕");
    el.hardIntroBadge.textContent = `공유할 때 ${choice.emoji} 표시가 붙습니다.`;
    el.hardIntro.hidden = false;

    try {
      localStorage.setItem(key, "1");
    } catch {
      /* 무시 */
    }
  }

  /** 설명 창의 규칙 한 줄. 색 칸 + 문구로 만든다.
   *
   * textContent 로만 넣는다. innerHTML 로 조립하면 나중에 여기에 사용자
   * 문자열이 섞였을 때 그대로 스크립트가 된다.
   */
  function addRule(mark, before, strong, after, glyph = "") {
    const item = document.createElement("li");
    const box = document.createElement("span");
    box.className = `rule-list__mark rule-list__mark--${mark}`;
    box.textContent = glyph;
    const bold = document.createElement("strong");
    bold.textContent = strong;
    item.append(box, document.createTextNode(before), bold);
    if (after) item.append(document.createTextNode(after));
    el.hardIntroRules.appendChild(item);
  }

  el.hardIntroOk.addEventListener("click", () => {
    el.hardIntro.hidden = true;
  });

  /** 시도 횟수 고르기.
   *
   * 길이와 달리 **하나만** 고른다. 여러 개를 켜는 것이 아니라 값 하나를
   * 정하는 것이라 라디오처럼 동작해야 한다.
   */
  function renderAttempts(choices, selected) {
    const box = el.settingsAttempts;
    box.textContent = "";
    (choices ?? []).forEach((count) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className =
        count === selected ? "length-chip length-chip--on" : "length-chip";
      chip.textContent = `${count}번`;
      chip.setAttribute("aria-pressed", String(count === selected));
      chip.addEventListener("click", async () => {
        if (count === selected) return;
        try {
          const saved = await Api.saveSettings({ max_attempts: count });
          renderAttempts(saved.attempt_choices, saved.max_attempts);
          setSettingsStatus("저장했어요. 다음 문제부터 적용돼요.");
        } catch (error) {
          setSettingsStatus(error.message);
        }
      });
      box.appendChild(chip);
    });
  }

  /** 문제 길이 고르기.
   *
   * 여러 개를 켜고 끄는 것이라 한 번에 하나만 고르는 테마와 다르다.
   * 마지막 하나를 끄려 하면 막는다 — 전부 끄면 낼 문제가 없다. 서버도
   * 그때 "전부" 로 되돌리지만, 화면에서 먼저 막아야 사용자가 자기가 뭘
   * 한 건지 안다.
   */
  function renderLengths(available, selected) {
    const box = el.settingsLengths;
    box.textContent = "";
    const chosen = new Set(selected ?? []);

    (available ?? []).forEach((length) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = chosen.has(length)
        ? "length-chip length-chip--on"
        : "length-chip";
      chip.textContent = `${length}칸`;
      chip.setAttribute("aria-pressed", String(chosen.has(length)));

      chip.addEventListener("click", async () => {
        if (chosen.has(length)) {
          if (chosen.size === 1) {
            setSettingsStatus("하나는 남겨 주세요.");
            return;
          }
          chosen.delete(length);
        } else {
          chosen.add(length);
        }
        const next = [...chosen].sort((a, b) => a - b);
        try {
          const saved = await Api.saveSettings({ puzzle_lengths: next });
          renderLengths(saved.available_lengths, saved.puzzle_lengths);
          setSettingsStatus("저장했어요. 다음 문제부터 적용돼요.");
        } catch (error) {
          setSettingsStatus(error.message);
        }
      });
      box.appendChild(chip);
    });
  }

  /**
   * 테마 고르기 칸을 그린다.
   *
   * 이름만 나열하면 무엇이 나올지 알 수 없다. 그래서 칸마다 실제 그림 세 개를
   * 미리 보여 준다. 고르는 순간 어떤 모양이 될지 바로 알 수 있다.
   */
  function renderThemes(themes, selected) {
    el.settingsThemes.replaceChildren();
    (themes ?? []).forEach((theme) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "theme-chip";
      chip.setAttribute("role", "radio");
      chip.setAttribute("aria-checked", String(theme.key === selected));
      chip.dataset.theme = theme.key;

      const preview = document.createElement("span");
      preview.className = "theme-chip__preview";
      preview.textContent = theme.preview;

      const label = document.createElement("span");
      label.textContent = theme.label;

      chip.append(preview, label);
      el.settingsThemes.append(chip);
    });
  }

  /** 테마를 저장한다. 고른 칸에 바로 표시가 옮겨 간다. */
  async function saveTheme(key) {
    try {
      const settings = await Api.saveSettings({ share_theme: key });
      renderThemes(settings.themes, settings.share_theme);
      setSettingsStatus("테마를 바꿨습니다");
      // 이미 끝난 판이 있으면 공유 문구도 새 테마로 다시 받아 둔다.
      // 보고 있던 **같은 문제**를 다시 받는 것이라, 오늘의 문제를 보는
      // 중에도 판이 엉뚱한 것으로 바뀌지 않는다.
      await refreshCurrentGame();
    } catch (error) {
      setSettingsStatus(error.message);
    }
  }

  function closeSettings() {
    el.settings.hidden = true;
  }

  function setSettingsStatus(text) {
    el.settingsStatus.textContent = text;
  }

  /** 스위치 옆 글자를 상태에 맞춘다. 색만으로 구분하지 않기 위해서다. */
  function updateSwitchLabel() {
    const label = el.settingsHints.nextElementSibling?.nextElementSibling;
    if (label) label.textContent = el.settingsHints.checked ? "켬" : "끔";
  }

  /**
   * 지금 보고 있는 판을 서버에서 다시 받아 온다.
   *
   * 힌트 단추를 그릴지 같은 것은 **서버가 판에 실어 보낸다.** 그래서 설정을
   * 바꾼 뒤 판을 다시 받지 않으면 화면이 옛 상태 그대로 남는다.
   *
   * 혼자 푸는 판과 오늘의 문제는 받아 오는 곳이 다르다. 한쪽만 챙기면
   * 다른 쪽에서 조용히 안 바뀐다 — 실제로 그랬다.
   */
  async function refreshCurrentGame() {
    if (state.room) {
      showDaily(await Api.daily(state.room, state.game?.slot));
    } else {
      setGame(await Api.game(), null);
    }
    // 그리기까지 여기서 한다. 부르는 쪽마다 render() 를 따로 붙이게 두면
    // 또 한 군데를 빠뜨린다 — 이 버그가 정확히 그렇게 생겼다.
    render();
  }

  /** 힌트 설정을 저장한다. 실패하면 스위치를 원래대로 되돌린다. */
  async function saveHintSetting() {
    const wanted = el.settingsHints.checked;
    el.settingsHints.disabled = true;
    updateSwitchLabel();
    try {
      const settings = await Api.saveSettings({ hints_enabled: wanted });
      el.settingsHints.checked = settings.hints_enabled;
      setSettingsStatus(settings.hints_enabled ? "힌트를 켰습니다" : "힌트를 껐습니다");
      // 게임판의 힌트 버튼이 **바로** 나타나거나 사라져야 한다. 버튼을
      // 그릴지는 서버가 내려준 판에 붙어 오므로, 판을 다시 받아야 바뀐다.
      //
      // 예전에는 혼자 푸는 판만 다시 받았다(`if (!state.room)`). 그래서
      // 오늘의 문제를 보는 중에 힌트를 끄면 단추가 그대로 남아 있었다.
      // 보고 있는 판이 어느 쪽이든 그쪽을 다시 받는다.
      await refreshCurrentGame();
    } catch (error) {
      el.settingsHints.checked = !wanted;
      setSettingsStatus(error.message);
    } finally {
      el.settingsHints.disabled = false;
      updateSwitchLabel();
    }
  }

  /**
   * 방장과의 사이를 저장한다.
   *
   * 저장 단추를 따로 두지 않고 **칸에서 손을 뗄 때** 저장한다. 설정 시트에는
   * 저장 단추가 하나도 없어서, 여기에만 하나 생기면 다른 항목도 눌러야
   * 저장되는 줄 알게 된다.
   */
  async function saveRelation() {
    const wanted = el.settingsRelation.value.trim();
    el.settingsRelation.disabled = true;
    try {
      const settings = await Api.saveSettings({ relation: wanted });
      el.settingsRelation.value = settings.relation ?? "";
      setSettingsStatus(wanted ? "소개를 저장했습니다" : "소개를 지웠습니다");
    } catch (error) {
      setSettingsStatus(error.message);
    } finally {
      el.settingsRelation.disabled = false;
    }
  }

  // --- 이벤트 배선 ---

  el.keyboard.addEventListener("click", (event) => {
    const key = event.target.closest("button");
    if (!key) return;
    if (key.dataset.action === "backspace") popJamo();
    else if (key.dataset.jamo) pushJamo(key.dataset.jamo);
  });

  el.submit.addEventListener("click", submitDraft);
  el.next.addEventListener("click", goNextRound);
  el.hint.addEventListener("click", revealHint);
  el.sheetNext.addEventListener("click", goNextRound);
  el.sheetShare.addEventListener("click", shareResult);
  el.statsButton.addEventListener("click", openSheet);
  el.sheetClose.addEventListener("click", closeSheet);
  el.sheet.addEventListener("click", (event) => {
    if (event.target === el.sheet) closeSheet();
  });

  el.menuButton.addEventListener("click", openSettings);
  el.settingsClose.addEventListener("click", closeSettings);
  el.settings.addEventListener("click", (event) => {
    if (event.target === el.settings) closeSettings();
  });
  el.settingsHints.addEventListener("change", saveHintSetting);
  // change 는 값이 실제로 바뀌고 칸에서 나갈 때만 뜬다. input 마다 보내면
  // 한 글자에 한 번씩 요청이 나간다.
  el.settingsRelation.addEventListener("change", saveRelation);
  el.settingsThemes.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-theme]");
    if (chip) saveTheme(chip.dataset.theme);
  });

  /* ==================================================================
   * 방 · 오늘의 문제 · 댓글
   * ==================================================================
   *
   * 방의 존재 이유는 하나다. **같은 방 사람은 같은 단어를 푼다.**
   * 사람마다 다른 문제를 풀면 "난 세 번 만에 맞췄어"를 비교할 수 없고,
   * 공유한 이모지 격자도 남이 보면 아무 의미가 없다.
   *
   * 판을 그리는 코드는 일반 게임과 **같은 것**을 쓴다. 서버가 오늘의 문제도
   * 같은 모양(rows, keyboard)으로 주기 때문이다. 색칠 규칙이 두 벌이 되면
   * 한쪽만 고쳐져 같은 자모가 화면마다 다른 색으로 보인다.
   */
  // showDaily 는 매개변수 이름이 state 라 바깥 state 를 가린다. 예전에는
  // 그것 때문에 gameState 라는 별칭이 필요했는데, 지금은 setGame 을 거치므로
  // 안 쓴다.
  let myRooms = [];
  let dailyShareText = null;

  function roomLink(code) {
    // 초대 링크. 현재 주소에 ?room= 만 붙인다 — 친구가 눌렀을 때 앱이 뜨고
    // 자동으로 그 방에 들어가진다.
    const base = location.origin + location.pathname;
    return `${base}?room=${encodeURIComponent(code)}`;
  }

  function renderRooms() {
    const box = el.roomsList;
    box.textContent = "";

    if (!myRooms.length) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "아직 방이 없어요. 아래에서 하나 만들어 보세요.";
      box.appendChild(empty);
      return;
    }

    myRooms.forEach((room) => {
      const card = document.createElement("div");
      card.className = "room";

      const head = document.createElement("div");
      head.className = "room__head";

      const name = document.createElement("span");
      name.className = "room__name";
      name.textContent = room.name;

      const count = document.createElement("span");
      count.className = "hint";
      count.textContent = `${room.member_count}명`;

      head.append(name, count);

      const actions = document.createElement("div");
      actions.className = "room__actions";

      const play = document.createElement("button");
      play.className = "button button--primary button--small";
      play.type = "button";
      play.textContent = "오늘의 문제";
      play.addEventListener("click", () => openDaily(room.id));

      const invite = document.createElement("button");
      invite.className = "button button--small";
      invite.type = "button";
      invite.textContent = "초대 링크";
      invite.addEventListener("click", () => copyInvite(room, invite));

      actions.append(play, invite);

      // 응원하기 노출은 **방 주인에게만** 보이는 스위치다.
      //
      // 회원 모두에게 보여 주면 남의 방 설정을 건드리려다 거절당한다.
      // 눌러 봐야 안 되는 것을 보여 주지 않는 편이 낫다.
      if (room.is_owner) {
        const money = document.createElement("button");
        money.className = "button button--small";
        money.type = "button";
        money.textContent = room.support_enabled ? "💛 운영비 켜짐" : "🚫 운영비 꺼짐";
        money.setAttribute("aria-pressed", String(room.support_enabled));
        money.addEventListener("click", async () => {
          money.disabled = true;
          try {
            await Api.setRoomSupport(room.id, !room.support_enabled);
            el.roomsStatus.textContent = room.support_enabled
              ? "이 방 사람들에게는 운영비 보내기가 안 보여요."
              : "이 방 사람들에게 운영비 보내기가 보여요.";
            await loadRooms();
          } catch (error) {
            el.roomsStatus.textContent = error.message;
            money.disabled = false;
          }
        });
        actions.appendChild(money);
      }

      // 링크를 **눈에 보이게** 둔다.
      //
      // 복사 버튼만 있으면 안 될 때 방법이 없다. 클립보드는 브라우저 권한이나
      // 비보안 컨텍스트에서 조용히 실패하는데, 그때 사용자는 눌렀는지조차
      // 모른다. 읽기 전용 입력칸에 담아 두면 눌러서 직접 고를 수 있다.
      const link = document.createElement("input");
      link.className = "room__link";
      link.type = "text";
      link.readOnly = true;
      link.value = roomLink(room.id);
      link.setAttribute("aria-label", `${room.name} 초대 링크`);
      // 누르면 전체가 선택된다. 긴 주소를 손으로 드래그하는 것은 폰에서 고역이다.
      link.addEventListener("focus", () => link.select());
      link.addEventListener("click", () => link.select());

      card.append(head, actions, link);
      box.appendChild(card);
    });
  }

  async function copyInvite(room, button) {
    const link = roomLink(room.id);
    const text = `[또박] ${room.name} 방에 초대했어요\n오늘의 문제 같이 풀어요\n${link}`;
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "복사됨!";
      setTimeout(() => (button.textContent = "초대 링크"), 1500);
    } catch {
      // 클립보드가 막힌 브라우저(권한 거부, 비보안 컨텍스트)에서는 직접
      // 고를 수 있게 보여 준다. 조용히 실패하면 사용자는 눌렀는지도 모른다.
      el.roomsStatus.textContent = link;
    }
  }

  async function loadRooms() {
    try {
      myRooms = (await Api.rooms()).rooms;
      renderRooms();
    } catch (error) {
      el.roomsStatus.textContent = error.message;
    }
  }

  function openRooms() {
    el.rooms.hidden = false;
    el.roomsStatus.textContent = "";
    loadRooms();
  }

  el.roomsButton.addEventListener("click", openRooms);
  el.roomsClose.addEventListener("click", () => (el.rooms.hidden = true));

  // click 이 아니라 submit 을 듣는다.
  //
  // 모바일에서 소프트 키보드가 올라와 있으면 **버튼을 처음 누른 것이 키보드를
  // 닫는 데 쓰이고 클릭은 삼켜지는** 일이 있다. 사용자 입장에서는 눌렀는데
  // 아무 일도 안 일어난다. form 으로 두면 키보드의 확인/전송 키로도 보낼 수
  // 있어서 그 경로가 하나 더 생긴다.
  el.roomForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = el.roomName.value.trim();
    if (!name) {
      el.roomsStatus.textContent = "방 이름을 적어 주세요.";
      return;
    }
    try {
      await Api.createRoom(name);
      el.roomName.value = "";
      el.roomsStatus.textContent = "만들었어요. 초대 링크를 보내 보세요.";
      // 방을 만들면 소속이 바뀐다. 운영비 단추도 다시 판단해야 한다.
      await loadSupport();
      await loadRooms();
    } catch (error) {
      el.roomsStatus.textContent = error.message;
    }
  });

  /* ---------------- 오늘의 문제 ---------------- */

  async function openDaily(code, slot) {
    el.rooms.hidden = true;
    try {
      const state = await Api.daily(code, slot);
      showDaily(state);
    } catch (error) {
      el.roomsStatus.textContent = error.message;
      el.rooms.hidden = false;
    }
  }

  /** 닉네임이 생긴 뒤, 들고 있던 초대 코드로 들어간다. */
  async function joinPendingRoom() {
    if (!pendingRoom) return;
    const code = pendingRoom;
    try {
      await Api.joinRoom(code);
      pendingRoom = null;
      history.replaceState(null, "", location.pathname);
      // 소속이 바뀌었으니 운영비 단추를 다시 판단한다. 이 자리를 빼먹으면
      // 방에 들어갔는데도 꺼야 할 단추가 남는다.
      await loadSupport();
      await loadRooms();
      await openDaily(code);
    } catch (error) {
      el.roomsStatus.textContent = error.message;
      el.rooms.hidden = false;
    }
  }

  function showDaily(state) {

    // 판과 "어디로 채점을 보낼지" 를 같이 바꾼다. 모양 손질은 asBoard 가
    // 맡으므로 여기서 따로 필드를 채우지 않는다 — 손질하는 곳이 둘이면
    // 한쪽만 고쳐져서 어긋난다.
    setGame(asBoard(state), state.room.id);
    render();

    el.dailySummary.textContent =
      `${state.room.name} · ${state.play_date} · ` +
      `${state.solved_count}/${state.total_count}명이 맞혔어요`;

    renderSlots(state);
    renderStandings(state.standings);
    // 끝난 뒤에만 공유할 수 있다. 진행 중에 공유하면 아직 아무것도 없고,
    // 무엇보다 남은 사람에게 힌트가 될 수 있다.
    dailyShareText = state.share_text || null;
    el.dailyShare.hidden = !dailyShareText;
    el.dailySheet.hidden = false;
    loadComments(state);
  }

  /** 그날 문제 고르기. 하나면 안 그린다 — 고를 것이 없으면 군더더기다. */
  function renderSlots(daily) {
    const box = el.dailySlots;
    box.textContent = "";
    const slots = daily.slots ?? [];
    if (slots.length < 2) return;

    const MARK = { won: "✅", lost: "❌", playing: "…", new: "" };
    slots.forEach((row, index) => {
      const on = row.slot === daily.slot;
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = on ? "length-chip length-chip--on" : "length-chip";
      const mark = MARK[row.status] ?? "";
      chip.textContent = `${index + 1}번 · ${row.length}칸 ${mark}`.trim();
      chip.setAttribute("aria-pressed", String(on));
      chip.addEventListener("click", () => {
        if (on) return;
        openDaily(daily.room.id, row.slot);
      });
      box.appendChild(chip);
    });
  }

  /**
   * 이 문제의 순위. **방 사람 전원**이 넘어오고, 아직 안 한 사람은 status 가
   * "none" 이다.
   *
   * 안 한 사람까지 줄줄이 세우면 29명짜리 방에서 스물몇 줄이 빈칸으로 깔린다.
   * 그래서 **한 일이 있는 사람만 줄로 그리고**, 나머지는 접힌 한 줄로 묶는다.
   * 눌러야 펼쳐진다 — 방이 비어 보이지도 않고, 화면을 잡아먹지도 않는다.
   */
  function renderStandings(rows) {
    fillStandings(el.dailyStandings, rows);
  }

  /**
   * 오늘의 순위를 ``box`` 에 채운다.
   *
   * 방 화면과 결과 창이 **같은 함수**를 쓴다. 따로 그리면 한쪽만 고쳐져서
   * "방에서는 보이는데 결과 창에서는 다르게 보인다" 가 된다.
   */
  function fillStandings(box, rows) {
    box.textContent = "";

    const active = rows.filter((row) => row.status !== "none");
    const waiting = rows.filter((row) => row.status === "none");

    if (!active.length) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "아직 아무도 안 풀었어요. 1등 하세요!";
      box.appendChild(empty);
    }

    // 등수는 **맞힌 사람에게만** 붙인다. 실패하거나 푸는 중인 사람에게
    // 4위·5위를 매기면 등수가 아니라 그냥 줄 번호가 된다.
    let rank = 0;
    active.forEach((row) => {
      if (row.status === "won") rank += 1;
      box.appendChild(standingLine(row, row.status === "won" ? rank : 0));
    });

    if (!waiting.length) return;

    const more = document.createElement("button");
    more.type = "button";
    more.className = "standing standing--more";
    more.textContent = `아직 안 푼 사람 ${waiting.length}명 보기`;
    more.addEventListener("click", () => {
      more.remove();
      waiting.forEach((row) => box.appendChild(standingLine(row, 0)));
    });
    box.appendChild(more);
  }

  /** 순위 한 줄. rank 가 0 이면 등수를 안 붙인다. */
  function standingLine(row, rank) {
    const line = document.createElement("div");
    line.className = "standing";
    if (row.is_me) line.classList.add("standing--me");
    if (row.status === "none") line.classList.add("standing--idle");

    const mark = document.createElement("span");
    mark.className = "standing__rank";
    mark.textContent = rank ? ["🥇", "🥈", "🥉"][rank - 1] || `${rank}` : "";

    const who = document.createElement("span");
    who.className = "standing__name";
    who.textContent = row.display_name;
    const rel = relationTag(row.relation);
    if (rel) who.append(rel);
    if (row.supporter) {
      // 후원해 준 사람에게 붙는 표시. 확인은 못 하지만 그게 유일한 보답이다.
      const badge = document.createElement("span");
      badge.className = "badge-supporter";
      badge.textContent = "💛";
      badge.title = "후원해 주신 분";
      who.appendChild(badge);
    }

    const result = document.createElement("span");
    result.className = "standing__result";
    if (row.status === "won") {
      result.textContent = `${row.attempts}번`;
    } else if (row.status === "playing") {
      result.textContent = "푸는 중";
    } else if (row.status === "lost") {
      result.textContent = "실패";
    } else {
      result.textContent = "아직";
    }

    line.append(mark, who, result);
    return line;
  }

  /* ---------------- 댓글 ----------------
   *
   * **오늘 문제를 끝낸 사람만 쓰고 본다.** 안 그러면 "ㄱ으로 시작함" 한 줄로
   * 그날 문제가 끝난다. 서버가 403 으로 막지만, 화면에서도 잠긴 이유를
   * 알려 줘야 사용자가 무엇을 해야 할지 안다.
   */
  async function loadComments(state) {
    // 지금 보고 있는 문제만이 아니라 **그날 문제를 전부** 끝내야 한다.
    // 1번만 끝낸 사람에게 댓글을 보여 주면 2번 이야기가 스포일러가 된다.
    const slots = state.slots ?? [];
    const finished = slots.length
      ? slots.every((row) => row.status === "won" || row.status === "lost")
      : state.status !== "playing";
    el.commentsLocked.hidden = finished;
    el.commentsForm.hidden = !finished;
    el.commentsList.textContent = "";
    el.commentsStatus.textContent = "";
    if (!finished) return;

    try {
      const data = await Api.comments(state.room.id);
      renderComments(data);
    } catch (error) {
      el.commentsStatus.textContent = error.message;
    }
  }

  function renderComments(data) {
    const box = el.commentsList;
    box.textContent = "";
    if (!data.comments.length) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "아직 한마디도 없어요. 첫 줄을 남겨 보세요.";
      box.appendChild(empty);
    }
    data.comments.forEach((comment) => {
      const line = document.createElement("div");
      line.className = comment.is_me ? "comment comment--me" : "comment";

      const who = document.createElement("span");
      who.className = "comment__who";
      who.textContent = comment.display_name;

      const body = document.createElement("span");
      body.className = "comment__body";
      // textContent 로만 넣는다. 서버는 태그를 지우지 않으므로 여기가
      // 유일한 방어선이다.
      body.textContent = comment.body;

      line.append(who, body);
      box.appendChild(line);
    });
    el.commentSend.disabled = data.remaining <= 0;
    if (data.remaining <= 0) {
      el.commentsStatus.textContent = "오늘 쓸 수 있는 만큼 다 썼어요.";
    }
  }

  el.commentsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = el.commentBody.value.trim();
    // 조용히 돌아가지 않는다. 눌렀는데 아무 반응이 없으면 고장으로 읽힌다.
    if (!body) {
      el.commentsStatus.textContent = "한마디 적어 주세요.";
      return;
    }
    if (!state.room) {
      el.commentsStatus.textContent = "방을 다시 열어 주세요.";
      return;
    }
    try {
      const data = await Api.addComment(state.room, body);
      el.commentBody.value = "";
      renderComments(data);
      el.commentsStatus.textContent = "";
    } catch (error) {
      el.commentsStatus.textContent = error.message;
    }
  });

  el.dailyClose.addEventListener("click", () => {
    el.dailySheet.hidden = true;
  });

  el.dailyShare.addEventListener("click", async () => {
    if (!dailyShareText) return;
    // 폰에서는 공유 시트를 띄운다. 카톡을 바로 고를 수 있어 한 단계가 준다.
    if (navigator.share) {
      try {
        await navigator.share({ text: dailyShareText });
        return;
      } catch {
        // 사용자가 취소했거나 막힌 경우. 복사로 넘어간다.
      }
    }
    try {
      await navigator.clipboard.writeText(dailyShareText);
      el.dailyShare.textContent = "복사됐어요!";
      setTimeout(() => (el.dailyShare.textContent = "결과 공유하기"), 1500);
    } catch {
      el.dailyShare.textContent = "복사할 수 없어요";
    }
  });

  /* ---------------- 초대 링크로 들어온 경우 ---------------- */

  /**
   * 초대 링크의 방 코드. 아직 못 들어갔으면 여기 남는다.
   *
   * **처음 오는 사람은 링크를 눌러도 바로 못 들어간다.** 방에 들어가려면
   * 닉네임이 있어야 하는데, 링크를 누른 시점에는 아직 없기 때문이다.
   * 예전에는 그 401 을 오류로 띄우고 코드를 잊어버렸다. 그래서 이렇게 됐다.
   *
   *   링크 클릭 → 401 → 닉네임 만듦 → **방에는 안 들어간 사람**
   *
   * 그 상태로 남으면 친구가 방 없는 사람으로 취급돼, 꺼 뒀어야 할
   * 운영비 단추까지 보였다. 실제로 그래서 100원을 받았다.
   *
   * 지금은 코드를 들고 있다가 닉네임이 생기면 그때 다시 들어간다.
   */
  let pendingRoom = null;

  /**
   * 초대 링크 안내를 참가 화면에 적는다.
   *
   * @param name  방 이름. 없으면 줄을 감춘다.
   * @param error 링크가 못 쓰는 것일 때의 안내. 있으면 이것을 대신 적는다.
   */
  function showRoomInvite(name, error) {
    const line = el.joinRoom;
    line.classList.toggle("join__room--bad", Boolean(error));
    if (error) {
      line.textContent = error;
    } else if (name) {
      line.textContent = `'${name}' 방에 초대받았어요`;
    }
    line.hidden = !(error || name);
  }

  async function joinFromLink() {
    const code = new URLSearchParams(location.search).get("room");
    if (!code) return;
    pendingRoom = code;

    // **참가보다 방 이름을 먼저 물어본다.** 참가는 닉네임이 있어야 되지만
    // 이름을 보는 데는 아무것도 필요 없다. 순서를 이렇게 두면 처음 온 사람도
    // 닉네임을 정하기 전에 자기가 어디에 초대받았는지 안다.
    try {
      showRoomInvite((await Api.peekRoom(code)).name);
    } catch {
      // 코드가 틀렸거나 없어진 방이다. 여기서 멈춘다 — 못 들어가는 링크로
      // 참가를 시도해 봐야 같은 거절을 한 번 더 볼 뿐이다.
      pendingRoom = null;
      showRoomInvite(null, "이 초대 링크는 쓸 수 없어요. 링크를 다시 받아 보세요.");
      history.replaceState(null, "", location.pathname);
      return;
    }

    try {
      await Api.joinRoom(code);
      pendingRoom = null;
      showRoomInvite(null);
      // 주소에서 코드를 지운다. 남겨 두면 새로고침할 때마다 다시 참가를
      // 시도하고, 브라우저 기록에 방 코드가 계속 쌓인다.
      history.replaceState(null, "", location.pathname);
      // 방이 생겼으니 운영비 단추를 다시 판단한다. 이 한 줄이 없어서
      // 친구가 꺼진 방에 있는데도 단추를 보고 100원을 보냈다.
      await loadSupport();
      await loadRooms();
      openDaily(code);
    } catch (error) {
      // 닉네임이 없어서 못 들어간 것뿐이면 오류가 아니다. 코드를 그대로
      // 들고 있다가 닉네임이 생기면 다시 들어간다(joinPendingRoom).
      // 여기서 창을 띄우면 처음 온 사람이 닉네임 화면 대신 빨간 글씨부터 본다.
      if (error.status === 401) return;
      pendingRoom = null;
      el.roomsStatus.textContent = error.message;
      el.rooms.hidden = false;
    }
  }


  /* ---------------- 응원하기 ----------------
   *
   * 광고를 안 붙이는 대신 두는 자리다. 애드센스는 13만 원이 쌓여야 지급하는데
   * 친구 100명 규모에서는 몇 년이 걸린다. 후원은 그 문턱이 없다.
   *
   * 서버가 링크를 안 주면(support_url 이 비어 있으면) 버튼 자체를 안 그린다.
   * 눌렀는데 아무 데도 안 가는 버튼은 없느니만 못하다.
   */
  let supportInfo = null;

  /**
   * 운영비 보내기를 보여 줄지 서버에 다시 물어본다.
   *
   * **방에 들어가고 나면 반드시 다시 물어야 한다.** 보여 줄지 말지는
   * "내가 어느 방에 속했는가" 로 정해지는데, 그건 방에 들어가는 순간 바뀐다.
   *
   * 예전에는 켜기만 하고 끄지 않았다. 그래서 이런 일이 났다.
   *
   *   00:57  초대 링크로 들어옴 (아직 방 없음)
   *          → 서버: "보여 줘도 된다"  → 단추가 뜬다
   *   00:58  방에 참가됨 (친구 방 = 꺼진 방)
   *          → 아무도 다시 안 물어봄. **단추가 그대로 남는다.**
   *   01:08  친구가 그 단추를 눌러 100원을 보냄
   *
   * 베타테스터에게 돈을 받은 셈이라 그대로 돌려줘야 했다.
   * 그래서 여기서는 **끄는 쪽도 반드시 처리한다.**
   */
  async function loadSupport() {
    try {
      supportInfo = await Api.support();
    } catch {
      supportInfo = null;   // 후원은 부가 기능이다. 실패해도 게임은 돌아야 한다.
      el.settingsSupport.hidden = true;
      return;
    }
    const show = Boolean(supportInfo?.providers?.length);
    el.settingsSupport.hidden = !show;
    // 열려 있던 창도 같이 닫는다. 방에 들어간 순간 못 보게 해야 하는데
    // 이미 떠 있으면 그 창으로 그냥 보내 버린다.
    if (!show) el.support.hidden = true;
  }

  /** 지금 고른 송금 수단. 사람마다 깔린 앱이 다르다. */
  let supportProvider = null;

  function renderSupportProviders() {
    const box = el.supportProviders;
    box.textContent = "";
    const list = supportInfo?.providers ?? [];
    // 하나뿐이면 고를 것이 없다. 선택지를 그리면 군더더기만 된다.
    if (list.length < 2) {
      supportProvider = list[0]?.key ?? null;
      return;
    }
    supportProvider = supportProvider ?? list[0].key;

    list.forEach((provider) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className =
        provider.key === supportProvider
          ? "support__provider support__provider--on"
          : "support__provider";
      button.textContent = `${provider.emoji} ${provider.label}`;
      button.addEventListener("click", () => {
        supportProvider = provider.key;
        renderSupportProviders();
        renderSupportButton();
        // 상태줄은 직전 수단에 대한 이야기였다. 수단을 바꾸면 지운다.
        setSupportStatus("");
      });
      box.appendChild(button);
    });
  }

  function setSupportStatus(text) {
    el.supportStatus.textContent = text;
  }

  /**
   * 클립보드에 넣는다. 성공하면 참.
   *
   * 두 가지를 다 쓴다. 최신 API 는 비동기라 **이 자리에서 성공을 알 수 없고**,
   * 링크를 누르는 즉시 앱으로 넘어가므로 결과를 기다릴 수도 없다. 그래서
   * 동기로 끝나는 옛 방법(execCommand)을 기준으로 성공을 판정하고,
   * 최신 API 는 함께 쏘기만 한다(카톡 인앱 브라우저처럼 옛 방법이 막힌 곳 대비).
   */
  function copyText(text) {
    try {
      navigator.clipboard?.writeText(text).catch(() => {});
    } catch {
      /* 무시 — 아래 방법으로 한 번 더 시도한다 */
    }
    try {
      const pad = document.createElement("textarea");
      pad.value = text;
      // 화면 밖에 두되 focusable 해야 한다. display:none 이면 선택이 안 된다.
      pad.setAttribute("readonly", "");
      pad.style.position = "fixed";
      pad.style.top = "-1000px";
      document.body.appendChild(pad);
      pad.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(pad);
      return ok;
    } catch {
      return false;
    }
  }

  /**
   * 후원 버튼 하나를 그린다.
   *
   * 예전에는 금액별 단계(추파춥스 300원, 카누 1,000원 …)를 늘어놓았다.
   * 그런데 카카오페이 QR 은 **주소에 금액을 못 싣는다.** 그래서 "1,000원"
   * 을 눌러도 결제창에는 아무 금액이 없고, 결국 앱에서 직접 쳐야 했다.
   * 고를 이유가 없는 선택지를 다섯 개 보여 준 셈이다.
   *
   * 금액을 어차피 손으로 넣어야 한다면, 그냥 버튼 하나가 낫다.
   */
  function renderSupportButton() {
    const box = el.supportTiers;
    box.textContent = "";
    const chosen = supportInfo?.providers?.find((p) => p.key === supportProvider);
    if (!chosen?.url) return;

    // 버튼이 아니라 링크로 만든다. 길게 눌러 새 탭으로 열거나 주소를
    // 복사하는 등, 브라우저가 원래 해 주는 것들이 그대로 동작한다.
    const item = document.createElement("a");
    item.className = "button button--primary support__go";
    item.href = chosen.url;
    item.target = "_blank";
    // noopener 가 없으면 열린 페이지가 window.opener 로 이 페이지를 조작할 수 있다.
    item.rel = "noopener noreferrer";
    // 금액을 문구에 적어 둔다. 카카오페이 주소에는 금액을 못 싣기 때문에
    // 결제창은 비어서 뜬다. 얼마를 치면 되는지 여기서 미리 말해 주지 않으면
    // 그 자리에서 고민하다 그냥 닫는다.
    item.textContent = `${chosen.emoji} ${chosen.label}로 100원 보내기`;
    // 누르면 앱으로 넘어간다. 돌아왔을 때 "보냈어요" 를 누를 수 있게 그때
    // 버튼을 띄운다. 처음부터 띄워 두면 안 보내고도 누른다.
    item.addEventListener("click", () => rememberLeaving(0));
    box.appendChild(item);
  }

  function openSupport() {
    if (!supportInfo || !supportInfo.providers?.length) return;
    renderSupportProviders();
    renderSupportButton();
    el.supportStatus.textContent = "";
    el.support.hidden = false;
  }

  function closeSupport() {
    el.support.hidden = true;
  }

  /* ---------------- 고마워요 ----------------
   *
   * 후원했는지는 **알 수 없다.** 카카오페이는 우리 서버에 아무것도 알려 주지
   * 않는다(웹훅도 API 도 없다). 그래서 본인이 눌러 준 것을 그대로 믿는다.
   * 거짓으로 얻는 것이 배지 하나뿐이라 검증에 드는 복잡도가 값어치보다 크다.
   *
   * 대신 확실히 해야 할 것은 **보답**이다. 이 화면이 유일한 보답이라
   * 짧고 분명하게 끝난다.
   */

  /** 폭죽. 조각을 만들어 떨어뜨리고 끝나면 지운다.
   *
   * 라이브러리를 안 쓴다. 이 하나를 위해 수십 KB 를 받게 하고 싶지 않고,
   * 필요한 것은 색종이 몇 십 개가 떨어지는 것뿐이다.
   */
  function confetti(host) {
    const colors = ["#6aaa64", "#c9b458", "#f2a1c0", "#7cb7ff", "#ffd166"];
    for (let i = 0; i < 36; i += 1) {
      const piece = document.createElement("span");
      piece.className = "confetti";
      piece.style.left = `${Math.random() * 100}%`;
      piece.style.background = colors[i % colors.length];
      piece.style.animationDelay = `${Math.random() * 0.5}s`;
      piece.style.animationDuration = `${1.6 + Math.random()}s`;
      piece.style.transform = `rotate(${Math.random() * 360}deg)`;
      host.appendChild(piece);
      // 끝난 조각은 지운다. 남겨 두면 여러 번 열 때마다 쌓인다.
      piece.addEventListener("animationend", () => piece.remove());
    }
  }

  function showThanks(count) {
    el.thanksLine.textContent =
      count > 1 ? `벌써 ${count}번째예요. 진심으로 고마워요` : "덕분에 계속 만들 수 있어요";
    el.thanks.hidden = false;
    confetti(el.thanks);
    // 눌러서 닫는다. 자동으로 사라지게 하면 문구를 못 읽는 사람이 생긴다.
    const close = () => {
      el.thanks.hidden = true;
      el.thanks.removeEventListener("click", close);
    };
    el.thanks.addEventListener("click", close);
  }

  /* 돌아오면 보냈다고 본다.
   *
   * 확인할 방법이 없으니 물어보기보다 그냥 축하하는 편이 낫다. "보내셨나요?"
   * 를 띄우면 안 보낸 사람에게는 추궁이 되고, 보낸 사람에게는 한 번 더
   * 일을 시키는 것이다.
   *
   * **기억을 localStorage 에 남기는 이유가 핵심이다.**
   *
   * 카톡 인앱 브라우저는 카카오페이를 열 때 웹뷰를 통째로 버린다. 돌아오면
   * 페이지가 **새로 로드**되므로 JS 변수(나갔던 시각 같은 것)가 전부 사라지고
   * visibilitychange 도 오지 않는다. 실제로 그래서 폭죽이 안 터졌다.
   * 저장소에 남겨 두면 새로 로드돼도 살아남는다.
   *
   * 돌아오는 길이 브라우저마다 달라서 세 가지를 다 듣는다 — 다시 보이거나
   * (visibilitychange), 뒤로가기 캐시에서 살아나거나(pageshow), 창이 다시
   * 초점을 얻거나(focus). 어느 하나만 듣다가 못 잡는 것보다 낫다.
   */
  const PENDING_KEY = "ttobak_pending_support";

  function rememberLeaving(amount) {
    try {
      localStorage.setItem(
        PENDING_KEY,
        JSON.stringify({ amount, at: Date.now() })
      );
    } catch {
      // 저장소가 막힌 브라우저(사생활 보호 모드 등)도 있다. 그때는 축하를
      // 못 할 뿐이고, 후원 자체는 이미 앱에서 끝났으므로 그냥 넘어간다.
    }
  }

  /** 돌아왔을 때 한 번만 축하한다. */
  async function celebrateIfReturned() {
    let pending = null;
    try {
      pending = JSON.parse(localStorage.getItem(PENDING_KEY) || "null");
    } catch {
      pending = null;
    }
    if (!pending) return;

    const away = Date.now() - pending.at;
    // 1초 미만은 잘못 눌러 바로 뒤로 온 것으로 본다.
    // 30분이 넘었으면 축하 시점을 놓친 것이라 조용히 버린다 — 한참 뒤에
    // 갑자기 폭죽이 터지면 무슨 일인지 알 수 없다.
    if (away < 1000 || away > 30 * 60 * 1000) {
      try {
        localStorage.removeItem(PENDING_KEY);
      } catch {
        /* 무시 */
      }
      return;
    }

    // **먼저 지운다.** 요청이 느릴 때 다른 이벤트가 또 들어와 두 번
    // 축하하는 것을 막는다.
    try {
      localStorage.removeItem(PENDING_KEY);
    } catch {
      /* 무시 */
    }

    try {
      const result = await Api.thanks(pending.amount);
      el.support.hidden = true;
      showThanks(result.count);
    } catch {
      // 실패해도 조용히 넘어간다. 후원은 이미 앱에서 끝났고, 여기서
      // 오류를 띄우면 보낸 사람에게 문제가 있는 것처럼 보인다.
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) celebrateIfReturned();
  });
  window.addEventListener("pageshow", celebrateIfReturned);
  window.addEventListener("focus", celebrateIfReturned);

  el.settingsSupport.addEventListener("click", () => {
    closeSettings();
    openSupport();
  });
  el.supportClose.addEventListener("click", closeSupport);
  el.support.addEventListener("click", (event) => {
    // 패널 바깥(어두운 배경)을 누르면 닫는다.
    if (event.target === el.support) closeSupport();
  });

  el.settingsRename.addEventListener("click", async () => {
    if (!confirm("다른 닉네임으로 바꿀까요? 지금까지의 기록은 그대로 남습니다.")) return;
    await Api.leave();
    location.reload();
  });

  /**
   * 글자를 치는 자리인가.
   *
   * **여기서 막지 않으면 게임 자판이 남의 입력칸을 가로챈다.** 아래 핸들러는
   * 자모 키에 preventDefault 를 걸고 게임판으로 보내므로, 한마디나 방 이름을
   * 치면 글자가 입력칸에 안 들어가고 뒤의 게임판에 쌓인다. 실제로 그 사고를
   * 냈다 — "한마디가 안 써진다" 는 제보가 이것이었다.
   */
  function isTypingTarget(node) {
    if (!node || node.nodeType !== 1) return false;
    if (node.isContentEditable) return true;
    return ["INPUT", "TEXTAREA", "SELECT"].includes(node.tagName);
  }

  /**
   * 덮개 창이 하나라도 열려 있는가.
   *
   * 예전에는 결과 시트와 설정만 손으로 확인했다. 그래서 방·오늘의 문제·
   * 난이도 안내·응원하기를 새로 만들 때마다 **그 위에서 자판이 뒤의 게임판을
   * 건드리는** 버그가 조용히 따라왔다. class 로 세면 시트를 더 만들어도
   * 여기를 고칠 필요가 없다.
   */
  function anySheetOpen() {
    return Array.from(document.querySelectorAll(".sheet")).some((s) => !s.hidden);
  }

  // 물리 키보드에서도 칠 수 있게 한다. 한글 자판을 켜고 치면 그대로 들어온다.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeSettings();
      closeSheet();
      return;
    }
    // 입력칸에 친 글자는 그 입력칸의 것이다. 게임이 가져가면 안 된다.
    if (isTypingTarget(event.target)) return;
    if (el.game.hidden || anySheetOpen()) return;
    if (event.metaKey || event.ctrlKey || event.altKey) return;

    if (event.key === "Enter") {
      event.preventDefault();
      if (state.game?.status === "playing") submitDraft();
      else goNextRound();
      return;
    }
    if (event.key === "Backspace") {
      event.preventDefault();
      popJamo();
      return;
    }
    const flat = Hangul.KEYBOARD_ROWS.flat();
    if (event.key.length === 1 && flat.includes(event.key)) {
      event.preventDefault();
      pushJamo(event.key);
    }
  });

  /* ---------------- 복구 코드 ----------------
   *
   * 닉네임만으로 들어오는 게임이라 **닉네임을 아는 사람이 곧 그 사람**이 된다.
   * 지인끼리 쓰는 물건에서는 이게 제일 큰 구멍이라(서로 이름을 안다) 처음 쓴
   * 사람에게 코드를 주고 못 박는다.
   *
   * 이 화면이 없던 시기가 있었다. 서버는 코드를 만들어 내려보냈는데 화면이
   * 그냥 버렸다. 그래서 코드를 **가진 적 없는** 사람들이 자기 닉네임에 잠겨
   * 버렸다. 값을 받으면 반드시 사람에게 보여 줘야 한다.
   */

  /** 코드를 보여 준다. 다시는 볼 수 없는 값이라 확인을 받고 닫는다. */
  function showRecovery(code) {
    el.recoveryCode.value = code;
    el.recoveryStatus.textContent = "";
    el.recovery.hidden = false;
  }

  el.recoveryCopy.addEventListener("click", () => {
    el.recoveryCode.select();
    el.recoveryStatus.textContent = copyText(el.recoveryCode.value)
      ? "복사했어요. 메모장이나 나에게 보내기에 붙여 두세요."
      : "복사가 막혀 있어요. 위 칸을 눌러 직접 복사해 주세요.";
  });

  el.recoveryOk.addEventListener("click", () => {
    el.recovery.hidden = true;
  });

  /* ---------------- 놀이법 ----------------
   *
   * 처음 들어온 사람에게 **한 번만** 띄운다. 규칙을 모르면 색이 무슨 뜻인지
   * 몰라서 몇 판을 헤매고, 그러다 그만둔다.
   *
   * 특히 "같은 자모가 둘 다 노랑이면 두 개 있다는 뜻" 은 말로 설명하면
   * 헷갈리는데 격자로 보면 한 번에 이해된다. 그래서 실제 채점 결과를
   * 그대로 그려 뒀다.
   */
  const HOWTO_SEEN_KEY = "ttobak_howto_seen";

  function openHowto() {
    el.howto.hidden = false;
  }

  function maybeShowHowto() {
    let seen = false;
    try {
      seen = localStorage.getItem(HOWTO_SEEN_KEY) === "1";
    } catch {
      // 저장소가 막혔으면 매번 보여 준다. 안 보여 주는 것보다 낫다.
    }
    if (seen) return;
    openHowto();
    try {
      localStorage.setItem(HOWTO_SEEN_KEY, "1");
    } catch {
      /* 무시 */
    }
  }

  el.howtoOk.addEventListener("click", () => {
    el.howto.hidden = true;
  });

  el.settingsHowto.addEventListener("click", () => {
    closeSettings();
    openHowto();
  });

  /* 포기.
   *
   * 막힌 판에 갇혀 있으면 그날 게임을 아예 안 하게 된다. 그건 패배 한 번보다
   * 훨씬 나쁘다. 그래서 나갈 길을 둔다.
   *
   * 대신 **패배로 적는다.** 그러지 않으면 어려운 단어마다 포기해서 쉬운 것만
   * 골라 풀 수 있고, 그러면 순위표의 승률이 아무 뜻도 없어진다.
   *
   * 제출 버튼 옆이 아니라 메뉴에 둔다. 게임 중에 잘못 눌러서 판을 날리는
   * 것만큼 허무한 일이 없다.
   */
  el.settingsResign.addEventListener("click", async () => {
    if (state.game?.status !== "playing") {
      setSettingsStatus("지금 풀고 있는 판이 없어요.");
      return;
    }
    // 오늘의 문제는 하루에 하나뿐이라 "다음 문제" 가 없다. 그래서 막히면
    // 빠져나갈 방법이 아예 없었다 — 여기서도 포기할 수 있어야 한다.
    const daily = Boolean(state.room);
    const ask = daily
      ? "오늘의 문제를 포기할까요? 정답을 보여 주고 실패로 기록됩니다."
      : "이 문제를 포기할까요? 정답을 보여 주고 패배로 기록됩니다.";
    if (!confirm(ask)) return;
    try {
      // 포기한 판을 **그대로** 보여 준다. 새 판을 바로 띄우면 제일 궁금한
      // 정답을 볼 기회가 사라진다. 진 판을 그리면 정답과 공유 문구가 같이
      // 나오고, 평소처럼 "다음 문제" 로 넘어가면 된다.
      const view = daily
        ? asBoard(await Api.resignDaily(state.room))
        : await Api.resign();
      setGame(view, state.room);
      closeSettings();
      render();
      openSheet();
    } catch (error) {
      setSettingsStatus(error.message);
    }
  });

  el.settingsRecovery.addEventListener("click", async () => {
    // 되돌릴 수 없는 동작이라 한 번 묻는다. 전에 적어 둔 코드를 믿고 있던
    // 사람이 모르는 새에 그 코드를 잃으면, 잃은 줄도 모른 채 기기를 바꾼다.
    const ask = "코드를 새로 만들까요? 전에 적어 둔 코드는 못 쓰게 됩니다.";
    if (!confirm(ask)) return;
    try {
      const data = await Api.reissueRecovery();
      closeSettings();
      showRecovery(data.recovery_code);
    } catch (error) {
      setSettingsStatus(error.message);
    }
  });

  el.joinForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    el.joinError.textContent = "";
    try {
      const me = await Api.join(
        el.nickname.value,
        el.joinRecovery.value,
        el.joinRelation.value.trim(),
      );
      await startGame();
      // 링크를 누르고 들어온 사람이면 이제서야 방에 들어갈 수 있다.
      // 이걸 빼먹으면 "링크로 초대했는데 방에 없다" 가 된다.
      await joinPendingRoom();
      // 소속이 바뀌었으니 운영비 단추를 다시 판단한다.
      await loadSupport();
      // 처음 차지한 닉네임이면 코드가 딱 한 번 내려온다. 여기서 안 보여 주면
      // 그 코드는 세상에 존재한 적이 없는 것과 같다.
      if (me?.recovery_code) showRecovery(me.recovery_code);
    } catch (error) {
      el.joinError.textContent = error.message;
      // 임자가 있는 닉네임(409)일 때만 코드 칸을 꺼낸다. 넣을 곳 없이
      // "복구 코드를 넣으세요" 라고만 하면 막다른 길이 된다.
      if (error.status === 409) {
        el.joinRecovery.hidden = false;
        el.joinRecovery.focus();
      }
    }
  });

  // --- 기동 ---

  /**
   * @param silent 결과창을 띄우지 않는다. 곧바로 오늘의 문제를 열 때 쓴다 —
   *   일반 판의 결과창이 잠깐 떴다 사라지면 무엇을 본 것인지 알 수 없다.
   */
  async function startGame({ silent = false } = {}) {
    setGame(await Api.game(), null);
    el.join.hidden = true;
    // 판이 그려진 뒤에 띄운다. 빈 화면 위에 설명만 뜨면 무엇에 대한
    // 설명인지 알 수 없다.
    maybeShowHowto();
    el.game.hidden = false;
    render();
    // 화면을 막 보이게 한 직후라 크기가 아직 안 정해졌을 수 있다.
    fitBoardSoon();
    if (!silent && state.game.status !== "playing") openSheet();
  }

  /**
   * 오늘 안 끝낸 문제가 남은 방을 하나 고른다. 없으면 null.
   *
   * 방이 여럿일 수 있어서 **남은 것이 많은 방**을 먼저 연다 — 그날 처음
   * 들어온 사람은 모든 방이 최대치라, 사실상 첫 번째 방이 열린다.
   */
  async function roomNeedingDaily() {
    try {
      const { rooms = [] } = await Api.rooms();
      const waiting = rooms.filter((r) => (r.daily_left ?? 0) > 0);
      if (!waiting.length) return null;
      waiting.sort((a, b) => b.daily_left - a.daily_left);
      return waiting[0].id;
    } catch {
      // 방 목록을 못 받아도 게임은 열려야 한다. 일반 판으로 간다.
      return null;
    }
  }

  async function boot() {
    const me = await Api.me();
    if (me.player_id) {
      // **방에 속해 있고 오늘 문제가 남았으면 그것부터 연다.**
      // 이 게임의 중심은 다 같이 같은 낱말을 푸는 오늘의 문제인데,
      // 예전에는 들어오면 혼자 푸는 판이 먼저 떠서 그냥 그것만 풀다 나갔다.
      const code = await roomNeedingDaily();
      if (code) {
        await startGame({ silent: true });
        await openDaily(code);
        return;
      }
      await startGame();
      return;
    }
    if (me.suggested_nickname) el.nickname.value = me.suggested_nickname;
    el.join.hidden = false;
    el.nickname.focus();
  }

  /* ---------------- 시작 ----------------
   *
   * 로딩 화면을 켜 둔 채로 시작해서, 무엇을 보여 줄지 정해지면 끈다.
   * 예전에는 두 화면이 모두 hidden 이라 첫 응답이 올 때까지 **본문이
   * 통째로 비어 있었다.** 로그인한 사람은 왕복이 두 번이라 더 오래 봤다.
   */
  function finishLoading() {
    el.loading.hidden = true;
  }

  async function start() {
    el.loading.hidden = false;
    el.loadingFailed.hidden = true;
    try {
      await boot();
      finishLoading();
    } catch (error) {
      // 실패를 **화면에 드러낸다.** 이게 로딩 화면을 두는 진짜 이유다 —
      // 백지로 두면 사용자는 기다려야 할지 새로고침해야 할지 알 수 없다.
      el.loadingFailed.hidden = false;
      el.loadingError.textContent = error.message;
    }
  }

  el.loadingRetry.addEventListener("click", start);

  // **순서가 중요하다.** loadSupport 를 먼저 부르면 방에 들어가기 전 상태로
  // 판단해서, 꺼진 방 사람에게도 단추가 뜬다. joinFromLink 가 끝난 뒤
  // 스스로 다시 물어보므로 여기서는 링크 처리를 먼저 건다.
  joinFromLink().finally(loadSupport);
  start();
  // 웹뷰가 통째로 새로 로드된 경우를 잡는다. 카톡이 카카오페이를
  // 열고 돌아올 때가 정확히 그 경우다.
  celebrateIfReturned();
})();
