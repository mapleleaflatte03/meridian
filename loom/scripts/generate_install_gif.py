#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


WIDTH = 880
HEIGHT = 520
PADDING_X = 44
PADDING_Y = 34
TERMINAL_TOP = 118
TERMINAL_HEIGHT = 396
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_PATH_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
BG = "#05080d"
CARD = "#0a1118"
CARD_EDGE = "#16212b"
TEXT = "#edf6ff"
DIM = "#8da3b6"
ACCENT = "#87d8ff"
ACCENT_SOFT = "#112330"
SUCCESS = "#5cd18d"
WARN = "#f7c96a"
PROMPT = "#9fe3ff"
CURSOR = "#f4fbff"


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size)


FONT_BODY = load_font(FONT_PATH, 20)
FONT_BODY_BOLD = load_font(FONT_PATH_BOLD, 20)
FONT_SMALL = load_font(FONT_PATH, 16)
FONT_TITLE = load_font(FONT_PATH_BOLD, 34)
FONT_SUBTITLE = load_font(FONT_PATH, 18)
FONT_WINDOW = load_font(FONT_PATH_BOLD, 17)


SCENES = [
    {
        "title": "1-command install",
        "label": "binary-first install",
        "command": "curl -fsSL https://raw.githubusercontent.com/mapleleaflatte03/meridian-loom/main/scripts/install.sh | bash",
        "output": [
            "[loom] preferred release asset: linux-x86_64",
            "[loom] downloaded v0.1.16",
            "[loom] linked binary -> ~/.local/bin/loom",
            "[loom] runtime root -> ~/.local/share/meridian-loom/runtime/default",
            "[loom] next: loom doctor --root ~/.local/share/meridian-loom/runtime/default --format human",
        ],
    },
    {
        "title": "Check readiness",
        "label": "doctor first",
        "command": "loom doctor --root ~/.local/share/meridian-loom/runtime/default --format human",
        "output": [
            "Meridian Loom // DOCTOR",
            "release:     official v0.1 local runtime",
            "overall:     ready",
            "checks:      52 total · 52 ok · 0 warn · 0 critical",
            "next_step:   loom status --root <path>",
        ],
    },
    {
        "title": "See the proof surface",
        "label": "status + receipts",
        "command": "loom status --root ~/.local/share/meridian-loom/runtime/default",
        "output": [
            "Meridian Loom // STATUS",
            "release:     official v0.1 local runtime",
            "runtime:     local queue supervisor + service shell",
            "governance_surfaces: agent_identity, action_envelope, cost_attribution, approval_hook, audit_emission, sanction_controls, budget_gate",
            "Next: loom service submit · loom parity report · loom job inspect",
        ],
    },
]


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill: str, outline: str | None = None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def wrap_command(text: str, width_chars: int = 76) -> list[str]:
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        if not current:
            candidate = word
        else:
            candidate = f"{current} {word}"
        if len(candidate) <= width_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_header(draw: ImageDraw.ImageDraw) -> None:
    draw.text((PADDING_X, PADDING_Y), "Install in 60 seconds", font=FONT_TITLE, fill=TEXT)
    draw.text(
        (PADDING_X, PADDING_Y + 44),
        "One command, then doctor and status. The point is not magic. The point is immediate proof.",
        font=FONT_SUBTITLE,
        fill=DIM,
    )
    pill_x = WIDTH - PADDING_X - 248
    rounded(draw, (pill_x, PADDING_Y + 10, WIDTH - PADDING_X, PADDING_Y + 48), 18, ACCENT_SOFT, ACCENT)
    draw.text((pill_x + 16, PADDING_Y + 19), "Meridian Loom v0.1.16", font=FONT_WINDOW, fill=ACCENT)


def draw_terminal_base(draw: ImageDraw.ImageDraw, title: str, label: str) -> None:
    left = PADDING_X
    top = TERMINAL_TOP
    right = WIDTH - PADDING_X
    bottom = TERMINAL_TOP + TERMINAL_HEIGHT
    rounded(draw, (left, top, right, bottom), 18, CARD, CARD_EDGE, width=2)
    rounded(draw, (left + 1, top + 1, right - 1, top + 46), 18, "#0d1620")
    draw.rectangle((left + 1, top + 26, right - 1, top + 46), fill="#0d1620")
    for idx, color in enumerate(("#ff6157", "#ffbd2f", "#28c840")):
        cx = left + 22 + idx * 18
        cy = top + 23
        draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=color)
    draw.text((left + 68, top + 14), title, font=FONT_WINDOW, fill=TEXT)
    rounded(draw, (right - 168, top + 11, right - 18, top + 35), 12, "#111d27", "#1f3140")
    draw.text((right - 153, top + 17), label, font=FONT_SMALL, fill=ACCENT)


