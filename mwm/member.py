from __future__ import annotations

import hmac
from html import escape

from .auth import cookie_header, create_session, destroy_session, hash_password, verify_password


class MemberMixin:
    def member_routes(self):
        return {
            ("GET", "/register"): self.register_form,
            ("POST", "/register"): self.register,
            ("GET", "/login"): self.login_form,
            ("POST", "/login"): self.login,
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
        message = f'<p class="notice" role="alert">{escape(error)}</p>' if error else ""
        content = f'<section class="detail"><h1>{escape(title)}</h1>{message}<form class="stack" method="post" action="{action}"><input type="hidden" name="csrf" value="{request.session["csrf_token"]}">{fields}<button type="submit">{escape(title)}</button></form></section>'
        return self.html(title, content, canonical=action)

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
        fields = '<label>Email<input name="email" required type="email" autocomplete="email"></label><label>Password<input name="password" required type="password" autocomplete="current-password"></label>'
        return self.form_page(request, "Log in", fields, "/login")

    def login(self, request):
        from .web import Response
        if not self.valid_csrf(request):
            return Response(b"Invalid CSRF token", 403)
        db = self.db()
        try:
            member = db.execute("SELECT * FROM members WHERE email=? AND status='active'", (request.form.get("email", "").strip().lower(),)).fetchone()
        finally:
            db.close()
        if not member or not verify_password(request.form.get("password", ""), member["password_hash"]):
            fields = '<label>Email<input name="email" required type="email"></label><label>Password<input name="password" required type="password"></label>'
            return self.form_page(request, "Log in", fields, "/login", "Email or password was not recognized.")
        destroy_session(self.config, request.session_token)
        token, _ = create_session(self.config, member["id"])
        return self.redirect("/profile", (cookie_header(self.config, token),))

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
        checked_adult = " checked" if request.member["show_adult"] else ""
        fields = f'<label>Display name<input name="display_name" value="{escape(request.member["display_name"])}" required maxlength="80"></label><label class="check"><input type="checkbox" name="interests_public" value="1"{checked_public}> Make my movie interests public</label><label class="check"><input type="checkbox" name="show_adult" value="1"{checked_adult}> Show clearly labeled adult collections</label>'
        logout = f'<form method="post" action="/logout"><input type="hidden" name="csrf" value="{request.session["csrf_token"]}"><button>Log out</button></form>'
        response = self.form_page(request, "Your profile", fields, "/profile")
        response.body = response.body.replace(b"</section>", logout.encode() + b"</section>", 1)
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
            db.execute("UPDATE members SET display_name=?,interests_public=?,show_adult=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (display, int(request.form.get("interests_public") == "1"), int(request.form.get("show_adult") == "1"), request.member["member_id"]))
        finally:
            db.close()
        return self.redirect("/profile")
