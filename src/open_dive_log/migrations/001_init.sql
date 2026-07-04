-- 001_init.sql
-- Open Dive Log schema v1.
-- See src/open_dive_log/models.py for the field-to-column mapping that
-- justified each choice. This file is the source of truth for the DDL.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Migration tracking. Single-row table (id always 0) holds the current
-- schema version. This lets the app detect a stale database and refuse to
-- start rather than silently corrupting it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_meta (
    id          INTEGER PRIMARY KEY CHECK (id = 0),
    version     INTEGER NOT NULL,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Site (dive location). Referenced by dive_site join so a single dive can
-- span multiple sites in a defined order.
-- ---------------------------------------------------------------------------
CREATE TABLE site (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    region      TEXT,        -- e.g. "South Coast", "Bay Islands"
    country     TEXT,        -- ISO-ish, free-form for now
    latitude    REAL,        -- decimal degrees, WGS84
    longitude   REAL,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (name, country)  -- same name allowed in different countries
);
CREATE INDEX idx_site_name ON site(name);
CREATE INDEX idx_site_country ON site(country);

-- ---------------------------------------------------------------------------
-- Buddy. Deduplicated on a normalized full_name so "Mike Smith" and
-- "mike smith" collapse to the same row. The app normalizes on insert.
-- ---------------------------------------------------------------------------
CREATE TABLE buddy (
    id                    INTEGER PRIMARY KEY,
    first_name            TEXT NOT NULL,
    last_name             TEXT NOT NULL,
    full_name             TEXT NOT NULL,        -- canonical, display form
    full_name_normalized  TEXT NOT NULL,        -- lower(trim(...)) for dedup
    notes                 TEXT,
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (full_name_normalized)
);
CREATE INDEX idx_buddy_last_name ON buddy(last_name);

-- ---------------------------------------------------------------------------
-- Lookup tables. All share the same shape:
--   id           PK
--   name         display value, UNIQUE
--   display_order for stable sort in comboboxes
--   is_active    lets you retire a value without deleting it (preserves FK)
-- Naming pattern: lookup_<field> so they're easy to enumerate.
-- ---------------------------------------------------------------------------
CREATE TABLE lookup_time_of_day (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
CREATE TABLE lookup_entry_type (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
CREATE TABLE lookup_surface_conditions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
CREATE TABLE lookup_equipment_type (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
CREATE TABLE lookup_tank_type (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
CREATE TABLE lookup_tank_configuration (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
CREATE TABLE lookup_gas_type (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
CREATE TABLE lookup_purpose (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);
CREATE TABLE lookup_buddy_role (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

-- ---------------------------------------------------------------------------
-- Seed lookup values.
-- ---------------------------------------------------------------------------
INSERT INTO lookup_time_of_day (name, display_order) VALUES
    ('dawn', 1),
    ('day', 2),
    ('dusk', 3),
    ('night', 4),
    ('full_moon', 5),
    ('other', 99);

INSERT INTO lookup_entry_type (name, display_order) VALUES
    ('shore', 1),
    ('boat', 2),
    ('other', 99);

INSERT INTO lookup_surface_conditions (name, display_order) VALUES
    ('calm', 1),
    ('choppy', 2),
    ('rough', 3),
    ('surge', 4),
    ('glassy', 5),
    ('other', 99);

INSERT INTO lookup_equipment_type (name, display_order) VALUES
    ('open_circuit', 1),
    ('semi_closed_circuit_rebreather', 2),
    ('closed_circuit_rebreather', 3),
    ('other', 99);

INSERT INTO lookup_tank_type (name, display_order) VALUES
    ('aluminum', 1),
    ('steel', 2);

INSERT INTO lookup_tank_configuration (name, display_order) VALUES
    ('single', 1),
    ('double', 2),
    ('sidemount', 3),
    ('other', 99);

INSERT INTO lookup_gas_type (name, display_order) VALUES
    ('air', 1),
    ('nitrox', 2),
    ('trimix', 3),
    ('other', 99);

INSERT INTO lookup_purpose (name, display_order) VALUES
    ('recreation', 1),
    ('training', 2),
    ('commercial', 3),
    ('photography', 4),
    ('other', 99);

INSERT INTO lookup_buddy_role (name, display_order) VALUES
    ('buddy', 1),
    ('lead', 2),
    ('student', 3),
    ('instructor', 4);

-- ---------------------------------------------------------------------------
-- Dive. The main fact table.
-- ---------------------------------------------------------------------------
CREATE TABLE dive (
    id                          INTEGER PRIMARY KEY,

    -- When
    dive_date                   TEXT NOT NULL,                -- 'YYYY-MM-DD'
    start_time                  TEXT,                         -- 'HH:MM' 24h, nullable
    end_time                    TEXT,                         -- 'HH:MM' 24h, nullable
    dive_time_minutes           INTEGER,                      -- computed-or-entered; if both end_time and dive_time are present they should agree
    time_of_day_id              INTEGER REFERENCES lookup_time_of_day(id),

    -- Entry
    entry_type_id               INTEGER REFERENCES lookup_entry_type(id),
    entry_notes                 TEXT,

    -- Surface
    surface_conditions_id       INTEGER REFERENCES lookup_surface_conditions(id),
    surface_conditions_notes    TEXT,

    -- Run time at surface (boat ride, surface interval — distinct from dive_time)
    run_time_minutes            INTEGER,

    -- Depth (meters)
    max_depth_m                 REAL,
    avg_depth_m                 REAL,                         -- manual or computed

    -- Equipment
    equipment_type_id           INTEGER REFERENCES lookup_equipment_type(id),
    tank_type_id                INTEGER REFERENCES lookup_tank_type(id),
    tank_configuration_id       INTEGER REFERENCES lookup_tank_configuration(id),
    gas_type_id                 INTEGER REFERENCES lookup_gas_type(id),
    o2_percentage               REAL CHECK (o2_percentage IS NULL OR (o2_percentage >= 0 AND o2_percentage <= 100)),
    mix_notes                   TEXT,
    gear_notes                  TEXT,

    -- Purpose & people
    purpose_id                  INTEGER REFERENCES lookup_purpose(id),

    -- Free text
    notes                       TEXT,

    -- Bookkeeping
    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_dive_date ON dive(dive_date DESC);
CREATE INDEX idx_dive_purpose ON dive(purpose_id);
CREATE INDEX idx_dive_time_of_day ON dive(time_of_day_id);

-- ---------------------------------------------------------------------------
-- Join: dive <-> site with ordering. (dive_id, site_order) is unique so a
-- dive can have site #1, #2, #3, etc.
-- ---------------------------------------------------------------------------
CREATE TABLE dive_site (
    dive_id     INTEGER NOT NULL REFERENCES dive(id) ON DELETE CASCADE,
    site_id     INTEGER NOT NULL REFERENCES site(id) ON DELETE RESTRICT,
    site_order  INTEGER NOT NULL CHECK (site_order >= 1),
    PRIMARY KEY (dive_id, site_order),
    UNIQUE (dive_id, site_id)            -- a site appears at most once per dive
);
CREATE INDEX idx_dive_site_site ON dive_site(site_id);

-- ---------------------------------------------------------------------------
-- Join: dive <-> buddy with a role.
-- ---------------------------------------------------------------------------
CREATE TABLE dive_buddy (
    dive_id   INTEGER NOT NULL REFERENCES dive(id) ON DELETE CASCADE,
    buddy_id  INTEGER NOT NULL REFERENCES buddy(id) ON DELETE RESTRICT,
    role_id   INTEGER REFERENCES lookup_buddy_role(id),
    PRIMARY KEY (dive_id, buddy_id)
);
CREATE INDEX idx_dive_buddy_buddy ON dive_buddy(buddy_id);

-- ---------------------------------------------------------------------------
-- Triggers to keep updated_at honest. (SQLite doesn't auto-update on UPDATE
-- without these; we could also do it in the app, but DB-level is harder to
-- forget.)
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_dive_updated_at AFTER UPDATE ON dive
BEGIN
    UPDATE dive SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER trg_site_updated_at AFTER UPDATE ON site
BEGIN
    UPDATE site SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER trg_buddy_updated_at AFTER UPDATE ON buddy
BEGIN
    UPDATE buddy SET updated_at = datetime('now') WHERE id = NEW.id;
END;
