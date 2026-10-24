#!/usr/bin/env python3
"""Draw the AI Factory onion from onion-layers.json. Standard library only.

    python make_onion_svg.py               # poster SVG + animated SVG
    python make_onion_svg.py --update-doc  # also rewrite the generated tables in the markdown page
    python make_onion_svg.py --frames DIR  # also write per-step scenes + timeline for make_onion_raster.py

Edit onion-layers.json and re-run: the picture, the animation and the doc tables redraw from the data.
The look, the step/key-point layout and the 3x timing follow the VisualLearner concept exports
(maui-apps ESAIF.ConfigWizard/tools/ConceptAnimationExport), drawn as concentric rings instead of a grid.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "onion-layers.json"

# VisualLearner palette (AsomRecordsAB.Base/VisualLearner/VisualLearnerScene.cs).
W, M = 1400, 48
BG, SURFACE, GRID, MUTED, WHITE, ACCENT, KEY = "#080E1B", "#14243A", "#304565", "#A0B5D0", "#ECF6FF", "#79DCED", "#FFD48A"
FONT = '"Open Sans","Segoe UI","Helvetica Neue",Arial,sans-serif'

# Diagram geometry, in diagram coordinates (width W - 2M).
DW = W - 2 * M
RADII = (360, 294, 228, 162, 96)  # outer edge of L1..L4 bands, then the L5 core
CARD_X, CARD_W = 800, DW - 800
CONSUMER_CARD = (0, 0, 224, 92)

# Approximate Open Sans advance widths (em/1000). Wrapping keeps a margin; make_onion_raster.py
# re-measures every line with the real font when one is available.
_ADV = {**dict.fromkeys("ijl|", 252), **dict.fromkeys(".,:;·'!", 266), **dict.fromkeys("ft()[]", 340),
        **dict.fromkeys("r-", 409), **dict.fromkeys("Iszc", 480), **dict.fromkeys("yvkx", 520),
        **dict.fromkeys("0123456789+=<>*#_~$", 572), **dict.fromkeys("aegbdhnopqu", 600),
        **dict.fromkeys("EFLPSTZJ", 560), **dict.fromkeys("ABKRXY", 630), **dict.fromkeys("CDGHNUV", 740),
        **dict.fromkeys("OQ&%", 780), "m": 931, "w": 778, "M": 903, "W": 907, " ": 260, "/": 371,
        "…": 800, "→": 1000, "@": 899, '"': 401, "?": 429}


def text_width(text: str, size: float, bold: bool = False) -> float:
    return sum(_ADV.get(ch, 620) for ch in text) / 1000 * size * (1.06 if bold else 1.0)


def wrap(text: str, width: float, size: float, bold: bool = False) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and text_width(candidate, size, bold) * 1.03 > width:
            lines.append(current)
            current = word
        else:
            current = candidate
        if text_width(current, size, bold) > width:
            raise ValueError(f"Unbreakable text is wider than {width}px: {current}")
    return lines + ([current] if current else [])


def num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def mix(color: str, other: str, t: float) -> str:
    a, b = bytes.fromhex(color[1:]), bytes.fromhex(other[1:])
    return "#" + "".join(f"{round(x * t + y * (1 - t)):02X}" for x, y in zip(a, b))


TEXT_CHECKS: list[dict] = []


class Scene:
    """An SVG fragment with wrapped text whose line boxes are recorded for later checks."""

    def __init__(self, name: str):
        self.name, self.parts = name, []

    def add(self, fragment: str) -> None:
        self.parts.append(fragment)

    def rect(self, x, y, w, h, fill=SURFACE, stroke=None, radius=12, stroke_width=1, opacity=None):
        extra = (f' stroke="{stroke}" stroke-width="{num(stroke_width)}"' if stroke else "") + \
                (f' opacity="{num(opacity)}"' if opacity is not None else "")
        self.add(f'<rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" rx="{radius}" fill="{fill}"{extra}/>')

    def text(self, text, x, y, width, size=20, color=WHITE, bold=False, leading=None, anchor="start") -> float:
        leading = leading or math.ceil(size * 1.38)
        lines = wrap(text, width, size, bold)
        weight = ' font-weight="600"' if bold else ""
        align = f' text-anchor="{anchor}"' if anchor != "start" else ""
        for index, line in enumerate(lines):
            top = y + index * leading
            TEXT_CHECKS.append({"scene": self.name, "text": line, "size": size, "bold": bold, "allowed": width})
            self.add(f'<text x="{num(x)}" y="{num(top + size)}" fill="{color}" font-size="{size}"{weight}{align}>{esc(line)}</text>')
        return y + len(lines) * leading

    def body(self) -> str:
        return "".join(self.parts)


def document(body: str, height: int, title: str, description: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}" role="img">'
            f'<title>{esc(title)}</title><desc>{esc(description)}</desc>'
            f'<style>text{{font-family:{FONT};font-kerning:normal}}</style>'
            f'<rect width="{W}" height="{height}" fill="{BG}"/>{body}</svg>\n')


# ---------------------------------------------------------------- diagram

def nodes(data) -> dict:
    return {data["consumer"]["id"]: data["consumer"], **{layer["id"]: layer for layer in data["layers"]}}


def onion_center() -> tuple[float, float]:
    return 410.0, RADII[0] + CONSUMER_CARD[3] + 30


def band_mid(index: int) -> float:
    """Middle radius of layer index 0..3; the core (index 4) uses a point near its edge."""
    return (RADII[index] + RADII[index + 1]) / 2 if index < 4 else 70.0


def polar(center, radius, degrees):
    a = math.radians(degrees)
    return center[0] + radius * math.cos(a), center[1] + radius * math.sin(a)


def path_points(data, center, path_id: str) -> dict[str, tuple[float, float]]:
    """Marker position of every node along one path."""
    path = next(p for p in data["paths"] if p["id"] == path_id)
    ids = [layer["id"] for layer in data["layers"]]
    points = {layer_id: polar(center, band_mid(i), path["angle"]) for i, layer_id in enumerate(ids)}
    x, y = polar(center, RADII[0], path["angle"])
    points["consumer"] = (x, CONSUMER_CARD[1] + CONSUMER_CARD[3])
    points["consumer-join"] = (x, y)
    return points


def route(data, center, link) -> list[tuple[float, float]]:
    points = path_points(data, center, link["path"])
    if link["from"] == "consumer":
        return [points["consumer"], points["consumer-join"], points[link["to"]]]
    return [points[link["from"]], points[link["to"]]]


def card_layout(data) -> tuple[list[dict], float]:
    """Measure the six cards (consumer + L1..L5) and spread them over the onion's height."""
    items = [data["consumer"]] + data["layers"]
    cards, inner = [], CARD_W - 32
    for item in items:
        height = 14 + 14 + 6 + 22 + len(wrap(item["where"], inner, 11.5)) * 16 + 6 + \
                 len(wrap(item["what"], inner, 13)) * 18 + 4 + len(wrap("e.g. " + item["example"], inner, 11.5, True)) * 16 + 12
        cards.append({"item": item, "height": height})
    total = sum(card["height"] for card in cards)
    height = max(total + 10 * (len(cards) - 1), 2 * RADII[0] + CONSUMER_CARD[3] + 60)
    gap = (height - total) / (len(cards) - 1)
    y = 0.0
    for card in cards:
        card["y"] = y
        y += card["height"] + gap
    return cards, height


