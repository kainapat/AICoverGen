import sys
import unittest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from main import clean_song_title, extract_song_and_artist


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



class TestExtractSongAndArtist(unittest.TestCase):
    def test_youtube_video_with_prod_by_and_official_mv(self):
        # Test exact metadata from YouTube video: 2OZktFecG_g
        info = {
            "title": "ZENTYARB - ฉบับท้ายสุด (Prod. by TRILOGY) [Official MV]",
            "uploader": "ZENTYARB",
            "channel": "ZENTYARB",
        }
        self.assertEqual(extract_song_and_artist(info), "ZENTYARB - ฉบับท้ายสุด")

    def test_youtube_video_with_song_by_artist(self):
        info = {
            "title": "《 เพลงรัก 》 by Liz's x NATNON",
            "uploader": "Liz's x NATNON",
            "channel": "Liz's x NATNON",
        }
        self.assertEqual(extract_song_and_artist(info), "Liz's x NATNON - เพลงรัก")

    def test_youtube_video_inversion_and_cleaning(self):
        info = {
            "title": "โฆษณาชวนเลือก - TaitosmitH |Official Lyrics Video|",
            "uploader": "TaitosmitH Official",
            "channel": "TaitosmitH Official",
        }
        self.assertEqual(extract_song_and_artist(info), "TaitosmitH - โฆษณาชวนเลือก")

    def test_youtube_video_with_cjk_and_prod(self):
        info = {
            "title": "Takaaki Natsushiro - 藍より群青 feat. Suisei Hoshimachi (Prod. by TRILOGY) [ MV]",
            "uploader": "Takaaki Natsushiro",
            "channel": "Takaaki Natsushiro",
        }
        self.assertEqual(
            extract_song_and_artist(info),
            "Takaaki Natsushiro - 藍より群青 (Ai Yori Gunjou) Feat. Suisei Hoshimachi",
        )

if __name__ == "__main__":
    unittest.main()
