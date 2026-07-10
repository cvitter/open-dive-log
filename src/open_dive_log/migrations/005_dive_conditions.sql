-- 005_dive_conditions.sql
-- Add air temperature, water temperature, and visibility to dives.
-- All stored in metric units (Celsius, meters). The UI handles
-- conversion to/from imperial at the form boundary.
--
-- Range checks are enforced via INSERT/UPDATE triggers rather than
-- ALTER TABLE ADD CONSTRAINT, because the latter requires SQLite
-- 3.53 (released 2025-04-09) and we want this migration to run on
-- any 3.45+ SQLite — including the version that ships with the
-- GitHub-hosted Ubuntu runner (currently 3.45.1).
--
-- Sanity-check ranges. These are bounds, not "every dive must
-- satisfy this" — but they catch typos at the boundary.
-- air_temp_c:  -50°C (Siberia in winter) to 60°C (Death Valley)
-- water_temp_c: -2°C (ice diving) to 40°C (tropical surface)
-- visibility_m: 0 (none, e.g. black water) to 60m (extreme viz)

ALTER TABLE dive ADD COLUMN air_temp_c    REAL;     -- °C
ALTER TABLE dive ADD COLUMN water_temp_c  REAL;     -- °C
ALTER TABLE dive ADD COLUMN visibility_m  REAL;     -- meters

-- air_temp_c range: -50..60
CREATE TRIGGER dive_air_temp_c_range_ins
    BEFORE INSERT ON dive
    FOR EACH ROW
    WHEN NEW.air_temp_c IS NOT NULL
     AND (NEW.air_temp_c < -50 OR NEW.air_temp_c > 60)
BEGIN
    SELECT RAISE(ABORT, 'air_temp_c out of range [-50, 60]');
END;

CREATE TRIGGER dive_air_temp_c_range_upd
    BEFORE UPDATE ON dive
    FOR EACH ROW
    WHEN NEW.air_temp_c IS NOT NULL
     AND (NEW.air_temp_c < -50 OR NEW.air_temp_c > 60)
BEGIN
    SELECT RAISE(ABORT, 'air_temp_c out of range [-50, 60]');
END;

-- water_temp_c range: -2..40
CREATE TRIGGER dive_water_temp_c_range_ins
    BEFORE INSERT ON dive
    FOR EACH ROW
    WHEN NEW.water_temp_c IS NOT NULL
     AND (NEW.water_temp_c < -2 OR NEW.water_temp_c > 40)
BEGIN
    SELECT RAISE(ABORT, 'water_temp_c out of range [-2, 40]');
END;

CREATE TRIGGER dive_water_temp_c_range_upd
    BEFORE UPDATE ON dive
    FOR EACH ROW
    WHEN NEW.water_temp_c IS NOT NULL
     AND (NEW.water_temp_c < -2 OR NEW.water_temp_c > 40)
BEGIN
    SELECT RAISE(ABORT, 'water_temp_c out of range [-2, 40]');
END;

-- visibility_m range: 0..60
CREATE TRIGGER dive_visibility_m_range_ins
    BEFORE INSERT ON dive
    FOR EACH ROW
    WHEN NEW.visibility_m IS NOT NULL
     AND (NEW.visibility_m < 0 OR NEW.visibility_m > 60)
BEGIN
    SELECT RAISE(ABORT, 'visibility_m out of range [0, 60]');
END;

CREATE TRIGGER dive_visibility_m_range_upd
    BEFORE UPDATE ON dive
    FOR EACH ROW
    WHEN NEW.visibility_m IS NOT NULL
     AND (NEW.visibility_m < 0 OR NEW.visibility_m > 60)
BEGIN
    SELECT RAISE(ABORT, 'visibility_m out of range [0, 60]');
END;
