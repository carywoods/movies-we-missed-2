UPDATE collections
SET name='Erotica',
    slug='erotica',
    description='Stories centered on desire, intimacy, and erotic themes.',
    adult_only=0
WHERE slug='adult-erotic-cinema';

INSERT INTO collections(name,slug,description,adult_only,family_safe)
VALUES ('LGBQ Stories','lgbq-stories','Movies centered on lesbian, gay, bisexual, and queer lives and stories.',0,0)
ON CONFLICT(slug) DO UPDATE SET name=excluded.name,description=excluded.description,adult_only=0;

INSERT INTO collections(name,slug,description,adult_only,family_safe)
VALUES ('Recent Additions','recent-additions','Newly added titles awaiting deeper editorial classification.',0,0)
ON CONFLICT(slug) DO UPDATE SET name=excluded.name,description=excluded.description,adult_only=0;

INSERT INTO collections(name,slug,description,adult_only,family_safe)
VALUES ('Comics & Graphic Novels','comics-graphic-novels','Screen stories adapted from comics and graphic novels.',0,0)
ON CONFLICT(slug) DO UPDATE SET name=excluded.name,description=excluded.description,adult_only=0;

INSERT INTO movie_collections(movie_id,collection_id,source,confidence)
SELECT DISTINCT s.movie_id,c.id,'migration',1.0
FROM movie_sources s JOIN collections c ON c.slug='recent-additions'
WHERE s.source_category='new'
ON CONFLICT(movie_id,collection_id) DO NOTHING;

INSERT INTO movie_collections(movie_id,collection_id,source,confidence)
SELECT DISTINCT s.movie_id,c.id,'migration',1.0
FROM movie_sources s JOIN collections c ON c.slug='comics-graphic-novels'
WHERE s.source_category='comics'
ON CONFLICT(movie_id,collection_id) DO NOTHING;

UPDATE movies SET adult_content=0
WHERE id IN (SELECT movie_id FROM movie_sources WHERE source_category='soft');
