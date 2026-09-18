from __future__ import annotations

from .mixins import AppMixin

import json
from html import escape


class SeoMixin(AppMixin):
    def seo_routes(self):
        return {
            ("GET", "/sitemap.xml"): self.sitemap,
            ("GET", "/robots.txt"): self.robots,
            ("GET", "/manifest.webmanifest"): self.manifest,
            ("GET", "/sw.js"): self.service_worker,
            ("GET", "/offline"): self.offline,
            ("GET", "/static/icon.svg"): self.pwa_icon,
        }

    def sitemap(self, request):
        from .web import Response
        db = self.db()
        try:
            paths = ["/", "/movies", "/genres", "/collections", "/screenings", "/newsletter"]
            paths += [f'/movies/{r["slug"]}' for r in db.execute("SELECT slug FROM movies WHERE published=1 AND adult_content=0 ORDER BY slug")]
            paths += [f'/genres/{r["slug"]}' for r in db.execute("SELECT slug FROM genres ORDER BY slug")]
            paths += [f'/collections/{r["slug"]}' for r in db.execute("SELECT slug FROM collections WHERE adult_only=0 ORDER BY slug")]
            paths += [f'/screenings/{r["slug"]}' for r in db.execute("SELECT slug FROM screenings WHERE status IN ('announced','rsvp_open','full','completed') ORDER BY slug")]
        finally:
            db.close()
        urls = "".join(f'<url><loc>{escape(self.config.site_url + path)}</loc></url>' for path in paths)
        body = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'.encode()
        return Response(body, content_type="application/xml; charset=utf-8", headers=(("Cache-Control", "public, max-age=3600"),))

    def robots(self, request):
        from .web import Response
        body = f"User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /profile\nDisallow: /discover\nSitemap: {self.config.site_url}/sitemap.xml\n"
        return Response(body.encode(), content_type="text/plain; charset=utf-8")

    def manifest(self, request):
        from .web import Response
        payload = {
            "name": "Movies We Missed",
            "short_name": "Movies Missed",
            "description": "Find the film. Join the conversation. Meet at the movies.",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#fffdf7",
            "theme_color": "#b6402c",
            "icons": [
                {"src": "/static/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
                {"src": "/static/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "maskable"},
            ],
        }
        return Response(json.dumps(payload, separators=(",", ":")).encode(), content_type="application/manifest+json")

    def service_worker(self, request):
        from .web import Response
        # Cache only immutable shell assets. HTML can contain member state and CSRF tokens.
        script = r"""const CACHE='mwm-v2';const SHELL=['/offline','/static/site.css','/static/icon.svg'];const CACHEABLE=new Set(SHELL);self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL))));self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))));self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;const url=new URL(e.request.url);const cacheable=url.origin===self.location.origin&&CACHEABLE.has(url.pathname);if(!cacheable){if(e.request.mode==='navigate')e.respondWith(fetch(e.request).catch(()=>caches.match('/offline')));return;}e.respondWith(caches.match(e.request).then(hit=>hit||fetch(e.request).then(r=>{if(r.ok){const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy));}return r})));});"""
        return Response(script.encode(), content_type="application/javascript; charset=utf-8", headers=(("Service-Worker-Allowed", "/"), ("Cache-Control", "no-cache")))

    def offline(self, request):
        return self.html("Offline", '<section class="detail"><h1>You’re offline</h1><p>Previously visited pages may still be available. Reconnect to follow movies, comment, or RSVP.</p><p><a href="/">Try the home page</a></p></section>', canonical="/offline")

    def pwa_icon(self, request):
        from .web import Response
        icon = (__import__("pathlib").Path(__file__).parent / "static" / "icon.svg").read_bytes()
        return Response(icon, content_type="image/svg+xml", headers=(("Cache-Control", "public, max-age=86400"),))
