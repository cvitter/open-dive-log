-- 006_dive_pressure.sql
-- Add tank pressure (start and end of dive) to the dive record.
-- Stored in BAR; the form handles conversion to PSI for the imperial
-- unit system. REAL (not INTEGER) so partial fills are stored exactly
-- (e.g. 195.5 bar is a real-world common value).
--
-- Range bounds:
--   0   bar = empty tank (a real and useful reading for SAC-rate work)
--   350 bar = comfortably above the highest standard fill (300 bar
--   European high-pressure); catches typos like "2000 bar".
--
-- At 14.5037738 PSI per BAR, 350 bar = 5076.32 PSI.

ALTER TABLE dive ADD COLUMN start_pressure_bar REAL;
ALTER TABLE dive ADD COLUMN end_pressure_bar   REAL;

ALTER TABLE dive ADD CONSTRAINT dive_start_pressure_bar_range
    CHECK (start_pressure_bar IS NULL OR (start_pressure_bar >= 0 AND start_pressure_bar <= 350));
ALTER TABLE dive ADD CONSTRAINT dive_end_pressure_bar_range
    CHECK (end_pressure_bar   IS NULL OR (end_pressure_bar   >= 0 AND end_pressure_bar   <= 350));
