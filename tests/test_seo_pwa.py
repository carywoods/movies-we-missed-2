import json

from mwm.config import Config
from mwm.db import connect
from mwm.web import create_app
from tests.web_client import request


def seo_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "seo.db"))
    monkeypatch.setenv("SITE_URL", "https://movies.example")
    app = create_app(Config.from_env())
    db = connect(app.config.database_path)
    db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES ('public','Public Movie','public-movie','high')")
    db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence,adult_content) VALUES ('restricted','Restricted Record','restricted-record','high',1)")
    db.close()
    return app


def test_metadata_canonical_social_and_structured_data(tmp_path, monkeypatch):
    app = seo_fixture(tmp_path, monkeypatch)
    status, _, body = request(app, "/movies/public-movie")
    assert status == 200
    assert b'<link rel="canonical" href="https://movies.example/movies/public-movie">' in body
    assert b'property="og:title"' in body
    assert b'application/ld+json' in body and b'"@type":"WebSite"' in body
    assert b'/manifest.webmanifest' in body and b'navigator.serviceWorker.register' in body


def test_sitemap_and_robots_are_public_safe(tmp_path, monkeypatch):
    app = seo_fixture(tmp_path, monkeypatch)
    status, headers, sitemap = request(app, "/sitemap.xml")
    assert status == 200 and headers["Content-Type"].startswith("application/xml")
    assert b"/movies/public-movie" in sitemap
    assert b"restricted-record" not in sitemap and b"/admin/" not in sitemap
    _, _, robots = request(app, "/robots.txt")
    assert b"Sitemap: https://movies.example/sitemap.xml" in robots
    assert b"Disallow: /admin/" in robots


def test_manifest_icon_worker_and_offline_fallback(tmp_path, monkeypatch):
    app = seo_fixture(tmp_path, monkeypatch)
    status, _, body = request(app, "/manifest.webmanifest")
    manifest = json.loads(body)
    assert status == 200 and manifest["display"] == "standalone"
    assert len(manifest["icons"]) == 2
    assert request(app, "/static/icon.svg")[0] == 200
    status, _, worker = request(app, "/sw.js")
    assert status == 200
    assert b"mwm-v3" in worker
    assert b"const SHELL=['/offline','/static/site.css','/static/site.js','/static/icon.svg']" in worker
    assert b"if(r.ok)" in worker
    assert b"caches.open(CACHE).then(c=>c.put(e.request,copy))" in worker
    assert b"caches.match(e.request)" in worker
    assert b"const SHELL=['/'" not in worker
    status, _, offline = request(app, "/offline")
    assert status == 200 and b"offline" in offline.lower()
