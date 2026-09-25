"""환경 변수로 주입되는 애플리케이션 설정.

모든 값은 ``TTOBAK_`` 접두사를 붙인 환경 변수나 ``.env`` 파일로 덮어쓸 수 있다.
예: ``TTOBAK_MAX_ATTEMPTS=8``.
"""

from __future__ import annotations

import functools
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """서버 기동에 필요한 모든 설정값."""

    model_config = SettingsConfigDict(
        env_prefix="TTOBAK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 게임 규칙 ---
    puzzle_lengths: tuple[int, ...] = Field(
        default=(5, 6, 7, 8),
        description="퍼즐에 쓰일 자모 길이 후보. 라운드마다 이 중 하나가 뽑힌다.",
    )
    max_attempts: int = Field(default=6, ge=1, le=12, description="한 판의 추측 기회")
    hints_offered: bool = Field(
        default=True,
        description=(
            "힌트 기능을 제공할지 여부. 서버 전체를 끄는 스위치다. "
            "켜 두더라도 사람마다 설정에서 따로 켜야 실제로 쓸 수 있고, "
            "개인 기본값은 꺼짐이다."
        ),
    )
    daily_salt: str = Field(
        default="ttobak-v1",
        description="정답 선정 난수의 시드. 바꾸면 전체 출제 순서가 달라진다.",
    )

    # --- 저장소 ---
    data_dir: Path = Field(
        default=PROJECT_ROOT / "data", description="단어 사전이 있는 디렉터리"
    )
    database_path: Path = Field(
        default=PROJECT_ROOT / "var" / "ttobak.sqlite3", description="SQLite 파일 경로"
    )

    # --- 웹 서버 ---
    #: 바인딩 주소. **기본값이 127.0.0.1 인 것은 의도된 보안 설정이다.**
    #:
    #: 친구들은 Tailscale Funnel 을 거쳐 들어오고, Funnel 은 이 서버를
    #: ``http://127.0.0.1:8790`` 으로만 찾는다. 즉 로컬호스트에만 열어 두어도
    #: 밖에서 들어오는 길은 전혀 막히지 않는다.
    #:
    #: 반대로 ``0.0.0.0`` 으로 열면 **같은 Wi-Fi 에 있는 아무 기기나** 이
    #: 서버에 직접 닿는다. 카페나 공용 網 에서는 그 기기들이 누구 것인지 알
    #: 수 없고, 그 경로는 Funnel 을 거치지 않으므로 Tailscale 이 걸러 주는
    #: 것도 없다. 얻는 것 없이 공격 면만 넓어지는 교환이라 기본값에서 뺐다.
    #:
    #: 같은 공유기의 다른 기기에서 직접 열어야 할 일이 있으면 그때만
    #: ``--host 0.0.0.0`` 을 주면 된다.
    host: str = Field(default="127.0.0.1", description="바인딩 주소")
    port: int = Field(default=8787, ge=1, le=65535, description="바인딩 포트")
    secret_key: str = Field(
        default="change-me-in-production",
        description="플레이어 쿠키 서명 키. 배포 시 반드시 교체한다.",
    )
    #: 이미 쓰는 닉네임으로 들어올 때 복구 코드를 요구할지.
    #:
    #: **기본은 꺼짐이다.** 켜면 "먼저 쓴 사람이 임자" 가 되어 남이 내 이름으로
    #: 못 들어오지만, 그 대가로 **쿠키를 잃은 본인도 못 들어온다.**
    #:
    #: 실제로 그 대가가 컸다. 카카오톡 인앱 브라우저가 쿠키를 안 남기는
    #: 경우가 있는데, 그러면 링크를 누를 때마다 처음 온 사람이 된다. 서버는
    #: 쿠키를 제대로 보내고 있어도(HttpOnly·Secure·SameSite=lax·1년) 소용이
    #: 없다 — 브라우저가 안 들고 있으면 서버가 할 수 있는 일이 없다.
    #: 그 상태에서 코드를 요구하면 친구들이 통째로 막힌다.
    #:
    #: 그래서 기본을 끈다. 아는 사람끼리 쓰는 동안에는 사칭 위험보다
    #: 못 들어오는 쪽이 훨씬 크고 자주 일어나는 문제다. 모르는 사람에게
    #: 열 때 켜면 된다.
    require_recovery_code: bool = Field(
        default=False,
        description="쓰던 닉네임에 복구 코드를 요구할지. 켜면 본인도 막힐 수 있다",
    )
    #: 후원 링크. **비어 있으면 후원 버튼 자체가 안 보인다.**
    #:
    #: 기본값을 비워 두는 이유: 링크를 안 정했는데 버튼만 떠 있으면 친구가
    #: 눌렀을 때 아무 데도 안 간다. 그건 후원을 못 받는 것보다 나쁘다 —
    #: "이 사람 만들다 말았네"가 되니까. (실제로 시험용 주소를 남겨 뒀다가
    #: 404 가 났다.)
    #:
    #: ``{amount}`` 를 넣으면 단계별 금액으로 바뀐다::
    #:
    #:     https://toss.me/내이름/{amount}
    #:
    #: 이 형태가 이 기능에 맞다. 화면의 단계가 원화(300원, 1,000원 …)이므로
    #: **금액을 주소에 실을 수 있는 서비스**여야 표시와 실제가 일치한다.
    #: 토스·카카오페이 송금 링크가 그렇다.
    #:
    #: Buy Me a Coffee 처럼 "커피 N잔" 단위인 곳은 ``{amount}`` 를 못 쓴다.
    #: 그때는 그냥 주소만 넣으면 모든 단계가 같은 페이지로 간다 — 다만
    #: 화면에 적힌 원화 금액과 실제 결제 금액이 달라지므로 권하지 않는다.
    support_url: str = Field(default="", description="후원 페이지 주소 (기타)")
    #: 토스 송금 링크. ``https://toss.me/내아이디/{amount}``
    support_toss: str = Field(default="", description="토스 송금 링크")
    #: 카카오페이 송금 링크.
    support_kakao: str = Field(default="", description="카카오페이 송금 링크")

    session_cookie: str = Field(default="ttobak_player", description="쿠키 이름")
    session_max_age_days: int = Field(default=365, ge=1, description="쿠키 유지 기간")
    tailscale_cli: str = Field(
        default="tailscale",
        description="`tailscale whois`로 접속자 기기명을 알아내는 데 쓰는 실행 파일",
    )

    # --- 보안 ---
    public: bool = Field(
        default=False,
        description=(
            "Tailscale Funnel 등으로 인터넷에 공개했는지 여부. 켜면 쿠키에 "
            "Secure 플래그가 붙고 HSTS 헤더가 나가며, API 문서 페이지가 닫힌다."
        ),
    )
    enable_docs: bool = Field(
        default=False,
        description="/docs 와 /openapi.json 을 열지 여부. 공개 배포에서는 끈다.",
    )

    # --- 정리 ---
    retention_days: int = Field(
        default=30,
        description=(
            "판·댓글·처리 끝난 신고를 며칠까지 두는가. 지난 것은 하루 한 번 지운다. "
            "0 이면 지우지 않는다."
        ),
    )
    dormant_days: int = Field(
        default=3,
        description=(
            "며칠 안 들어온 계정을 지우는가(방장은 제외). 0 이면 지우지 않는다."
        ),
    )

    # --- 공유 ---
    share_url: str = Field(
        default="",
        description=(
            "공유 문구 끝에 붙일 접속 주소. 받은 사람이 바로 들어올 수 있게 한다. "
            "비워 두면 주소를 넣지 않는다."
        ),
    )

    @field_validator("puzzle_lengths")
    @classmethod
    def _validate_lengths(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value:
            raise ValueError("puzzle_lengths는 비어 있을 수 없습니다.")
        if any(length < 2 for length in value):
            raise ValueError("puzzle_lengths의 각 길이는 2 이상이어야 합니다.")
        return tuple(sorted(set(value)))

    @property
    def templates_dir(self) -> Path:
        return PACKAGE_ROOT / "templates"

    @property
    def static_dir(self) -> Path:
        return PACKAGE_ROOT / "static"


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """프로세스 전체에서 공유되는 설정 인스턴스."""
    return Settings()
