from __future__ import annotations

import re
from html import escape
from urllib.parse import urlparse


class SponsorMixin:
    def dispatch_sponsors(self, request):
        match = re.fullmatch(r"/out/sponsor/(\d+)", request.path)
        if not match or request.method != "GET":
            return None
        from .web import Response
        sponsor_id = int(match.group(1))
        placement = request.query.get("placement", ["site"])[0][:80]
        db = self.db()
        try:
            sponsor = db.execute("SELECT * FROM sponsors WHERE id=? AND active=1", (sponsor_id,)).fetchone()
            if not sponsor:
                return Response(b"Not found", 404)
            if urlparse(sponsor["destination_url"]).scheme not in {"http", "https"}:
                return Response(b"Invalid sponsor destination", 500)
            member_id = request.member["member_id"] if request.member else None
            db.execute("INSERT INTO analytics_events(event_type,object_type,object_id,member_id,source,metadata_json) VALUES ('sponsor_click','sponsor',?,?,?,?)", (sponsor_id, member_id, placement, '{"placement":"' + placement.replace('"', '') + '"}'))
            if sponsor["is_site_primary"] or sponsor["name"].lower() == "it's made by hand":
                db.execute("INSERT INTO analytics_events(event_type,object_type,object_id,member_id,source) VALUES ('imbh_click','sponsor',?,?,?)", (sponsor_id, member_id, placement))
        finally:
            db.close()
        return Response(b"", 302, headers=(("Location", sponsor["destination_url"]), ("Referrer-Policy", "strict-origin-when-cross-origin")))

    def sponsor_for(self, placement: str):
        db = self.db()
        try:
            setting = db.execute("SELECT value FROM settings WHERE key=?", (f"sponsor_placement_{placement}",)).fetchone()
            if setting and setting["value"].isdigit():
                sponsor = db.execute("SELECT * FROM sponsors WHERE id=? AND active=1 AND (starts_on IS NULL OR starts_on<=date('now')) AND (ends_on IS NULL OR ends_on>=date('now'))", (int(setting["value"]),)).fetchone()
                if sponsor:
                    return sponsor
            return db.execute("SELECT * FROM sponsors WHERE active=1 AND is_site_primary=1 AND (starts_on IS NULL OR starts_on<=date('now')) AND (ends_on IS NULL OR ends_on>=date('now')) ORDER BY id LIMIT 1").fetchone()
        finally:
            db.close()

    def sponsor_block(self, placement: str = "site-footer") -> str:
        sponsor = self.sponsor_for(placement)
        if not sponsor:
            return ""
        return f'<aside class="sponsor"><small>{escape(sponsor["label"])}</small><p><a rel="sponsored" href="/out/sponsor/{sponsor["id"]}?placement={escape(placement)}">{escape(sponsor["name"])}</a></p></aside>'
