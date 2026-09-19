from __future__ import annotations

import json

from html import escape
from urllib.parse import quote

from .config import Config


def field(movie, name: str):
    """Read a column from a sqlite3.Row or plain mapping, tolerating absence."""
    try:
        return movie[name]
    except (KeyError, IndexError, TypeError):
        return None


def teaser(text: str, limit: int = 130) -> str:
    """Trim a synopsis to a readable card teaser at a word boundary."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return f"{cut}…"


def movie_poster(movie, *, css_class: str = "") -> str:
    url = field(movie, "poster_url")
    title = str(field(movie, "title") or "Movie")
    classes = f"poster {css_class}".strip()
    if url:
        return f'<div class="{classes}"><img src="{escape(str(url), quote=True)}" alt="Poster for {escape(title)}" loading="lazy"></div>'
    initial = next((character.upper() for character in title if character.isalpha()), "")
    return f'<div class="{classes}" aria-hidden="true">{escape(initial)}</div>'


def page(config: Config, title: str, content: str, *, description: str = "Discover movies, screenings, and conversation.", canonical: str = "/", image: str | None = None) -> str:
    canonical_url = f"{config.site_url}{canonical}"
    og_image = image or f"{config.site_url}/static/icon.svg"
    attribution = '<p class="attribution">This product uses the TMDB API but is not endorsed or certified by TMDB.</p>' if config.metadata_provider == "tmdb" else ""
    structured = json.dumps({"@context": "https://schema.org", "@type": "WebSite", "name": "Movies We Missed", "url": config.site_url, "description": description}, separators=(",", ":")).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · Movies We Missed</title><meta name="description" content="{escape(description)}">
<meta property="og:title" content="{escape(title)} · Movies We Missed"><meta property="og:description" content="{escape(description)}"><meta property="og:url" content="{escape(canonical_url)}"><meta property="og:type" content="website"><meta property="og:image" content="{escape(og_image)}"><meta name="twitter:card" content="summary"><meta name="twitter:image" content="{escape(og_image)}">
<link rel="canonical" href="{escape(canonical_url)}"><link rel="manifest" href="/manifest.webmanifest"><meta name="theme-color" content="#b6402c"><link rel="icon" href="/static/icon.svg" type="image/svg+xml"><link rel="stylesheet" href="/static/site.css"><script type="application/ld+json">{structured}</script>
</head><body><header><a class="brand" href="/">Movies We Missed</a><nav><a href="/movies">Browse</a><a href="/genres">Genres</a><a href="/collections">Collections</a><a href="/screenings">Screenings</a><!--member-nav--></nav></header>
<main>{content}</main><footer><p>Find the film. Join the conversation. Meet at the movies.</p>{attribution}</footer><script>if("serviceWorker" in navigator){{window.addEventListener("load",()=>navigator.serviceWorker.register("/sw.js"))}}</script></body></html>"""


def movie_card(movie) -> str:
    year = f" <span>({movie['release_year']})</span>" if movie["release_year"] else ""
    director = field(movie, "director")
    credits = f'<p class="meta">Directed by {escape(str(director))}</p>' if director else ""
    summary = teaser(movie["synopsis"] or "A movie waiting to be rediscovered.")
    return f'<article class="card">{movie_poster(movie)}<div><h3><a href="/movies/{escape(movie["slug"])}">{escape(movie["title"])}</a>{year}</h3>{credits}<p class="summary">{escape(summary)}</p></div></article>'


def movie_grid(movies) -> str:
    cards = "".join(movie_card(movie) for movie in movies)
    return f'<div class="grid">{cards}</div>' if cards else '<div class="empty"><h2>No movies found</h2><p>Try another search or check back after the next inventory update.</p></div>'


def search_form(query: str = "") -> str:
    return f'<form class="search" action="/movies" method="get"><label for="q">Search the catalog</label><div><input id="q" name="q" value="{escape(query)}" placeholder="Title or year"><button>Search</button></div></form>'


def pagination(path: str, page_number: int, has_more: bool, query: str = "") -> str:
    links = []
    if page_number > 1:
        links.append(f'<a href="{path}?q={quote(query)}&page={page_number - 1}">Previous</a>')
    if has_more:
        links.append(f'<a href="{path}?q={quote(query)}&page={page_number + 1}">Next</a>')
    return f'<nav class="pagination">{"".join(links)}</nav>'
