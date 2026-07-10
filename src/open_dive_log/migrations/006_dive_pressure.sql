-- 006_dive_pressure.sql
-- Add tank pressure (start and end of dive) to the dive record.
-- Stored in BAR; the form handles conversion to PSI for the imperial
-- unit system. REAL (not INTEGER) so partial fills are stored exactly
-- (e.g. 195.5 bar is a real-world common value).
--
-- Range checks are enforced via INSERT/UPDATE triggers rather than
-- ALTER TABLE ADD CONSTRAINT, which requires SQLite 3.53. We want
-- this migration to run on any 3.45+ SQLite — see migration 005
-- for the full rationale.
--
-- Range bounds:
--   0   bar = empty tank (a real and useful reading for SAC-rate work)
--   350 bar = comfortably above the highest standard fill (300 bar
--   European high-pressure); catches typos like "2000 bar".
--
-- At 14.5037738 PSI per BAR, 350 bar = 5076.32 PSI.

ALTER TABLE dive ADD COLUMN start_pressure_bar REAL;
ALTER TABLE dive ADD COLUMN end_pressure_bar   REAL;

-- start_pressure_bar range: 0..350
CREATE TRIGGER dive_start_pressure_bar_range_ins
    BEFORE INSERT ON dive
    FOR EACH ROW
    WHEN NEW.start_pressure_bar IS NOT NULL
     AND (NEW.start_pressure_bar < 0 OR NEW.start_pressure_bar > 350)
BEGIN
    SELECT RAISE(ABORT, 'start_pressure_bar out of range [0, 350]');
END;

CREATE TRIGGER dive_start_pressure_bar_range_upd
    BEFORE UPDATE ON dive
    FOR EACH ROW
    WHEN NEW.start_pressure_bar IS NOT NULL
     AND (NEW.start_pressure_bar < 0 OR NEW.start_pressure_bar > 350)
BEGIN
    SELECT RAISE(ABORT, 'start_pressure_bar out of range [0, 350]');
END;

-- end_pressure_bar range: 0..350
CREATE TRIGGER dive_end_pressure_bar_range_ins
    BEFORE INSERT ON dive
    FOR EACH ROW
    WHEN NEW.end_pressure_bar IS NOT NULL
     AND (NEW.end_pressure_bar < 0 OR NEW.end_pressure_bar > 350)
BEGIN
    SELECT RAISE(ABORT, 'end_pressure_bar out of range [0, 350]');
END;

CREATE TRIGGER dive_end_pressure_bar_range_upd
    BEFORE UPDATE ON dive
    FOR EACH ROW
    WHEN NEW.end_pressure_bar IS NOT NULL
     AND (NEW.end_pressure_bar < 0 OR NEW.end_pressure_bar > 350)
BEGIN
    SELECT RAISE(ABORT, 'end_pressure_bar out of range [0, 350]');
END;
