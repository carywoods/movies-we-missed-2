"""TMDB catalog metadata client with an explicit, auditable title-matching ladder.

Inventory titles are shelf filenames like ``01 Police Academy - Comedy 1984``
or ``02 Die Hard 2 Die Harder - Bruce Willis Action``. A strict "normalized
title must be identical" rule rejects nearly all of them, and a sloppy
fuzzy rule happily attaches the wrong movie. This module therefore:

1. Generates up to three ordered query candidates per stored title
   (most-cleaned first: leading shelf index and trailing codec/category
   noise removed, then progressively rawer variants).
2. Scores every TMDB result against *all* candidate keys with a small,
   explicit relation ladder (exact / truncated / prefixed / weak /
   contained) tightened by the stored release year.
3. Accepts only matches at or above ``ACCEPT_CONFIDENCE``; everything else
   stays in operator review instead of guessing.

The confidence ladder (stored year vs TMDB release year):

====================  ======  =====  =======  =========
relation              same    ±1     no year  unknown
====================  ======  =====  =======  =========
exact                 1.00    0.90   0.85     0.80
truncated (≤2 chars)  0.85    0.80   0.78     —
prefixed (≤3 chars)   0.85    0.80   0.78*    —
weak (≤12 chars)      0.75    —      —        —
contained (≥8 chars)  0.75    —      —        —
====================  ======  =====  =======  =========

* prefixed with no stored year requires a remainder of at most one
character (e.g. ``Twilight1``). A year gap of two or more years rejects
the candidate outright.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
_TITLE_KEY_RE = re.compile(r"[^a-z0-9]+")

# Matches at or above this confidence are applied automatically; below it the
# row is left in operator review rather than guessed at.
ACCEPT_CONFIDENCE = 0.75

# Words that shelf filenames append after the actual title. Removed only from
# the end of a candidate and never from a single-word title.
_TRAILING_TOKENS = frozenset(
    {
        "hd", "sd", "4k", "uhd", "720p", "1080p", "2160p", "hdtv", "dvd", "dvdr",
        "dvdrip", "rip", "br", "brrip", "bdrip", "bluray", "webrip", "webdl", "web",
        "hdrip", "xvid", "divx", "x264", "x265", "h264", "h265", "hevc", "aac",
        "ac3", "dts", "mp3", "ddp", "remux", "10bit", "8bit", "hdr", "sdr",
        "repack", "proper", "remastered", "internal", "limited", "festival", "kino",
        "extended", "uncut", "unrated", "subbed", "dubbed", "subs", "eng", "english",
        "edition", "special", "anniversary", "complete", "version",
    }
)

# Category words frequently appended by the inventory tooling. A trailing token
# that is a slightly truncated genre word (``Comed``) is removed as well, but
# only for a conservative subset where the truncation is unambiguous.
_GENRE_WORDS = frozenset(
    {
        "comedy", "drama", "action", "thriller", "horror", "romance", "documentary",
        "musical", "sports", "family", "western", "fantasy", "adventure", "crime",
        "mystery", "animation", "war", "history", "music", "erotic", "erotica",
    }
)
_TRUNCATED_GENRE_WORDS = ("comedy", "drama", "action", "thriller", "horror", "musical", "mystery")

# Zero-padded shelf numbers ("01 Police Academy ...", "07-leonard-and-max-...");
# a bare leading number is often part of the real title ("100 Rifles").
_LEADING_INDEX_RE = re.compile(r"^\s*0\d\s*[-.:)\]]*\s+(?=[A-Za-z])")
_ATTACHED_SUFFIX_RE = re.compile(
    r"(?<=[a-z])(?:\d{3,4}p(?:hdtv|hd|web|bluray)?|x26[45]|h26[45]|hevc|hdrip|webrip|bluray)$",
    re.IGNORECASE,
)
_ATTACHED_DIGIT_RE = re.compile(r"(?<=[a-z]{3})\d$")
_RESOLUTION_RE = re.compile(r"^\d{3,4}p(?:hdtv|web|br)?$", re.IGNORECASE)
_PARENTHETICAL_YEAR_RE = re.compile(r"[(\[]\s*(?:18|19|20)\d{2}\s*[)\]]")


class MetadataLookupError(RuntimeError):
    pass


@dataclass(frozen=True)
class MovieMetadata:
    provider_id: int
    title: str
    release_year: int | None
    synopsis: str
    poster_url: str | None
    director: str
    cast_text: str
    genres: tuple[str, ...]
    external_ids: dict[str, str | int]
    confidence: float
    matched_query: str
    matched_via: str


def _title_key(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return _TITLE_KEY_RE.sub("", folded.casefold())


def _release_year(value: object) -> int | None:
    text = str(value or "")
    if len(text) >= 4 and text[:4].isdigit():
        year = int(text[:4])
        if 1888 <= year <= 2100:
            return year
    return None


def _strip_leading_index(value: str) -> str:
    match = _LEADING_INDEX_RE.match(value)
    return value[match.end():] if match else value


def _is_noise_word(word: str) -> bool:
    cleaned = word.strip(" .-_()[]{}!,").casefold()
    if not cleaned:
        return True
    if cleaned in _TRAILING_TOKENS or cleaned in _GENRE_WORDS:
        return True
    if _RESOLUTION_RE.fullmatch(cleaned):
        return True
    if _PARENTHETICAL_YEAR_RE.fullmatch(cleaned):
        return True
    if len(cleaned) >= 5:
        for genre in _TRUNCATED_GENRE_WORDS:
            if genre.startswith(cleaned) and 0 < len(genre) - len(cleaned) <= 2:
                return True
    return False


def _strip_trailing_noise(value: str) -> str:
    text = value.strip()
    while True:
        text = text.strip(" .-_()[]{}")
        if not text:
            return ""
        attached = _ATTACHED_SUFFIX_RE.search(text)
        if attached:
            text = text[: attached.start()]
            continue
        if len(text) >= 4 and _ATTACHED_DIGIT_RE.search(text):
            text = text[:-1]
            continue
        words = text.split()
        if len(words) >= 2 and _is_noise_word(words[-1]):
            text = " ".join(words[:-1])
            continue
        return " ".join(words)


def query_candidates(title: str, limit: int = 3) -> list[str]:
    """Ordered, de-duplicated search queries for a stored inventory title.

    Most-cleaned variant first (shelf index and trailing noise removed), then
    the index-stripped variant, then the raw title, capped at ``limit``.
    """
    if not title.strip():
        return []
    stripped = _strip_leading_index(title)
    variants = [
        _strip_trailing_noise(stripped),
        stripped,
        title,
    ]
    out: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        text = " ".join(variant.split()).strip(" .-_")
        if not text or len(_title_key(text)) < 2:
            continue
        key = _title_key(text)
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


_RELATION_RANK = {"exact": 5, "truncated": 4, "prefixed": 3, "weak": 2, "contained": 1}


def _relations(result_key: str, candidate_key: str) -> tuple[str, int] | None:
    if not result_key or not candidate_key:
        return None
    if result_key == candidate_key:
        return ("exact", 0)
    if candidate_key.startswith(result_key):
        remainder = len(candidate_key) - len(result_key)
        if remainder <= 3:
            return ("prefixed", remainder)
        if remainder <= 12:
            return ("weak", remainder)
    elif result_key.startswith(candidate_key):
        remainder = len(result_key) - len(candidate_key)
        if remainder <= 2:
            return ("truncated", remainder)
        if remainder <= 12:
            return ("weak", remainder)
    if len(result_key) >= 8 and result_key in candidate_key:
        return ("contained", 0)
    return None


def _weak_numeric(key: str) -> bool:
    """Very short numeric keys ("622") match junk and short films alike; they
    only ever count with matching year evidence on both sides."""
    return len(key) <= 4 and key.isdigit()


def _confidence_for(kind: str, remainder: int, stored_year: int | None, result_year: int | None) -> float | None:
    if stored_year is not None and result_year is not None:
        gap = abs(stored_year - result_year)
        if gap >= 2:
            return None
        if kind == "exact":
            return 1.0 if gap == 0 else 0.90
        if kind == "truncated":
            return 0.85 if gap == 0 else 0.80
        if kind == "prefixed":
            return 0.85 if gap == 0 else 0.80
        if kind == "weak":
            return 0.75 if gap == 0 else None
        if kind == "contained":
            return 0.75 if gap == 0 else None
        return None
    if stored_year is not None and result_year is None:
        return 0.80 if kind == "exact" else None
    if stored_year is None:
        if kind == "exact":
            return 0.85
        if kind == "truncated":
            return 0.78
        if kind == "prefixed":
            return 0.78 if remainder <= 1 else None
        return None
    return None


class TmdbClient:
    def __init__(self, access_token: str):
        if not access_token.strip():
            raise ValueError("TMDB access token is required")
        self.access_token = access_token.strip()

    def _get(self, path: str, params: dict[str, object] | None = None) -> dict:
        query = urlencode(params or {})
        url = f"{TMDB_API_BASE}{path}" + (f"?{query}" if query else "")
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.access_token}",
                "User-Agent": "MoviesWeMissed/1.0",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise MetadataLookupError(f"TMDB request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise MetadataLookupError("TMDB returned an invalid response")
        return payload

    def search(self, query: str) -> list[dict]:
        payload = self._get(
            "/search/movie",
            {"query": query, "include_adult": "false", "language": "en-US"},
        )
        results = payload.get("results", [])
        return [item for item in results if isinstance(item, dict)]

    def _score(self, result: dict, candidate_keys: list[str], stored_year: int | None) -> tuple[float, str, int] | None:
        result_keys = {
            _title_key(str(result.get("title") or "")),
            _title_key(str(result.get("original_title") or "")),
        }
        result_keys.discard("")
        if not result_keys:
            return None
        result_year = _release_year(result.get("release_date"))
        year_evidenced = (
            stored_year is not None
            and result_year is not None
            and abs(stored_year - result_year) <= 1
        )
        best: tuple[int, int, str] | None = None  # rank, -remainder, kind
        for result_key in result_keys:
            for candidate_key in candidate_keys:
                if _weak_numeric(candidate_key) and not year_evidenced:
                    continue
                relation = _relations(result_key, candidate_key)
                if relation is None:
                    continue
                kind, remainder = relation
                candidate = (_RELATION_RANK[kind], -remainder, kind)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
        if best is None:
            return None
        kind = best[2]
        remainder = -best[1]
        confidence = _confidence_for(kind, remainder, stored_year, result_year)
        if confidence is None:
            return None
        return (confidence, kind, remainder)

    def lookup(self, title: str, year: int | None = None, *, query: str | None = None) -> MovieMetadata | None:
        """Find the best acceptable TMDB match for a stored title.

        ``query`` overrides candidate generation (used by curated overrides).
        Returns ``None`` when nothing clears ``ACCEPT_CONFIDENCE``.
        """
        queries = [query] if query else query_candidates(title)
        if not queries:
            return None
        candidate_keys = [key for key in (_title_key(value) for value in queries) if key]
        if not candidate_keys:
            return None
        best: tuple[float, float, str, str, dict] | None = None
        seen: dict[int, float] = {}
        for search_query in queries[:3]:
            for result in self.search(search_query):
                provider_id = result.get("id")
                if not isinstance(provider_id, int):
                    continue
                scored = self._score(result, candidate_keys, year)
                if scored is None:
                    continue
                confidence, relation, _remainder = scored
                if seen.get(provider_id, 0.0) >= confidence:
                    continue
                seen[provider_id] = confidence
                popularity = result.get("popularity")
                rank = float(popularity) if isinstance(popularity, (int, float)) else 0.0
                candidate = (confidence, rank, search_query, relation, result)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
        if best is None or best[0] < ACCEPT_CONFIDENCE:
            return None
        confidence, _rank, matched_query, relation, match = best
        provider_id = int(match["id"])
        details = self._get(
            f"/movie/{provider_id}",
            {"append_to_response": "credits,external_ids", "language": "en-US"},
        )
        return self._build(
            details,
            fallback_title=title,
            stored_year=year,
            confidence=confidence,
            matched_query=matched_query,
            matched_via=f"search:{relation}",
        )

    def fetch(self, provider_id: int, *, fallback_title: str = "", matched_via: str = "pin") -> MovieMetadata | None:
        """Fetch one specific TMDB movie by id (curated overrides and pins)."""
        details = self._get(
            f"/movie/{provider_id}",
            {"append_to_response": "credits,external_ids", "language": "en-US"},
        )
        if not isinstance(details.get("id"), int):
            return None
        return self._build(
            details,
            fallback_title=fallback_title,
            stored_year=None,
            confidence=1.0,
            matched_query=str(provider_id),
            matched_via=matched_via,
        )

    @staticmethod
    def _build(
        details: dict,
        *,
        fallback_title: str,
        stored_year: int | None,
        confidence: float,
        matched_query: str,
        matched_via: str,
    ) -> MovieMetadata:
        provider_id = int(details["id"])
        credits_value = details.get("credits")
        credits: dict = credits_value if isinstance(credits_value, dict) else {}
        crew_value = credits.get("crew")
        crew: list = crew_value if isinstance(crew_value, list) else []
        cast_value = credits.get("cast")
        cast: list = cast_value if isinstance(cast_value, list) else []
        directors = [
            str(person.get("name"))
            for person in crew
            if isinstance(person, dict) and person.get("job") == "Director" and person.get("name")
        ][:3]
        cast_names = [
            str(person.get("name"))
            for person in sorted(
                (person for person in cast if isinstance(person, dict)),
                key=lambda person: int(person.get("order") or 0),
            )
            if person.get("name")
        ][:8]
        genres_value = details.get("genres")
        genre_items: list = genres_value if isinstance(genres_value, list) else []
        genres = tuple(
            str(genre["name"])
            for genre in genre_items
            if isinstance(genre, dict) and genre.get("name")
        )
        external_value = details.get("external_ids")
        external: dict = external_value if isinstance(external_value, dict) else {}
        external_ids: dict[str, str | int] = {"tmdb": provider_id}
        if external.get("imdb_id"):
            external_ids["imdb"] = str(external["imdb_id"])
        if external.get("wikidata_id"):
            external_ids["wikidata"] = str(external["wikidata_id"])
        poster_path = details.get("poster_path")
        poster_url = (
            f"{TMDB_IMAGE_BASE}{poster_path}"
            if isinstance(poster_path, str) and re.fullmatch(r"/[A-Za-z0-9._-]+", poster_path)
            else None
        )
        return MovieMetadata(
            provider_id=provider_id,
            title=str(details.get("title") or fallback_title).strip()[:300],
            release_year=_release_year(details.get("release_date")) or stored_year,
            synopsis=str(details.get("overview") or "").strip()[:5000],
            poster_url=poster_url,
            director=", ".join(dict.fromkeys(directors))[:300],
            cast_text=", ".join(dict.fromkeys(cast_names))[:2000],
            genres=genres,
            external_ids=external_ids,
            confidence=confidence,
            matched_query=matched_query,
            matched_via=matched_via,
        )
