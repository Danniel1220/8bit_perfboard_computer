from pathlib import Path
import tempfile
import unittest
from perfopt.snapshots import save_svg_snapshot


class SnapshotTests(unittest.TestCase):
    def test_interval_manual_save_and_retention(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'exports').mkdir();source=root/'exports/best.svg'
            source.write_text('<svg>first</svg>')
            self.assertIsNone(save_svg_snapshot(root,4,8,new_best=True))
            first=save_svg_snapshot(root,5,8,new_best=True,retention=2)
            self.assertEqual(first.read_bytes(),source.read_bytes())
            self.assertIn('8-unresolved',first.name)
            self.assertIsNone(save_svg_snapshot(root,5,8))
            source.write_text('<svg>second</svg>')
            manual=save_svg_snapshot(root,6,7,force=True,retention=2)
            self.assertEqual(first.read_text(),'<svg>first</svg>')
            self.assertEqual(manual.read_bytes(),source.read_bytes())
            save_svg_snapshot(root,10,6,new_best=True,retention=2)
            self.assertFalse(first.exists())
            self.assertEqual(len(list((root/'exports/snapshots').glob('*.svg'))),2)
            self.assertFalse(list((root/'exports/snapshots').glob('*.tmp')))

    def test_custom_interval_and_invalid_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'exports').mkdir();(root/'exports/best.svg').write_text('<svg/>')
            self.assertTrue(save_svg_snapshot(root,2,8,new_best=True,every=2).exists())
            with self.assertRaises(ValueError):save_svg_snapshot(root,2,8,every=0)
