#!/usr/bin/env python3
"""Build a Meridian demo video that matches live web style and brand assets."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "assets"
CAPTURE_DIR = ASSETS_DIR / "captures"
SCENE_DIR = ASSETS_DIR / "scenes"
CLIP_DIR = ASSETS_DIR / "clips"
CONCAT_FILE = ASSETS_DIR / "meridian_demo_clips.ffconcat"
OUTPUT_VIDEO = ASSETS_DIR / "meridian_demo_2m20s.mp4"

WIDTH = 1920
HEIGHT = 1080
FPS = 30

# Palette aligned to company/www/assets/meridian.css
BG_TOP = (3, 5, 7)
BG_BOTTOM = (2, 3, 5)
PANEL = (9, 13, 22)
PANEL_SOFT = (7, 11, 18)
BORDER = (23, 37, 54)
ACCENT = (135, 216, 255)
TEXT = (229, 235, 242)
DIM = (141, 152, 168)

LOGO_AVATAR = Path("/home/ubuntu/.meridian/workspace/company/www/assets/logo_avatar_192.png")
LOGO_BANNER = Path("/home/ubuntu/.meridian/workspace/company/www/assets/logo_banner_1200x630.jpg")

SCENES: list[dict[str, object]] = [
    {
        "kind": "brand",
        "slug": "intro",
        "duration": 12,
        "title": "Meridian Loom",
        "subtitle": "Governed local agent runtime with verifiable execution receipts.",
    },
    {
        "kind": "web",
        "slug": "home",
        "duration": 14,
        "url": "https://app.welliam.codes/",
        "wait_ms": 2600,
        "title": "Homepage surface",
        "subtitle": "Single narrative shell with live runtime identity and clear boundary.",
    },
    {
        "kind": "web",
        "slug": "loom",
        "duration": 14,
        "url": "https://app.welliam.codes/loom",
        "wait_ms": 2200,
        "title": "Loom runtime page",
        "subtitle": "Local runtime first, governance hooks explicit, no hidden execution claims.",
    },
    {
        "kind": "web",
        "slug": "proofs",
        "duration": 14,
        "url": "https://app.welliam.codes/proofs",
        "wait_ms": 2800,
        "title": "Public proof dashboard",
        "subtitle": "Runtime proof status, queue pressure, and live operator event stream.",
    },
    {
        "kind": "web",
        "slug": "demo",
        "duration": 14,
        "url": "https://app.welliam.codes/demo",
        "wait_ms": 2600,
        "title": "Demo surface",
        "subtitle": "Proof-backed workflow examples displayed on the same host boundary.",
    },
    {
        "kind": "web",
        "slug": "workflows",
        "duration": 14,
        "url": "https://app.welliam.codes/workflows",
        "wait_ms": 2400,
        "title": "Workflow portfolio",
        "subtitle": "First-party execution lanes tied to runtime evidence and operating metrics.",
    },
    {
        "kind": "web",
        "slug": "compare",
        "duration": 14,
        "url": "https://app.welliam.codes/compare",
        "wait_ms": 2200,
        "title": "Competitive framing",
        "subtitle": "Runtime-neutral comparison where governance and proof are first-class criteria.",
    },
    {
        "kind": "web",
        "slug": "community",
        "duration": 14,
        "url": "https://app.welliam.codes/community",
        "wait_ms": 2200,
        "title": "Community motion",
        "subtitle": "Operational cadence for contributors and operator review loops.",
    },
    {
        "kind": "card",
        "slug": "desktop_lane",
        "duration": 16,
        "title": "Desktop / Browser / Shell lanes",
        "subtitle": (
            "loom connect scaffold --name desktop_ops --transport desktop --action-schema meridian.runtime.v1\n"
            "loom connect validate | enable | test | health | scorecard\n"
            "acceptance: ./scripts/acceptance_connect_desktop_lane.sh"
        ),
    },
    {
        "kind": "brand",
        "slug": "outro",
        "duration": 14,
        "title": "Meridian",
        "subtitle": "Loom runtime + Kernel governance + inspectable proofs on a live host.",
    },
]

_RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _reset_dirs() -> None:
    for path in (CAPTURE_DIR, SCENE_DIR, CLIP_DIR):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)


def _gradient_canvas() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        ratio = y / max(1, HEIGHT - 1)
        r = int(BG_TOP[0] * (1 - ratio) + BG_BOTTOM[0] * ratio)
        g = int(BG_TOP[1] * (1 - ratio) + BG_BOTTOM[1] * ratio)
        b = int(BG_TOP[2] * (1 - ratio) + BG_BOTTOM[2] * ratio)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))
    draw.line([(WIDTH // 2, 0), (WIDTH // 2, HEIGHT)], fill=(50, 80, 104, 48), width=1)
    return img


def _brand_header(canvas: Image.Image, draw: ImageDraw.ImageDraw, avatar: Image.Image, index: int, total: int) -> None:
    draw.rounded_rectangle([(34, 24), (WIDTH - 34, 94)], radius=16, fill=PANEL_SOFT, outline=BORDER, width=2)
    avatar_small = avatar.resize((52, 52), _RESAMPLE)
    header_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    header_layer.paste(avatar_small, (52, 33), avatar_small)
    draw_text = ImageDraw.Draw(header_layer)
    draw_text.text((118, 38), "MERIDIAN", fill=ACCENT, font=_font(25, bold=True))
    draw_text.text((118, 64), "Governed Runtime Surface", fill=DIM, font=_font(16, bold=False))
    draw_text.text((WIDTH - 180, 48), f"{index:02d}/{total:02d}", fill=DIM, font=_font(22, bold=False))
    canvas.alpha_composite(header_layer)


def _draw_wrapped(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, width_chars: int, font: ImageFont.ImageFont, fill: tuple[int, int, int]) -> None:
    wrapped = "\n".join(textwrap.wrap(text, width=width_chars)) if "\n" not in text else text
    draw.multiline_text((x, y), wrapped, fill=fill, font=font, spacing=8)


def _compose_web_scene(capture: Path, scene: dict[str, object], index: int, total: int, avatar: Image.Image) -> Path:
    canvas = _gradient_canvas().convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    _brand_header(canvas, draw, avatar, index, total)

    panel_rect = (96, 118, WIDTH - 96, 878)
    draw.rounded_rectangle(panel_rect, radius=22, fill=PANEL, outline=BORDER, width=2)

    shot = Image.open(capture).convert("RGB")
    shot_fit = ImageOps.fit(shot, (panel_rect[2] - panel_rect[0] - 28, panel_rect[3] - panel_rect[1] - 28), _RESAMPLE)
    shot_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shot_layer.paste(shot_fit, (panel_rect[0] + 14, panel_rect[1] + 14))
    canvas.alpha_composite(shot_layer)

    caption_rect = (96, 902, WIDTH - 96, HEIGHT - 70)
    draw.rounded_rectangle(caption_rect, radius=16, fill=PANEL_SOFT, outline=BORDER, width=2)
    title = str(scene["title"])
    subtitle = str(scene["subtitle"])
    draw.text((128, 928), title, fill=TEXT, font=_font(44, bold=True))
    _draw_wrapped(draw, subtitle, 128, 986, 88, _font(24), DIM)

    target = SCENE_DIR / f"{index:02d}_{scene['slug']}.png"
    canvas.convert("RGB").save(target)
    return target


def _compose_card_scene(scene: dict[str, object], index: int, total: int, avatar: Image.Image, banner: Image.Image) -> Path:
    canvas = _gradient_canvas().convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    _brand_header(canvas, draw, avatar, index, total)

    hero_rect = (110, 132, WIDTH - 110, 792)
    draw.rounded_rectangle(hero_rect, radius=24, fill=PANEL, outline=BORDER, width=2)
    banner_fit = ImageOps.fit(banner.convert("RGB"), (hero_rect[2] - hero_rect[0] - 30, hero_rect[3] - hero_rect[1] - 30), _RESAMPLE)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(banner_fit, (hero_rect[0] + 15, hero_rect[1] + 15))
    canvas.alpha_composite(layer)

    caption_rect = (110, 830, WIDTH - 110, HEIGHT - 70)
    draw.rounded_rectangle(caption_rect, radius=16, fill=PANEL_SOFT, outline=BORDER, width=2)
    draw.text((144, 858), str(scene["title"]), fill=TEXT, font=_font(50, bold=True))
    subtitle = str(scene["subtitle"])
    _draw_wrapped(draw, subtitle, 144, 928, 86, _font(26), DIM)

    target = SCENE_DIR / f"{index:02d}_{scene['slug']}.png"
    canvas.convert("RGB").save(target)
    return target


def _capture_web_pages() -> dict[str, Path]:
    captures: dict[str, Path] = {}
    for scene in SCENES:
        if scene["kind"] != "web":
            continue
        slug = str(scene["slug"])
        url = str(scene["url"])
        wait_ms = int(scene.get("wait_ms", 2200))
        target = CAPTURE_DIR / f"{slug}.png"
        _run(
            [
                "npx",
                "-y",
                "playwright@latest",
                "screenshot",
                "--browser",
                "chromium",
                "--viewport-size",
                f"{WIDTH},{HEIGHT}",
                "--color-scheme",
                "dark",
                "--wait-for-timeout",
                str(wait_ms),
                url,
                str(target),
            ]
        )
        captures[slug] = target
    return captures


def _build_clip(scene_image: Path, clip_path: Path, duration: int) -> None:
    fade_out_start = max(0.0, float(duration) - 0.6)
    vf = (
        f"fps={FPS},format=yuv420p,"
        "eq=contrast=1.03:saturation=1.04,"
        "fade=t=in:st=0:d=0.45,"
        f"fade=t=out:st={fade_out_start:.2f}:d=0.55"
    )
    _run(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(scene_image),
            "-t",
            str(duration),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(clip_path),
        ]
    )


def _concat_clips(clips: list[Path]) -> None:
    lines = ["ffconcat version 1.0"]
    for clip in clips:
        lines.append(f"file '{clip}'")
    CONCAT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _run(
        [
            "ffmpeg",
            "-y",
            "-safe",
            "0",
            "-f",
            "concat",
            "-i",
            str(CONCAT_FILE),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(OUTPUT_VIDEO),
        ]
    )


def _check_dependencies() -> None:
    if not LOGO_AVATAR.exists():
        raise SystemExit(f"missing logo asset: {LOGO_AVATAR}")
    if not LOGO_BANNER.exists():
        raise SystemExit(f"missing logo asset: {LOGO_BANNER}")
    ffmpeg = subprocess.run(["bash", "-lc", "command -v ffmpeg"], capture_output=True, text=True)
    if ffmpeg.returncode != 0 or not ffmpeg.stdout.strip():
        raise SystemExit("ffmpeg is required: sudo apt update && sudo apt install -y ffmpeg")


def main() -> None:
    _check_dependencies()
    _reset_dirs()
    captures = _capture_web_pages()
    avatar = Image.open(LOGO_AVATAR).convert("RGBA")
    banner = Image.open(LOGO_BANNER).convert("RGB")

    scene_images: list[Path] = []
    total = len(SCENES)
    for idx, scene in enumerate(SCENES, start=1):
        kind = str(scene["kind"])
        if kind == "web":
            capture = captures[str(scene["slug"])]
            scene_image = _compose_web_scene(capture, scene, idx, total, avatar)
        else:
            scene_image = _compose_card_scene(scene, idx, total, avatar, banner)
        scene_images.append(scene_image)

    clips: list[Path] = []
    for scene_image, scene in zip(scene_images, SCENES):
        duration = int(scene["duration"])
        clip = CLIP_DIR / f"{scene_image.stem}.mp4"
        _build_clip(scene_image, clip, duration)
        clips.append(clip)

    _concat_clips(clips)
    total_seconds = sum(int(scene["duration"]) for scene in SCENES)
    print(f"Built {OUTPUT_VIDEO} ({total_seconds}s)")


if __name__ == "__main__":
    main()