def dash(on: bool, pattern: str = "7 6") -> str:
    return f' stroke-dasharray="{pattern}"' if on else ""


def arrow(scene: Scene, points, color, dashed=False, badge=None, width=2.4, head=True):
    d = "M" + " L".join(f"{num(x)},{num(y)}" for x, y in points)
    scene.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"{dash(dashed)}/>')
    if head:
        (ax, ay), (bx, by) = points[-2], points[-1]
        length = math.dist((ax, ay), (bx, by)) or 1
        dx, dy = (bx - ax) / length, (by - ay) / length
        tip = (bx - dx * 9, by - dy * 9)
        corners = [tip, (tip[0] - dx * 10 - dy * 5, tip[1] - dy * 10 + dx * 5), (tip[0] - dx * 10 + dy * 5, tip[1] - dy * 10 - dx * 5)]
        scene.add(f'<path d="M{" L".join(f"{num(x)},{num(y)}" for x, y in corners)} Z" fill="{color}"/>')
    if badge is not None:
        mx, my = along(points, .5)
        scene.rect(mx - 12, my - 13, 24, 26, BG, color, 6)
        scene.text(str(badge), mx, my - 10, 20, 13, WHITE, True, anchor="middle")


def along(points, progress):
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    remaining = sum(lengths) * max(0.0, min(1.0, progress))
    for (a, b), length in zip(zip(points, points[1:]), lengths):
        if remaining <= length and length:
            t = remaining / length
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        remaining -= length
    return points[-1]


