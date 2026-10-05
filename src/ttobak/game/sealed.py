"""진행 중인 판의 정답을 **살짝 감춰서** 화면에 보낸다.

왜 보내나
---------

원격 DB 로 옮긴 뒤 답을 낼 때마다 서버까지 다녀오느라 1초 안팎을 기다렸다.
정답이 화면에 있으면 화면이 **그 자리에서 채점**해 타일을 바로 뒤집고, 저장은
뒤에서 한다. 사장님 판단: "친구끼리 하는 게임이라 그렇게까지 빡빡할 필요는
없다, 정 그러면 약간 암호화해서."

이것은 암호가 아니다
--------------------

열쇠를 같이 보내므로 개발자 도구를 열고 작정하면 풀린다. 막는 것은
**우연히 보이는 것**(응답을 훑다가 정답 글자가 눈에 띄는 것)까지다. 판정의
최종 권한은 여전히 서버에 있다 — 화면이 채점한 결과와 서버가 저장한 결과가
다르면 서버 쪽이 이긴다.

모양: ``{"k": 열쇠(base64), "v": 감춘 값(base64)}``. 값은 정답 자모 나열의
UTF-8 바이트를 열쇠와 XOR 한 것이다. 열쇠는 응답마다 새로 뽑는다.
"""

from __future__ import annotations

import base64
import secrets

__all__ = ["seal", "unseal"]

#: 열쇠 길이(바이트). 길 필요는 없다 — 암호가 아니라 가림막이다.
KEY_BYTES = 8


def seal(jamos: str) -> dict[str, str]:
    """자모 나열을 가림막에 싼다."""
    key = secrets.token_bytes(KEY_BYTES)
    data = jamos.encode("utf-8")
    masked = bytes(b ^ key[i % KEY_BYTES] for i, b in enumerate(data))
    return {
        "k": base64.b64encode(key).decode("ascii"),
        "v": base64.b64encode(masked).decode("ascii"),
    }


def unseal(sealed: dict[str, str]) -> str:
    """:func:`seal` 을 되돌린다. 화면(app.js)이 하는 일과 똑같다 — 시험용."""
    key = base64.b64decode(sealed["k"])
    masked = base64.b64decode(sealed["v"])
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(masked)).decode("utf-8")
