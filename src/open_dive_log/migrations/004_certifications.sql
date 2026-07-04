-- 004_certifications.sql
-- Certifications earned by the diver. Independent of any specific dive;
-- a cert is about the diver, not a dive entry.

CREATE TABLE lookup_certifying_agency (
    id            INTEGER PRIMARY KEY,
    name          TEXT    NOT NULL UNIQUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

-- Major recreational + technical agencies. Add yours via the lookup
-- table; the UI will surface new entries when the form reloads.
INSERT INTO lookup_certifying_agency (name, display_order) VALUES
    ('PADI',   10),
    ('SSI',    20),
    ('NAUI',   30),
    ('BSAC',   40),
    ('CMAS',   50),
    ('SDI',    60),
    ('TDI',    70),
    ('IANTD',  80),
    ('RAID',   90),
    ('GUE',   100),
    ('PSAI',  110),
    ('PSA',   120);

CREATE TABLE certification (
    id                  INTEGER PRIMARY KEY,
    cert_date           TEXT    NOT NULL,                -- ISO-8601 YYYY-MM-DD
    cert_name           TEXT    NOT NULL,                -- e.g. "Advanced Open Water Diver"
    cert_number         TEXT    NOT NULL,                -- agency-issued number
    certifying_agency_id INTEGER NOT NULL REFERENCES lookup_certifying_agency(id)
                                                 ON DELETE RESTRICT,
    certifying_facility TEXT,                            -- free text (shop / training center)
    instructor          TEXT,                            -- free text
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (length(trim(cert_name)) > 0),
    CHECK (length(trim(cert_number)) > 0)
);

-- Indexes for the common list views:
-- - sort by date DESC (latest first) in the list window
-- - filter by agency later
CREATE INDEX idx_certification_date     ON certification(cert_date DESC);
CREATE INDEX idx_certification_agency   ON certification(certifying_agency_id);

-- updated_at trigger (same pattern as the other tables)
CREATE TRIGGER certification_set_updated_at
    AFTER UPDATE ON certification
    FOR EACH ROW
BEGIN
    UPDATE certification SET updated_at = datetime('now') WHERE id = OLD.id;
END;
