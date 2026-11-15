import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from obs_capture import crop_frame
from PIL import Image


class CropTests(unittest.TestCase):
    def test_crop(self):
        img = Image.new('RGB', (1920,1080))
        cropped = crop_frame(img, 0, 65, 100, 95)
        self.assertEqual(cropped.size, (1920, 324))

    def test_invalid_bounds(self):
        img = Image.new('RGB', (100,100))
        with self.assertRaises(ValueError):
            crop_frame(img, 80, 10, 20, 90)


if __name__ == '__main__':
    unittest.main()
