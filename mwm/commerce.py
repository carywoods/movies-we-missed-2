from __future__ import annotations

from .mixins import AppMixin

import re
from html import escape
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def amazon_affiliate_url(destination: str, tag: str) -> str:
    if not tag:
        return destination
    parsed = urlparse(destination)
    if parsed.hostname not in {"amazon.com", "www.amazon.com"}:
        return destination
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["tag"] = tag
    return urlunparse(parsed._replace(query=urlencode(query)))


class CommerceMixin(AppMixin):
    def dispatch_commerce(self, request):
        match = re.fullmatch(r"/out/merchandise/(\d+)", request.path)
        if not match or request.method != "GET":
            return None
        from .web import Response
        db = self.db()
        try:
            offer = db.execute("SELECT * FROM merchandise WHERE id=? AND active=1", (int(match.group(1)),)).fetchone()
            if not offer:
                return Response(b"Not found", 404)
            destination = offer["affiliate_url"] or amazon_affiliate_url(offer["destination_url"], self.config.amazon_associate_tag)
            member_id = request.member["member_id"] if request.member else None
            db.execute("INSERT INTO analytics_events(event_type,object_type,object_id,member_id,source) VALUES ('merchandise_click','merchandise',?,?,?)", (offer["id"], member_id, offer["merchant"]))
            if offer["merchant"].lower() == "amazon":
                db.execute("INSERT INTO analytics_events(event_type,object_type,object_id,member_id,source) VALUES ('amazon_click','merchandise',?,?,?)", (offer["id"], member_id, "amazon-associates"))
        finally:
            db.close()
        return Response(b"", 302, headers=(("Location", destination), ("Referrer-Policy", "no-referrer")))

    def offers_for_movie(self, movie_id: int, include_adult: bool = False):
        db = self.db()
        try:
            return list(db.execute(
                "SELECT * FROM merchandise WHERE active=1 AND (movie_id=? OR movie_id IS NULL) AND (audience!='adult' OR ?) ORDER BY CASE WHEN movie_id=? THEN 0 ELSE 1 END,priority DESC LIMIT 4",
                (movie_id, int(include_adult), movie_id),
            ))
        finally:
            db.close()

    def commerce_panel(self, movie_id: int) -> str:
        offers = self.offers_for_movie(movie_id)
        links = "".join(f'<li><a rel="sponsored nofollow" href="/out/merchandise/{offer["id"]}">{escape(offer["display_label"])}</a> <small>{escape(offer["merchant"])}</small></li>' for offer in offers)
        return f'<aside class="commerce"><p class="meta">MOVIE-NIGHT SHOP</p><ul>{links}</ul><small>Purchases through affiliate links may support Movies We Missed.</small></aside>'