def draw_diagram(data, active=None, links=(), name="poster", chart=True) -> tuple[Scene, float, list[dict]]:
    """The onion, its paths, the six cards and the path legend. Returns scene, height and link routes."""
    scene = Scene(name)
    focus = set(active) if active is not None else None
    lit = lambda node_id: focus is None or node_id in focus
    cards, height = card_layout(data)
    center = onion_center()
    cx, cy = center
    defs = []
    # Rings from the outside in; each inner disc covers the middle of the outer one.
    for index, layer in enumerate(data["layers"]):
        on = lit(layer["id"])
        color = layer["color"]
        fill = mix(color, BG, .16 if on else .05)
        stroke = color if on else GRID
        scene.add(f'<circle cx="{num(cx)}" cy="{num(cy)}" r="{RADII[index]}" fill="{fill}" stroke="{stroke}" '
                  f'stroke-width="{2.4 if on and focus is not None else 1.6}"/>')
    for index, layer in enumerate(data["layers"][:4]):
        on = lit(layer["id"])
        mid = band_mid(index)
        top, bottom = f"ring-top-{index}-{name}", f"ring-bottom-{index}-{name}"
        r_top, r_bottom = mid - 14 * .36, mid + 11 * .36
        defs.append(f'<path id="{top}" d="M{num(cx - r_top)},{num(cy)} A{num(r_top)},{num(r_top)} 0 0 1 {num(cx + r_top)},{num(cy)}"/>')
        defs.append(f'<path id="{bottom}" d="M{num(cx - r_bottom)},{num(cy)} A{num(r_bottom)},{num(r_bottom)} 0 0 0 {num(cx + r_bottom)},{num(cy)}"/>')
        for path_id, label, size, color in ((top, layer["ring_top"], 14, layer["color"] if on else MUTED),
                                            (bottom, layer["ring_bottom"], 11, mix(layer["color"], MUTED, .55) if on else GRID)):
            TEXT_CHECKS.append({"scene": name, "text": label, "size": size, "bold": True, "allowed": math.pi * mid * .62})
            scene.add(f'<text font-size="{size}" font-weight="600" letter-spacing="1" fill="{color}">'
                      f'<textPath href="#{path_id}" startOffset="50%" text-anchor="middle">{esc(label)}</textPath></text>')
    core = data["layers"][4]
    on = lit(core["id"])
    scene.text("L5 · CORE", cx, cy - 50, 150, 12, core["color"] if on else MUTED, True, anchor="middle")
    for offset, word in zip((-30, -8, 14), ("AZURE", "RESOURCE", "MANAGER")):
        scene.text(word, cx, cy + offset, 150, 17, WHITE if on else MUTED, True, anchor="middle")
    scene.add("<defs>" + "".join(defs) + "</defs>")

    # Consumer card, outside the onion.
    consumer = data["consumer"]
    on = lit(consumer["id"])
    x, y, w, h = CONSUMER_CARD
    scene.rect(x, y, w, h, SURFACE, consumer["color"] if on else GRID, 14, 2.4 if on and focus is not None else 1)
    scene.rect(x + 14, y + 15, 22, 4, consumer["color"], radius=2)
    scene.text("EXTERNAL CONSUMER", x + 46, y + 9, w - 56, 10, consumer["color"] if on else MUTED, True)
    scene.text("Azure Function", x + 14, y + 30, w - 28, 17, WHITE, True)
    scene.text("lifecycle Function > Python SDK", x + 14, y + 58, w - 28, 12, MUTED)

    # Paths: markers on every band they cross; arrows for the poster or for the step's links.
    by_id = nodes(data)
    for path in data["paths"]:
        points = path_points(data, center, path["id"])
        color = KEY if path["dashed"] else WHITE
        if focus is None:
            sequence = [points["consumer"], points["consumer-join"]] if path["via"][0] == "consumer" else []
            sequence += [points[node_id] for node_id in path["via"] if node_id != "consumer"]
            arrow(scene, sequence, mix(color, BG, .7), path["dashed"], width=1.6, head=False)
        for node_id in path["via"] + path.get("skips", []):
            if node_id == "consumer":
                continue
            px, py = points[node_id]
            skipped = node_id in path.get("skips", [])
            ring = by_id[node_id]["color"]
            scene.add(f'<circle cx="{num(px)}" cy="{num(py)}" r="{8 if skipped else 7}" fill="{BG}" '
                      f'stroke="{GRID if skipped else (ring if lit(node_id) else GRID)}" stroke-width="2"{dash(skipped, "3 3")}/>')
            if not skipped:
                scene.add(f'<circle cx="{num(px)}" cy="{num(py)}" r="3" fill="{ring if lit(node_id) else GRID}"/>')
            else:
                scene.text(f'skips {by_id[node_id]["label"]}', px + 12, py + 2, 70, 11, KEY if lit(path["via"][0]) else GRID, True)
    routes = []
    for index, link in enumerate(links):
        points = route(data, center, link)
        color = by_id[link["from"]]["color"]
        dashed = next(p for p in data["paths"] if p["id"] == link["path"])["dashed"]
        long_enough = sum(math.dist(a, b) for a, b in zip(points, points[1:])) >= 90
        arrow(scene, points, color, dashed, badge=index + 1 if long_enough else None)
        routes.append({"points": points, "color": color, "label": link["label"], "from": link["from"], "to": link["to"]})

    # Cards, consumer first, then L1..L5 (outside in).
    inner = CARD_W - 32
    for index, card in enumerate(cards):
        item, top = card["item"], card["y"]
        on = lit(item["id"])
        color = item["color"]
        scene.rect(CARD_X, top, CARD_W, card["height"], SURFACE, color if on else GRID, 14,
                   2.4 if on and focus is not None else 1)
        scene.rect(CARD_X + 16, top + 19, 22, 4, color, radius=2)
        tag = ("CONSUMER" if item["id"] == "consumer" else f"LAYER {item['n']}") + (" / IN FOCUS" if on and focus is not None else "")
        scene.text(tag, CARD_X + 48, top + 13, 220, 10.5, color if on else MUTED, True)
        scene.text(item["tag"], CARD_X + CARD_W - 16, top + 13, 230, 10.5, color if on else MUTED, True, anchor="end")
        title = item["name"] if item["id"] == "consumer" else f'{item["label"]} · {item["name"]}'
        y = scene.text(title, CARD_X + 16, top + 31, inner, 16, WHITE if on else MUTED, True, 22)
        y = scene.text(item["where"], CARD_X + 16, y + 4, inner, 11.5, MUTED, leading=16)
        y = scene.text(item["what"], CARD_X + 16, y + 4, inner, 13, WHITE if on else MUTED, leading=18)
        scene.text("e.g. " + item["example"], CARD_X + 16, y + 4, inner, 11.5, mix(color, MUTED, .7) if on else GRID, True, 16)

    if chart:
        time_chart(scene, data, (0, center[1] + RADII[0] + 44, CARD_X - 40, height))

    # Path legend under the diagram.
    y = height + 18
    for path in data["paths"]:
        color = KEY if path["dashed"] else WHITE
        scene.add(f'<path d="M0,{num(y + 10)} H44" stroke="{color}" stroke-width="2.4"{dash(path["dashed"])}/>')
        scene.text(f'{path["label"]}: {path["text"]}', 56, y, DW - 56, 14, color if path["dashed"] else WHITE, True, 20)
        y += 24
    return scene, y, routes


