from __future__ import annotations

from .mixins import AppMixin

import re
from html import escape
from urllib.parse import urlparse


class AdminMixin(AppMixin):
    def admin_routes(self):
        return {
            ("GET", "/admin"): self.admin_dashboard,
            ("GET", "/admin/movies"): self.admin_movies,
            ("GET", "/admin/import-review"): self.admin_import_review,
            ("GET", "/admin/merchandise"): self.admin_merchandise,
            ("POST", "/admin/merchandise"): self.save_merchandise,
            ("GET", "/admin/sponsors"): self.admin_sponsors,
            ("POST", "/admin/sponsors"): self.save_sponsor,
        }

    def dispatch_admin(self, request):
        match = re.fullmatch(r"/admin/movies/(\d+)/edit", request.path)
        if not match:
            return None
        movie_id = int(match.group(1))
        return self.admin_movie_form(request, movie_id) if request.method == "GET" else self.save_admin_movie(request, movie_id)

    @staticmethod
    def _operator(request):
        return bool(request.member and request.member["role"] in {"editor", "admin"})

    def _require_operator(self, request):
        if self._operator(request):
            return None
        from .web import Response
        return Response(b"Forbidden", 403)

    def admin_dashboard(self, request):
        denied = self._require_operator(request)
        if denied:
            return denied
        sections = (("Movies & classification", "/admin/movies"), ("Import review", "/admin/import-review"), ("Screenings", "/admin/screenings"), ("Merchandise", "/admin/merchandise"), ("Comments", "/admin/comments"), ("Newsletter", "/admin/newsletter"), ("Sponsors", "/admin/sponsors"), ("Analytics", "/admin/analytics"))
        cards = "".join(f'<article class="card"><div><h2><a href="{path}">{label}</a></h2></div></article>' for label, path in sections)
        return self.html("Operations", f'<h1>Operations</h1><div class="grid">{cards}</div>', canonical="/admin")

    def admin_movies(self, request):
        denied = self._require_operator(request)
        if denied:
            return denied
        query = request.query.get("q", [""])[0].strip()[:100]
        db = self.db()
        try:
            movies = list(db.execute("SELECT * FROM movies WHERE title LIKE ? ORDER BY title LIMIT 200", (f"%{query}%",)))
        finally:
            db.close()
        rows = "".join(f'<tr><td><a href="/admin/movies/{m["id"]}/edit">{escape(m["title"])}</a></td><td>{m["release_year"] or ""}</td><td>{"public" if m["published"] else "hidden"}</td><td>{m["parsing_confidence"]}</td></tr>' for m in movies)
        return self.html("Manage movies", f'<h1>Movies</h1><form class="search"><input name="q" value="{escape(query)}"><button>Search</button></form><table><tr><th>Title</th><th>Year</th><th>Visibility</th><th>Parse</th></tr>{rows}</table>', canonical="/admin/movies")

    def admin_movie_form(self, request, movie_id: int):
        denied = self._require_operator(request)
        if denied:
            return denied
        from .web import Response
        db = self.db()
        try:
            movie = db.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone()
            if not movie:
                return Response(b"Not found", 404)
            genres = list(db.execute("SELECT g.*,mg.movie_id selected FROM genres g LEFT JOIN movie_genres mg ON mg.genre_id=g.id AND mg.movie_id=? ORDER BY g.name", (movie_id,)))
            collections = list(db.execute("SELECT c.*,mc.movie_id selected FROM collections c LEFT JOIN movie_collections mc ON mc.collection_id=c.id AND mc.movie_id=? ORDER BY c.name", (movie_id,)))
        finally:
            db.close()
        genre_fields = "".join(f'<label class="check"><input type="checkbox" name="genre_{g["id"]}" value="1"{" checked" if g["selected"] else ""}>{escape(g["name"])}</label>' for g in genres)
        collection_fields = "".join(f'<label class="check"><input type="checkbox" name="collection_{c["id"]}" value="1"{" checked" if c["selected"] else ""}>{escape(c["name"])}</label>' for c in collections)
        fields = f'<label>Title<input name="title" value="{escape(movie["title"])}" required></label><label>Year<input name="release_year" type="number" value="{movie["release_year"] or ""}"></label><label>Synopsis<textarea name="synopsis">{escape(movie["synopsis"] or "")}</textarea></label><label class="check"><input type="checkbox" name="published" value="1"{" checked" if movie["published"] else ""}> Public</label><label class="check"><input type="checkbox" name="featured" value="1"{" checked" if movie["featured"] else ""}> Featured</label><fieldset><legend>Genres</legend>{genre_fields}</fieldset><fieldset><legend>Collections</legend>{collection_fields}</fieldset>'
        return self.form_page(request, "Edit movie", fields, f"/admin/movies/{movie_id}/edit")

    def save_admin_movie(self, request, movie_id: int):
        denied = self._require_operator(request)
        if denied:
            return denied
        from .web import Response
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        title = request.form.get("title", "").strip()[:300]
        try:
            year = int(request.form["release_year"]) if request.form.get("release_year") else None
        except ValueError:
            return Response(b"Invalid year", 400)
        if not title or (year and not 1888 <= year <= 2100):
            return Response(b"Invalid title or year", 400)
        db = self.db()
        try:
            db.execute("UPDATE movies SET title=?,release_year=?,synopsis=?,published=?,featured=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (title, year, request.form.get("synopsis", "").strip()[:5000], int(request.form.get("published") == "1"), int(request.form.get("featured") == "1"), movie_id))
            genre_ids = {row[0] for row in db.execute("SELECT id FROM genres")}
            collection_ids = {row[0] for row in db.execute("SELECT id FROM collections")}
            db.execute("DELETE FROM movie_genres WHERE movie_id=? AND source='editorial'", (movie_id,))
            db.execute("DELETE FROM movie_collections WHERE movie_id=? AND source='editorial'", (movie_id,))
            for identifier in genre_ids:
                if request.form.get(f"genre_{identifier}") == "1":
                    db.execute("INSERT INTO movie_genres(movie_id,genre_id,source) VALUES (?,?,'editorial') ON CONFLICT(movie_id,genre_id) DO UPDATE SET source='editorial',confidence=1", (movie_id, identifier))
            for identifier in collection_ids:
                if request.form.get(f"collection_{identifier}") == "1":
                    db.execute("INSERT INTO movie_collections(movie_id,collection_id,source) VALUES (?,?,'editorial') ON CONFLICT(movie_id,collection_id) DO UPDATE SET source='editorial',confidence=1", (movie_id, identifier))
            db.execute("INSERT INTO audit_log(actor_id,action,object_type,object_id) VALUES (?,'edit_movie','movie',?)", (request.member["member_id"], movie_id))
        finally:
            db.close()
        return self.redirect("/admin/movies")

    def admin_import_review(self, request):
        denied = self._require_operator(request)
        if denied:
            return denied
        db = self.db()
        try:
            reviews = list(db.execute("SELECT * FROM import_review WHERE status='open' ORDER BY created_at DESC LIMIT 200"))
        finally:
            db.close()
        items = "".join(f'<li>{escape(r["raw_filename"])} — {escape(r["source_category"])} — {escape(r["reason"])}</li>' for r in reviews) or "<li>No open import reviews.</li>"
        return self.html("Import review", f"<h1>Import review</h1><ul>{items}</ul>", canonical="/admin/import-review")

    def admin_merchandise(self, request):
        denied = self._require_operator(request)
        if denied:
            return denied
        db = self.db()
        try:
            offers = list(db.execute("SELECT x.*,m.title movie_title FROM merchandise x LEFT JOIN movies m ON m.id=x.movie_id ORDER BY x.created_at DESC LIMIT 200"))
            movies = list(db.execute("SELECT id,title FROM movies WHERE published=1 ORDER BY title LIMIT 2000"))
        finally:
            db.close()
        options = '<option value="">Universal fallback</option>' + "".join(f'<option value="{m["id"]}">{escape(m["title"])}</option>' for m in movies)
        fields = f'<label>Movie<select name="movie_id">{options}</select></label><label>Merchant<input name="merchant" required value="Amazon"></label><label>Label<input name="display_label" required></label><label>Product type<input name="product_type" required value="movie"></label><label>Destination URL<input type="url" name="destination_url" required></label><label>Match<select name="match_type"><option>specific</option><option>contextual</option><option>fallback</option></select></label>'
        form = self.form_markup(request, "Add merchandise", fields, "/admin/merchandise")
        rows = "".join(f'<tr><td>{escape(o["movie_title"] or "All movies")}</td><td>{escape(o["display_label"])}</td><td>{escape(o["merchant"])}</td></tr>' for o in offers)
        return self.html("Merchandise", f'<h1>Merchandise</h1>{form}<table><tr><th>Movie</th><th>Offer</th><th>Merchant</th></tr>{rows}</table>', canonical="/admin/merchandise")

    def save_merchandise(self, request):
        denied = self._require_operator(request)
        if denied:
            return denied
        from .web import Response
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        url = request.form.get("destination_url", "").strip()
        match_type = request.form.get("match_type", "specific")
        if urlparse(url).scheme not in {"http", "https"} or match_type not in {"specific", "contextual", "fallback"}:
            return Response(b"Invalid merchandise URL or match type", 400)
        movie_id = int(request.form["movie_id"]) if request.form.get("movie_id") else None
        db = self.db()
        try:
            offer_id = db.execute("INSERT INTO merchandise(movie_id,merchant,product_type,display_label,destination_url,match_type,generated_by) VALUES (?,?,?,?,?,?,'admin')", (movie_id, request.form.get("merchant", "").strip()[:100], request.form.get("product_type", "").strip()[:100], request.form.get("display_label", "").strip()[:200], url, match_type)).lastrowid
            db.execute("INSERT INTO audit_log(actor_id,action,object_type,object_id) VALUES (?,'add_merchandise','merchandise',?)", (request.member["member_id"], offer_id))
        finally:
            db.close()
        return self.redirect("/admin/merchandise")

    def admin_sponsors(self, request):
        denied = self._require_operator(request)
        if denied:
            return denied
        db = self.db()
        try:
            sponsors = list(db.execute("SELECT * FROM sponsors ORDER BY active DESC,name"))
        finally:
            db.close()
        fields = '<label>Name<input name="name" required></label><label>Destination URL<input name="destination_url" type="url" required></label><label>Label<input name="label" value="Presented by"></label><label class="check"><input name="paid" value="1" type="checkbox"> Paid sponsor</label>'
        form = self.form_markup(request, "Add sponsor", fields, "/admin/sponsors")
        rows = "".join(f'<tr><td>{escape(s["name"])}</td><td>{"paid" if s["paid"] else "house"}</td><td>{"active" if s["active"] else "inactive"}</td></tr>' for s in sponsors)
        return self.html("Sponsors", f'<h1>Sponsors</h1>{form}<table><tr><th>Name</th><th>Type</th><th>Status</th></tr>{rows}</table>', canonical="/admin/sponsors")

    def save_sponsor(self, request):
        denied = self._require_operator(request)
        if denied:
            return denied
        from .web import Response
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        name = request.form.get("name", "").strip()[:200]
        url = request.form.get("destination_url", "").strip()
        if not name or urlparse(url).scheme not in {"http", "https"}:
            return Response(b"Valid sponsor name and URL required", 400)
        db = self.db()
        try:
            sponsor_id = db.execute("INSERT INTO sponsors(name,label,destination_url,paid) VALUES (?,?,?,?)", (name, request.form.get("label", "Presented by").strip()[:100], url, int(request.form.get("paid") == "1"))).lastrowid
            db.execute("INSERT INTO audit_log(actor_id,action,object_type,object_id) VALUES (?,'add_sponsor','sponsor',?)", (request.member["member_id"], sponsor_id))
        finally:
            db.close()
        return self.redirect("/admin/sponsors")
