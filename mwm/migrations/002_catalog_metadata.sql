INSERT INTO genres(name,slug,description) VALUES
    ('Adventure','adventure','Journeys, quests, exploration, and discovery.'),
    ('Crime','crime','Stories centered on crime, investigation, and consequence.'),
    ('Fantasy','fantasy','Mythic worlds, magic, and imaginative possibilities.'),
    ('History','history','Stories shaped by historical people and events.'),
    ('Horror','horror','Cinema built around fear, dread, and the uncanny.'),
    ('Music','music','Performances, artists, and stories driven by music.'),
    ('Mystery','mystery','Puzzles, secrets, and investigations.'),
    ('Romance','romance','Stories centered on love and relationships.'),
    ('Thriller','thriller','Suspenseful stories driven by danger and uncertainty.'),
    ('War','war','Stories of armed conflict and the people affected by it.'),
    ('Western','western','Frontier stories and modern variations on the Western.')
ON CONFLICT(slug) DO UPDATE SET description=excluded.description;

INSERT INTO collections(name,slug,description,adult_only,family_safe) VALUES
    ('Recent Additions','recent-additions','Movies newly added to the library, across every genre.',0,0),
    ('Comic Book Movies','comic-book-movies','Superheroes, graphic-novel adaptations, and comic-book cinema.',0,0)
ON CONFLICT(slug) DO UPDATE SET description=excluded.description;

INSERT OR IGNORE INTO movie_collections(movie_id,collection_id,source,confidence)
SELECT DISTINCT ms.movie_id,c.id,'inventory-category',1.0
FROM movie_sources ms CROSS JOIN collections c
WHERE ms.source_category='new' AND c.slug='recent-additions';

INSERT OR IGNORE INTO movie_collections(movie_id,collection_id,source,confidence)
SELECT DISTINCT ms.movie_id,c.id,'inventory-category',1.0
FROM movie_sources ms CROSS JOIN collections c
WHERE ms.source_category='comics' AND c.slug='comic-book-movies';

INSERT OR IGNORE INTO movie_genres(movie_id,genre_id,source,confidence)
SELECT DISTINCT ms.movie_id,g.id,'inventory-category',1.0
FROM movie_sources ms JOIN genres g ON g.slug IN ('action','science-fiction')
WHERE ms.source_category='comics';