def time_chart(scene: Scene, data, box) -> None:
    """Stacked bars: upper estimate of each layer's minutes per scenario, segments labelled directly."""
    x0, y0, x1, y1 = box
    layers = [data["consumer"]] + data["layers"]
    y = scene.text("Where the time goes: minutes per scenario, by layer", x0, y0, x1 - x0, 15, WHITE, True)
    y = scene.text("Upper value of each layer's range, stacked; the range total is on the right. "
                   "Scenarios 4-6 ran simulated only.", x0, y + 2, x1 - x0, 11.5, MUTED, leading=16) + 10
    label_w, total_w = 168, 92
    bar_x, bar_w = x0 + label_w, x1 - x0 - label_w - total_w
    scale = bar_w / max(scenario_total(s)[1] for s in data["scenarios"])
    for s in data["scenarios"]:
        scene.text(f'{s["n"]} · {s["name"]}', x0, y, label_w - 8, 12.5, WHITE)
        x = bar_x
        for item in layers:
            minutes_high = s["times"][item["id"]]["max"] or 0
            width = minutes_high * scale
            if width <= 0:
                continue
            scene.rect(x, y + 2, max(width - 2, 1), 16, item["color"], radius=3)
            if width >= 28:
                scene.text(item["label"], x + (width - 2) / 2, y + 3, width, 10.5, BG, True, anchor="middle")
            x += width
        low, high = scenario_total(s)
        scene.text(f"{low:g}-{high:g} min", x + 8, y + 1, total_w + 40, 12, MUTED, True)
        y += 27
    x = x0
    for item in layers:
        scene.rect(x, y + 6, 12, 12, item["color"], radius=3)
        label = "Consumer" if item["id"] == "consumer" else f'{item["label"]} {item["name"].split(" ")[0]}'
        scene.text(label, x + 18, y + 3, 110, 11.5, MUTED)
        x += 18 + text_width(label, 11.5) + 18


