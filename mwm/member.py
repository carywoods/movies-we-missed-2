from __future__ import annotations

from .mixins import AppMixin

import hmac
import secrets
from html import escape

from .auth import cookie_header, create_session, destroy_session, hash_password, token_hash, verify_password
from .emailer import EmailMessage, get_email_provider


class MemberMixin(AppMixin):
    def member_routes(self):
        return {
            ("GET", "/register"): self.register_form,
            ("POST", "/register"): self.register,
            ("GET", "/login"): self.login_form,
            ("POST", "/login"): self.login,
            ("GET", "/forgot-password"): self.forgot_password_form,
            ("POST", "/forgot-password"): self.forgot_password,
            ("GET", "/reset-password"): self.password_reset_form,
            ("POST", "/reset-password"): self.reset_password,
            ("POST", "/logout"): self.logout,
            ("GET", "/profile"): self.profile,
            ("POST", "/profile"): self.update_profile,
        }

    def redirect(self, location: str, headers=()):
        from .web import Response
        return Response(b"", 303, headers=(("Location", location), *headers))

    def valid_csrf(self, request) -> bool:
        return bool(request.session and request.form and hmac.compare_digest(request.session["csrf_token"], request.form.get("csrf", "")))

    def form_page(self, request, title: str, fields: str, action: str, error: str = ""):
        return self.html(title, self.form_markup(request, title, fields, action, error), canonical=action)

    def form_markup(self, request, title: str, fields: str, action: str, error: str = "") -> str:
        message = f'<p class="notice" role="alert">{escape(error)}</p>' if error else ""
        return f'<section class="detail"><h1>{escape(title)}</h1>{message}<form class="stack" method="post" action="{escape(action, quote=True)}"><input type="hidden" name="csrf" value="{request.session["csrf_token"]}">{fields}<button type="submit">{escape(title)}</button></form></section>'

    def register_form(self, request):
        fields = '<label>Display name<input name="display_name" required maxlength="80" autocomplete="name"></label><label>Email<input name="email" required type="email" autocomplete="email"></label><label>Password<input name="password" required type="password" minlength="10" autocomplete="new-password"></label>'
        return self.form_page(request, "Create account", fields, "/register")

    def register(self, request):
        from .web import Response
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        email = request.form.get("email", "").strip().lower()[:254]
        display = request.form.get("display_name", "").strip()[:80]
        password = request.form.get("password", "")
        fields = '<label>Display name<input name="display_name" required maxlength="80"></label><label>Email<input name="email" required type="email"></label><label>Password<input name="password" required type="password" minlength="10"></label>'
        if "@" not in email or not display or len(password) < 10:
            return self.form_page(request, "Create account", fields, "/register", "Use a valid email, display name, and password of at least 10 characters.")
        db = self.db()
        try:
            try:
                member_id = db.execute("INSERT INTO members(email,password_hash,display_name) VALUES (?,?,?)", (email, hash_password(password), display)).lastrowid
            except Exception as exc:
                if "UNIQUE" in str(exc):
                    return self.form_page(request, "Create account", fields, "/register", "An account with that email already exists.")
                raise
        finally:
            db.close()
        destroy_session(self.config, request.session_token)
        token, _ = create_session(self.config, member_id)
        return self.redirect("/profile", (cookie_header(self.config, token),))

    def login_form(self, request):
        fields = '<label>Email<input name="email" required type="email" autocomplete="email"></label><label>Password<input name="password" required type="password" autocomplete="current-password"></label><p><a href="/forgot-password">Forgot password?</a></p>'
        return self.form_page(request, "Log in", fields, "/login")

    def login(self, request):
        from .web import Response
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        if self.auth_rate_limited(request):
            return Response(b"Too many login attempts. Try again later.", 429)
        db = self.db()
        try:
            member = db.execute("SELECT * FROM members WHERE email=? AND status='active'", (request.form.get("email", "").strip().lower(),)).fetchone()
        finally:
            db.close()
        if not member or not verify_password(request.form.get("password", ""), member["password_hash"]):
            self.record_auth_failure(request)
            fields = '<label>Email<input name="email" required type="email"></label><label>Password<input name="password" required type="password"></label>'
            return self.form_page(request, "Log in", fields, "/login", "Email or password was not recognized.")
        self.clear_auth_failures(request)
        destroy_session(self.config, request.session_token)
        token, _ = create_session(self.config, member["id"])
        return self.redirect("/profile", (cookie_header(self.config, token),))

    def forgot_password_form(self, request):
        fields = '<label>Email<input name="email" required type="email" autocomplete="email"></label>'
        return self.form_page(request, "Reset password", fields, "/forgot-password")

    def forgot_password(self, request):
        from .web import Response
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        email = request.form.get("email", "").strip().lower()[:254]
        db = self.db()
        try:
            member = db.execute("SELECT id,email FROM members WHERE email=? AND status='active'", (email,)).fetchone()
            provider = get_email_provider(self.config)
            if member and provider.name != "disabled":
                raw_token = secrets.token_urlsafe(32)
                db.execute("DELETE FROM password_reset_tokens WHERE member_id=? OR expires_at<CURRENT_TIMESTAMP", (member["id"],))
                db.execute(
                    "INSERT INTO password_reset_tokens(member_id,token_hash,expires_at) VALUES (?,?,datetime('now','+1 hour'))",
                    (member["id"], token_hash(raw_token)),
                )
                reset_url = f'{self.config.site_url.rstrip("/")}/reset-password?token={raw_token}'
                body = f'<h1>Reset your password</h1><p><a href="{escape(reset_url, quote=True)}">Choose a new password</a>. This link expires in one hour.</p>'
                try:
                    provider.send(EmailMessage(member["email"], "Reset your Movies We Missed password", body))
                except Exception:
                    pass
        finally:
            db.close()
        return self.html(
            "Check your email",
            "<h1>Check your email</h1><p>If an active account matches that address, a reset link has been sent.</p>",
            canonical="/forgot-password",
        )

    def password_reset_form(self, request):
        from .web import Response
        token = request.query.get("token", [""])[0]
        if not token:
            return Response(b"Missing reset token", 400)
        fields = f'<input type="hidden" name="token" value="{escape(token, quote=True)}"><label>New password<input name="password" required type="password" minlength="10" autocomplete="new-password"></label>'
        return self.form_page(request, "Choose a new password", fields, "/reset-password")

    def reset_password(self, request):
        from .web import Response
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        raw_token = request.form.get("token", "")
        password = request.form.get("password", "")
        if not raw_token or len(password) < 10:
            return Response(b"Valid reset token and password of at least 10 characters required", 400)
        db = self.db()
        try:
            db.execute("BEGIN IMMEDIATE")
            reset = db.execute("SELECT * FROM password_reset_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at>CURRENT_TIMESTAMP", (token_hash(raw_token),)).fetchone()
            if not reset:
                db.execute("ROLLBACK")
                return Response(b"Invalid or expired reset link", 400)
            db.execute("UPDATE members SET password_hash=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (hash_password(password), reset["member_id"]))
            db.execute("UPDATE password_reset_tokens SET used_at=CURRENT_TIMESTAMP WHERE id=?", (reset["id"],))
            db.execute("DELETE FROM sessions WHERE member_id=?", (reset["member_id"],))
            db.execute("INSERT INTO audit_log(actor_id,action,object_type,object_id) VALUES (?,'reset_password','member',?)", (reset["member_id"], reset["member_id"]))
            db.execute("COMMIT")
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()
        return self.redirect("/login")

    def logout(self, request):
        from .web import Response
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        destroy_session(self.config, request.session_token)
        return self.redirect("/", (cookie_header(self.config, "", clear=True),))

    def profile(self, request):
        if not request.member:
            return self.redirect("/login")
        checked_public = " checked" if request.member["interests_public"] else ""
        db = self.db()
        try:
            notifications = list(db.execute("SELECT * FROM notifications WHERE member_id=? ORDER BY created_at DESC LIMIT 10", (request.member["member_id"],)))
        finally:
            db.close()
        notices = "".join(
            f'<li><a href="{escape(n["destination_url"] or "/", quote=True)}">{escape(n["title"])}</a> — {escape(n["body"])}</li>'
            for n in notifications
        ) or "<li>No notifications yet.</li>"
        fields = f'<label>Display name<input name="display_name" value="{escape(request.member["display_name"])}" required maxlength="80"></label><label class="check"><input type="checkbox" name="interests_public" value="1"{checked_public}> Make my movie interests public</label>'
        logout = f'<form method="post" action="/logout"><input type="hidden" name="csrf" value="{request.session["csrf_token"]}"><button>Log out</button></form>'
        response = self.form_page(request, "Your profile", fields, "/profile")
        account_extras = f'{logout}<h2>Notifications</h2><ul>{notices}</ul>'
        response.body = response.body.replace(b"</section>", account_extras.encode() + b"</section>", 1)
        return response

    def update_profile(self, request):
        from .web import Response
        if not request.member:
            return self.redirect("/login")
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        display = request.form.get("display_name", "").strip()[:80]
        if not display:
            return Response(b"Display name is required", 400)
        db = self.db()
        try:
            db.execute("UPDATE members SET display_name=?,interests_public=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (display, int(request.form.get("interests_public") == "1"), request.member["member_id"]))
        finally:
            db.close()
        return self.redirect("/profile")
