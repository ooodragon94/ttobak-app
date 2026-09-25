/**
 * 서버 API 래퍼.
 *
 * fetch 호출과 오류 변환을 한곳에 모아, 화면 코드가 응답 상태 코드를 직접
 * 다루지 않게 한다. 서버가 보낸 안내 문구는 `ApiError.message`로 전달된다.
 *
 * **주소에 앞의 슬래시를 붙이지 않는다.** 이 앱은 루트(`/`)에도 붙고 하위
 * 경로(`/ttobak/`)에도 붙을 수 있다. Tailscale Funnel이 경로 접두사를 떼고
 * 넘기기 때문에 서버는 자기가 어디에 걸려 있는지 알 방법이 없다. 상대 주소를
 * 쓰면 브라우저가 현재 문서 위치를 기준으로 알아서 맞춰 준다.
 */

/** 서버가 요청을 거절했을 때 던지는 오류. */
class ApiError extends Error {
  /**
   * @param code 서버가 붙인 짧은 이름. 화면이 이걸로 분기한다.
   *   문장을 문자열로 비교하면 서버에서 말투를 한 번 다듬는 순간 깨진다.
   */
  constructor(message, status, code = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const Api = (() => {
  /**
   * JSON 요청 한 번을 보낸다.
   * @throws {ApiError} 응답이 2xx가 아닐 때
   */
  /** 요청 하나에 허용할 시간.
   *
   * **타임아웃이 없으면 서버가 응답을 안 줄 때 영원히 매달린다.** 화면은
   * 백지인 채로 멈추고 catch 도 안 걸려서 오류 문구조차 안 뜬다. 사용자
   * 입장에서 "느린 것" 과 "죽은 것" 이 똑같아 보이는데, 그 둘은 할 일이
   * 완전히 다르다(기다리기 vs 새로고침).
   *
   * 12초는 폰에서 신호가 나쁠 때의 정상 응답보다는 넉넉하고, 사람이
   * 포기하기 전에는 답을 주는 길이다.
   */
  const TIMEOUT_MS = 12_000;

  async function request(path, { method = "GET", body } = {}) {
    // **스트림릿 위에서 돌 때는 fetch 대신 다리로 보낸다.** 그곳에는 이
    // 화면이 부를 HTTP 서버가 따로 없다. 다리(스트림릿 컴포넌트)가 요청을
    // 파이썬으로 넘기고, 파이썬이 같은 FastAPI 앱에 그대로 전해 준다.
    // 다리가 없으면(집 PC 판) 아래의 원래 fetch 로 간다 — 두 판이 이 파일
    // 하나를 같이 쓴다.
    if (window.TtobakBridge) {
      const reply = await window.TtobakBridge.send({ method, path, body }, TIMEOUT_MS);
      return settle(reply.status, reply.payload);
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

    let response;
    try {
      response = await fetch(path, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } catch (error) {
      // 중단과 네트워크 오류를 구분해 준다. "서버가 안 됨" 과 "인터넷이
      // 끊김" 은 사용자가 할 일이 다르다.
      if (error.name === "AbortError") {
        throw new ApiError("서버가 응답하지 않아요. 잠시 뒤 다시 시도해 주세요.", 0);
      }
      throw new ApiError("연결할 수 없어요. 인터넷을 확인해 주세요.", 0);
    } finally {
      clearTimeout(timer);
    }

    if (response.status === 204) return null;

    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    return settle(response.status, payload);
  }

  /**
   * 상태 코드와 본문으로 결과를 정한다. fetch 와 다리가 **같은 규칙**을 쓰게
   * 한곳에 둔다 — 따로 적으면 한쪽만 고쳐져서 두 판의 오류 문구가 갈린다.
   */
  function settle(status, payload) {
    if (status === 204) return null;
    if (status < 200 || status >= 300) {
      throw new ApiError(
        detailOf(payload) ?? "요청을 처리하지 못했습니다.",
        status,
        payload?.detail?.code ?? null,
      );
    }
    return payload;
  }

  /** FastAPI의 오류 본문에서 사람이 읽을 문구를 뽑아낸다. */
  function detailOf(payload) {
    const detail = payload?.detail;
    if (typeof detail === "string") return detail;
    // 추측·힌트의 거절은 {message, code} 로 온다. code 는 화면이 분기용으로
    // 쓰고, 사람에게 보여 줄 것은 message 다.
    if (detail && typeof detail.message === "string") return detail.message;
    if (Array.isArray(detail) && detail.length > 0) return detail[0]?.msg ?? null;
    return null;
  }

  return {
    me: () => request("api/me"),
    join: (nickname, recoveryCode, relation) =>
      request("api/join", {
        method: "POST",
        // 코드가 없을 때는 아예 안 실어 보낸다. 빈 문자열을 보내면 서버가
        // "코드를 냈는데 틀렸다" 와 "안 냈다" 를 구분하기 어려워진다.
        body: {
          nickname,
          ...(recoveryCode ? { recovery_code: recoveryCode } : {}),
          // 소개도 마찬가지로 빈 값은 안 보낸다. 기기를 바꿔 다시 들어온
          // 사람의 기존 소개를 빈 값으로 덮어쓰면 안 된다.
          ...(relation ? { relation } : {}),
        },
      }),
    reissueRecovery: () => request("api/recovery", { method: "POST" }),
    // 거절당한 자모 나열을 "이건 진짜 단어" 라고 알린다. 받아만 두고
    // 사전에 바로 넣지는 않는다 — 판정은 나중에 따로 한다.
    reportWord: (guess) =>
      request("api/words/report", { method: "POST", body: { guess } }),
    leave: () => request("api/leave", { method: "POST" }),
    game: () => request("api/game"),
    nextRound: () => request("api/game/next", { method: "POST" }),
    resign: () => request("api/game/resign", { method: "POST" }),
    resignDaily: (code, slot) =>
      request(
        `api/rooms/${encodeURIComponent(code)}/daily/resign` +
          (slot === undefined ? "" : `?slot=${slot}`),
        { method: "POST" },
      ),
    hint: () => request("api/game/hint", { method: "POST" }),
    hintDaily: (code, slot) =>
      request(
        `api/rooms/${encodeURIComponent(code)}/daily/hint` +
          (slot === undefined ? "" : `?slot=${slot}`),
        { method: "POST" },
      ),
    guess: (jamos) => request("api/game/guess", { method: "POST", body: { guess: jamos } }),
    stats: () => request("api/stats"),
    leaderboard: () => request("api/leaderboard"),
    settings: () => request("api/settings"),
    saveSettings: (patch) =>
      request("api/settings", { method: "PUT", body: patch }),
    support: () => request("api/support"),
    thanks: (amount) =>
      request("api/support/thanks", { method: "POST", body: { amount } }),

    // --- 방 ---
    rooms: () => request("api/rooms"),
    createRoom: (name) => request("api/rooms", { method: "POST", body: { name } }),
    // 로그인 없이 부를 수 있는 유일한 방 API. 링크를 막 누른 사람이
    // "어느 방인지" 를 보려면 닉네임보다 먼저 필요하다.
    peekRoom: (code) => request(`api/rooms/${encodeURIComponent(code)}/peek`),
    joinRoom: (code) => request(`api/rooms/${encodeURIComponent(code)}/join`, { method: "POST" }),
    leaveRoom: (code) => request(`api/rooms/${encodeURIComponent(code)}/leave`, { method: "POST" }),
    daily: (code, slot) =>
      request(
        `api/rooms/${encodeURIComponent(code)}/daily` +
          (slot === undefined ? "" : `?slot=${slot}`),
      ),
    dailyGuess: (code, jamos, slot) =>
      request(`api/rooms/${encodeURIComponent(code)}/daily/guess`, {
        method: "POST",
        // 어느 문제인지 반드시 함께 보낸다. 서버가 짐작하면 화면이 2번을
        // 보고 있는데 1번에 채점이 들어간다.
        body: { guess: jamos, slot },
      }),
    comments: (code) => request(`api/rooms/${encodeURIComponent(code)}/comments`),
    setRoomSupport: (code, enabled) =>
      request(`api/rooms/${encodeURIComponent(code)}/support`, {
        method: "POST",
        body: { enabled },
      }),

    addComment: (code, body) =>
      request(`api/rooms/${encodeURIComponent(code)}/comments`, {
        method: "POST",
        body: { body },
      }),
  };
})();
