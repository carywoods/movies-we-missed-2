from __future__ import annotations

from .mixins import AppMixin

import json
import re
from html import escape

from .importer import slugify


SCREENING_STATUSES = ("draft", "announced", "rsvp_open", "full", "completed", "cancelled")


class ScreeningMixin(AppMixin):
    def screening_routes(self):
        return {
            ("GET", "/screenings"): self.screening_index,
            ("GET", "/admin/screenings"): self.admin_screenings,
            ("GET", "/admin/screenings/new"): self.screening_form,
            ("POST", "/admin/screenings/new"): self.save_screening,
        }

    def dispatch_screenings(self, request):
        admin = re.fullmatch(r"/admin/screenings/(\d+)/edit", request.path)
        if admin:
            return self.screening_form(request, int(admin.group(1))) if request.method == "GET" else self.save_screening(request, int(admin.group(1)))
        rsvp = re.fullmatch(r"/screenings/([^/]+)/(rsvp|cancel-rsvp)", request.path)
        if rsvp and request.method == "POST":
            return self.change_rsvp(request, rsvp.group(1), rsvp.group(2))
        detail = re.fullmatch(r"/screenings/([^/]+)", request.path)
        if detail and request.method == "GET":
            return self.screening_detail(request, detail.group(1))
        return None

    def screening_index(self, request):
        db = self.db()
        try:
            screenings = list(db.execute("SELECT s.*,m.title AS movie_title FROM screenings s JOIN movies m ON m.id=s.movie_id WHERE s.status IN ('announced','rsvp_open','full') AND s.starts_at>=CURRENT_TIMESTAMP ORDER BY s.starts_at"))
        finally:
            db.close()
        items = "".join(f'<article class="card"><div><p class="meta">{escape(s["starts_at"])}</p><h2><a href="/screenings/{s["slug"]}">{escape(s["title"])}</a></h2><p>{escape(s["movie_title"])} · {escape(s["venue_name"])} · {escape(s["city"])}, {escape(s["region"])}</p></div></article>' for s in screenings)
        if not items:
            items = '<div class="empty"><h2>No screenings announced</h2><p>Follow movies and genres to hear when the next gathering is scheduled.</p></div>'
        return self.html("Screenings", f'<h1>Meet at the movies</h1><div class="grid">{items}</div>', canonical="/screenings")

    def screening_detail(self, request, slug: str):
        from .web import Response
        db = self.db()
        try:
            screening = db.execute("SELECT s.*,m.title AS movie_title,m.slug AS movie_slug FROM screenings s JOIN movies m ON m.id=s.movie_id WHERE s.slug=? AND s.status!='draft'", (slug,)).fetchone()
            if not screening:
                return Response(b"Not found", 404)
            genres = list(db.execute("SELECT g.* FROM genres g JOIN movie_genres mg ON mg.genre_id=g.id WHERE mg.movie_id=? ORDER BY g.name", (screening["movie_id"],)))
            attending = db.execute("SELECT COALESCE(sum(1+guest_count),0) FROM rsvps WHERE screening_id=? AND status IN ('going','attended')", (screening["id"],)).fetchone()[0]
            current = None if not request.member else db.execute("SELECT * FROM rsvps WHERE screening_id=? AND member_id=?", (screening["id"], request.member["member_id"])).fetchone()
            db.execute("INSERT INTO analytics_events(event_type,object_type,object_id,member_id) VALUES ('screening_view','screening',?,?)", (screening["id"], request.member["member_id"] if request.member else None))
        finally:
            db.close()
        genre_links = "".join(f'<a href="/genres/{g["slug"]}">{escape(g["name"])}</a>' for g in genres)
        capacity = f' of {screening["capacity"]}' if screening["capacity"] else ""
        rsvp = '<p><a href="/login">Log in</a> to RSVP.</p>'
        if request.member and screening["status"] in {"announced", "rsvp_open", "full"}:
            if current and current["status"] in {"going", "waitlisted"}:
                rsvp = f'<p>Your RSVP: <strong>{current["status"]}</strong></p><form method="post" action="/screenings/{slug}/cancel-rsvp"><input type="hidden" name="csrf" value="{request.session["csrf_token"]}"><button>Cancel RSVP</button></form>'
            else:
                rsvp = f'<form class="inline" method="post" action="/screenings/{slug}/rsvp"><input type="hidden" name="csrf" value="{request.session["csrf_token"]}"><label>Guests <select name="guest_count"><option>0</option><option>1</option><option>2</option><option>3</option><option>4</option></select></label><button>RSVP</button></form>'
        content = f'<article class="detail"><p class="meta">{escape(screening["starts_at"])} · {escape(screening["status"].replace("_", " ").title())}</p><h1>{escape(screening["title"])}</h1><p><a href="/movies/{screening["movie_slug"]}">{escape(screening["movie_title"])}</a></p><p>{escape(screening["description"])}</p><h2>Venue</h2><address>{escape(screening["venue_name"])}<br>{escape(screening["address_line1"])}<br>{escape(screening["city"])}, {escape(screening["region"])} {escape(screening["postal_code"])}</address><p>{attending}{capacity} attending · {escape(screening["cost_label"])}</p><div class="chips">{genre_links}</div>{rsvp}<p><a href="/screenings/{slug}/comments">Screening discussion</a></p></article>'
        return self.html(screening["title"], content, description=screening["description"], canonical=f"/screenings/{slug}")

    def change_rsvp(self, request, slug: str, action: str):
        from .web import Response
        if not request.member:
            return self.redirect("/login")
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        db = self.db()
        try:
            db.execute("BEGIN IMMEDIATE")
            screening = db.execute("SELECT * FROM screenings WHERE slug=? AND status IN ('announced','rsvp_open','full')", (slug,)).fetchone()
            if not screening:
                return Response(b"RSVP is not available", 409)
            if action == "cancel-rsvp":
                changed = db.execute("UPDATE rsvps SET status='cancelled',updated_at=CURRENT_TIMESTAMP WHERE screening_id=? AND member_id=? AND status IN ('going','waitlisted')", (screening["id"], request.member["member_id"]))
                if changed.rowcount and screening["capacity"]:
                    attending = db.execute("SELECT COALESCE(sum(1+guest_count),0) FROM rsvps WHERE screening_id=? AND status='going'", (screening["id"],)).fetchone()[0]
                    available = screening["capacity"] - attending
                    waitlisted = list(db.execute("SELECT * FROM rsvps WHERE screening_id=? AND status='waitlisted' ORDER BY created_at,id", (screening["id"],)))
                    for candidate in waitlisted:
                        party_size = candidate["guest_count"] + 1
                        if party_size > available:
                            continue
                        db.execute("UPDATE rsvps SET status='going',updated_at=CURRENT_TIMESTAMP WHERE id=?", (candidate["id"],))
                        db.execute(
                            "INSERT INTO notifications(member_id,kind,title,body,destination_url) VALUES (?,?,?,?,?)",
                            (candidate["member_id"], "rsvp_promoted", "You are in", f'A place opened for {screening["title"]}. Your RSVP is confirmed.', f'/screenings/{slug}'),
                        )
                        available -= party_size
                        if available <= 0:
                            break
            else:
                try:
                    guests = min(4, max(0, int(request.form.get("guest_count", "0"))))
                except ValueError:
                    return Response(b"Invalid guest count", 400)
                attending = db.execute("SELECT COALESCE(sum(1+guest_count),0) FROM rsvps WHERE screening_id=? AND status='going' AND member_id!=?", (screening["id"], request.member["member_id"])).fetchone()[0]
                status = "waitlisted" if screening["capacity"] and attending + guests + 1 > screening["capacity"] else "going"
                db.execute("INSERT INTO rsvps(screening_id,member_id,guest_count,status) VALUES (?,?,?,?) ON CONFLICT(screening_id,member_id) DO UPDATE SET guest_count=excluded.guest_count,status=excluded.status,updated_at=CURRENT_TIMESTAMP", (screening["id"], request.member["member_id"], guests, status))
                db.execute("INSERT INTO analytics_events(event_type,object_type,object_id,member_id,metadata_json) VALUES ('rsvp','screening',?,?,?)", (screening["id"], request.member["member_id"], json.dumps({"status": status}, separators=(",", ":"))))
            db.execute("COMMIT")
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()
        return self.redirect(f"/screenings/{slug}")

    def _screening_admin(self, request):
        return bool(request.member and request.member["role"] in {"editor", "admin"})

    def admin_screenings(self, request):
        from .web import Response
        if not self._screening_admin(request):
            return Response(b"Forbidden", 403)
        db = self.db()
        try:
            screenings = list(db.execute("SELECT s.*,m.title movie_title FROM screenings s JOIN movies m ON m.id=s.movie_id ORDER BY s.starts_at DESC"))
        finally:
            db.close()
        items = "".join(f'<li><a href="/admin/screenings/{s["id"]}/edit">{escape(s["title"])}</a> — {s["status"]} — {escape(s["movie_title"])}</li>' for s in screenings)
        return self.html("Manage screenings", f'<h1>Manage screenings</h1><p><a class="button" href="/admin/screenings/new">New screening</a></p><ul>{items}</ul>', canonical="/admin/screenings")

    def screening_form(self, request, screening_id: int | None = None):
        from .web import Response
        if not self._screening_admin(request):
            return Response(b"Forbidden", 403)
        db = self.db()
        try:
            screening = None if not screening_id else db.execute("SELECT * FROM screenings WHERE id=?", (screening_id,)).fetchone()
            movies = list(db.execute("SELECT id,title,release_year FROM movies WHERE published=1 ORDER BY title LIMIT 2000"))
        finally:
            db.close()
        value = lambda key, default="": escape(str(screening[key] if screening and screening[key] is not None else default))
        movie_options = "".join(f'<option value="{m["id"]}"{" selected" if screening and m["id"] == screening["movie_id"] else ""}>{escape(m["title"])} ({m["release_year"] or "?"})</option>' for m in movies)
        statuses = "".join(f'<option value="{s}"{" selected" if value("status", "draft") == s else ""}>{s.replace("_", " ").title()}</option>' for s in SCREENING_STATUSES)
        action = "/admin/screenings/new" if not screening_id else f"/admin/screenings/{screening_id}/edit"
        fields = f'<label>Movie<select name="movie_id" required>{movie_options}</select></label><label>Title<input name="title" value="{value("title")}" required></label><label>Description<textarea name="description">{value("description")}</textarea></label><label>Starts at<input name="starts_at" value="{value("starts_at")}" placeholder="2027-10-15 19:00:00" required></label><label>Ends at<input name="ends_at" value="{value("ends_at")}"></label><label>Status<select name="status">{statuses}</select></label><label>Venue<input name="venue_name" value="{value("venue_name")}" required></label><label>Address<input name="address_line1" value="{value("address_line1")}" required></label><label>City<input name="city" value="{value("city")}" required></label><label>State/region<input name="region" value="{value("region")}" required></label><label>Postal code<input name="postal_code" value="{value("postal_code")}" required></label><label>Capacity<input name="capacity" type="number" min="1" value="{value("capacity")}"></label><label>Cost label<input name="cost_label" value="{value("cost_label", "Free")}"></label>'
        return self.form_page(request, "Edit screening" if screening_id else "New screening", fields, action)

    def save_screening(self, request, screening_id: int | None = None):
        from .web import Response
        if not self._screening_admin(request):
            return Response(b"Forbidden", 403)
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        required = ("movie_id", "title", "starts_at", "venue_name", "address_line1", "city", "region", "postal_code")
        if any(not request.form.get(key, "").strip() for key in required) or request.form.get("status", "draft") not in SCREENING_STATUSES:
            return Response(b"Missing or invalid screening fields", 400)
        try:
            movie_id = int(request.form["movie_id"])
            capacity = int(request.form["capacity"]) if request.form.get("capacity") else None
        except ValueError:
            return Response(b"Invalid movie or capacity", 400)
        db = self.db()
        try:
            if not db.execute("SELECT id FROM movies WHERE id=?", (movie_id,)).fetchone():
                return Response(b"Movie not found", 404)
            fields = (movie_id, request.form["title"].strip()[:200], request.form.get("description", "").strip()[:4000], request.form["starts_at"].strip(), request.form.get("ends_at") or None, request.form["venue_name"].strip()[:200], request.form["address_line1"].strip()[:200], request.form["city"].strip()[:100], request.form["region"].strip()[:100], request.form["postal_code"].strip()[:20], capacity, request.form["status"], request.form.get("cost_label", "Free").strip()[:80] or "Free")
            if screening_id:
                db.execute("UPDATE screenings SET movie_id=?,title=?,description=?,starts_at=?,ends_at=?,venue_name=?,address_line1=?,city=?,region=?,postal_code=?,capacity=?,status=?,cost_label=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (*fields, screening_id))
            else:
                slug = f"{slugify(request.form['title'])}-{slugify(request.form['starts_at'])}"
                screening_id = db.execute("INSERT INTO screenings(movie_id,slug,title,description,starts_at,ends_at,venue_name,address_line1,city,region,postal_code,capacity,status,cost_label) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (movie_id, slug, *fields[1:])).lastrowid
            db.execute("INSERT INTO audit_log(actor_id,action,object_type,object_id) VALUES (?,'save_screening','screening',?)", (request.member["member_id"], screening_id))
        finally:
            db.close()
        return self.redirect("/admin/screenings")
