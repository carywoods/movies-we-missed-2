from __future__ import annotations

import json

from html import escape
from urllib.parse import quote

from .config import Config


def page(config: Config, title: str, content: str, *, description: str = "Discover movies, screenings, and conversation.", canonical: str = "/") -> str:
    canonical_url = f"{config.site_url}{canonical}"
    structured = json.dumps({"@context": "https://schema.org", "@type": "WebSite", "name": "Movies We Missed", "url": config.site_url, "description": description}, separators=(",", ":")).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · Movies We Missed</title><meta name="description" content="{escape(description)}">
<meta property="og:title" content="{escape(title)} · Movies We Missed"><meta property="og:description" content="{escape(description)}"><meta property="og:url" content="{escape(canonical_url)}"><meta property="og:type" content="website"><meta property="og:image" content="{config.site_url}/static/icon.svg"><meta name="twitter:card" content="summary">
<link rel="canonical" href="{escape(canonical_url)}"><link rel="manifest" href="/manifest.webmanifest"><meta name="theme-color" content="#b6402c"><link rel="icon" href="/static/icon.svg" type="image/svg+xml"><link rel="stylesheet" href="/static/site.css"><script type="application/ld+json">{structured}</script>
</head><body><header><a class="brand" href="/">Movies We Missed</a><nav><a href="/movies">Browse</a><a href="/genres">Genres</a><a href="/collections">Collections</a><a href="/screenings">Screenings</a><a href="/login">Log in</a></nav></header>
<main>{content}</main><footer><p>Find the film. Join the conversation. Meet at the movies.</p></footer><script>if("serviceWorker" in navigator){{window.addEventListener("load",()=>navigator.serviceWorker.register("/sw.js"))}}</script></body></html>"""


def movie_card(movie) -> str:
    year = f" <span>({movie['release_year']})</span>" if movie["release_year"] else ""
    return f'<article class="card"><div class="poster">M</div><div><h3><a href="/movies/{escape(movie["slug"])}">{escape(movie["title"])}</a>{year}</h3><p>{escape(movie["synopsis"] or "A movie waiting to be rediscovered.")}</p></div></article>'


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
