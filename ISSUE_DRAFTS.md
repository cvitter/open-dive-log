# Future-improvement issue drafts

These are the 17 issues from the [Future improvements](../README.md#future-improvements)
section of the README, drafted as full GitHub issue bodies so they can
be filed in one batch. Each draft is structured as:

- **Title** (GitHub issue title)
- **Labels** (suggested — adjust to what the repo already has)
- **Motivation** (why this matters)
- **What to build** (concrete scope)
- **Acceptance criteria** (testable)
- **Related** (cross-references to other drafts in this batch)

## Labels (suggested)

All of these should use labels that already exist on the repo, or new
labels that the user wants. Suggested colors:
- `enhancement` (green) — every issue
- `priority: high` (red) — high-value / modest-effort items
- `priority: low` (gray) — longer-term items
- `area: ui` (blue)
- `area: data` (purple)
- `area: import` (yellow)
- `area: print` (orange)
- `area: integration` (cyan)
- `good first issue` (light blue) — small, well-scoped ones

---

## 1. (issue #2) Dive search and filtering  *(high priority, modest effort)*

**Labels:** `enhancement`, `priority: high`, `area: ui`, `area: data`

**Motivation:** The dive list currently has no search or filter. A
diver with hundreds of dives can't find a specific one without
scrolling. The sites list already has a search box; the dive list
should match.

**What to build:**
- A search box on the dive list window toolbar (top-right, like
  the sites list)
- Filter by: site name substring, buddy name substring, date range
  (from / to), or free-text on notes
- Filters compose (AND)
- Status bar shows `N dive(s) matching '<query>'` or
  `N dive(s) from <from> to <to>`
- `Esc` in the search box clears the filter
- Filters persist for the session (cleared on app restart)

**Acceptance criteria:**
- Typing in the search box filters the table within 200ms for a DB
  with 1,000 dives
- All four filter dimensions work and compose
- Status bar reflects the active filter
- A test seeds 50 dives and asserts each filter dimension works

**Related:** #5 (charts), #12 (trends over time)

---

## 2. (issue #3) CSV / JSON export (and import)  *(high priority, modest effort)*

**Labels:** `enhancement`, `priority: high`, `area: data`, `area: import`

**Motivation:** Dives live in a local SQLite file. Users need a way
to back up, share, and migrate. CSV and JSON are the lowest common
denominator for logbook portability.

**What to build:**
- File menu → Export → CSV / JSON (all dives, or filtered by current
  search)
- File menu → Import → CSV (creates dives from a file matching
  the export schema)
- CSV columns: dive_date, start_time, end_time, dive_time_minutes,
  max_depth_m, avg_depth_m, air_temp_c, water_temp_c, visibility_m,
  start_pressure_bar, end_pressure_bar, sites (semicolon-separated),
  buddies (semicolon-separated as `name:role`), notes
- JSON: same fields, nested arrays for sites / buddies
- Export dialog: "All dives" / "Filtered to current search" toggle
- Import dialog: file picker, preview first 5 rows, confirm
- Use the existing `find_or_create` semantics for sites and buddies
  on import (no duplicates by name+country or normalized name)

**Acceptance criteria:**
- Round-trip: export → wipe DB → import produces identical rows
  (modulo ids)
- CSV opens correctly in Excel / Numbers / Google Sheets
- JSON validates with `json.loads`
- Import shows progress for files with 100+ rows
- 3 new tests: export-empty, export-nonempty, import-roundtrip

**Related:** #17 (test data generator)

---

## 3. (issue #4) Photo attachments per dive  *(high priority, modest effort)*

**Labels:** `enhancement`, `priority: high`, `area: ui`, `area: data`

**Motivation:** Divers take photos — marine life, the dive site,
buddies. The current logbook has no way to attach these to a dive.

**What to build:**
- New table `dive_media(id, dive_id, file_path, caption, taken_at,
  created_at)` — `file_path` is a relative path under
  `~/.open-dive-log/media/<dive_id>/`
- Detail dialog: gallery section with thumbnails
- Add photo button in the dive form: file picker, copy file into
  the media dir, save path
- Delete photo button on each thumbnail
- Open photo on click (system default app, via `QDesktopServices`)
- Supported formats: JPEG, PNG, HEIC

**Acceptance criteria:**
- Adding a photo via the form persists the file and shows the
  thumbnail in the detail dialog
- Deleting a photo removes the row and the file
- Files outside the media dir are rejected (security)
- 2 new tests: add photo, delete photo

**Related:** #2 (search — search by photo caption), #9 (Markdown notes)

---

## 4. (issue #5) Dive profile chart in the detail dialog  *(high priority, modest effort)*

**Labels:** `enhancement`, `priority: high`, `area: ui`

**Motivation:** Divers care about depth profiles. A visual chart
makes a 30m dive at 45 min with a 5m safety stop much more
informative than a row of numbers.

**What to build:**
- Detail dialog: new "Profile" section with a depth-vs-time chart
- Data: each dive gets a single `(time, depth)` point at its
  `dive_time_minutes` and `max_depth_m` for now (no per-second
  samples — see #11 for that)
- Use `QPainter` directly (no extra deps) or a minimal chart helper
- Show `avg_depth_m` as a horizontal reference line
- Chart honors the unit toggle (metric / imperial)
- If the dive has no time or depth, show a placeholder

**Acceptance criteria:**
- The chart renders in the detail dialog for any dive with both
  `dive_time_minutes` and `max_depth_m` set
- The unit toggle changes axis labels
- 1 test: chart renders without error in offscreen Qt

**Related:** #6 (GPX import — real profile data), #12 (trends)

---

## 5. (issue #6) GPX track import with profile chart  *(high priority, modest effort)*

**Labels:** `enhancement`, `priority: high`, `area: import`, `area: data`

**Motivation:** Most dive computers export GPX files with
per-second depth samples. Importing these turns a static logbook
into a real dive recorder.

**What to build:**
- Dives menu → Import GPX…
- Parse the GPX file, extract `<trkpt>` elements with
  `<ele>` (depth) and `<time>`
- If the file's first trackpoint is at depth > 0, prompt the user
  to confirm it's a dive (not a surface hike)
- Aggregate samples: pick the deepest, average, total time, and
  store as the dive's fields
- Optionally: store the full sample series in a `dive_samples`
  table for charting
- Show a per-sample chart in the detail dialog (extends #5)

**Acceptance criteria:**
- A sample GPX file (provided in tests) imports cleanly
- A dive with 5,000 samples processes in <2s
- The chart renders the actual profile
- 2 new tests: import-and-aggregate, sample-storage

**Related:** #5 (chart), #11 (dive computer integration)

---

## 6. (issue #7) Site map view  *(high priority, modest effort)*

**Labels:** `enhancement`, `priority: high`, `area: ui`, `area: data`

**Motivation:** Sites already have `latitude` and `longitude`. A
map view lets the user see where they dive and explore sites in
regions they're traveling to.

**What to build:**
- Sites window → View menu → Map (or a "Show on Map" button)
- Use `QWebEngineView` with a Leaflet map, or `pyqtgraph` with
  OpenStreetMap tiles
- Plot all sites as markers, color-coded by environment
- Click a marker → shows the site's name, country, max depth
- Optional: filter the map to current search
- Offline fallback: if no internet, show a static image with all
  the markers

**Acceptance criteria:**
- Map loads within 3s with 3,000+ sites
- Markers are clickable and show site info
- A test seeds 100 sites with random lat/lon and asserts the map
  renders

**Related:** #2 (search filter on the map), #15 (geolocation fill-in)

---

## 7. (issue #8) Markdown notes for dives  *(high priority, modest effort)*

**Labels:** `enhancement`, `priority: high`, `area: ui`

**Motivation:** Dive reports often have structure — conditions,
what was seen, what went wrong. Plain text can't represent that.
Markdown lets the user write once and renders nicely in the
detail dialog.

**What to build:**
- Detail dialog: notes section is rendered as Markdown (via
  Python's `markdown` library) instead of plain text
- Show a "source" toggle (rendered vs raw) for editing
- Add a basic formatting toolbar (bold, italic, list, link)
- Sanitize HTML to prevent injection (the existing pattern in
  the cert print is a good reference)

**Acceptance criteria:**
- A dive with `**bold**` notes shows bold text in the detail
  dialog
- Raw view shows the unrendered markdown
- A test seeds a dive with markdown notes and asserts the
  rendered output

**Related:** #4 (photo captions could be markdown)

---

## 8. (issue #9) Dive computer integration  *(longer-term)*

**Labels:** `enhancement`, `area: import`, `area: integration`

**Motivation:** Shearwater, Suunto, Garmin, and Oceanic each ship
desktop software that exports dives in vendor-specific formats.
Today, getting a computer dive into the logbook requires manual
transcription.

**What to build:**
- Vendor plugin architecture: a `dive_computers/` package with one
  module per vendor
- Each plugin implements:
  ```python
  def parse(file_path: str) -> Iterator[DiveRecord]: ...
  def supported_extensions() -> list[str]: ...
  ```
- Plugins: Shearwater (CSV from Petrel/Perdix desktop), Suunto
  (DM5 / Movescount XML), Garmin (CSV from Connect), Oceanic
  (custom binary → converter script)
- UI: Dives → Import from Dive Computer… → file picker
- Per-vendor review screen: show parsed dives, let the user
  confirm / edit before saving

**Acceptance criteria:**
- Shearwater CSV imports work with a sample file
- The plugin contract is documented
- A test that loads each plugin's `parse()` and asserts the
  output shape

**Related:** #6 (GPX — simpler version of this)

---

## 9. (issue #10) Multi-user / cloud sync  *(longer-term)*

**Labels:** `enhancement`, `area: integration`

**Motivation:** A local-first app needs a backup story. Cloud sync
also lets a diver use the logbook on multiple machines.

**What to build:**
- Configurable remote (S3, WebDAV, or a simple HTTP endpoint)
- Sync direction: push, pull, or two-way
- Conflict resolution: last-write-wins for the main `dive` row;
  the local site wins for `site` rows (the local DB is canonical)
- Settings: Tools → Sync → Configure Remote…
- A status-bar indicator shows last sync time
- Encrypt the local cache of the remote before upload

**Acceptance criteria:**
- A round-trip push / pull of a 100-dive DB succeeds
- A 2-way merge of 10 divergent rows converges
- 2 new tests: push-empty, push-then-pull

**Related:** #18 (backup reminder)

---

## 10. (issue #11) Print a full dive log  *(longer-term)*

**Labels:** `enhancement`, `area: ui`, `area: print`

**Motivation:** Divers often want a paper backup or a shareable
PDF of their full logbook. The cert print pipeline exists; extend
it to the full dive list.

**What to build:**
- File menu → Print Full Log…
- Page 1: cover page (diver's name, total dive count, date range,
  photo if available)
- Subsequent pages: dives sorted by date, with site, depth,
  bottom time, buddies, notes
- Layout: 2 dives per page, or 1 with photo space
- HTML-based, like the cert print

**Acceptance criteria:**
- A test seeds 30 dives and renders to PDF without error
- The PDF has a cover page and at least 15 dive rows
- 1 test: render-empty renders a "no dives" cover

**Related:** #4 (photo attachments — printed alongside the dive)

---

## 11. (issue #12) Statistics: trends over time  *(longer-term)*

**Labels:** `enhancement`, `area: ui`, `area: data`

**Motivation:** A diver with 5+ years of data wants to see
*progress*: annual dive count, depth progression, deepest dive
per year. The data is there; the visualizations aren't.

**What to build:**
- Stats window → Trends tab
- Charts: dives per year (bar), depth over time (line), bottom
  time over time (line)
- Time period selector: last 1y / 5y / 10y / all
- Use the same chart helper as #5

**Acceptance criteria:**
- Charts render for a DB with 200 dives spanning 3 years
- Time period selector filters correctly
- 1 test: each chart type renders in offscreen Qt

**Related:** #5 (chart helper), #6 (profile data for depth-over-time)

---

## 12. (issue #13) Configurable unit precision  *(longer-term)*

**Labels:** `enhancement`, `area: ui`

**Motivation:** Divers have different preferences. Some want
"26.4 m" precise, others want "26 m" rough. The current formatters
hardcode the precision.

**What to build:**
- Edit → Preferences → Unit Precision
- Sliders or spinners for: depth (0–2 decimals), temp (0–1
  decimal), pressure (0–0 decimal — pressure is typically integer
  in display)
- Persist to `~/.open-dive-log/preferences.json`
- The form, list, detail dialog, and stats window all read the
  precision

**Acceptance criteria:**
- Setting depth precision to 0 shows "26 m" instead of "26.4 m"
- The setting persists across restarts
- A test seeds the preferences file and asserts display output

**Related:** #14 (precision already works for some values)

---

## 13. (issue #14) Bulk import from other logbook apps  *(longer-term)*

**Labels:** `enhancement`, `area: import`

**Motivation:** Divers switching from Subsurface, Divelog, Diving
Log, or MacDive need a way to bring their data.

**What to build:**
- One importer module per source app:
  - `subsurface.py` — Subsurface's native XML format
  - `divelog.py` — Divelog XML
  - `divinglog.py` — DivingLog CSV
  - `macdive.py` — MacDive XML
- File menu → Import from → <Source>
- Source-specific mapping (some use fsw, some use meters, etc.)
- Pre-import report: "Found 247 dives, will be imported. Already
  in DB: 12."

**Acceptance criteria:**
- A sample file from each source app (in tests/) imports without
  error
- Unit conversions are correct
- Sites and buddies are de-duplicated

**Related:** #3 (CSV / JSON — simpler version), #9 (dive computer)

---

## 14. (issue #15) Auto-fill country from geolocation  *(longer-term)*

**Labels:** `enhancement`, `area: ui`, `area: data`

**Motivation:** Sites with lat/lon but no country are common
(opendivemap doesn't always include the country). A reverse-geocode
hint fills in the country in one click.

**What to build:**
- Site form: "Guess country from coordinates" button (visible
  only if `latitude` and `longitude` are set and `country` is
  empty)
- Use a local dataset (Natural Earth countries, ~5MB shapefile)
  — no network call, no API key
- Polygon-point check: does the site fall inside Bonaire, Curaçao,
  or some other country?
- If found, populate `country` and `country_code`; show a
  "Country set to: Bonaire" message

**Acceptance criteria:**
- A site at (12.15, -68.28) gets `country_code="BQ"`
- A site in the open ocean (lat 0, lon 0) gets a "no country
  found" message
- 2 new tests: hit, miss

**Related:** #7 (map view)

---

## 15. (issue #16) Site topology editor  *(longer-term)*

**Labels:** `enhancement`, `area: ui`, `area: data`

**Motivation:** The `site_site_topology` join is populated by
opendivemap but there's no way for a user to tag their own sites
with "wreck", "cave", "wall", "drift", etc.

**What to build:**
- Site form: "Topologies" multi-select (checkbox list of all
  `lookup_site_topology` values)
- Save through a new `sites_repo.set_topologies(site_id, ids)` method
- Show current topologies in the site detail dialog
- Allow add / remove without overwriting the opendivemap data

**Acceptance criteria:**
- A test seeds a site and adds 2 topologies; the join is correct
- A test that removes one topology and re-fetches shows the
  remaining one
- 2 new tests

**Related:** #7 (map view — color-code markers by topology)

---

## 16. (issue #17) Test data generator  *(longer-term, `good first issue`)*

**Labels:** `enhancement`, `good first issue`, `area: data`

**Motivation:** UI work, screenshot demos, and stress testing all
need a populated DB. Today, getting one means running the
opendivemap import (3 minutes) then manually adding dives.

**What to build:**
- CLI subcommand: `.venv/bin/python -m open_dive_log.synthesize N`
- Generates N synthetic dives spread across the opendivemap sites
- Realistic values: 20–60 min bottom time, 10–40 m max depth,
  dates spread over the last 5 years
- Uses real site data so lat/lon, country, etc. are meaningful
- CLI flags: `--from YYYY-MM-DD`, `--to YYYY-MM-DD`,
  `--site-ids 1,2,3`, `--seed 42` for reproducibility

**Acceptance criteria:**
- `synthesize 100` produces 100 dives in <5s
- A test runs the synthesizer and asserts the count and that
  the values are within reasonable ranges

**Related:** #3 (CSV export of the synthesized data)

---

## 17. (issue #18) Backup reminder status-bar indicator  *(longer-term, `good first issue`)*

**Labels:** `enhancement`, `good first issue`, `area: ui`

**Motivation:** Local-first means the user is the only backup.
A status-bar hint that surfaces if the last DB modification (or
explicit backup) is older than N days nudges the user to take
action.

**What to build:**
- Status bar: a small badge / icon that turns yellow if the DB
  is >30 days since last backup, red if >90 days
- "Backup now…" menu item: copies `data/open_dive_log.db` to
  `~/backups/open-dive-log-<timestamp>.db`
- "Mark as backed up" button: records `last_backup_at` in
  `~/.open-dive-log/preferences.json`
- Auto-dismiss the badge if a backup is taken

**Acceptance criteria:**
- Manually back-dating the `last_backup_at` field in preferences
  makes the badge turn yellow after the next launch
- "Backup now" creates a copy that can be restored by symlinking
- 1 test: badge color logic

**Related:** #10 (cloud sync is a richer version of this)

---

## 18. (issue #19) The 6 remaining opendivemap tags  *(longer-term, `good first issue`)*

**Labels:** `enhancement`, `good first issue`, `area: import`, `area: data`

**Motivation:** The opendivemap import currently pulls
`description` and `description_wildlife` from the upstream tags
bag. The other 6 tags — `average_vis_m`, `average_divetime_min`,
`average_rating`, `logged_dives`, `source`, `thumbnail` — are
discarded.

**What to build:**
- Schema migration 007: add columns to `site`:
  - `average_visibility_m REAL`
  - `average_dive_time_minutes INTEGER`
  - `average_rating REAL`
  - `logged_dives INTEGER`
  - `source TEXT`
  - `thumbnail_url TEXT`
- Update the opendivemap importer to populate them
- Update the sites list / detail dialog to show the new fields
- Update the stats screen to surface the rating distribution

**Acceptance criteria:**
- Migration 007 applies cleanly
- Re-running the opendivemap import populates the new columns
- The new fields show in the sites list (or detail dialog)
- 1 test: each new field is populated from a sample tag bag

**Related:** #7 (map view — color markers by rating)
