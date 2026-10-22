import importlib.util
from pathlib import Path
import re
import struct
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[4]
CONVERTER = ROOT / "documentation" / "gh-io" / "tools" / "svg_to_gif.py"
spec = importlib.util.spec_from_file_location("svg_to_gif", CONVERTER)
converter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(converter)

ANIMATED = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">
  <rect width="200" height="100" fill="#ffffff"/>
  <rect y="40" height="20" fill="#0078d4" width="0">
    <animate attributeName="width" dur="2s" repeatCount="indefinite" values="0;200"/>
  </rect>
</svg>"""


class LoopTimingTests(unittest.TestCase):
    def test_loop_is_the_shared_indefinite_duration(self):
        self.assertEqual(converter.loop_seconds(ANIMATED), 2.0)

    def test_millisecond_and_clock_durations_are_parsed(self):
        svg = ('<svg><animate dur="1500ms" repeatCount="indefinite"/>'
               '<set dur="00:00:01.5" repeatCount="indefinite"/></svg>')
        self.assertEqual(converter.loop_seconds(svg), 1.5)

    def test_static_svg_has_no_loop(self):
        self.assertIsNone(converter.loop_seconds('<svg viewBox="0 0 10 10"><rect/></svg>'))

    def test_css_keyframes_are_rejected_rather_than_rendered_static(self):
        with self.assertRaises(ValueError):
            converter.loop_seconds("<svg><style>@keyframes spin { to { opacity: 0 } }</style></svg>")

    def test_conflicting_loop_durations_are_rejected(self):
        svg = ('<svg><animate dur="2s" repeatCount="indefinite"/>'
               '<animate dur="3s" repeatCount="indefinite"/></svg>')
        with self.assertRaises(ValueError):
            converter.loop_seconds(svg)

    def test_frames_cover_exactly_one_loop_without_repeating_the_first_frame(self):
        times = converter.frame_times(2.0, 10)
        self.assertEqual(len(times), 20)
        self.assertEqual(times[0], 0.0)
        self.assertAlmostEqual(times[-1], 1.9)

    def test_static_svg_renders_one_frame(self):
        self.assertEqual(converter.frame_times(None, 10), [0.0])

    def test_frame_rate_must_map_to_whole_gif_centiseconds(self):
        self.assertEqual(converter.gif_delay_cs(12.5), 8)
        self.assertEqual(converter.gif_delay_cs(10), 10)
        with self.assertRaises(ValueError):
            converter.gif_delay_cs(12)


class GeometryTests(unittest.TestCase):
    def test_height_follows_the_viewbox_aspect_ratio_and_is_even(self):
        self.assertEqual(converter.output_size(ANIMATED, 320), (320, 160))
        self.assertEqual(converter.output_size('<svg viewBox="0 0 1400 940"/>', 720), (720, 484))

    def test_svg_without_viewbox_is_rejected(self):
        with self.assertRaises(ValueError):
            converter.output_size("<svg/>", 320)


class WatermarkTests(unittest.TestCase):
    def test_watermark_is_a_faint_centered_plaque_drawn_last(self):
        marked = converter.add_watermark(ANIMATED, "Enterprise Scale AI Factory (ESAIF)")
        self.assertEqual(marked.count("Enterprise Scale AI Factory (ESAIF)"), 1)
        self.assertTrue(marked.rstrip().endswith("</g></svg>"))
        plaque = marked[marked.index(f'<g id="{converter.WATERMARK_ID}"'):]
        text = plaque[plaque.index("<text"):]
        self.assertIn('x="100"', text)
        self.assertIn('y="50"', text)
        self.assertIn('text-anchor="middle"', text)
        self.assertIn('dominant-baseline="middle"', text)
        self.assertLessEqual(float(re.search(r'opacity="([\d.]+)"', text).group(1)), 0.2)
        font_size = float(re.search(r'font-size="([\d.]+)"', text).group(1))
        self.assertLessEqual(font_size, 200 * 0.015, "small relative to the drawing")
        rect = re.search(r"<rect\b[^>]*>", plaque).group(0)
        self.assertRegex(rect, r'\brx="[\d.]+"')
        self.assertLessEqual(float(re.search(r'fill-opacity="([\d.]+)"', rect).group(1)), 0.06)
        self.assertLessEqual(float(re.search(r'stroke-opacity="([\d.]+)"', rect).group(1)), 0.2)
        rect_x, rect_width = (float(re.search(rf'\b{name}="([-\d.]+)"', rect).group(1)) for name in ("x", "width"))
        self.assertAlmostEqual(rect_x + rect_width / 2, 100, msg="the border is centred on the text")

    def test_plaque_is_light_so_it_melts_into_dark_diagrams(self):
        marked = converter.add_watermark(ANIMATED, "ESAIF")
        self.assertNotIn('#000', marked[marked.index(f'<g id="{converter.WATERMARK_ID}"'):])
        self.assertIn('fill="#fff"', marked)

    def test_watermark_follows_a_viewbox_origin_escapes_markup_and_can_move_vertically(self):
        marked = converter.add_watermark('<svg viewBox="-100 20 400 200"></svg>', "R&D <lab>", y_fraction=0.6)
        self.assertIn('x="100"', marked)
        self.assertIn('y="140"', marked)
        self.assertIn("R&amp;D &lt;lab&gt;", marked)

    def test_empty_watermark_leaves_the_svg_unchanged(self):
        self.assertEqual(converter.add_watermark(ANIMATED, ""), ANIMATED)


class EncoderTests(unittest.TestCase):
    def test_ffmpeg_command_builds_a_looping_diff_palette_gif(self):
        command = converter.ffmpeg_command(Path("frames"), 12.5, Path("out.gif"), colors=96)
        joined = " ".join(command)
        self.assertIn("-framerate 12.5", joined)
        self.assertIn("palettegen=max_colors=96:stats_mode=diff", joined)
        self.assertIn("diff_mode=rectangle", joined)
        self.assertEqual(command[-3:], ["-loop", "0", "out.gif"])

    def test_gifsicle_command_is_optimized_and_lossy(self):
        self.assertEqual(converter.gifsicle_command(Path("a.gif"), lossy=30),
                         ["gifsicle", "-O3", "--lossy=30", "--batch", "a.gif"])


def _write_gif(path, frames, delay_ms, size=(40, 20)):
    """Minimal GIF89a: a 2-colour global palette, a NETSCAPE loop and 1x1 frames on a WxH screen."""
    data = bytearray(b"GIF89a" + struct.pack("<HHBBB", *size, 0x80, 0, 0) + b"\xff\xff\xff\x00\x00\x00")
    data += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    for _ in range(frames):
        data += b"\x21\xf9\x04\x00" + struct.pack("<H", delay_ms // 10) + b"\x00\x00"
        data += b"\x2c" + struct.pack("<HHHHB", 0, 0, 1, 1, 0) + b"\x02\x02\x44\x01\x00"
    path.write_bytes(bytes(data + b"\x3b"))


def _write_frame(path):
    path.write_bytes(b"\x89PNG placeholder frame")


class ConvertPipelineTests(unittest.TestCase):
    def test_one_loop_of_frames_is_rendered_encoded_and_reported(self):
        rendered, encoded = {}, {}

        def render(svg_text, size, times, frames_dir):
            rendered.update(size=size, times=list(times))
            for index, _ in enumerate(times):
                _write_frame(frames_dir / f"frame_{index:05d}.png")

        def encode(frames_dir, fps, output, colors):
            encoded.update(fps=fps, colors=colors, frames=len(list(frames_dir.glob("*.png"))))
            _write_gif(output, encoded["frames"], converter.gif_delay_cs(fps) * 10)

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "bar.svg"
            source.write_text(ANIMATED, encoding="utf-8")
            output = Path(temporary) / "out" / "bar.gif"
            report = converter.convert(source, output, width=100, fps=10, colors=32, lossy=None,
                                       render=render, encode=encode)
            self.assertTrue(output.is_file())
        self.assertEqual(rendered["size"], (100, 50))
        self.assertEqual(len(rendered["times"]), 20)
        self.assertEqual(encoded, {"fps": 10, "colors": 32, "frames": 20})
        self.assertEqual(report["frames"], 20)
        self.assertEqual(report["loop_seconds"], 2.0)
        self.assertGreater(report["bytes"], 0)

    def test_budget_overrun_is_reported_not_hidden(self):
        def render(svg_text, size, times, frames_dir):
            _write_frame(frames_dir / "frame_00000.png")

        def encode(frames_dir, fps, output, colors):
            output.write_bytes(b"G" * 4096)

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "bar.svg"
            source.write_text(ANIMATED, encoding="utf-8")
            report = converter.convert(source, Path(temporary) / "bar.gif", width=100, fps=10,
                                       colors=32, lossy=None, max_kb=1, render=render, encode=encode)
        self.assertFalse(report["within_budget"])

    def test_watermark_is_rendered_into_every_frame(self):
        seen = {}

        def render(svg_text, size, times, frames_dir):
            seen["svg"] = svg_text
            _write_frame(frames_dir / "frame_00000.png")

        def encode(frames_dir, fps, output, colors):
            _write_gif(output, 1, 100)

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "bar.svg"
            source.write_text(ANIMATED, encoding="utf-8")
            report = converter.convert(source, Path(temporary) / "bar.gif", width=100, fps=10, colors=32,
                                       lossy=None, watermark="ESAIF", render=render, encode=encode)
        self.assertIn(">ESAIF</text>", seen["svg"])
        self.assertEqual(report["watermark"], "ESAIF")


class InspectTests(unittest.TestCase):
    def test_inspect_reports_size_frames_total_duration_and_loop(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "a.gif"
            _write_gif(path, 4, 100)
            info = converter.inspect_gif(path)
        self.assertEqual((info["width"], info["height"]), (40, 20))
        self.assertEqual(info["frames"], 4)
        self.assertEqual(info["duration_ms"], 400)
        self.assertEqual(info["loop"], 0)


if __name__ == "__main__":
    unittest.main()
