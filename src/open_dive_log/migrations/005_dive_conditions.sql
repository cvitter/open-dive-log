-- 005_dive_conditions.sql
-- Add air temperature, water temperature, and visibility to dives.
-- All stored in metric units (Celsius, meters). The UI handles
-- conversion to/from imperial at the form boundary.

ALTER TABLE dive ADD COLUMN air_temp_c    REAL;     -- °C
ALTER TABLE dive ADD COLUMN water_temp_c  REAL;     -- °C
ALTER TABLE dive ADD COLUMN visibility_m  REAL;     -- meters

-- Sanity-check ranges. These are bounds, not "every dive must
-- satisfy this" — but they catch typos at the boundary.
-- air_temp_c:  -50°C (Siberia in winter) to 60°C (Death Valley)
-- water_temp_c: -2°C (ice diving) to 40°C (tropical surface)
-- visibility_m: 0 (none, e.g. black water) to 60m (extreme viz)
ALTER TABLE dive ADD CONSTRAINT dive_air_temp_c_range
    CHECK (air_temp_c IS NULL OR (air_temp_c >= -50 AND air_temp_c <= 60));
ALTER TABLE dive ADD CONSTRAINT dive_water_temp_c_range
    CHECK (water_temp_c IS NULL OR (water_temp_c >= -2 AND water_temp_c <= 40));
ALTER TABLE dive ADD CONSTRAINT dive_visibility_m_range
    CHECK (visibility_m IS NULL OR (visibility_m >= 0 AND visibility_m <= 60));
