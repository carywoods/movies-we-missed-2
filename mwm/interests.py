from __future__ import annotations

import re

from .views import movie_grid


class InterestMixin:
    def interest_routes(self):
        return {("GET", "/discover"): self.discovery}

    def follow_control(self, request, target_type: str, target_id: int, followed: bool) -> str:
        action = "unfollow" if followed else "follow"
        label = "Unfollow" if followed else "Follow"
        return f'<form class="inline" method="post" action="/{target_type}s/{target_id}/{action}"><input type="hidden" name="csrf" value="{request.session["csrf_token"]}"><button>{label} {target_type}</button></form>'

    def dispatch_interest(self, request):
        match = re.fullmatch(r"/(movies|genres)/(\d+)/(follow|unfollow)", request.path)
        if not match or request.method != "POST":
            return None
        from .web import Response
        if not request.member:
            return self.redirect("/login")
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        plural, raw_id, action = match.groups()
        target_type = plural[:-1]
        target_id = int(raw_id)
        table = "movies" if target_type == "movie" else "genres"
        db = self.db()
        try:
            target = db.execute(f"SELECT id FROM {table} WHERE id=?", (target_id,)).fetchone()
            if not target:
                return Response(b"Not found", 404)
            if action == "follow":
                db.execute("INSERT OR IGNORE INTO follows(member_id,target_type,target_id) VALUES (?,?,?)", (request.member["member_id"], target_type, target_id))
                db.execute("INSERT INTO analytics_events(event_type,object_type,object_id,member_id) VALUES ('follow',?,?,?)", (target_type, target_id, request.member["member_id"]))
            else:
                db.execute("DELETE FROM follows WHERE member_id=? AND target_type=? AND target_id=?", (request.member["member_id"], target_type, target_id))
        finally:
            db.close()
        return self.redirect(request.environ.get("HTTP_REFERER", "/discover"))

    def discovery(self, request):
        if not request.member:
            return self.redirect("/login")
        member_id = request.member["member_id"]
        db = self.db()
        try:
            followed_movies = list(db.execute("SELECT m.* FROM movies m JOIN follows f ON f.target_id=m.id AND f.target_type='movie' WHERE f.member_id=? AND m.published=1 ORDER BY f.created_at DESC LIMIT 24", (member_id,)))
            followed_genres = list(db.execute("SELECT g.* FROM genres g JOIN follows f ON f.target_id=g.id AND f.target_type='genre' WHERE f.member_id=? ORDER BY g.name", (member_id,)))
            recommendations = list(db.execute("SELECT DISTINCT m.* FROM movies m JOIN movie_genres mg ON mg.movie_id=m.id JOIN follows f ON f.target_id=mg.genre_id AND f.target_type='genre' WHERE f.member_id=? AND m.published=1 AND m.adult_content=0 AND m.id NOT IN (SELECT target_id FROM follows WHERE member_id=? AND target_type='movie') ORDER BY m.featured DESC,m.title LIMIT 24", (member_id, member_id)))
            screenings = list(db.execute("SELECT DISTINCT s.*,m.title AS movie_title FROM screenings s JOIN movies m ON m.id=s.movie_id LEFT JOIN movie_genres mg ON mg.movie_id=m.id WHERE s.status IN ('announced','rsvp_open','full') AND s.starts_at>=CURRENT_TIMESTAMP AND (m.id IN (SELECT target_id FROM follows WHERE member_id=? AND target_type='movie') OR mg.genre_id IN (SELECT target_id FROM follows WHERE member_id=? AND target_type='genre')) ORDER BY s.starts_at LIMIT 8", (member_id, member_id)))
        finally:
            db.close()
        genre_chips = "".join(f'<span>{g["name"]}</span>' for g in followed_genres) or "<span>No genres followed yet.</span>"
        screening_items = "".join(f'<li><a href="/screenings/{s["slug"]}">{s["title"]}</a> — {s["starts_at"]}</li>' for s in screenings) or "<li>No related upcoming screenings yet.</li>"
        content = f'<h1>Your discovery feed</h1><section><h2>Followed genres</h2><div class="chips">{genre_chips}</div></section><section><h2>Movies you follow</h2>{movie_grid(followed_movies)}</section><section><h2>From your genres</h2>{movie_grid(recommendations)}</section><section><h2>Related screenings</h2><ul>{screening_items}</ul></section>'
        return self.html("Your discovery feed", content, canonical="/discover")