# ---------------------------------------------------------------- poster

def header(scene: Scene, data) -> float:
    y = scene.text(data["title"], M, 26, DW, 32, WHITE, True)
    return scene.text(data["summary"], M, y + 10, DW, 19, MUTED) + 22


def poster(data) -> tuple[str, int]:
    scene = Scene("poster-header")
    y = header(scene, data)
    diagram, bottom, _ = draw_diagram(data)
    scene.add(f'<g transform="translate({M} {num(y)})">{diagram.body()}</g>')
    height = math.ceil(y + bottom + 24)
    note = "Measured and estimated times per layer: documentation/v2/10-19/10-factory-onion-architecture.md"
    scene.text(note, M, height - 12, DW, 12, MUTED)
    height += 16
    return document(scene.body(), height, data["title"], data["summary"]), height


# ---------------------------------------------------------------- animation

def minutes(total: float) -> str:
    return f"{total / 60:.1f} h" if total >= 90 else f"{total:g} min"


def span(low: float, high: float) -> str:
    if high >= 90:
        return f"{low / 60:.1f}-{high / 60:.1f} h"
    return f"{low:g}-{high:g} min"


def scenario_total(scenario) -> tuple[float, float]:
    times = scenario["times"].values()
    return sum(t["min"] for t in times), sum(t["max"] for t in times)


def totals_sentence(data) -> str:
    parts = [f'{s["name"]} {span(*scenario_total(s))}' for s in data["scenarios"]]
    return "Estimated wall-clock time: " + ", ".join(parts)


