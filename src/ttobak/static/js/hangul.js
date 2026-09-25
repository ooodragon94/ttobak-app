/**
 * 브라우저 쪽 한글 유틸리티.
 *
 * 서버가 정답 채점을 모두 맡으므로 여기서는 두 가지만 한다.
 *   1. 키보드에 그릴 자모 배열을 제공한다.
 *   2. 입력한 자모 나열을 사람이 읽을 수 있는 음절로 조립해 보여 준다.
 *
 * 조립은 화면 표시용 편의 기능이라 실패해도 게임에는 영향이 없다.
 */
const Hangul = (() => {
  const CHOSEONGS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
  const JUNGSEONGS = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ";
  const JONGSEONGS = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ";

  /** 두벌식 자판 배열. 게임에서 쓰는 기본 자모 24개가 전부다. */
  const KEYBOARD_ROWS = [
    ["ㅂ", "ㅈ", "ㄷ", "ㄱ", "ㅅ", "ㅛ", "ㅕ", "ㅑ"],
    ["ㅁ", "ㄴ", "ㅇ", "ㄹ", "ㅎ", "ㅗ", "ㅓ", "ㅏ", "ㅣ"],
    ["ㅋ", "ㅌ", "ㅊ", "ㅍ", "ㅠ", "ㅜ", "ㅡ"],
  ];

  const VOWELS = new Set("ㅏㅑㅓㅕㅗㅛㅜㅠㅡㅣ");

  /** 기본 모음 두 개를 합쳐 만드는 복합 모음. */
  const VOWEL_PAIRS = {
    "ㅏㅣ": "ㅐ", "ㅑㅣ": "ㅒ", "ㅓㅣ": "ㅔ", "ㅕㅣ": "ㅖ",
    "ㅗㅏ": "ㅘ", "ㅗㅣ": "ㅚ", "ㅜㅓ": "ㅝ", "ㅜㅣ": "ㅟ",
    "ㅡㅣ": "ㅢ", "ㅘㅣ": "ㅙ", "ㅝㅣ": "ㅞ",
  };

  /** 받침 자리에서 두 자음이 합쳐지는 겹받침. */
  const FINAL_PAIRS = {
    "ㄱㅅ": "ㄳ", "ㄴㅈ": "ㄵ", "ㄴㅎ": "ㄶ", "ㄹㄱ": "ㄺ", "ㄹㅁ": "ㄻ",
    "ㄹㅂ": "ㄼ", "ㄹㅅ": "ㄽ", "ㄹㅌ": "ㄾ", "ㄹㅍ": "ㄿ", "ㄹㅎ": "ㅀ",
    "ㅂㅅ": "ㅄ",
  };

  /** 같은 자음이 겹쳐 초성이 되는 쌍자음. */
  const TWIN_CONSONANTS = { "ㄱ": "ㄲ", "ㄷ": "ㄸ", "ㅂ": "ㅃ", "ㅅ": "ㅆ", "ㅈ": "ㅉ" };

  /** 겹받침을 되돌리는 표. 뒤 글자가 모음이면 뒷자음만 넘겨야 한다. */
  const FINAL_SPLITS = Object.fromEntries(
    Object.entries(FINAL_PAIRS).map(([pair, merged]) => [merged, [pair[0], pair[1]]])
  );

  const isVowel = (jamo) => VOWELS.has(jamo);

  /**
   * 초성/중성/종성 인덱스로 완성형 음절 하나를 만든다.
   * @returns {string} 조합할 수 없으면 빈 문자열.
   */
  function buildSyllable(choseong, jungseong, jongseong) {
    // **초성과 중성이 둘 다 있어야 글자가 된다.** 빈 문자열로 indexOf 를
    // 부르면 -1 이 아니라 0 이 나온다. 그래서 모음 없이 남은 자음 하나(ㄱ)가
    // 중성 0번(ㅏ)을 달고 '가' 로 조립됐다. ㄱㄱㄱㄱㄱ 이 'ㄲㄲ가' 로 보인
    // 원인이다(맞는 것은 'ㄲㄲㄱ').
    if (!choseong || !jungseong) return "";
    const cho = CHOSEONGS.indexOf(choseong);
    const jung = JUNGSEONGS.indexOf(jungseong);
    const jong = jongseong ? JONGSEONGS.indexOf(jongseong) : 0;
    if (cho < 0 || jung < 0 || jong < 0) return "";
    return String.fromCharCode(0xac00 + (cho * 21 + jung) * 28 + jong);
  }

  /**
   * 자모 배열을 음절 문자열로 조립한다.
   *
   * 한국어 입력기와 같은 규칙을 쓴다. 자음 뒤에 모음이 오면 초성이 되고,
   * 모음 뒤의 자음은 일단 받침으로 붙였다가 다음 글자가 모음이면 떼어 준다.
   *
   * @param {string[]} jamos 기본 자모 배열
   * @returns {string} 조립된 문자열. 조립이 안 되는 부분은 자모 그대로 남는다.
   */
  function compose(jamos) {
    const out = [];
    // 조립 중인 글자. null이면 아직 시작하지 않았다.
    let cur = null;

    const flush = () => {
      if (!cur) return;
      const built = buildSyllable(cur.cho, cur.jung, cur.jong);
      out.push(built || [cur.cho, cur.jung, cur.jong].filter(Boolean).join(""));
      cur = null;
    };

    for (const jamo of jamos) {
      if (!isVowel(jamo)) {
        if (!cur) {
          cur = { cho: jamo, jung: "", jong: "" };
        } else if (!cur.jung) {
          // 모음 없이 자음이 이어지면 쌍자음이거나 별개 글자다.
          const twin = cur.cho === jamo ? TWIN_CONSONANTS[jamo] : null;
          if (twin) {
            cur.cho = twin;
          } else {
            out.push(cur.cho);
            cur = { cho: jamo, jung: "", jong: "" };
          }
        } else if (!cur.jong) {
          cur.jong = jamo;
        } else {
          const merged = FINAL_PAIRS[cur.jong + jamo];
          if (merged) {
            cur.jong = merged;
          } else {
            flush();
            cur = { cho: jamo, jung: "", jong: "" };
          }
        }
        continue;
      }

      // 모음 차례
      if (!cur) {
        out.push(jamo);
      } else if (!cur.jung) {
        cur.jung = jamo;
      } else if (!cur.jong) {
        const merged = VOWEL_PAIRS[cur.jung + jamo];
        if (merged) {
          cur.jung = merged;
        } else {
          flush();
          out.push(jamo);
        }
      } else {
        // 받침이 다음 글자의 초성으로 넘어간다. 겹받침이면 뒷자음만 넘긴다.
        const split = FINAL_SPLITS[cur.jong];
        const moved = split ? split[1] : cur.jong;
        cur.jong = split ? split[0] : "";
        flush();
        cur = { cho: moved, jung: jamo, jong: "" };
      }
    }
    flush();
    return out.join("");
  }

  return { KEYBOARD_ROWS, compose, isVowel };
})();
