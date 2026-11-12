"""The edges of the motion core: a frame that is not the size it says, the mask of ignore rectangles (what is read, what is left out) and a mask of the wrong size."""
import unittest

from armor_vision.motion_core import analyze, check_frame, rect_mask


class FrameTests(unittest.TestCase):
    def test_a_frame_needs_a_positive_size_and_exactly_that_many_grey_bytes(self):
        for width, height in ((0, 4), (4, 0), (-1, 4)):
            with self.assertRaises(ValueError):
                check_frame(bytes(16), width, height)
        for frame in (bytes(15), bytes(17), "not bytes", None):
            with self.assertRaises(ValueError):
                check_frame(frame, 4, 4)  # type: ignore[arg-type]
        check_frame(bytes(16), 4, 4)
        check_frame(bytearray(16), 4, 4)

    def test_a_mask_of_the_wrong_size_is_refused(self):
        with self.assertRaises(ValueError):
            analyze(bytes(16), bytes(16), 4, 4, mask=bytes(15))


class MaskTests(unittest.TestCase):
    def test_nothing_to_ignore_is_no_mask(self):
        self.assertIsNone(rect_mask(None, 10, 10))
        self.assertIsNone(rect_mask([], 10, 10))

    def test_a_rectangle_as_a_tuple_or_a_dictionary_blanks_its_pixels_in_fractions_of_the_picture(self):
        mask = rect_mask([(0.0, 0.0, 0.5, 0.5)], 10, 10)
        assert mask is not None
        self.assertEqual(sum(1 for value in mask if value == 0), 25)
        self.assertEqual(mask[0], 0)
        self.assertEqual(mask[99], 1)
        same = rect_mask([{"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}], 10, 10)
        self.assertEqual(mask, same)

    def test_what_is_not_a_rectangle_inside_the_picture_is_left_out_and_only_sixteen_are_read(self):
        wrong = [{"x": 0.1}, "abc", (0.1, 0.1), (0.1, 0.1, "w", 0.2), (-0.1, 0, 0.5, 0.5), (0, 0, 0, 0.5), (0, 0, 0.5, 1.5), (1.5, 0, 0.2, 0.2), None]
        self.assertIsNone(rect_mask(wrong, 10, 10))
        valid = (0.0, 0.0, 0.5, 0.5)
        self.assertIsNone(rect_mask([(2, 2, 2, 2)] * 16 + [valid], 10, 10), "the seventeenth is not read")
        self.assertIsNotNone(rect_mask([(2, 2, 2, 2)] * 15 + [valid], 10, 10))

    def test_a_blanked_corner_does_not_count_as_movement(self):
        before, after = bytes(100), bytes(50) + bytes([255]) * 50
        plain = analyze(before, after, 10, 10)
        masked = analyze(before, after, 10, 10, mask=rect_mask([(0.0, 0.5, 1.0, 0.5)], 10, 10))
        self.assertGreaterEqual(plain.ratio, masked.ratio)


if __name__ == "__main__":
    unittest.main()
