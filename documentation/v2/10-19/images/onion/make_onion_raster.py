#!/usr/bin/env python3
"""PNG poster and animated GIF for the AI Factory onion (Pillow + the pinned resvg rasterizer).

    npm ci --ignore-scripts --no-audit --no-fund     # once, in this folder (@resvg/resvg-js 2.6.2)
    python make_onion_raster.py --font-dir <folder with OpenSans-Regular.ttf and OpenSans-Semibold.ttf>

The GIF follows the VisualLearner concept exports: each step's scene is rasterized once, then signal dots
move along that step's links and a progress bar fills, sampled like VisualLessonExportTimeline (about
20 fps, cumulative centisecond rounding, 1 s end hold) and streamed as global-palette delta frames.
With --font-dir every wrapped text line is re-measured with the real Open Sans before anything is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, GifImagePlugin

HERE = Path(__file__).resolve().parent
ART = HERE / "artifacts"
sys.path.insert(0, str(HERE))
import make_onion_svg as onion  # noqa: E402


def check_text(font_dir: Path) -> int:
    fonts = {}
    checks = json.loads((ART / "text-checks.json").read_text(encoding="utf-8"))
    for check in checks:
        key = (check["size"], check["bold"])
        if key not in fonts:
            name = "OpenSans-Semibold.ttf" if check["bold"] else "OpenSans-Regular.ttf"
            fonts[key] = ImageFont.truetype(str(font_dir / name), check["size"])
        width = fonts[key].getlength(check["text"]) * (1.06 if check["text"].isupper() else 1)  # letter-spacing on ring labels
        if width > check["allowed"] + .5:
            raise SystemExit(f'Text wider than its box ({width:.1f} > {check["allowed"]:.1f}) in {check["scene"]}: {check["text"]}')
    return len(checks)


def palette_for(backgrounds, colors):
    """One palette for every scene keeps antialiased text stable across frames."""
    sheet = Image.new("RGB", (700, sum(min(700, b.height // 2) for b in backgrounds)), onion.BG)
    y = 0
    for background in backgrounds:
        thumb = background.copy()
        thumb.thumbnail((700, 700))
        sheet.paste(thumb, (0, y))
        y += thumb.height
    palette_image = sheet.quantize(colors=240, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    palette = palette_image.getpalette()[:720]
    for color in colors[:16]:
        palette.extend(bytes.fromhex(color[1:]))
    palette.extend([0] * (765 - len(palette)))
    palette.extend((255, 0, 255))  # index 255: reserved for transparent "unchanged" pixels in delta frames
    palette_image.putpalette(palette)
    return palette_image


TRANSPARENT = 255


def unchanged_transparent(current, previous):
    """Inside the changed box, pixels equal to the previous frame become transparent so LZW collapses them."""
    now = Image.frombytes("L", current.size, current.tobytes())
    before = Image.frombytes("L", previous.size, previous.tobytes())
    changed = ImageChops.difference(now, before).point(lambda v: 255 if v else 0)
    merged = Image.composite(now, Image.new("L", now.size, TRANSPARENT), changed)
    return Image.frombytes("P", current.size, merged.tobytes())


def make_gif(plan, target: Path) -> dict:
    backgrounds = [Image.open(job["png"]).convert("RGB") for job in plan["jobs"]]
    colors = [onion.BG, onion.ACCENT, "#FFFFFF"] + sorted({r["color"] for s in plan["steps"] for r in s["routes"]})
    palette = palette_for(backgrounds, colors)
    backgrounds = [b.quantize(palette=palette, dither=Image.Dither.NONE) for b in backgrounds]
    rgb = palette.getpalette()

    def index_of(color):
        wanted = list(bytes.fromhex(color[1:]))
        return next(i for i in range(256) if rgb[i * 3:i * 3 + 3] == wanted)

    def draw(frame):
        image = backgrounds[frame["step"]].copy()
        pen = ImageDraw.Draw(image)
        for route in plan["steps"][frame["step"]]["routes"]:
            x, y = onion.along([tuple(p) for p in route["points"]], frame["progress"])
            pen.ellipse((round(x - 10), round(y - 10), round(x + 10), round(y + 10)), fill=index_of(onion.BG), outline=index_of(route["color"]), width=2)
            pen.ellipse((round(x - 5), round(y - 5), round(x + 5), round(y + 5)), fill=index_of(route["color"]))
            pen.ellipse((round(x - 2), round(y - 2), round(x + 2), round(y + 2)), fill=index_of("#FFFFFF"))
        length = round(plan["progress_w"] * frame["progress"])
        if length:
            pen.rectangle((plan["progress_x"], plan["progress_y"], plan["progress_x"] + length, plan["progress_y"] + 4), fill=index_of(onion.ACCENT))
        return image

    previous = None
    with target.open("wb") as stream:
        for number, frame in enumerate(plan["frames"]):
            image = draw(frame)
            if number == 0:
                for block in GifImagePlugin.getheader(image, info={"loop": 0, "background": 0})[0]:
                    stream.write(block)
                box = (0, 0, plan["width"], plan["height"])
                delta = image
            else:
                box = ImageChops.difference(previous, image).getbbox() or (0, 0, 1, 1)
                delta = unchanged_transparent(image.crop(box), previous.crop(box))
            delta.putpalette(rgb)
            extra = {"transparency": TRANSPARENT} if number else {}
            for block in GifImagePlugin.getdata(delta, offset=box[:2], duration=frame["delay"] * 10, disposal=1, **extra):
                stream.write(block)
            previous = image
        stream.write(b";")
    samples = sorted({0, len(plan["frames"]) - 1} | {
        next(i for i, f in enumerate(plan["frames"]) if f["step"] == s and f["progress"] >= .5) for s in range(len(plan["steps"]))})
    with Image.open(target) as gif:
        assert gif.size == (plan["width"], plan["height"]) and gif.info.get("loop") == 0
        delays = []
        for number in range(gif.n_frames):
            gif.seek(number)
            delays.append(gif.info["duration"])
            if number in samples:
                reference = draw(plan["frames"][number]).convert("RGB")
                assert gif.convert("RGB").tobytes() == reference.tobytes(), f"GIF delta compositing differs at frame {number}"
                reference.save(ART / f"sample-{number:04}.png")
        assert delays == [f["delay"] * 10 for f in plan["frames"]]
    return {"frames": len(delays), "durationSeconds": sum(delays) / 1000, "checkedFrames": samples}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--font-dir", type=Path, help="folder with OpenSans-Regular.ttf and OpenSans-Semibold.ttf")
    args = parser.parse_args()
    subprocess.run([sys.executable, str(HERE / "make_onion_svg.py"), "--frames", str(ART)], check=True)
    data = onion.load()
    out = {key: (HERE / value).resolve() for key, value in data["outputs"].items()}
    plan = json.loads((ART / "timeline.json").read_text(encoding="utf-8"))
    jobs = plan["jobs"] + [{"svg": str(out["poster_svg"]), "png": str(out["poster_png"])}]
    (ART / "raster-jobs.json").write_text(json.dumps(jobs, indent=1), encoding="utf-8")
    node = ["node", str(HERE / "rasterize.cjs"), str(ART / "raster-jobs.json")] + ([str(args.font_dir)] if args.font_dir else [])
    subprocess.run(node, check=True, cwd=HERE)
    checked = check_text(args.font_dir) if args.font_dir else 0
    gif = make_gif(plan, out["animated_gif"])
    manifest = {
        "schemaVersion": 1, "generated": data["updated"], "speed": plan["speed"], "endHoldSeconds": plan["end_hold_seconds"],
        "nominalFramesPerSecond": 20, "width": plan["width"], "animationHeight": plan["height"],
        "steps": [s["id"] for s in data["animation"]["steps"]], "gif": {"file": out["animated_gif"].name, **gif},
        "textLinesCheckedWithOpenSans": checked,
        "renderer": {"svg": "make_onion_svg.py (standard library), SMIL animation",
                     "raster": "@resvg/resvg-js 2.6.2 (CPU, no browser capture)", "gif": f"Pillow {Image.__version__} global palette, delta frames"},
        "files": {path.name: {"bytes": path.stat().st_size, "sha256": sha(path)}
                  for path in (out["poster_svg"], out["poster_png"], out["animated_svg"], out["animated_gif"])},
        "limitations": [
            "The animated SVG needs SMIL support (browsers do; GitHub shows it when the file is opened directly). A static viewer shows the first step.",
            "GIF timestamps are whole centiseconds and the palette has 256 colors.",
            "Fonts are not embedded: the SVGs use Open Sans when installed and fall back to Segoe UI, Helvetica or Arial.",
        ],
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f'GIF {plan["width"]}x{plan["height"]}: {gif["frames"]} frames, {gif["durationSeconds"]:.2f}s, '
          f'{out["animated_gif"].stat().st_size / 1048576:.2f} MiB; PNG {out["poster_png"].name}; '
          f'{checked} text lines checked with Open Sans' if checked else "text not re-measured (no --font-dir)")


if __name__ == "__main__":
    main()
