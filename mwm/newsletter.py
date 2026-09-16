from __future__ import annotations

from .mixins import AppMixin

import hashlib
import json
import re
import secrets
from html import escape

from .emailer import EmailMessage, get_email_provider
from .importer import slugify


class NewsletterMixin(AppMixin):
    def newsletter_routes(self):
        return {
            ("GET", "/newsletter"): self.newsletter_signup_form,
            ("POST", "/newsletter"): self.newsletter_signup,
            ("GET", "/newsletter/unsubscribe"): self.newsletter_unsubscribe,
            ("GET", "/admin/newsletter"): self.admin_newsletter,
            ("GET", "/admin/newsletter/new"): self.newsletter_issue_form,
            ("POST", "/admin/newsletter/new"): self.save_newsletter_issue,
        }

    def dispatch_newsletter(self, request):
        match = re.fullmatch(r"/admin/newsletter/(\d+)/(preview|send)", request.path)
        if not match:
            return None
        issue_id = int(match.group(1))
        if match.group(2) == "preview" and request.method == "GET":
            return self.newsletter_preview(request, issue_id)
        if match.group(2) == "send" and request.method == "POST":
            return self.send_newsletter(request, issue_id)
        return None

    def _newsletter_admin(self, request):
        return bool(request.member and request.member["role"] in {"editor", "admin"})

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def newsletter_signup_form(self, request):
        db = self.db()
        try:
            cadence = db.execute("SELECT value FROM settings WHERE key='newsletter_cadence'").fetchone()[0]
        finally:
            db.close()
        fields = f'<label>Email<input type="email" name="email" required autocomplete="email"></label><label>Cadence<select name="cadence"><option value="{cadence}">{cadence.title()} (site default)</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select></label>'
        return self.form_page(request, "Join the newsletter", fields, "/newsletter")

    def newsletter_signup(self, request):
        from .web import Response
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        email = request.form.get("email", "").strip().lower()[:254]
        cadence = request.form.get("cadence", "monthly")
        if "@" not in email or cadence not in {"monthly", "weekly"}:
            return Response(b"Valid email and cadence required", 400)
        token = secrets.token_urlsafe(32)
        db = self.db()
        try:
            db.execute("INSERT INTO newsletter_subscribers(member_id,email,status,cadence,confirmed_at,unsubscribe_token_hash) VALUES (?,?, 'active',?,CURRENT_TIMESTAMP,?) ON CONFLICT(email) DO UPDATE SET status='active',cadence=excluded.cadence,confirmed_at=CURRENT_TIMESTAMP,unsubscribe_token_hash=excluded.unsubscribe_token_hash,updated_at=CURRENT_TIMESTAMP", (request.member["member_id"] if request.member else None, email, cadence, self._token_hash(token)))
            subscriber = db.execute("SELECT id FROM newsletter_subscribers WHERE email=?", (email,)).fetchone()
            db.execute("INSERT INTO analytics_events(event_type,object_type,object_id,member_id) VALUES ('newsletter_signup','newsletter_subscriber',?,?)", (subscriber["id"], request.member["member_id"] if request.member else None))
        finally:
            db.close()
        content = f'<h1>You’re subscribed</h1><p>Look for Movies We Missed on a {cadence} cadence.</p><p class="meta">Manage link: <a href="/newsletter/unsubscribe?token={token}">unsubscribe</a></p>'
        return self.html("Subscription confirmed", content, canonical="/newsletter")

    def newsletter_unsubscribe(self, request):
        from .web import Response
        token = request.query.get("token", [""])[0]
        if not token:
            return Response(b"Missing unsubscribe token", 400)
        db = self.db()
        try:
            result = db.execute("UPDATE newsletter_subscribers SET status='unsubscribed',updated_at=CURRENT_TIMESTAMP WHERE unsubscribe_token_hash=?", (self._token_hash(token),))
        finally:
            db.close()
        if not result.rowcount:
            return Response(b"Invalid or expired unsubscribe link", 404)
        return self.html("Unsubscribed", "<h1>You’re unsubscribed</h1><p>You won’t receive another issue unless you subscribe again.</p>", canonical="/newsletter/unsubscribe")

    def content_candidates(self):
        db = self.db()
        try:
            movies = [dict(row) for row in db.execute("SELECT id,title,slug,release_year FROM movies WHERE published=1 AND adult_content=0 ORDER BY created_at DESC LIMIT 6")]
            screenings = [dict(row) for row in db.execute("SELECT id,title,slug,starts_at,venue_name,city,region FROM screenings WHERE status IN ('announced','rsvp_open') AND starts_at>=CURRENT_TIMESTAMP ORDER BY starts_at LIMIT 6")]
        finally:
            db.close()
        return {"movies": movies, "screenings": screenings}

    def admin_newsletter(self, request):
        from .web import Response
        if not self._newsletter_admin(request):
            return Response(b"Forbidden", 403)
        db = self.db()
        try:
            issues = list(db.execute("SELECT * FROM newsletter_issues ORDER BY created_at DESC"))
            counts = dict(db.execute("SELECT status,count(*) FROM newsletter_subscribers GROUP BY status"))
        finally:
            db.close()
        items = "".join(f'<li>{escape(i["subject"])} — {i["status"]} — <a href="/admin/newsletter/{i["id"]}/preview">Preview</a></li>' for i in issues)
        return self.html("Newsletter operations", f'<h1>Newsletter</h1><p>Subscribers: {escape(str(counts))}</p><a class="button" href="/admin/newsletter/new">New issue</a><ul>{items}</ul>', canonical="/admin/newsletter")

    def newsletter_issue_form(self, request):
        from .web import Response
        if not self._newsletter_admin(request):
            return Response(b"Forbidden", 403)
        db = self.db()
        try:
            default = db.execute("SELECT value FROM settings WHERE key='newsletter_cadence'").fetchone()[0]
            sponsors = list(db.execute("SELECT * FROM sponsors WHERE active=1 AND (is_site_primary=1 OR paid=1) ORDER BY paid DESC,name"))
        finally:
            db.close()
        options = "".join(f'<option value="{s["id"]}">{escape(s["name"])}{" (paid)" if s["paid"] else " (default)"}</option>' for s in sponsors)
        fields = f'<label>Subject<input name="subject" required maxlength="200"></label><label>Introduction<textarea name="intro"></textarea></label><label>Cadence<select name="cadence"><option value="{default}">{default.title()} (current default)</option><option value="monthly">Monthly</option><option value="weekly">Weekly</option></select></label><label>Single sponsor slot<select name="sponsor_id">{options}</select></label><label class="check"><input type="checkbox" name="make_default" value="1"> Make this cadence the site default</label>'
        return self.form_page(request, "New newsletter issue", fields, "/admin/newsletter/new")

    def save_newsletter_issue(self, request):
        from .web import Response
        if not self._newsletter_admin(request):
            return Response(b"Forbidden", 403)
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        subject = request.form.get("subject", "").strip()[:200]
        cadence = request.form.get("cadence", "monthly")
        if not subject or cadence not in {"monthly", "weekly"}:
            return Response(b"Subject and valid cadence required", 400)
        db = self.db()
        try:
            sponsor_id = int(request.form.get("sponsor_id", "0"))
            sponsor = db.execute("SELECT id FROM sponsors WHERE id=? AND active=1", (sponsor_id,)).fetchone()
            if not sponsor:
                sponsor_id = db.execute("SELECT id FROM sponsors WHERE is_site_primary=1 AND active=1 ORDER BY id LIMIT 1").fetchone()[0]
            slug = f"{slugify(subject)}-{secrets.token_hex(3)}"
            issue_id = db.execute("INSERT INTO newsletter_issues(subject,slug,intro,cadence,sponsor_id,content_json) VALUES (?,?,?,?,?,?)", (subject, slug, request.form.get("intro", "").strip()[:4000], cadence, sponsor_id, json.dumps(self.content_candidates()))).lastrowid
            if request.form.get("make_default") == "1":
                db.execute("UPDATE settings SET value=?,updated_at=CURRENT_TIMESTAMP WHERE key='newsletter_cadence'", (cadence,))
            db.execute("INSERT INTO audit_log(actor_id,action,object_type,object_id) VALUES (?,'create_newsletter_issue','newsletter_issue',?)", (request.member["member_id"], issue_id))
        finally:
            db.close()
        return self.redirect(f"/admin/newsletter/{issue_id}/preview")

    def newsletter_preview(self, request, issue_id: int):
        from .web import Response
        if not self._newsletter_admin(request):
            return Response(b"Forbidden", 403)
        db = self.db()
        try:
            issue = db.execute("SELECT i.*,s.name sponsor_name FROM newsletter_issues i LEFT JOIN sponsors s ON s.id=i.sponsor_id WHERE i.id=?", (issue_id,)).fetchone()
        finally:
            db.close()
        if not issue:
            return Response(b"Not found", 404)
        content_data = json.loads(issue["content_json"])
        movies = "".join(f'<li><a href="/movies/{m["slug"]}">{escape(m["title"])}</a></li>' for m in content_data.get("movies", []))
        screenings = "".join(f'<li><a href="/screenings/{s["slug"]}">{escape(s["title"])}</a></li>' for s in content_data.get("screenings", []))
        send = f'<form method="post" action="/admin/newsletter/{issue_id}/send"><input type="hidden" name="csrf" value="{request.session["csrf_token"]}"><button>Send issue</button></form>'
        return self.html("Newsletter preview", f'<p class="meta">PREVIEW · {issue["cadence"]}</p><h1>{escape(issue["subject"])}</h1><p>{escape(issue["intro"])}</p><h2>Movies</h2><ul>{movies}</ul><h2>Screenings</h2><ul>{screenings}</ul><aside class="sponsor">Sponsored by {escape(issue["sponsor_name"] or "")}</aside>{send}', canonical=f"/admin/newsletter/{issue_id}/preview")

    def send_newsletter(self, request, issue_id: int):
        from .web import Response
        if not self._newsletter_admin(request):
            return Response(b"Forbidden", 403)
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        provider = get_email_provider(self.config)
        if provider.name == "disabled":
            return self.html("Email provider disabled", "<h1>Issue remains ready</h1><p>Configure EMAIL_PROVIDER to send. Preview and subscriber management remain available.</p>", canonical="/admin/newsletter")
        db = self.db()
        sent = 0
        try:
            issue = db.execute("SELECT * FROM newsletter_issues WHERE id=?", (issue_id,)).fetchone()
            if not issue:
                return Response(b"Not found", 404)
            for subscriber in db.execute("SELECT email FROM newsletter_subscribers WHERE status='active' AND cadence=?", (issue["cadence"],)):
                sent += int(provider.send(EmailMessage(subscriber["email"], issue["subject"], issue["intro"])))
            db.execute("UPDATE newsletter_issues SET status='sent',sent_at=CURRENT_TIMESTAMP,send_count=? WHERE id=?", (sent, issue_id))
        finally:
            db.close()
        return self.redirect("/admin/newsletter")
