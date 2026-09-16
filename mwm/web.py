from __future__ import annotations

import json
import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import Callable, Iterable
from urllib.parse import parse_qs

from .config import Config
from .db import connect, initialize
from .views import movie_grid, page, pagination, search_form


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    environ: dict


@dataclass
class Response:
    body: bytes
    status: int = 200
    content_type: str = "text/plain; charset=utf-8"
    headers: tuple[tuple[str, str], ...] = ()

    @classmethod
    def json(cls, payload: object, status: int = 200) -> "Response":
        return cls(json.dumps(payload, separators=(",", ":")).encode(), status, "application/json")


Handler = Callable[[Request], Response]


class Application:
    def __init__(self, config: Config):
        self.config = config
        initialize(config)
        self.routes: dict[tuple[str, str], Handler] = {
            ("GET", "/health"): self.health,
            ("GET", "/"): self.home,
            ("GET", "/movies"): self.movies,
            ("GET", "/genres"): self.genres,
            ("GET", "/collections"): self.collections,
            ("GET", "/static/site.css"): self.styles,
        }

    def html(self, title: str, content: str, **kwargs) -> Response:
        return Response(page(self.config, title, content, **kwargs).encode(), content_type="text/html; charset=utf-8")

    def db(self):
        return connect(self.config.database_path)

    def health(self, request: Request) -> Response:
        connection = connect(self.config.database_path)
        try:
            connection.execute("SELECT 1").fetchone()
        finally:
            connection.close()
        return Response.json({"status": "ok", "service": "movies-we-missed"})

    def styles(self, request: Request) -> Response:
        css = (__import__("pathlib").Path(__file__).parent / "static" / "site.css").read_bytes()
        return Response(css, content_type="text/css; charset=utf-8", headers=(("Cache-Control", "public, max-age=3600"),))

    def home(self, request: Request) -> Response:
        db = self.db()
        try:
            movies = list(db.execute("SELECT * FROM movies WHERE published=1 AND adult_content=0 ORDER BY featured DESC, created_at DESC, title LIMIT 12"))
        finally:
            db.close()
        content = '<section class="hero"><p>THE MOVIE CLUB FOR THE ONES THAT GOT AWAY</p><h1>There’s always another great movie.</h1><p>Explore overlooked films, follow what interests you, and meet up at the movies.</p><a class="button" href="/movies">Browse the catalog</a></section><section><h2>Recently added</h2>' + movie_grid(movies) + "</section>"
        return self.html("Home", content, canonical="/")

    def movies(self, request: Request) -> Response:
        query = request.query.get("q", [""])[0].strip()[:100]
        try:
            page_number = max(1, int(request.query.get("page", ["1"])[0]))
        except ValueError:
            page_number = 1
        params: list[object] = []
        where = "published=1 AND adult_content=0"
        if query:
            where += " AND (title LIKE ? OR CAST(release_year AS TEXT)=?)"
            params += [f"%{query}%", query]
        params += [25, (page_number - 1) * 24]
        db = self.db()
        try:
            movies = list(db.execute(f"SELECT * FROM movies WHERE {where} ORDER BY title LIMIT ? OFFSET ?", params))
        finally:
            db.close()
        content = f"<h1>Browse movies</h1>{search_form(query)}{movie_grid(movies[:24])}{pagination('/movies', page_number, len(movies) > 24, query)}"
        canonical = "/movies" + (f"?q={query}" if query else "")
        return self.html("Browse movies", content, canonical=canonical)

    def genres(self, request: Request) -> Response:
        return self._taxonomy_index("Genres", "genres", "/genres")

    def collections(self, request: Request) -> Response:
        return self._taxonomy_index("Collections", "collections", "/collections", "adult_only=0")

    def _taxonomy_index(self, title: str, table: str, path: str, where: str = "1=1") -> Response:
        db = self.db()
        try:
            items = list(db.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY name"))
        finally:
            db.close()
        content = f'<h1>{title}</h1><div class="chips">' + "".join(f'<a href="{path}/{item["slug"]}">{item["name"]}</a>' for item in items) + "</div>"
        return self.html(title, content, canonical=path)

    def movie_detail(self, slug: str) -> Response:
        db = self.db()
        try:
            movie = db.execute("SELECT * FROM movies WHERE slug=? AND published=1 AND adult_content=0", (slug,)).fetchone()
            if not movie:
                return Response(b"Not found", 404)
            genres = list(db.execute("SELECT g.* FROM genres g JOIN movie_genres mg ON mg.genre_id=g.id WHERE mg.movie_id=? ORDER BY g.name", (movie["id"],)))
            collections = list(db.execute("SELECT c.* FROM collections c JOIN movie_collections mc ON mc.collection_id=c.id WHERE mc.movie_id=? AND c.adult_only=0 ORDER BY c.name", (movie["id"],)))
        finally:
            db.close()
        year = f' <span class="meta">({movie["release_year"]})</span>' if movie["release_year"] else ""
        chips = "".join(f'<a href="/genres/{x["slug"]}">{x["name"]}</a>' for x in genres) + "".join(f'<a href="/collections/{x["slug"]}">{x["name"]}</a>' for x in collections)
        content = f'<article class="detail"><p class="meta">MOVIE</p><h1>{movie["title"]}{year}</h1><p>{movie["synopsis"] or "A movie waiting to be rediscovered and discussed."}</p><div class="chips">{chips}</div></article>'
        return self.html(movie["title"], content, description=movie["synopsis"] or f'Discover {movie["title"]} at Movies We Missed.', canonical=f'/movies/{slug}')

    def taxonomy_detail(self, table: str, join_table: str, foreign_key: str, path: str, slug: str) -> Response:
        db = self.db()
        try:
            item = db.execute(f"SELECT * FROM {table} WHERE slug=?", (slug,)).fetchone()
            if not item or ("adult_only" in item.keys() and item["adult_only"]):
                return Response(b"Not found", 404)
            movies = list(db.execute(f"SELECT m.* FROM movies m JOIN {join_table} j ON j.movie_id=m.id WHERE j.{foreign_key}=? AND m.published=1 AND m.adult_content=0 ORDER BY m.title", (item["id"],)))
        finally:
            db.close()
        content = f'<h1>{item["name"]}</h1><p>{item["description"]}</p>{movie_grid(movies)}'
        return self.html(item["name"], content, description=item["description"], canonical=f'{path}/{slug}')

    def dispatch_dynamic(self, request: Request) -> Response | None:
        patterns = (
            (r"/movies/([^/]+)", lambda slug: self.movie_detail(slug)),
            (r"/genres/([^/]+)", lambda slug: self.taxonomy_detail("genres", "movie_genres", "genre_id", "/genres", slug)),
            (r"/collections/([^/]+)", lambda slug: self.taxonomy_detail("collections", "movie_collections", "collection_id", "/collections", slug)),
        )
        if request.method == "GET":
            for pattern, callback in patterns:
                match = re.fullmatch(pattern, request.path)
                if match:
                    return callback(match.group(1))
        return None

    def __call__(self, environ: dict, start_response: Callable) -> Iterable[bytes]:
        request = Request(
            method=environ.get("REQUEST_METHOD", "GET").upper(),
            path=environ.get("PATH_INFO", "/") or "/",
            query=parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True),
            environ=environ,
        )
        handler = self.routes.get((request.method, request.path))
        response = handler(request) if handler else self.dispatch_dynamic(request) or Response(b"Not found", 404)
        phrase = HTTPStatus(response.status).phrase
        headers = [("Content-Type", response.content_type), ("Content-Length", str(len(response.body))), *response.headers]
        start_response(f"{response.status} {phrase}", headers)
        return [response.body]


def create_app(config: Config | None = None) -> Application:
    return Application(config or Config.from_env())
