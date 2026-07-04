-- 003_site_descriptions.sql
-- Add textual descriptions from opendivemap. opendivemap stores these inside
-- the GeoJSON `properties.tags` bag as `description` and `description_wildlife`.
-- We surface them as first-class columns so the UI doesn't have to know about
-- the JSON shape, and so they can be searched/filtered efficiently.
--
-- Both columns are nullable: many sites in the wild lack one or both, and
-- preserving the absence of a description (vs. an empty string) is useful.
-- The importer stores NULL when the upstream value is missing or empty.

PRAGMA foreign_keys = ON;

ALTER TABLE site ADD COLUMN description           TEXT;
ALTER TABLE site ADD COLUMN description_wildlife  TEXT;
