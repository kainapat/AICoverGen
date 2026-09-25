"""
SongMetadata Deep Module — AICoverGen
Encapsulates Unicode normalization, promotional noise removal, producer tag stripping,
CJK Romanization, featured artist extraction, and smart song-artist inversion.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

_kakasi = None


def _get_kakasi():
    """Lazy initializer for pykakasi converter."""
    global _kakasi
    if _kakasi is None:
        try:
            import pykakasi

            _kakasi = pykakasi.kakasi()
        except Exception:
            _kakasi = False
    return _kakasi or None


@dataclass(frozen=True)
class SongMetadata:
    """Canonical domain representation of song identity and formatted metadata."""

    title: str
    artist: Optional[str] = None
    featured_artist: Optional[str] = None
    raw_title: str = ""

    @property
    def formatted_title(self) -> str:
        """Returns the full human-readable title: '[Artist] - [Song] Feat. [Featured]' or '[Song]'."""
        if self.artist:
            if self.featured_artist:
                return f"{self.artist} - {self.title} Feat. {self.featured_artist}"
            return f"{self.artist} - {self.title}"
        if self.featured_artist:
            return f"{self.title} Feat. {self.featured_artist}"
        return self.title

    @classmethod
    def from_input(
        cls,
        info_or_title: Union[str, Dict[str, Any]],
        channel_fallback: Optional[str] = None,
    ) -> SongMetadata:
        """Deep seam interface: accepts raw video title string or yt-dlp metadata dictionary.

        Returns a validated, clean, normalized SongMetadata instance.
        """
        if not info_or_title:
            return cls(title="song", raw_title="")

        if isinstance(info_or_title, str):
            clean = SongMetadataNormalizer.clean_title(info_or_title)
            return cls(title=clean or "song", raw_title=info_or_title)

        if isinstance(info_or_title, dict):
            return SongMetadataNormalizer.extract_from_ytdlp(info_or_title, channel_fallback)

        clean = SongMetadataNormalizer.clean_title(str(info_or_title))
        return cls(title=clean or "song", raw_title=str(info_or_title))


class SongMetadataNormalizer:
    """Private implementation encapsulated behind SongMetadata."""

    @staticmethod
    def sanitize_filename(name: str, max_len: int = 150) -> str:
        """Sanitize string for Windows filesystem safety while preserving Thai/CJK Unicode."""
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", str(name))
        name = re.sub(r"\s+", " ", name).strip().rstrip(".")
        if len(name) > max_len:
            name = name[:max_len].rstrip()
        return name or "song"

    @classmethod
    def clean_title(cls, raw_title: str) -> str:
        """Strip promo tags, brackets, producer credits, and video labels."""
        if not raw_title:
            return "song"
        cleaned = unicodedata.normalize("NFKC", str(raw_title))
        noise_patterns = [
            r"\[\s*(?:official\s*)?(?:music\s*)?(?:video|audio|m/?v|lyrics?\s*video|visualizer|hd|4k|hq)\s*\]",
            r"\(\s*(?:official\s*)?(?:music\s*)?(?:video|audio|m/?v|lyrics?\s*video|visualizer|hd|4k|hq)\s*\)",
            r"【\s*(?:official\s*)?(?:music\s*)?(?:video|audio|m/?v|lyrics?\s*video|visualizer|hd|4k|hq)\s*】",
            r"[\(\[\{【]\s*(?:prod\.?|produced)\s*(?:by)?\s*[^)\]\}】]+[\)\]\}】]",
            r"[\s\-_|/]+(?:prod\.?|produced)\s+by\s+[^\-_|/]+",
            r"\|\s*[^|]*(?:official|music|video|audio|m/?v|lyrics?|visualizer)[^|]*\|?",
            r"//\s*(?:official\s*)?(?:music\s*)?(?:video|audio|m/?v|lyrics?\s*video|visualizer|hd|4k|hq).*$",
            r"\b(?:official\s+)?(?:music\s+)?(?:lyrics?\s+video|visualizer)\b.*$",
            r"\b(?:4K|HD|HQ|1080p|720p)\b",
        ]
        for pat in noise_patterns:
            cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(r"^[《【\[(]\s*", "", cleaned)
        cleaned = re.sub(r"\s*[》】\])]$", "", cleaned)
        cleaned = re.sub(r"[\s\-_|/]+$", "", cleaned)
        cleaned = re.sub(r"^[\s\-_|/]+", "", cleaned)
        return cls.sanitize_filename(cleaned)

    @classmethod
    def clean_channel_name(cls, channel: Optional[str]) -> str:
        """Strip promotional and agency suffixes from artist/channel identities."""
        if not channel:
            return ""
        ch = unicodedata.normalize("NFKC", str(channel))
        ch = re.sub(r"\s*\|\s*.*$", "", ch)
        ch = re.sub(r"\s*-\s*Topic$", "", ch, flags=re.IGNORECASE)
        ch = re.sub(
            r"\b(?:official(?:\s*(?:channel|music|video|audio))?|vevo|topic|records)\b",
            "",
            ch,
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", ch).strip(" \t\n\r-_|/")

    @classmethod
    def romanize_cjk(cls, text: str) -> str:
        """Appends Title-Cased Romaji / Romaja for Japanese or Korean songs in parentheses."""
        if not text or not isinstance(text, str):
            return text or ""
        # 1. Japanese check
        if re.search(r"[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]", text):
            k = _get_kakasi()
            if k:
                conv = k.convert(text)
                hepburn = " ".join(item["hepburn"] for item in conv if item.get("hepburn")).strip()
                hepburn = re.sub(r"\s+", " ", hepburn).title()
                if hepburn and hepburn.lower() not in text.lower():
                    return f"{text} ({hepburn})"

        # 2. Korean check
        if re.search(r"[\uac00-\ud7a3]", text):
            try:
                import kroman

                romaja = kroman.parse(text).strip()
                romaja = re.sub(r"\s+", " ", romaja).title()
                if romaja and romaja.lower() not in text.lower():
                    return f"{text} ({romaja})"
            except Exception:
                pass

        return text

    @classmethod
    def parse_feat_clause(cls, text: str):
        """Extracts 'feat.', 'ft.', or 'featuring' clause from string."""
        if not text:
            return text, None
        feat_pattern = r"\s*[\(\[\{]?\s*(?:feat\.?|ft\.?|featuring)\s+([^\)\]\}]+)[\)\]\}]?"
        m = re.search(feat_pattern, text, re.IGNORECASE)
        if m:
            feat_artist = m.group(1).strip()
            clean_text = re.sub(feat_pattern, "", text, flags=re.IGNORECASE).strip()
            return clean_text, feat_artist
        return text, None

    @classmethod
    def resolve_feat_artist(cls, feat_raw: Optional[str], artists_list: Optional[List[str]] = None):
        """Resolve clean featured artist name with CJK romanization support."""
        if artists_list and len(artists_list) > 1:
            return ", ".join(artists_list[1:])
        if not feat_raw:
            return None
        if re.search(r"[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]", feat_raw):
            k = _get_kakasi()
            if k:
                conv = k.convert(feat_raw)
                rom = " ".join(item["hepburn"] for item in conv if item.get("hepburn")).strip().title()
                if rom:
                    return rom
        elif re.search(r"[\uac00-\ud7a3]", feat_raw):
            try:
                import kroman

                rom = kroman.parse(feat_raw).strip().title()
                if rom:
                    return rom
            except Exception:
                pass
        return feat_raw

    @classmethod
    def resolve_artist_name(
        cls,
        raw_artist: Optional[str],
        raw_channel: Optional[str],
        artists_list: Optional[List[str]] = None,
    ) -> str:
        """Resolve main artist name with CJK Romanization when no Latin representation exists."""
        if artists_list and len(artists_list) > 0:
            candidate = artists_list[0]
        else:
            candidate = raw_artist or raw_channel
        cleaned = cls.clean_channel_name(candidate)
        if cleaned and not re.search(r"[a-zA-Z]", cleaned):
            if re.search(r"[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]", cleaned):
                k = _get_kakasi()
                if k:
                    conv = k.convert(cleaned)
                    rom = " ".join(item["hepburn"] for item in conv if item.get("hepburn")).strip().title()
                    if rom:
                        return f"{cleaned} ({rom})"
            elif re.search(r"[\uac00-\ud7a3]", cleaned):
                try:
                    import kroman

                    rom = kroman.parse(cleaned).strip().title()
                    if rom:
                        return f"{cleaned} ({rom})"
                except Exception:
                    pass
        return cleaned

    @classmethod
    def extract_from_ytdlp(
        cls, info: Dict[str, Any], channel_fallback: Optional[str] = None
    ) -> SongMetadata:
        """Extract structured SongMetadata from yt-dlp metadata info dictionary."""
        raw_title = info.get("title") or info.get("fulltitle") or info.get("id") or "song"
        raw_track = info.get("track")
        raw_artist = info.get("artist")
        raw_channel = info.get("channel") or info.get("uploader") or channel_fallback
        artists_list = info.get("artists") or []

        # 1. Official YouTube Music track metadata
        if raw_track and raw_artist:
            base_track, feat_in_track = cls.parse_feat_clause(raw_track)
            clean_track = cls.clean_title(base_track)
            song_with_romaji = cls.romanize_cjk(clean_track)
            main_artist = cls.resolve_artist_name(raw_artist, raw_channel, artists_list)
            feat_artist = cls.resolve_feat_artist(feat_in_track, artists_list) if feat_in_track else None
            return SongMetadata(
                title=song_with_romaji,
                artist=main_artist,
                featured_artist=feat_artist,
                raw_title=str(raw_title),
            )

        title_norm = unicodedata.normalize("NFKC", str(raw_title))
        clean_title = cls.clean_title(title_norm)

        # 2. Check for 'Song by Artist' pattern (e.g. 《 เพลงรัก 》 by Liz's x NATNON)
        if " - " not in clean_title:
            by_match = re.match(
                r"^[《【\[(]?\s*(.*?)\s*[》】\])]?\s+(?:by|โดย)\s+(.+)$",
                clean_title,
                re.IGNORECASE,
            )
            if by_match:
                base_song, feat_in_song = cls.parse_feat_clause(by_match.group(1))
                song = cls.clean_title(base_song)
                song_with_romaji = cls.romanize_cjk(song)
                artist = cls.resolve_artist_name(by_match.group(2), raw_channel, artists_list)
                feat_artist = cls.resolve_feat_artist(feat_in_song, artists_list) if feat_in_song else None
                return SongMetadata(
                    title=song_with_romaji,
                    artist=artist,
                    featured_artist=feat_artist,
                    raw_title=str(raw_title),
                )

        # 3. If title already has ' - ' (Artist - Song or Song - Artist)
        if " - " in clean_title:
            part1, part2 = clean_title.split(" - ", 1)
            part1 = part1.strip()
            part2 = part2.strip()

            ch = cls.clean_channel_name(raw_artist or raw_channel)
            if ch and ch.lower() in part2.lower() and ch.lower() not in part1.lower():
                artist_raw = part2
                song_raw = part1
            else:
                artist_raw = part1
                song_raw = part2

            base_song, feat_in_song = cls.parse_feat_clause(song_raw)
            base_artist, feat_in_artist = cls.parse_feat_clause(artist_raw)
            feat_candidate = feat_in_song or feat_in_artist

            clean_song = cls.clean_title(base_song)
            song_with_romaji = cls.romanize_cjk(clean_song)
            main_artist = cls.resolve_artist_name(base_artist, raw_channel, artists_list)
            feat_artist = cls.resolve_feat_artist(feat_candidate, artists_list) if feat_candidate else None

            return SongMetadata(
                title=song_with_romaji,
                artist=main_artist,
                featured_artist=feat_artist,
                raw_title=str(raw_title),
            )

        # 4. Fallback to channel/artist if not already in title
        base_title, feat_in_title = cls.parse_feat_clause(clean_title)
        clean_title = cls.clean_title(base_title)
        song_with_romaji = cls.romanize_cjk(clean_title)
        artist_candidate = cls.resolve_artist_name(raw_artist, raw_channel, artists_list)
        feat_artist = cls.resolve_feat_artist(feat_in_title, artists_list) if feat_in_title else None

        if artist_candidate and artist_candidate.lower() not in song_with_romaji.lower():
            return SongMetadata(
                title=song_with_romaji,
                artist=artist_candidate,
                featured_artist=feat_artist,
                raw_title=str(raw_title),
            )

        return SongMetadata(
            title=song_with_romaji,
            artist=None,
            featured_artist=feat_artist,
            raw_title=str(raw_title),
        )