def visibility(start, end, total, first=False) -> str:
    points = [(0, "visible" if first else "hidden")]
    if start:
        points.append((start / total, "visible"))
    if end < total:
        points.append((end / total, "hidden"))
    points.append((1, points[-1][1]))
    return (f'<animate attributeName="visibility" dur="{num(total)}s" repeatCount="indefinite" calcMode="discrete" '
            f'keyTimes="{";".join(num(t) for t, _ in points)}" values="{";".join(v for _, v in points)}"/>')


def timed(start, end, total, low, high) -> tuple[str, str]:
    points = [(0, low)] + ([(start / total, low)] if start else []) + [(end / total, high)] + ([(1, high)] if end < total else [])
    return ";".join(num(t) for t, _ in points), ";".join(num(v) for _, v in points)


def signal(points, color, start, end, total) -> str:
    ox, oy = points[0]
    rel = "M" + " L".join(f"{num(x - ox)},{num(y - oy)}" for x, y in points)
    times, values = timed(start, end, total, 0, 1)
    return (f'<g transform="translate({num(ox)} {num(oy)})"><g><animateMotion path="{rel}" dur="{num(total)}s" '
            f'repeatCount="indefinite" keyTimes="{times}" keyPoints="{values}" calcMode="linear"/>'
            f'<circle r="10" fill="{BG}" stroke="{color}" stroke-width="2"/><circle r="5" fill="{color}"/>'
            '<circle r="2" fill="#FFFFFF"/></g></g>')


def centiseconds(seconds: float) -> int:
    return int(math.floor(seconds * 100 + .5))


def partition(start: int, end: int):
    count = max(1, int(math.floor((end - start) / 5 + .5)))
    for i in range(count):
        at = start + int(math.floor((end - start) * i / count + .5))
        nxt = start + int(math.floor((end - start) * (i + 1) / count + .5))
        yield at, nxt - at


def timeline(steps, speed, hold) -> list[dict]:
    """Same sampling as VisualLessonExportTimeline.Create: ~20 fps, cumulative centisecond rounding, end hold."""
    frames, source = [], 0.0
    for index, step in enumerate(steps):
        start, end = centiseconds(source / speed), centiseconds((source + step["seconds"]) / speed)
        for at, delay in partition(start, end):
            frames.append({"start": at, "delay": delay, "step": index, "progress": (at - start) / (end - start), "hold": False})
        source += step["seconds"]
    if hold:
        frames.append({"start": centiseconds(source / speed), "delay": centiseconds(hold), "step": len(steps) - 1, "progress": 1, "hold": True})
    return frames


