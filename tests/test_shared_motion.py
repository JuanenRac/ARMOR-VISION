"""The movement model is the one of ARMOR-COMMON, and the grid, masks and regions of the vision pipeline keep working on top of it."""
import os
import unittest
from pathlib import Path

from armor_vision import motion_core
from armor_vision.motion import Frame, analyze, moved_cells, region_rects, regions

ROOT = Path(__file__).resolve().parents[1]
COMMON = Path(os.environ.get("ARMOR_COMMON_DIR") or ROOT.parent / "ARMOR-COMMON")


def grey(value, width=64, height=36):
    return Frame(width, height, bytes([value]) * (width * height))


class SharedMotionTests(unittest.TestCase):
    def test_the_copy_is_the_original_of_the_shared_repository(self):
        original = COMMON / "src" / "armor_common" / "motion_core.py"
        if not original.is_file():
            self.skipTest("ARMOR-COMMON is not next to this repository")
        wanted = original.read_bytes().decode("utf-8").replace("\r\n", "\n")
        mine = (ROOT / "src" / "armor_vision" / "motion_core.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        self.assertEqual(mine, wanted, "copy src/armor_common/motion_core.py of ARMOR-COMMON here (python tools/sync_motion_core.py sync there)")

    def test_a_moved_patch_gives_cells_a_share_and_rectangles(self):
        pixels = bytearray(grey(0).pixels)
        for y in range(8, 20):
            pixels[y * 64 + 16:y * 64 + 32] = bytes([200]) * 16
        moved = Frame(64, 36, bytes(pixels))
        motion = analyze(grey(0), moved, 25)
        self.assertEqual(moved_cells(grey(0), moved, 25), set(motion.cells))
        self.assertAlmostEqual(motion.ratio, 16 * 12 / (64 * 36))
        self.assertEqual(regions(set(motion.cells)), [(0.25, 2 / 9, 0.5, 5 / 9)])
        self.assertEqual(region_rects(set(motion.cells)), [{"x": 0.25, "y": 0.2222, "w": 0.25, "h": 0.3333}])

    def test_the_light_of_the_whole_picture_is_not_movement(self):
        self.assertEqual(analyze(grey(20), grey(200), 25).ratio, 0.0)
        self.assertIsInstance(analyze(grey(20), grey(200), 25), motion_core.Motion)


if __name__ == "__main__":
    unittest.main()
