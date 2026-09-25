"""닉네임 선점 — 비밀번호 없이 "먼저 쓴 사람이 임자" 를 만든다.

왜 필요한가
-----------

이 게임은 닉네임만 입력하면 들어온다. 친구들이 쉽게 들어와야 한다는 요구가
먼저라서 그렇게 만들었고, 그 자체는 바꾸지 않는다.

문제는 **닉네임을 아는 사람이 곧 그 사람이 된다** 는 것이다. 인터넷 무작위
공격에는 별 의미가 없다(닉네임을 모르니까). 그런데 이 게임은 지인끼리
쓰는 물건이고, **지인은 서로 닉네임을 안다.** 실제로 해 보면 남의 진행 중인
판이 그대로 보이고 기회를 대신 소모시킬 수 있다.

어떻게 막는가
-------------

닉네임을 처음 쓴 사람에게 **복구 코드**를 한 번 보여 주고, 그 해시만 저장한다.
그 뒤로 같은 닉네임으로 들어오려면 그 코드가 있어야 한다.

- 평소에는 아무것도 안 바뀐다. 쿠키가 1년이라 코드를 쓸 일이 없다.
- 기기를 바꾸거나 브라우저를 지웠을 때만 코드를 넣는다.
- 코드를 잃어버리면 그 닉네임은 못 쓴다. 다른 이름으로 새로 시작하면 된다 —
  비밀번호 찾기 메일 같은 걸 붙이는 것보다 이 편이 이 규모에 맞다.

**코드 자체는 저장하지 않는다.** 해시만 둔다. DB 파일이 새어도 그것으로
남의 계정을 되찾을 수는 없어야 한다.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

__all__ = [
    "RECOVERY_CODE_LENGTH",
    "hash_recovery_code",
    "new_recovery_code",
    "verify_recovery_code",
]

#: 복구 코드에 쓸 글자. 방 코드와 같은 이유로 헷갈리는 글자를 뺐다 —
#: 이 코드는 사람이 받아 적고 나중에 옮겨 치게 된다.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

#: 코드 길이. 31글자 10자리면 약 50비트다.
#:
#: 방 코드(14자)보다 짧다. 이건 **사람이 메모장에 옮겨 적는 값** 이라 길수록
#: 안 적게 되고, 안 적으면 있으나 마나다. 대신 온라인 추측만 가능하고(해시를
#: 얻을 방법이 없다) 참가 요청에는 요청 수 제한이 걸려 있어, 50비트면 실질적
#: 으로 못 뚫는다.
RECOVERY_CODE_LENGTH = 10


def new_recovery_code() -> str:
    """새 복구 코드. 4글자씩 끊어 읽기 쉽게 만든다."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:7]}-{raw[7:]}"


def _normalize(code: str) -> str:
    """비교 전에 다듬는다. 사람이 옮겨 적으면 하이픈과 대소문자가 흔들린다."""
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def hash_recovery_code(code: str) -> str:
    """저장할 해시.

    SHA-256 을 그냥 쓴다. 비밀번호가 아니라 **50비트 난수** 라서 사전 공격이
    통하지 않고, 느린 해시(bcrypt 등)를 쓸 이유가 없다. 사람이 고른 값이었다면
    반대로 반드시 느린 해시를 써야 한다.
    """
    return hashlib.sha256(_normalize(code).encode("ascii")).hexdigest()


def verify_recovery_code(code: str, expected_hash: str) -> bool:
    """코드가 맞는지. **비교는 반드시 상수 시간으로 한다.**

    ``==`` 는 앞에서부터 비교하다 다르면 즉시 끝나서, 응답 시간 차이로 코드를
    한 글자씩 알아낼 수 있다(타이밍 공격). 로컬 게임에 과해 보이지만 공개
    배포할 것이고, 맞추는 비용이 지수적으로 줄어드는 종류의 실수다.
    """
    if not expected_hash:
        return False
    return hmac.compare_digest(hash_recovery_code(code), expected_hash)
