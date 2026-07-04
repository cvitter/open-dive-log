-- 002_opendivemap.sql
-- OpenDiveMap integration. Adds:
--   * country lookup (ISO 3166-1 alpha-2)
--   * site_source + site_external_id (multi-source external references)
--   * lookup_site_environment
--   * lookup_site_topology + site_site_topology join (multi-value)
--   * new columns on site: country_code, sea_mrgid, environment_id, entry_id
-- See src/open_dive_log/repositories/opendivemap.py for the import logic.
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Country. ISO 3166-1 alpha-2 code as PK, name as free text.
-- Seeded with a sensible starter set; the import will auto-insert new
-- country codes as they appear in upstream data.
-- ---------------------------------------------------------------------------
CREATE TABLE country (
    code        TEXT PRIMARY KEY,        -- 'MX', 'BZ', 'US', etc.
    name        TEXT NOT NULL UNIQUE    -- 'Mexico', 'Belize', 'United States'
);
CREATE INDEX idx_country_name ON country(name);

INSERT INTO country (code, name) VALUES
    ('MX', 'Mexico'),
    ('BZ', 'Belize'),
    ('US', 'United States'),
    ('CA', 'Canada'),
    ('ID', 'Indonesia'),
    ('PH', 'Philippines'),
    ('TH', 'Thailand'),
    ('MY', 'Malaysia'),
    ('AU', 'Australia'),
    ('EG', 'Egypt'),
    ('NL', 'Netherlands'),
    ('BS', 'Bahamas'),
    ('CW', 'Curaçao'),
    ('AW', 'Aruba'),
    ('HN', 'Honduras'),
    ('CR', 'Costa Rica'),
    ('PA', 'Panama'),
    ('CO', 'Colombia'),
    ('BR', 'Brazil'),
    ('AR', 'Argentina'),
    ('CL', 'Chile'),
    ('PE', 'Peru'),
    ('JP', 'Japan'),
    ('TW', 'Taiwan'),
    ('KR', 'South Korea'),
    ('FJ', 'Fiji'),
    ('NZ', 'New Zealand'),
    ('PG', 'Papua New Guinea'),
    ('MV', 'Maldives'),
    ('SC', 'Seychelles'),
    ('ZA', 'South Africa'),
    ('IT', 'Italy'),
    ('GR', 'Greece'),
    ('HR', 'Croatia'),
    ('ES', 'Spain'),
    ('PT', 'Portugal'),
    ('FR', 'France'),
    ('MT', 'Malta'),
    ('CY', 'Cyprus'),
    ('TR', 'Türkiye'),
    ('IL', 'Israel'),
    ('JO', 'Jordan'),
    ('AE', 'United Arab Emirates'),
    ('SA', 'Saudi Arabia'),
    ('IN', 'India'),
    ('LK', 'Sri Lanka'),
    ('VN', 'Vietnam'),
    ('KH', 'Cambodia'),
    ('MM', 'Myanmar'),
    ('BN', 'Brunei'),
    ('SG', 'Singapore'),
    ('HK', 'Hong Kong'),
    ('CN', 'China'),
    ('GB', 'United Kingdom'),
    ('IE', 'Ireland'),
    ('IS', 'Iceland'),
    ('NO', 'Norway'),
    ('SE', 'Sweden'),
    ('DK', 'Denmark'),
    ('FI', 'Finland'),
    ('PL', 'Poland'),
    ('DE', 'Germany');

-- ---------------------------------------------------------------------------
-- Site source catalog. Lets us reference the same site from multiple open
-- data sources. See site_external_id below.
-- ---------------------------------------------------------------------------
CREATE TABLE site_source (
    id          INTEGER PRIMARY KEY,
    system_name TEXT NOT NULL UNIQUE,    -- 'opendivemap', 'padi', etc.
    base_url    TEXT,                    -- human home page of the source
    api_url     TEXT,                    -- canonical API root, if any
    license     TEXT,                    -- 'ODbL', etc.
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO site_source (system_name, base_url, api_url, license, notes) VALUES
    ('opendivemap', 'https://opendivemap.com', 'https://api.opendivemap.com/v1', 'ODbL',
     'Community-driven open database of dive sites. GeoJSON, 6-char base36 ids.');

-- ---------------------------------------------------------------------------
-- External id join. (site_id, source_id) UNIQUE so a site can have at most
-- one id per source. (source_id, external_id) UNIQUE so an external id
-- resolves to at most one site in our DB.
-- ---------------------------------------------------------------------------
CREATE TABLE site_external_id (
    id           INTEGER PRIMARY KEY,
    site_id      INTEGER NOT NULL REFERENCES site(id) ON DELETE CASCADE,
    source_id    INTEGER NOT NULL REFERENCES site_source(id) ON DELETE RESTRICT,
    external_id  TEXT NOT NULL,
    external_url TEXT,                    -- canonical link to the upstream record
    fetched_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (site_id, source_id),
    UNIQUE (source_id, external_id)
);
CREATE INDEX idx_site_external_site ON site_external_id(site_id);

-- ---------------------------------------------------------------------------
-- Site environment lookup. Where the dive happens — exactly one per site.
-- ---------------------------------------------------------------------------
CREATE TABLE lookup_site_environment (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
INSERT INTO lookup_site_environment (name, display_order) VALUES
    ('ocean', 1),
    ('lake', 2),
    ('river', 3),
    ('spring', 4),
    ('quarry', 5),
    ('fjord', 6),
    ('pool', 7),
    ('other', 99);

-- ---------------------------------------------------------------------------
-- Site topology lookup. Terrain features — one or more per site, modeled
-- via the site_site_topology join below.
-- ---------------------------------------------------------------------------
CREATE TABLE lookup_site_topology (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
INSERT INTO lookup_site_topology (name, display_order) VALUES
    ('reef', 1),
    ('wall', 2),
    ('pinnacle', 3),
    ('wreck', 4),
    ('cave', 5),
    ('cavern', 6),
    ('blue_hole', 7),
    ('muck', 8),
    ('kelp_forest', 9),
    ('channel', 10),
    ('artificial_reef', 11),
    ('open_water', 12),
    ('other', 99);

CREATE TABLE site_site_topology (
    site_id     INTEGER NOT NULL REFERENCES site(id) ON DELETE CASCADE,
    topology_id INTEGER NOT NULL REFERENCES lookup_site_topology(id) ON DELETE RESTRICT,
    PRIMARY KEY (site_id, topology_id)
);
CREATE INDEX idx_site_site_topology_topology ON site_site_topology(topology_id);

-- ---------------------------------------------------------------------------
-- Extend site. New columns are nullable so existing rows (and the migration
-- of an existing dive-log) survive without backfill. The import will fill
-- them in for the new opendivemap-imported rows.
-- ---------------------------------------------------------------------------
ALTER TABLE site ADD COLUMN country_code    TEXT REFERENCES country(code);
ALTER TABLE site ADD COLUMN sea_mrgid       INTEGER;                -- Marine Regions
ALTER TABLE site ADD COLUMN environment_id  INTEGER REFERENCES lookup_site_environment(id);
ALTER TABLE site ADD COLUMN entry_id        INTEGER REFERENCES lookup_entry_type(id);
ALTER TABLE site ADD COLUMN max_depth_m     REAL;                   -- site-level max depth (m)

CREATE INDEX idx_site_country_code ON site(country_code);
CREATE INDEX idx_site_environment ON site(environment_id);
CREATE INDEX idx_site_sea_mrgid ON site(sea_mrgid);
