from __future__ import annotations

import re
from html import escape

from .auth import token_hash


TRACKED_EVENTS = (
    "page_view",
    "movie_view",
    "genre_view",
    "follow",
    "comment",
    "screening_view",
    "rsvp",
    "newsletter_signup",
    "amazon_click",
    "imbh_click",
    "sponsor_click",
    "merchandise_click",
)


class AnalyticsMixin:
    def analytics_routes(self):
        return {("GET", "/admin/analytics"): self.analytics_dashboard}

    def track_response(self, request, response) -> None:
        if request.method != "GET" or response.status != 200 or not response.content_type.startswith("text/html") or request.path.startswith("/admin/"):
            return
        object_type = None
        object_id = None
        specific_event = None
        db = self.db()
        try:
            movie = re.fullmatch(r"/movies/([^/]+)", request.path)
            genre = re.fullmatch(r"/genres/([^/]+)", request.path)
            if movie:
                row = db.execute("SELECT id FROM movies WHERE slug=?", (movie.group(1),)).fetchone()
                if row:
                    object_type, object_id, specific_event = "movie", row["id"], "movie_view"
            elif genre:
                row = db.execute("SELECT id FROM genres WHERE slug=?", (genre.group(1),)).fetchone()
                if row:
                    object_type, object_id, specific_event = "genre", row["id"], "genre_view"
            member_id = request.member["member_id"] if request.member else None
            session_hash = token_hash(request.session_token) if request.session_token else None
            db.execute("INSERT INTO analytics_events(event_type,object_type,object_id,member_id,session_hash,source) VALUES ('page_view',?,?,?,?,?)", (object_type, object_id, member_id, session_hash, request.path[:300]))
            if specific_event:
                db.execute("INSERT INTO analytics_events(event_type,object_type,object_id,member_id,session_hash,source) VALUES (?,?,?,?,?,?)", (specific_event, object_type, object_id, member_id, session_hash, request.path[:300]))
        finally:
            db.close()

    def analytics_dashboard(self, request):
        from .web import Response
        if not request.member or request.member["role"] not in {"editor", "admin"}:
            return Response(b"Forbidden", 403)
        db = self.db()
        try:
            counts = {row["event_type"]: row["total"] for row in db.execute("SELECT event_type,count(*) total FROM analytics_events WHERE occurred_at>=datetime('now','-30 days') GROUP BY event_type")}
            top_movies = list(db.execute("SELECT m.title,count(*) views FROM analytics_events e JOIN movies m ON m.id=e.object_id WHERE e.event_type='movie_view' AND e.occurred_at>=datetime('now','-30 days') GROUP BY m.id ORDER BY views DESC,m.title LIMIT 20"))
            daily = list(db.execute("SELECT date(occurred_at) day,count(*) total FROM analytics_events WHERE occurred_at>=datetime('now','-30 days') GROUP BY day ORDER BY day DESC"))
        finally:
            db.close()
        cards = "".join(f'<article class="card"><div><p class="meta">{escape(event.replace("_", " ").upper())}</p><h2>{counts.get(event, 0)}</h2></div></article>' for event in TRACKED_EVENTS)
        movie_rows = "".join(f'<tr><td>{escape(row["title"])}</td><td>{row["views"]}</td></tr>' for row in top_movies)
        daily_rows = "".join(f'<tr><td>{row["day"]}</td><td>{row["total"]}</td></tr>' for row in daily)
        content = f'<h1>First-party analytics</h1><p>Last 30 days. IP addresses and user-agent strings are not stored.</p><div class="grid">{cards}</div><h2>Top movies</h2><table><tr><th>Movie</th><th>Views</th></tr>{movie_rows}</table><h2>Daily activity</h2><table><tr><th>Day</th><th>Events</th></tr>{daily_rows}</table>'
        return self.html("Analytics", content, canonical="/admin/analytics")
