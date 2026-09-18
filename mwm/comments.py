from __future__ import annotations

from .mixins import AppMixin, safe_redirect_target

import re
from html import escape


class CommentMixin(AppMixin):
    def comment_routes(self):
        return {("GET", "/admin/comments"): self.moderation_queue}

    def dispatch_comments(self, request):
        thread = re.fullmatch(r"/(movies|screenings)/([^/]+)/comments", request.path)
        if thread:
            object_type = thread.group(1)[:-1]
            return self.comment_thread(request, object_type, thread.group(2))
        report = re.fullmatch(r"/comments/(\d+)/report", request.path)
        if report and request.method == "POST":
            return self.report_comment(request, int(report.group(1)))
        moderate = re.fullmatch(r"/admin/comments/(\d+)/(visible|hidden|deleted)", request.path)
        if moderate and request.method == "POST":
            return self.moderate_comment(request, int(moderate.group(1)), moderate.group(2))
        return None

    def comment_thread(self, request, object_type: str, slug: str):
        from .web import Response
        table = "movies" if object_type == "movie" else "screenings"
        db = self.db()
        try:
            obj = db.execute(f"SELECT id,title,slug FROM {table} WHERE slug=?", (slug,)).fetchone()
            if not obj:
                return Response(b"Not found", 404)
            if request.method == "POST":
                if not request.member:
                    return self.redirect("/login")
                if not self.valid_csrf(request):
                    return Response(b"Invalid CSRF token", 403)
                body = request.form.get("body", "").strip()
                if not 1 <= len(body) <= 4000:
                    return Response(b"Comment must be between 1 and 4000 characters", 400)
                db.execute("INSERT INTO comments(member_id,object_type,object_id,body) VALUES (?,?,?,?)", (request.member["member_id"], object_type, obj["id"], body))
                db.execute("INSERT INTO analytics_events(event_type,object_type,object_id,member_id) VALUES ('comment',?,?,?)", (object_type, obj["id"], request.member["member_id"]))
                return self.redirect(request.path)
            show_all = request.query.get("all", [""])[0] == "1"
            limit = 100 if show_all else 6
            comments = list(db.execute("SELECT c.*,m.display_name FROM comments c JOIN members m ON m.id=c.member_id WHERE c.object_type=? AND c.object_id=? AND c.status='visible' ORDER BY c.created_at DESC,c.id DESC LIMIT ?", (object_type, obj["id"], limit)))
        finally:
            db.close()
        has_more = not show_all and len(comments) > 5
        comments = comments[:5] if not show_all else comments
        rendered_comments = []
        for comment in comments:
            report = ""
            if request.member and comment["member_id"] != request.member["member_id"]:
                report = (
                    f'<form class="inline" method="post" action="/comments/{comment["id"]}/report">'
                    f'<input type="hidden" name="csrf" value="{request.session["csrf_token"]}">'
                    '<input type="hidden" name="reason" value="Flagged from discussion"><button type="submit">Report</button></form>'
                )
            rendered_comments.append(f'<article class="comment"><h3>{escape(comment["display_name"])}</h3><p>{escape(comment["body"])}</p><small>{comment["created_at"]}</small>{report}</article>')
        items = "".join(rendered_comments) or "<p>No comments yet. Start the conversation.</p>"
        more = f'<a class="button" href="{request.path}?all=1">View more comments</a>' if has_more else ""
        form = ""
        if request.member:
            form = f'<form class="stack" method="post"><input type="hidden" name="csrf" value="{request.session["csrf_token"]}"><label>Add to the discussion<textarea name="body" required maxlength="4000"></textarea></label><button>Post comment</button></form>'
        else:
            form = '<p><a href="/login">Log in</a> to comment.</p>'
        content = f'<p class="meta">{object_type.upper()} DISCUSSION</p><h1>{escape(obj["title"])}</h1>{form}<section class="comments">{items}</section>{more}'
        return self.html(f'{obj["title"]} discussion', content, canonical=request.path)

    def report_comment(self, request, comment_id: int):
        from .web import Response
        if not request.member:
            return self.redirect("/login")
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        reason = request.form.get("reason", "Needs moderator review").strip()[:500]
        db = self.db()
        try:
            if not db.execute("SELECT id FROM comments WHERE id=?", (comment_id,)).fetchone():
                return Response(b"Not found", 404)
            db.execute("INSERT OR IGNORE INTO comment_reports(comment_id,reporter_id,reason) VALUES (?,?,?)", (comment_id, request.member["member_id"], reason or "Needs moderator review"))
        finally:
            db.close()
        return self.redirect(safe_redirect_target(request.environ.get("HTTP_REFERER"), "/"))

    def moderation_queue(self, request):
        if not request.member or request.member["role"] not in {"moderator", "admin"}:
            from .web import Response
            return Response(b"Forbidden", 403)
        db = self.db()
        try:
            comments = list(db.execute("SELECT c.*,m.display_name,(SELECT count(*) FROM comment_reports r WHERE r.comment_id=c.id AND r.status='open') reports FROM comments c JOIN members m ON m.id=c.member_id ORDER BY reports DESC,c.created_at DESC LIMIT 100"))
        finally:
            db.close()
        items = "".join(f'<article class="comment"><h3>{escape(c["display_name"])}</h3><p>{escape(c["body"])}</p><p>Status: {c["status"]}; reports: {c["reports"]}</p><form method="post" action="/admin/comments/{c["id"]}/hidden"><input type="hidden" name="csrf" value="{request.session["csrf_token"]}"><button>Hide</button></form></article>' for c in comments)
        return self.html("Comment moderation", f"<h1>Comment moderation</h1>{items}", canonical="/admin/comments")

    def moderate_comment(self, request, comment_id: int, status: str):
        from .web import Response
        if not request.member or request.member["role"] not in {"moderator", "admin"}:
            return Response(b"Forbidden", 403)
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        db = self.db()
        try:
            db.execute("UPDATE comments SET status=?,moderated_by=?,moderated_at=CURRENT_TIMESTAMP,moderation_note=? WHERE id=?", (status, request.member["member_id"], request.form.get("note", "")[:500], comment_id))
            db.execute("UPDATE comment_reports SET status='reviewed' WHERE comment_id=?", (comment_id,))
            db.execute("INSERT INTO audit_log(actor_id,action,object_type,object_id) VALUES (?,'moderate_comment','comment',?)", (request.member["member_id"], comment_id))
        finally:
            db.close()
        return self.redirect("/admin/comments")
