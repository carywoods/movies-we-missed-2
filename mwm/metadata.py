from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
_TITLE_KEY_RE = re.compile(r"[^a-z0-9]+")


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


def _title_key(value: str) -> str:
    return _TITLE_KEY_RE.sub("", value.casefold())


def _release_year(value: object) -> int | None:
    text = str(value or "")
    if len(text) >= 4 and text[:4].isdigit():
        year = int(text[:4])
        if 1888 <= year <= 2100:
            return year
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

    @staticmethod
    def _match_score(result: dict, title: str, year: int | None) -> float:
        requested_title = _title_key(title)
        candidate_titles = {
            _title_key(str(result.get("title") or "")),
            _title_key(str(result.get("original_title") or "")),
        }
        if not requested_title or requested_title not in candidate_titles:
            return 0.0
        score = 0.7
        candidate_year = _release_year(result.get("release_date"))
        if year:
            if candidate_year == year:
                score += 0.25
            elif candidate_year is not None:
                score -= 0.35
        else:
            score += 0.15
        if result.get("poster_path"):
            score += 0.05
        return max(0.0, min(score, 1.0))

    def lookup(self, title: str, year: int | None = None) -> MovieMetadata | None:
        params: dict[str, object] = {
            "query": title,
            "include_adult": "false",
            "language": "en-US",
        }
        if year:
            params["primary_release_year"] = year
        search = self._get("/search/movie", params)
        candidates = [item for item in search.get("results", []) if isinstance(item, dict)]
        ranked = sorted(
            ((self._match_score(item, title, year), item) for item in candidates),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if not ranked or ranked[0][0] < 0.8:
            return None
        confidence, match = ranked[0]
        provider_id = int(match["id"])
        details = self._get(
            f"/movie/{provider_id}",
            {"append_to_response": "credits,external_ids", "language": "en-US"},
        )
        credits = details.get("credits") if isinstance(details.get("credits"), dict) else {}
        crew = credits.get("crew") if isinstance(credits.get("crew"), list) else []
        cast = credits.get("cast") if isinstance(credits.get("cast"), list) else []
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
        genres = tuple(
            str(genre["name"])
            for genre in details.get("genres", [])
            if isinstance(genre, dict) and genre.get("name")
        )
        external = details.get("external_ids") if isinstance(details.get("external_ids"), dict) else {}
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
            title=str(details.get("title") or match.get("title") or title).strip()[:300],
            release_year=_release_year(details.get("release_date")) or year,
            synopsis=str(details.get("overview") or "").strip()[:5000],
            poster_url=poster_url,
            director=", ".join(dict.fromkeys(directors))[:300],
            cast_text=", ".join(dict.fromkeys(cast_names))[:2000],
            genres=genres,
            external_ids=external_ids,
            confidence=confidence,
        )