def draw_scene(
    draw: ImageDraw.ImageDraw,
    scene: dict[str, object],
    typed_chars: int,
    output_lines: int,
    cursor_on: bool,
) -> None:
    draw_terminal_base(draw, str(scene["title"]), str(scene["label"]))
    start_x = PADDING_X + 26
    start_y = TERMINAL_TOP + 72
    line_height = 31
    command_lines = wrap_command(str(scene["command"]))
    remaining = typed_chars
    rendered_lines: list[str] = []
    for line in command_lines:
        take = max(0, min(len(line), remaining))
        rendered_lines.append(line[:take])
        remaining -= take
    for idx, line in enumerate(rendered_lines):
        prefix = "$ " if idx == 0 else "  "
        draw.text((start_x, start_y + idx * line_height), prefix, font=FONT_BODY_BOLD, fill=PROMPT)
        draw.text((start_x + 30, start_y + idx * line_height), line, font=FONT_BODY, fill=TEXT)
    all_command_len = sum(len(line) for line in command_lines)
    if typed_chars <= all_command_len and cursor_on:
        cursor_line = 0
        count = typed_chars
        for idx, line in enumerate(command_lines):
            if count <= len(line):
                cursor_line = idx
                cursor_col = count
                break
            count -= len(line)
        else:
            cursor_col = len(command_lines[-1])
            cursor_line = len(command_lines) - 1
        x = start_x + 30 + cursor_col * 12
        y = start_y + cursor_line * line_height + 3
        draw.rectangle((x, y, x + 12, y + 22), fill=CURSOR)
    output_y = start_y + max(1, len(command_lines)) * line_height + 18
    for idx, line in enumerate(scene["output"][:output_lines]):
        fill = SUCCESS if line.startswith("[loom]") or "overall:" in line or "release:" in line else DIM
        if "Next:" in line or "next_step:" in line:
            fill = WARN
        draw.text((start_x, output_y + idx * 28), line, font=FONT_BODY, fill=fill)


def build_frames() -> list[Image.Image]:
    frames: list[Image.Image] = []
    for scene in SCENES:
        command_len = sum(len(line) for line in wrap_command(str(scene["command"])))
        for typed in range(0, command_len + 1, 5):
            im = Image.new("RGB", (WIDTH, HEIGHT), BG)
            draw = ImageDraw.Draw(im)
            draw_header(draw)
            draw_scene(draw, scene, typed, 0, cursor_on=True)
            frames.append(im)
        for blink in range(3):
            im = Image.new("RGB", (WIDTH, HEIGHT), BG)
            draw = ImageDraw.Draw(im)
            draw_header(draw)
            draw_scene(draw, scene, command_len, 0, cursor_on=blink % 2 == 0)
            frames.append(im)
        for shown in range(1, len(scene["output"]) + 1):
            im = Image.new("RGB", (WIDTH, HEIGHT), BG)
            draw = ImageDraw.Draw(im)
            draw_header(draw)
            draw_scene(draw, scene, command_len, shown, cursor_on=False)
            frames.append(im)
        for _ in range(4):
            im = Image.new("RGB", (WIDTH, HEIGHT), BG)
            draw = ImageDraw.Draw(im)
            draw_header(draw)
            draw_scene(draw, scene, command_len, len(scene["output"]), cursor_on=False)
            frames.append(im)
    return frames


def save_gif(frames: Iterable[Image.Image], out_path: Path) -> None:
    frames = [frame.convert("P", palette=Image.ADAPTIVE) for frame in frames]
    durations = []
    for idx, _ in enumerate(frames):
        durations.append(80)
        if idx and idx % 18 == 0:
            durations[-1] = 220
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=False,
        disposal=2,
    )


def save_poster(frame: Image.Image, out_path: Path) -> None:
    frame.save(out_path, format="PNG", optimize=True)


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    assets = repo / "docs" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    gif_path = assets / "install_in_60_seconds.gif"
    poster_path = assets / "install_in_60_seconds.png"
    frames = build_frames()
    save_gif(frames, gif_path)
    save_poster(frames[-1], poster_path)
    print(gif_path)
    print(poster_path)


if __name__ == "__main__":
    main()
