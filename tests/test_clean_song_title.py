import sys
import unittest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from main import clean_song_title


class TestCleanSongTitle(unittest.TestCase):
    def test_prod_variations_brackets(self):
        cases = [
            ("Song Name (Prod. by TRILOGY)", "Song Name"),
            ("Song Name (prod by TRILOGY)", "Song Name"),
            ("Song Name [PROD. BY TRILOGY]", "Song Name"),
            ("Song Name [prod. by TRILOGY]", "Song Name"),
            ("Song Name (Produced by TRILOGY)", "Song Name"),
            ("Song Name 【Prod. TRILOGY】", "Song Name"),
            ("Song Name {prod. TRILOGY}", "Song Name"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(clean_song_title(raw), expected)

    def test_prod_variations_delimiters(self):
        cases = [
            ("Song Name - Prod. by TRILOGY", "Song Name"),
            ("Song Name - prod by TRILOGY", "Song Name"),
            ("Song Name | PRODUCED BY TRILOGY", "Song Name"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(clean_song_title(raw), expected)

    def test_mv_variations(self):
        cases = [
            ("Song Name [ MV]", "Song Name"),
            ("Song Name [MV]", "Song Name"),
            ("Song Name [ MV ]", "Song Name"),
            ("Song Name [M/V]", "Song Name"),
            ("Song Name [ M/V ]", "Song Name"),
            ("Song Name (MV)", "Song Name"),
            ("Song Name ( MV )", "Song Name"),
            ("Song Name 【 MV 】", "Song Name"),
            ("Song Name [Official MV]", "Song Name"),
            ("Song Name [ Official M/V ]", "Song Name"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(clean_song_title(raw), expected)

    def test_combined_prod_and_mv(self):
        cases = [
            ("Song Name (Prod. by TRILOGY) [ MV]", "Song Name"),
            ("Song Name [Official MV] (prod by TRILOGY)", "Song Name"),
            ("Artist - Song Name (Prod. by TRILOGY) [MV]", "Artist - Song Name"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(clean_song_title(raw), expected)

    def test_preserves_legitimate_words_starting_with_prod(self):
        cases = [
            ("Product of Love [ MV]", "Product of Love"),
            ("Prodigy - Firestarter", "Prodigy - Firestarter"),
            ("Production Line", "Production Line"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(clean_song_title(raw), expected)


if __name__ == "__main__":
    unittest.main()
