"""生成应用 logo：蓝底圆 + 白色中继发射塔 + 信号波纹。
输出 assets/icon.png（256）与 assets/icon.ico（16~256 多尺寸）。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

S = 256
CX = CY = S / 2
OUT = Path(__file__).resolve().parent / "assets"
OUT.mkdir(parents=True, exist_ok=True)


def _lerp(a, b, t):
    return int(a + (b - a) * t)


def _bg(draw: ImageDraw.ImageDraw) -> None:
    R = S / 2 - 4
    # 径向渐变：中心亮蓝 → 边缘深蓝
    for r in range(int(R), 0, -1):
        t = 1 - r / R
        color = (
            _lerp(24, 74, t), _lerp(96, 168, t), _lerp(200, 245, t), 255,
        )
        draw.ellipse([CX - r, CY - r, CX + r, CY + r], fill=color)
    # 细描边
    draw.ellipse([CX - R, CY - R, CX + R, CY + R], outline=(255, 255, 255, 255), width=2)


def _tower(draw: ImageDraw.ImageDraw) -> None:
    """白色中继发射塔（居中）+ 顶部信号波纹。"""
    W = 8  # 线条粗细
    # 底座（三角支架）
    bx0, bx1 = CX - 52, CX + 52
    by = CY + 56
    draw.line([(bx0, by), (CX - 16, CY + 4)], fill=(255, 255, 255), width=W)
    draw.line([(bx1, by), (CX + 16, CY + 4)], fill=(255, 255, 255), width=W)
    draw.line([(bx0, by), (bx1, by)], fill=(255, 255, 255), width=W)
    # 塔杆
    draw.line([(CX, CY + 4), (CX, CY - 58)], fill=(255, 255, 255), width=W)
    # 横档
    draw.line([(CX - 18, CY - 12), (CX + 18, CY - 12)], fill=(255, 255, 255), width=5)
    draw.line([(CX - 14, CY - 30), (CX + 14, CY - 30)], fill=(255, 255, 255), width=5)
    # 顶部天线小球
    r = 9
    draw.ellipse([CX - r, CY - 58 - r, CX + r, CY - 58 + r],
                 fill=(255, 215, 0, 255))  # 金色小球点缀


def _waves(draw: ImageDraw.ImageDraw) -> None:
    """从塔顶发出的 3 道白色信号弧（同心圆弧，向右上）。"""
    top = (CX, CY - 58)
    for i, radius in enumerate((38, 66, 96)):
        # 画一段弧（0°~75°，向右）
        bbox = [top[0] - radius, top[1] - radius, top[0] + radius, top[1] + radius]
        draw.arc(bbox, start=-70, end=10, fill=(255, 255, 255, 255), width=6 - i)


def main() -> None:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    _bg(d)
    _tower(d)
    _waves(d)
    img.save(OUT / "icon.png")
    img.save(OUT / "icon.ico", sizes=[
        (16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("已生成:", OUT / "icon.png", "|", OUT / "icon.ico")


if __name__ == "__main__":
    main()
