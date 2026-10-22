"""Render an animated (SMIL) or static SVG into a small, seamlessly looping GIF.

GIF is the README format that animates everywhere (GitHub, Azure DevOps, VS Code
preview, MkDocs). Regenerating from the SVG source at the display size is much
smaller than reusing the full-size 1400 px export.

Usage, from the repository root:

    python documentation/gh-io/tools/svg_to_gif.py SOURCE.svg OUTPUT.gif --preset header
    python documentation/gh-io/tools/svg_to_gif.py SOURCE.svg OUTPUT.gif --preset thumb
    python documentation/gh-io/tools/svg_to_gif.py SOURCE.svg OUTPUT.gif --width 600 --fps 10 --colors 64 --max-kb 900

Presets (explicit flags override them):

    header  720 px wide, 12.5 fps, 128 colours, budget 1500 KB
    thumb   320 px wide, 10 fps,   64 colours,  budget 400 KB

How it works: headless Chromium (Playwright) pauses the SVG's SMIL timeline and
seeks it to evenly spaced times across exactly one loop (the shared
``dur`` of its ``repeatCount="indefinite"`` animations), so the last frame flows
into the first. ffmpeg encodes the frames with a frame-difference palette and
rectangle-diff frames. gifsicle ``-O3 --lossy`` runs afterwards when it is on
PATH. The frame rate must divide 100 (GIF delays are whole centiseconds), so use
12.5, 10, 5, 4 ... rather than 12. Every frame carries a small, nearly invisible
"Enterprise Scale AI Factory (ESAIF)" plaque - light text in a hairline rounded
border at very low opacity - centred horizontally (``--watermark-y`` moves it
vertically, ``--watermark ""`` turns it off; the source SVG is not modified). CSS ``@keyframes`` SVGs are rejected instead of
being exported as a single static frame. The JSON report is printed; the exit
code is 2 when the GIF exceeds its budget.

Requirements: ``python -m pip install playwright``, ``python -m playwright install
chromium`` and ffmpeg on PATH; gifsicle is optional.
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape


PRESETS = {
    "header": {"width": 720, "fps": 12.5, "colors": 128, "max_kb": 1500},
    "thumb": {"width": 320, "fps": 10, "colors": 64, "max_kb": 400},
}
WATERMARK = "Enterprise Scale AI Factory (ESAIF)"
WATERMARK_ID = "svg-to-gif-watermark"
WATERMARK_TEXT, WATERMARK_STROKE, WATERMARK_FILL = 0.16, 0.14, 0.035
ANIMATION = re.compile(r"<(?:animate|animateColor|animateMotion|animateTransform|set)\b[^>]*>")
CLOCK_UNITS = {"h": 3600.0, "min": 60.0, "s": 1.0, "ms": 0.001}


def _clock_seconds(value: str) -> float:
    value = value.strip()
    if ":" in value:
        seconds = 0.0
        for part in value.split(":"):
            seconds = seconds * 60 + float(part)
        return seconds
    match = re.fullmatch(r"([\d.]+)(h|min|s|ms)?", value)
    if not match:
        raise ValueError(f"unsupported SMIL clock value {value!r}")
    return float(match.group(1)) * CLOCK_UNITS[match.group(2) or "s"]


def loop_seconds(svg_text: str) -> float | None:
    """Length of one seamless loop, or None for a static SVG."""
    if "@keyframes" in svg_text:
        raise ValueError("CSS @keyframes animation is not supported; use SMIL or export frames another way")
    animations = ANIMATION.findall(svg_text)
    if not animations:
        return None
    loops = set()
    for element in animations:
        duration = re.search(r'\bdur="([^"]+)"', element)
        if duration and re.search(r'\brepeatCount="indefinite"', element):
            loops.add(round(_clock_seconds(duration.group(1)), 6))
    if not loops:
        raise ValueError("SVG animates but has no repeatCount=\"indefinite\" loop to capture")
    if len(loops) > 1:
        raise ValueError(f"SVG animations loop at different durations {sorted(loops)}; one loop is ambiguous")
    return loops.pop()


def frame_times(loop: float | None, fps: float) -> list[float]:
    """Evenly spaced sample times across exactly one loop; the loop end equals frame 0."""
    if loop is None:
        return [0.0]
    count = max(1, round(loop * fps))
    return [index * loop / count for index in range(count)]


def gif_delay_cs(fps: float) -> int:
    delay = 100 / fps
    if abs(delay - round(delay)) > 1e-9:
        raise ValueError(f"{fps:g} fps is not a whole GIF delay; choose a rate that divides 100 (12.5, 10, 5 ...)")
    return round(delay)


def _viewbox(svg_text: str) -> tuple[float, float, float, float]:
    match = re.search(r'<svg\b[^>]*\bviewBox="([^"]+)"', svg_text)
    if not match:
        raise ValueError("SVG needs a viewBox to scale it to the requested width")
    return tuple(float(value) for value in re.split(r"[\s,]+", match.group(1).strip()))


def output_size(svg_text: str, width: int) -> tuple[int, int]:
    _, _, view_width, view_height = _viewbox(svg_text)
    height = round(width * view_height / view_width)
    return width, height + height % 2


def add_watermark(svg_text: str, text: str, y_fraction: float = 0.5) -> str:
    """Draw a small, nearly invisible plaque (hairline rounded border + text) above every layer.

    The light colour at very low opacity melts into the dark concept diagrams. The border is
    estimated here and refitted to the measured text by render_frames.
    """
    if not text:
        return svg_text
    left, top, width, height = _viewbox(svg_text)
    x, y, size = left + width / 2, top + height * y_fraction, width * 0.0105
    pad_x, pad_y = size * 1.1, size * 0.7
    box_width, box_height = len(text) * size * 0.56 + 2 * pad_x, size + 2 * pad_y
    mark = (f'<g id="{WATERMARK_ID}" pointer-events="none">'
            f'<rect x="{x - box_width / 2:g}" y="{y - box_height / 2:g}" width="{box_width:g}" '
            f'height="{box_height:g}" rx="{size * 0.5:g}" fill="#fff" fill-opacity="{WATERMARK_FILL:g}" '
            f'stroke="#fff" stroke-opacity="{WATERMARK_STROKE:g}" stroke-width="{size * 0.08:g}" '
            f'data-pad-x="{pad_x:g}" data-pad-y="{pad_y:g}"/>'
            f'<text x="{x:g}" y="{y:g}" text-anchor="middle" dominant-baseline="middle" '
            f'font-family="\'Open Sans\', \'Segoe UI\', Arial, sans-serif" font-size="{size:g}" '
            f'letter-spacing="{size * 0.04:g}" fill="#fff" opacity="{WATERMARK_TEXT:g}">{escape(text)}</text></g>')
    end = svg_text.rindex("</svg>")
    return svg_text[:end] + mark + svg_text[end:]


def ffmpeg_command(frames_dir: Path, fps: float, output: Path, colors: int) -> list[str]:
    graph = (f"split[a][b];[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
             "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
    return ["ffmpeg", "-y", "-loglevel", "error", "-framerate", f"{fps:g}",
            "-i", str(frames_dir / "frame_%05d.png"), "-lavfi", graph, "-loop", "0", str(output)]


def gifsicle_command(path: Path, lossy: int) -> list[str]:
    return ["gifsicle", "-O3", f"--lossy={lossy}", "--batch", str(path)]


def render_frames(svg_text: str, size: tuple[int, int], times: list[float], frames_dir: Path) -> None:
    from playwright.sync_api import sync_playwright

    width, height = size
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(f"<!doctype html><body style='margin:0;background:#fff'>{svg_text}</body>")
            page.evaluate("""([w, h]) => {
                const svg = document.querySelector('svg');
                svg.setAttribute('width', w);
                svg.setAttribute('height', h);
                svg.style.display = 'block';
                svg.pauseAnimations();
                return document.fonts.ready.then(() => true);
            }""", [width, height])
            page.evaluate("""id => {
                const plaque = document.getElementById(id);
                if (!plaque) return;
                const rect = plaque.querySelector('rect'), box = plaque.querySelector('text').getBBox();
                const padX = +rect.dataset.padX, padY = +rect.dataset.padY;
                rect.setAttribute('x', box.x - padX);
                rect.setAttribute('y', box.y - padY);
                rect.setAttribute('width', box.width + 2 * padX);
                rect.setAttribute('height', box.height + 2 * padY);
            }""", WATERMARK_ID)
            for index, seconds in enumerate(times):
                page.evaluate("t => document.querySelector('svg').setCurrentTime(t)", seconds)
                page.screenshot(path=str(frames_dir / f"frame_{index:05d}.png"),
                                clip={"x": 0, "y": 0, "width": width, "height": height})
        finally:
            browser.close()


def encode_gif(frames_dir: Path, fps: float, output: Path, colors: int) -> None:
    subprocess.run(ffmpeg_command(frames_dir, fps, output, colors), check=True)


def convert(source: Path, output: Path, *, width: int, fps: float, colors: int, lossy: int | None,
            max_kb: int | None = None, watermark: str = "", watermark_y: float = 0.5,
            render=render_frames, encode=encode_gif) -> dict:
    svg_text = Path(source).read_text(encoding="utf-8")
    loop = loop_seconds(svg_text)
    gif_delay_cs(fps)
    size = output_size(svg_text, width)
    times = frame_times(loop, fps)
    svg_text = add_watermark(svg_text, watermark, watermark_y)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="svg-to-gif-") as temporary:
        frames_dir = Path(temporary)
        render(svg_text, size, times, frames_dir)
        encode(frames_dir, fps, output, colors)
    optimized = lossy is not None and shutil.which("gifsicle") is not None
    if optimized:
        subprocess.run(gifsicle_command(output, lossy), check=True)
    size_bytes = output.stat().st_size
    return {"source": str(source), "output": str(output), "width": size[0], "height": size[1],
            "fps": fps, "frames": len(times), "loop_seconds": loop, "colors": colors, "watermark": watermark,
            "gifsicle": optimized, "bytes": size_bytes, "kb": round(size_bytes / 1024),
            "max_kb": max_kb, "within_budget": max_kb is None or size_bytes <= max_kb * 1024}


def _skip_sub_blocks(data: bytes, position: int) -> int:
    while data[position]:
        position += data[position] + 1
    return position + 1


def inspect_gif(path: Path) -> dict:
    """Logical size, frame count, total duration and NETSCAPE loop count of a GIF (stdlib only)."""
    data = Path(path).read_bytes()
    if data[:6] not in (b"GIF87a", b"GIF89a"):
        raise ValueError(f"{path} is not a GIF")
    width, height, packed = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little"), data[10]
    position = 13 + (3 * 2 ** ((packed & 7) + 1) if packed & 0x80 else 0)
    frames, duration_ms, delay_cs, loop = 0, 0, 0, None
    while position < len(data) and data[position] != 0x3B:
        block = data[position]
        if block == 0x21:
            label = data[position + 1]
            if label == 0xF9:
                delay_cs = int.from_bytes(data[position + 4:position + 6], "little")
            elif label == 0xFF and data[position + 3:position + 14] == b"NETSCAPE2.0":
                loop = int.from_bytes(data[position + 16:position + 18], "little")
            position = _skip_sub_blocks(data, position + 2)
        elif block == 0x2C:
            local = data[position + 9]
            position += 10 + (3 * 2 ** ((local & 7) + 1) if local & 0x80 else 0)
            position = _skip_sub_blocks(data, position + 1)
            frames += 1
            duration_ms += delay_cs * 10
            delay_cs = 0
        else:
            raise ValueError(f"unexpected GIF block 0x{block:02x} at byte {position}")
    return {"width": width, "height": height, "frames": frames, "duration_ms": duration_ms,
            "loop": loop, "bytes": len(data)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--preset", choices=sorted(PRESETS), default="header")
    parser.add_argument("--width", type=int)
    parser.add_argument("--fps", type=float)
    parser.add_argument("--colors", type=int)
    parser.add_argument("--max-kb", type=int)
    parser.add_argument("--lossy", type=int, default=30, help="gifsicle --lossy level when gifsicle is on PATH")
    parser.add_argument("--watermark", default=WATERMARK, help='faint centred plaque text; --watermark "" for none')
    parser.add_argument("--watermark-y", type=float, default=0.5,
                        help="plaque centre as a fraction of the height, e.g. 0.62 to sit between card rows")
    args = parser.parse_args(argv)
    settings = {**PRESETS[args.preset],
                **{key: value for key, value in vars(args).items()
                   if key in ("width", "fps", "colors", "max_kb") and value is not None}}
    settings.update(watermark=args.watermark, watermark_y=args.watermark_y)
    report = convert(args.source, args.output, lossy=args.lossy, **settings)
    report.update(inspect_gif(args.output))
    print(json.dumps(report, indent=2))
    return 0 if report["within_budget"] else 2


if __name__ == "__main__":
    sys.exit(main())
