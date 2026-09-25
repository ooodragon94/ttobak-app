/**
 * 스트림릿 안에서 또박 화면을 띄우는 다리.
 *
 * 왜 이렇게 만들었나
 * ------------------
 *
 * 또박 화면(자모 키보드, 타일 애니메이션, 결과 창)은 4,500줄짜리 HTML/CSS/JS
 * 다. 스트림릿 위젯으로 다시 짜면 손맛이 사라지고 일도 많다. 그런데 스트림릿
 * 컴포넌트(v2)는 iframe 에 갇히지 않고 페이지 안에서 그대로 돈다. 그래서
 * **지금 화면을 한 글자도 안 바꾸고 올리고**, 서버와 주고받는 길만 이어 준다.
 *
 * - 처음 한 번: 파이썬이 준 화면 조각(HTML·CSS·JS)을 페이지에 붙인다.
 * - 그 뒤로는: 화면이 보내는 요청을 파이썬에 넘기고, 답을 받아 돌려준다.
 *
 * 스트림릿은 무엇이 바뀔 때마다 이 함수를 **다시 부른다.** 그래서 화면을 붙이는
 * 일은 딱 한 번만 하고(window.__ttobakHost 로 기억), 매번 하는 일은 답을 나르는
 * 것뿐이다. 시험판에서 여섯 번 불려도 화면은 한 번만 만들어지는 것을 확인했다.
 */

// 서명된 신원 열쇠를 둘 곳. 쿠키를 쓸 수 없는 대신 브라우저 저장소에 둔다.
// 서버가 서명을 검사하므로 남이 값을 지어내도 소용없다.
const TOKEN_KEY = "ttobak.token";

// 스트림릿 자체의 머리띠·메뉴·상태 표시를 감추고, 또박을 화면 전체에 띄운다.
//
// **태그 이름(footer, header)으로 감추면 안 된다.** 또박의 자모 키보드가
// <footer> 안에 있어서, 처음에 `footer { display: none }` 을 넣었더니 키보드가
// 통째로 사라졌다. 스트림릿 것만 고르도록 data-testid 로 짚는다.
const HOST_CSS = `
  header[data-testid="stHeader"],
  [data-testid="stToolbar"],
  [data-testid="stDecoration"],
  [data-testid="stStatusWidget"],
  #MainMenu {
    display: none !important;
  }
  #ttobak-root {
    position: fixed;
    inset: 0;
    z-index: 999990;
    overflow-y: auto;
    background: var(--color-bg);
  }
`;

function storedToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    // 사생활 보호 모드 등에서 저장소가 막혀 있을 수 있다. 그러면 새로고침할
    // 때마다 다시 참가해야 하지만, 게임 자체는 돈다.
    return null;
  }
}

function rememberToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // 위와 같은 이유로 조용히 넘어간다.
  }
}

function mount(host, assets) {
  const style = document.createElement("style");
  style.textContent = assets.css + HOST_CSS;
  document.head.appendChild(style);

  // 스트림릿의 요소 나무 밖(body)에 붙인다. 안에 붙이면 스트림릿이 다시 그릴
  // 때 흐리게 만들거나(실행 중 표시) 자리를 옮길 수 있다.
  const root = document.createElement("div");
  root.id = "ttobak-root";
  root.innerHTML = assets.body;
  document.body.appendChild(root);

  // api.js 가 이것을 보고 fetch 대신 다리로 보낸다.
  window.TtobakBridge = { send: (request, timeoutMs) => send(host, request, timeoutMs) };

  // innerHTML 로 넣은 <script> 는 실행되지 않는다. 하나씩 새로 만들어 붙여야
  // 원래 페이지처럼 순서대로 돈다(hangul.js → api.js → app.js).
  for (const code of assets.scripts) {
    const script = document.createElement("script");
    script.textContent = code;
    document.body.appendChild(script);
  }
}

function send(host, request, timeoutMs) {
  return new Promise((resolve) => {
    const id = host.next++;
    const timer = setTimeout(() => {
      host.pending.delete(id);
      resolve({
        status: 0,
        payload: { detail: "서버가 응답하지 않아요. 잠시 뒤 다시 시도해 주세요." },
      });
    }, timeoutMs);
    host.pending.set(id, {
      resolve,
      timer,
      request: { id, ...request },
      sentAt: performance.now(),
    });
    flush(host);
  });
}

/**
 * 아직 답을 못 받은 요청을 **전부** 실어 보낸다.
 *
 * 하나씩 보내면 안 된다. 같은 이름의 신호가 파이썬이 처리하기 전에 연달아
 * 오면 마지막 것만 남는다. 결과 창은 요청 둘을 동시에 보내는데(전적과 순위),
 * 그러면 하나가 사라져 영원히 기다린다. 전부 다시 실어 보내면 사라질 수가
 * 없고, 이미 처리한 번호는 파이썬이 알아보고 두 번 실행하지 않는다.
 */
function flush(host) {
  const requests = [...host.pending.values()].map((waiting) => waiting.request);
  if (!requests.length) return;
  host.setTriggerValue("requests", {
    requests,
    token: storedToken(),
    nonce: host.nonce++,
  });
}

/**
 * 요청마다 걸린 시간을 모아 둔다. 느릴 때 어디서 느린지 가르는 데 쓴다.
 * 개발자 도구에서 `console.table(window.__ttobakTimings)` 로 본다.
 *
 * - roundtrip_ms: 화면이 보내고 답을 받기까지(브라우저가 잰 것)
 * - total_ms: 그중 서버가 요청을 처리한 시간
 * - connect_ms / query_ms: 그중 DB 에 붙고 질의한 시간
 */
function record(waiting, reply) {
  const log = (window.__ttobakTimings ??= []);
  log.push({
    path: `${waiting.request.method || "GET"} ${waiting.request.path}`,
    roundtrip_ms: Math.round(performance.now() - waiting.sentAt),
    ...(reply.timing || {}),
  });
  if (log.length > 200) log.shift();
}

export default function (component) {
  const { data, setTriggerValue, setStateValue } = component;
  const host = (window.__ttobakHost ??= {
    started: false,
    pending: new Map(),
    next: 1,
    nonce: 1,
    setTriggerValue: null,
  });
  // 스트림릿이 다시 그릴 때마다 새 함수를 준다. 늘 최신 것을 쓴다.
  host.setTriggerValue = setTriggerValue;

  if (!host.started && data && data.assets) {
    host.started = true;
    mount(host, data.assets);
    // 파이썬에 "화면을 붙였다" 고 알린다. 그 뒤로는 무거운 화면 조각을
    // 다시 보내지 않는다.
    setStateValue("ready", true);
  }

  if (data && "token" in data) rememberToken(data.token);
  if (data && data.diag) window.__ttobakDiag = data.diag; // 임시: 지역 측정

  for (const reply of (data && data.replies) || []) {
    const waiting = host.pending.get(reply.id);
    if (!waiting) continue;
    host.pending.delete(reply.id);
    clearTimeout(waiting.timer);
    record(waiting, reply);
    waiting.resolve(reply);
  }
}
