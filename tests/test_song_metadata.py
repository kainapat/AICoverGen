import sys
import unittest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from song_metadata import SongMetadata, SongMetadataNormalizer


class TestSongMetadataModule(unittest.TestCase):
    def test_from_input_with_plain_string(self):
        meta = SongMetadata.from_input("Song Name [Official MV]")
        self.assertEqual(meta.title, "Song Name")
        self.assertIsNone(meta.artist)
        self.assertEqual(meta.formatted_title, "Song Name")

    def test_from_input_with_empty_or_none(self):
        meta_none = SongMetadata.from_input(None)
        self.assertEqual(meta_none.formatted_title, "song")
        meta_empty = SongMetadata.from_input("")
        self.assertEqual(meta_empty.formatted_title, "song")

    def test_from_input_with_ytdlp_metadata(self):
        info = {
            "title": "ZENTYARB - ฉบับท้ายสุด (Prod. by TRILOGY) [Official MV]",
            "uploader": "ZENTYARB",
            "channel": "ZENTYARB",
        }
        meta = SongMetadata.from_input(info)
        self.assertEqual(meta.artist, "ZENTYARB")
        self.assertEqual(meta.title, "ฉบับท้ายสุด")
        self.assertEqual(meta.formatted_title, "ZENTYARB - ฉบับท้ายสุด")

    def test_from_input_with_featured_artist_and_cjk(self):
        info = {
            "title": "Takaaki Natsushiro - 藍より群青 feat. Suisei Hoshimachi (Prod. by TRILOGY) [ MV]",
            "uploader": "Takaaki Natsushiro",
        }
        meta = SongMetadata.from_input(info)
        self.assertEqual(meta.artist, "Takaaki Natsushiro")
        self.assertEqual(meta.title, "藍より群青 (Ai Yori Gunjou)")
        self.assertEqual(meta.featured_artist, "Suisei Hoshimachi")
        self.assertEqual(
            meta.formatted_title,
            "Takaaki Natsushiro - 藍より群青 (Ai Yori Gunjou) Feat. Suisei Hoshimachi",
        )

    def test_from_input_with_smart_inversion(self):
        info = {
            "title": "โฆษณาชวนเลือก - TaitosmitH |Official Lyrics Video|",
            "uploader": "TaitosmitH Official",
        }
        meta = SongMetadata.from_input(info)
        self.assertEqual(meta.artist, "TaitosmitH")
        self.assertEqual(meta.title, "โฆษณาชวนเลือก")
        self.assertEqual(meta.formatted_title, "TaitosmitH - โฆษณาชวนเลือก")


if __name__ == "__main__":
    unittest.main()