def animation(data, frames_dir: Path | None):
    info = data["animation"]
    steps, speed = info["steps"], info["speed"]
    by_id = nodes(data)
    prepared, text_bottoms = [], []
    for index, step in enumerate(steps):
        scene = Scene(f"step-{step['id']}")
        y = header(scene, data)
        y = scene.text(f'{step["chapter"]}  ·  STEP {index + 1} / {len(steps)}', M, y, DW, 15, ACCENT, True)
        y = scene.text(step["title"], M, y + 10, DW, 27, WHITE, True)
        y = scene.text(step["explanation"].replace("{totals}", totals_sentence(data)), M, y + 14, DW, 20)
        y += 16
        key_height = len(wrap(step["key"], DW - 36, 17, True)) * 24 + 32
        scene.rect(M, y, DW, key_height, SURFACE, GRID)
        scene.text(step["key"], M + 18, y + 14, DW - 36, 17, KEY, True, 24)
        text_bottoms.append(y + key_height + 18)
        prepared.append(scene)
    fixed_y = max(text_bottoms)  # stable diagram position across steps
    stages, bottom_max = [], 0.0
    for index, (scene, step) in enumerate(zip(prepared, steps)):
        diagram, bottom, routes = draw_diagram(data, step["active"], step["links"], f"step-{step['id']}", step.get("chart", False))
        scene.add(f'<g transform="translate({M} {num(fixed_y)})">{diagram.body()}</g>')
        y = fixed_y + bottom + 4
        for number, info_route in enumerate(routes, 1):
            a, b = by_id[info_route["from"]], by_id[info_route["to"]]
            name = lambda n: n["label"] + (" " + n["name"] if n["id"] != "consumer" else "")
            y = scene.text(f'{number} · {name(a)} > {name(b)}: {info_route["label"]}', M + 12, y + 6, DW - 24, 15,
                           info_route["color"], True)
        for info_route in routes:
            info_route["points"] = [(M + x, fixed_y + py) for x, py in info_route["points"]]
        stages.append({"scene": scene, "routes": routes})
        bottom_max = max(bottom_max, y)
    progress_y = math.ceil(bottom_max + 22)
    height = progress_y + 25
    track = f'<rect x="{M}" y="{progress_y}" width="{DW}" height="5" rx="2" fill="{GRID}"/>'
    total = sum(s["seconds"] for s in steps) / speed + info["end_hold_seconds"]
    groups, start, jobs = [], 0.0, []
    for index, (stage, step) in enumerate(zip(stages, steps)):
        end = start + step["seconds"] / speed
        body = stage["scene"].body() + track
        if frames_dir:
            frames_dir.mkdir(parents=True, exist_ok=True)
            background = frames_dir / f"step-{index:02}.svg"
            background.write_text(document(body, height, data["title"], step["explanation"]), encoding="utf-8")
            jobs.append({"svg": str(background), "png": str(background.with_suffix(".png"))})
        times, widths = timed(start, end, total, 0, DW)
        body += (f'<rect x="{M}" y="{progress_y}" width="{DW if index == 0 else 0}" height="5" rx="2" fill="{ACCENT}">'
                 f'<animate attributeName="width" dur="{num(total)}s" repeatCount="indefinite" keyTimes="{times}" values="{widths}"/></rect>')
        body += "".join(signal(r["points"], r["color"], start, end, total) for r in stage["routes"])
        until = total if index == len(steps) - 1 else end
        groups.append(f'<g id="step-{esc(step["id"])}" visibility="{"visible" if index == 0 else "hidden"}">'
                      + visibility(start, until, total, index == 0) + body + "</g>")
        start = end
    svg = document("".join(groups), height, data["title"],
                   data["summary"] + " Illustrative animation; times are measured where marked, otherwise estimated.")
    if frames_dir:
        plan = {"width": W, "height": height, "progress_y": progress_y, "progress_x": M, "progress_w": DW,
                "speed": speed, "end_hold_seconds": info["end_hold_seconds"],
                "steps": [{"id": s["id"], "routes": [{"points": r["points"], "color": r["color"]} for r in stage["routes"]]}
                          for s, stage in zip(steps, stages)],
                "frames": timeline(steps, speed, info["end_hold_seconds"]), "jobs": jobs}
        (frames_dir / "timeline.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    return svg, height, total


# ---------------------------------------------------------------- markdown tables

KIND = {"measured": "M", "estimated": "E", "mixed": "M+E", "n/a": ""}


def cell(t) -> str:
    if t["min"] is None:
        return "n/a"
    value = "seconds" if t["max"] == 0 else (f'{t["min"]}' if t["min"] == t["max"] else f'{t["min"]}-{t["max"]}')
    return f'{value} {KIND[t["kind"]]}'.strip()


def tables(data) -> dict[str, str]:
    layers = [data["consumer"]] + data["layers"]
    head = lambda item: "Consumer" if item["id"] == "consumer" else f'{item["label"]} {item["name"]}'
    out = {}
    rows = ["| Layer | What it is | Repository and paths | Called by | Calls |", "|---|---|---|---|---|"]
    for item in layers:
        rows.append(f'| **{head(item)}** | {item["what"]} | {item["where"]} | {item["called_by"]} | {item["calls"]} |')
    out["layers"] = "\n".join(rows)
    for layer in data["layers"]:
        if layer.get("scripts"):
            rows = ["| Script | Language | Called by | Does |", "|---|---|---|---|"]
            rows += [f'| `{s["name"]}` | {s["lang"]} | {s["by"]} | {s["does"]} |' for s in layer["scripts"]]
            out[f'scripts-{layer["id"]}'] = "\n".join(rows)
    rows = ["| Scenario | SDK call | " + " | ".join(head(i) for i in layers) + " | Total |", "|---" * (len(layers) + 3) + "|"]
    for s in data["scenarios"]:
        low, high = scenario_total(s)
        rows.append(f'| {s["n"]}. {s["name"]} | `{s["sdk"]}` | ' + " | ".join(cell(s["times"][i["id"]]) for i in layers)
                    + f" | **{low:g}-{high:g}**" + (f" ({span(low, high)})" if high >= 90 else "") + " |")
    out["scenario-times"] = "\n".join(rows)
    rows = ["| Scenario | Layer | Minutes | Basis |", "|---|---|---|---|"]
    for s in data["scenarios"]:
        for item in layers:
            t = s["times"][item["id"]]
            if t.get("note") or t.get("evidence"):
                basis = ", ".join(filter(None, [t.get("note"), t.get("evidence") and "evidence " + t["evidence"]]))
                rows.append(f'| {s["n"]} | {head(item)} | {cell(t)} | {basis} |')
    out["scenario-notes"] = "\n".join(rows)
    rows = ["| Layer | Time for a code change (min) | What the loop contains |", "|---|---|---|"]
    rows += [f'| **{head(i)}** | {cell(i["change"])} | {i["change"]["note"]} |' for i in layers]
    out["change-times"] = "\n".join(rows)
    fix = data["fix_iteration"]["steps"]
    now, future = sum(s["now"] for s in fix), sum(s["future"] for s in fix)
    rows = ["| # | Step | Now (min) | % | Future (min, estimated) | How |", "|---|---|---|---|---|---|"]
    rows += [f'| {s["n"]} | {s["step"]} | {s["now"]} | {round(100 * s["now"] / now)}% | {s["future"]} | {s["how"]} |' for s in fix]
    rows.append(f"| | **Total** | **{now}** | 100% | **{future}** ({round(100 * (future - now) / now)}%) | |")
    out["fix-iteration"] = "\n".join(rows)
    loops = data["prevention"]["loops_minutes"]
    out["loops"] = " + ".join(f"{v} {k}" for k, v in loops.items()) + f" = **{sum(loops.values())} min**"
    out["fifth-bug"] = data["prevention"]["fifth_bug"]
    out["evidence"] = "\n".join(f"- **{key}**: {text}" for key, text in data["evidence"].items())
    return out


def update_doc(path: Path, data) -> None:
    text = path.read_text(encoding="utf-8")
    for name, table in tables(data).items():
        pattern = re.compile(rf"(<!-- onion:{name}:start -->\n).*?(<!-- onion:{name}:end -->)", re.S)
        if not pattern.search(text):
            raise SystemExit(f"Marker onion:{name} missing in {path}")
        text = pattern.sub(lambda m: m.group(1) + table + "\n" + m.group(2), text)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--update-doc", action="store_true", help="rewrite the generated tables in the markdown page")
    parser.add_argument("--frames", type=Path, help="write per-step scenes and timeline.json for make_onion_raster.py")
    args = parser.parse_args()
    data = json.loads(args.data.read_text(encoding="utf-8"))
    out = {key: (args.data.parent / value).resolve() for key, value in data["outputs"].items()}
    svg, height = poster(data)
    out["poster_svg"].write_text(svg, encoding="utf-8")
    animated, animated_height, seconds = animation(data, args.frames)
    out["animated_svg"].write_text(animated, encoding="utf-8")
    if args.frames:
        (args.frames / "text-checks.json").write_text(json.dumps(TEXT_CHECKS, indent=1, ensure_ascii=False), encoding="utf-8")
    if args.update_doc:
        update_doc(out["doc"], data)
    print(f'poster {W}x{height} -> {out["poster_svg"].name}; animation {W}x{animated_height}, '
          f'{len(data["animation"]["steps"])} steps, {seconds:.2f}s -> {out["animated_svg"].name}'
          + ("; doc tables updated" if args.update_doc else ""))


if __name__ == "__main__":
    main()
