"""明日方舟图鉴：保留参考项目的完整文字内容，长图自动分张。"""
from PIL import Image, ImageDraw, ImageOps

from .guide_image import core_font, load_icon, save_image

WIDTH = 1120
MAX_HEIGHT = 3500


def _wrap(text: str, width: int, size: int) -> list[str]:
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = []
    for paragraph in text.split("\n"):
        current = ""
        for char in paragraph:
            if current and draw.textlength(current + char, font=core_font(size)) > width:
                lines.append(current)
                current = ""
            current += char
        lines.append(current)
    return lines


def render_wiki(char_id: str, name: str, kind: str, sections: list[tuple[str, str]]) -> list[str]:
    pages, rows = [], []
    used = 210
    for title, body in sections:
        pending = _wrap(body, WIDTH - 144, 26)
        while pending:
            capacity = (MAX_HEIGHT - 100 - used - 72 - 24) // 38
            if capacity < 1:
                pages.append(rows)
                rows, used = [], 210
                continue
            lines, pending = pending[:capacity], pending[capacity:]
            rows.append((title, lines))
            used += 72 + len(lines) * 38 + 24
            if pending:
                pages.append(rows)
                rows, used = [], 210
                title += "（续）"
    if rows:
        pages.append(rows)
    paths = []
    avatar = load_icon("arknights", "char", char_id)
    for index, rows in enumerate(pages, 1):
        height = 210 + sum(72 + len(lines) * 38 + 24 for _, lines in rows) + 100
        image = Image.new("RGB", (WIDTH, height), (234, 237, 239))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, WIDTH, 176), fill=(28, 32, 38))
        draw.rectangle((42, 170, WIDTH - 42, 178), fill=(246, 202, 64))
        if avatar:
            image.paste(ImageOps.contain(avatar, (130, 130)), (WIDTH - 182, 20),
                        ImageOps.contain(avatar, (130, 130)))
        draw.text((52, 27), name, font=core_font(48), fill="white")
        draw.text((54, 99), f"明日方舟 / {kind}　{index} / {len(pages)}", font=core_font(27), fill=(194, 201, 209))
        y = 210
        for title, lines in rows:
            draw.rounded_rectangle((42, y, WIDTH - 42, y + 72 + len(lines) * 38), radius=14, fill="white")
            draw.rectangle((42, y + 18, 48, y + 49), fill=(223, 175, 35))
            draw.text((70, y + 14), title, font=core_font(30), fill=(30, 39, 49))
            for offset, line in enumerate(lines):
                draw.text((72, y + 63 + offset * 38), line, font=core_font(26), fill=(56, 63, 73))
            y += 72 + len(lines) * 38 + 24
        draw.text((WIDTH // 2, height - 47), "function by manshuo", font=core_font(23), anchor="mm", fill=(106, 116, 128))
        paths.append(save_image(image, f"skland_arknights_{'module' if kind == '模组图鉴' else 'wiki'}"))
    return paths
