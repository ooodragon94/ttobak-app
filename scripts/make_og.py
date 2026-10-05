#!/usr/bin/env python
"""카톡 링크 미리보기에 쓸 카드 이미지를 만든다.

    python scripts/make_og.py

**왜 SVG 가 아니라 PNG 인가**

카톡·트위터 등의 미리보기 수집기는 SVG 를 안 읽는다. 벡터라 관리가 편할 것
같지만 화면에 아무것도 안 뜬다. OG 이미지는 반드시 래스터(PNG/JPEG)여야 한다.

**왜 1200x630 인가**

미리보기 카드의 사실상 표준 비율(1.91:1)이다. 다른 비율로 만들면 카톡이
위아래를 잘라 내서 글자가 반쯤 사라진다.

이 스크립트는 한 번 돌려 두면 되고, 결과물(static/og.png)은 그대로 쓰인다.
문구나 색을 바꾸고 싶을 때만 다시 돌린다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "src" / "ttobak" / "static" / "og.png"

WIDTH, HEIGHT = 1200, 630
BG = (246, 247, 249)
GREEN = (106, 170, 100)
YELLOW = (201, 180, 88)
GREY = (120, 124, 126)
INK = (22, 24, 29)
MUTED = (107, 114, 128)

#: 한글이 나오는 폰트를 찾는다. 없으면 네모(두부)만 잔뜩 나온다.
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    sys.exit(
        "한글 폰트를 못 찾았습니다. FONT_CANDIDATES 에 경로를 추가해 주세요.\n"
        "기본 폰트로 그리면 한글이 네모로 나옵니다."
    )


def centered(draw: ImageDraw.ImageDraw, text: str, font, y: int, fill) -> None:
    """가로 가운데 정렬. anchor 를 쓰면 폰트마다 기준선이 달라 흔들린다."""
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = (WIDTH - (right - left)) / 2 - left
    draw.text((x, y - top), text, font=font, fill=fill)


def main() -> int:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    # 게임판 한 줄. 초록·노랑·회색이 이 게임의 정체성이라 글자보다 먼저 보인다.
    tile, gap, size = 118, 18, 3
    total = tile * size + gap * (size - 1)
    x0, y0 = (WIDTH - total) // 2, 120
    tile_font = load_font(66)
    for index, (color, label) in enumerate(
        ((GREEN, "또"), (YELLOW, "박"), (GREY, "?"))
    ):
        x = x0 + index * (tile + gap)
        draw.rounded_rectangle([x, y0, x + tile, y0 + tile], radius=16, fill=color)
        left, top, right, bottom = draw.textbbox((0, 0), label, font=tile_font)
        draw.text(
            (
                x + (tile - (right - left)) / 2 - left,
                y0 + (tile - (bottom - top)) / 2 - top,
            ),
            label,
            font=tile_font,
            fill=(255, 255, 255),
        )

    centered(draw, "또박", load_font(88), 300, INK)
    centered(draw, "한글 자모로 단어 맞히기", load_font(40), 410, MUTED)
    centered(draw, "친구들과 매일 같은 문제", load_font(34), 480, GREEN)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, "PNG", optimize=True)
    print(f"{OUT} ({OUT.stat().st_size // 1024}KB, {WIDTH}x{HEIGHT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
