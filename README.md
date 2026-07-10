# Open Dive Log

An open-source desktop application for logging scuba dives. Built for
divers who want to keep a local, portable logbook without giving their
data to a cloud service.

![Python](https://img.shields.io/badge/python-3.13-blue)
![License](https://img.shields.io/badge/license-Apache_2.0-green)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)

## Highlights

- **Local-first** — your dives live in a single SQLite file you control
- **Open data** — bundled with 3,123 dive sites from
  [opendivemap.com](https://opendivemap.com), no API key required
- **Multi-site dives** — log a single dive that touched several sites
- **Full CRUD everywhere** — dives, sites, buddies, certifications, and
  lookup tables can all be added, edited, and deleted from the UI
- **Metric or imperial** — a global toggle (View → Units) honors your
  preference in the form, list, detail dialog, and stats screen
- **Print cert cards** — render certifications to standard paper via
  the system print pipeline (PDF export is a freebie)

## Tech stack

- Python 3.13 (3.13.14 from Homebrew)
- PySide6 6.8+ (Qt 6 GUI; 6.8.3 and 6.10.3 verified; **6.11.x is broken
  on macOS arm64** — its Cocoa plugin can't be loaded by Qt's plugin
  loader)
- SQLite 3.45.x (Python's bundled `sqlite3` module)
- pytest 8.x (pinned in `pyproject.toml`; 9.x broke a hard import of
  `pygments`)

## Install

```bash
brew install python@3.13
cd open-dive-log
python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -c "import sqlite3; print(sqlite3.sqlite_version)"   # 3.45.x
```

The first time the app launches it will run any pending migrations and
create `data/open_dive_log.db`.

## Run

```bash
bin/run-app.sh                       # the GUI
.venv/bin/python -m pytest           # 218 tests
```

`bin/run-app.sh` is a shell wrapper that handles three macOS
quirks so the app launches reliably:

1. Strips the inherited `PYTHONPATH` (some terminals — and Hermes — set
   it, which breaks the editable-install shim and can shadow local
   packages with byte-incompatible copies from another Python's
   site-packages).
2. Detects a corrupted `libqcocoa.dylib` (the Qt Cocoa plugin) by
   checking its `codesign` identifier, and force-reinstalls
   `PySide6_Essentials` at the matching version if the signature is
   broken. This makes the "app can only be opened once" symptom
   self-healing.
3. Sets `PYTHONPATH=src` explicitly so the editable-install shim
   resolves to the project's own source tree.

If you'd rather skip the wrapper, the direct equivalent is:

```bash
env -u PYTHONPATH PYTHONPATH=src .venv/bin/python -m open_dive_log
```

After `pip install -e .` is in the venv, just `python -m open_dive_log`
works without `PYTHONPATH` at all.

## Features

### Dives

- **Add / Edit / Delete dives** from a full-featured form (Dives → New,
  or double-click a row in the list to edit)
- **11-column dive list**: Dive # · Date · Bottom time · Air temp ·
  Water temp · Visibility · P start · P end · Depth avg · Depth max ·
  Site. Double-click a row to edit; new dives are pre-selected.
  **Dive # is chronological** (1 = the earliest dive in time,
  n = the most recent), not the row id — so backdating a dive
  renumbers everything after it the way a paper logbook would.
  The internal id stays stable and is exposed via the table's
  UserRole for selection / lookup.
- **Inline site creation**: while logging a dive, you can add a brand
  new site on the fly — it shows up in the Sites window once the
  dive is saved
- **Multi-site dives**: attach several sites to one dive (e.g. a
  drift dive that passed two wrecks), order is preserved
- **Buddies with roles**: each dive can have multiple buddies, each
  tagged with their role (Dive Buddy, Dive Leader, Student, etc.)
- **Tank pressure**: start and end pressure stored in BAR; the form
  accepts BAR or PSI depending on the unit toggle
- **Conditions**: air temp, water temp, visibility, and surface
  conditions are recorded per dive

### Sites

- **3,123 opendivemap sites** bundled — searchable, with name /
  region / country / environment / entry type / max depth
- **Filter by name** in the sites list window (case-insensitive
  substring)
- **Add / Edit sites in the UI** (in the sites list window toolbar
  and right-click context menu)
- **Country picker** with ISO 3166-1 alpha-2 codes; free-text legacy
  country field preserved
- **External id tracking**: opendivemap imports are linked to the
  upstream record so re-imports update rather than duplicate

### Buddies

- **List window** with full add / edit / delete (Buddies → List
  Buddies…)
- Deduped by normalized full name (`lower(trim(...))` with internal
  whitespace collapsed)
- Deletion warns if the buddy is referenced by any dive

### Certifications

- **List window** with full add / edit / delete (Certifications →
  List Certifications…)
- **Print a cert card**: standard paper, with centered title,
  structured key-value table, optional notes, and a "Generated from
  Open Dive Log" footer. Both system printer and PDF export
- Certs are versioned (issue date, optional expiry, card number,
  instructor)

### Lookups

- **Admin window** (Lookups → Manage Lookups…) with two-pane layout:
  categories on the left, values on the right
- Add, Edit, Deactivate, and Reactivate for any of the 12 lookup
  tables (Time of day, Entry type, Surface conditions, Equipment
  type, Tank type, Tank configuration, Gas type, Purpose, Buddy role,
  Site environment, Site topology, Certifying agency)
- Soft-delete (sets `is_active=0`) so historical dives that reference
  a lookup value stay valid after the value is removed from
  dropdowns; can be undone with Reactivate
- Hard-delete is intentionally not exposed — every referenced table
  has `ON DELETE RESTRICT` so the DB rejects it

### Stats

- **Stats screen** (View → Show Stats…) with the key dive-book
  aggregates:
  - Number of dives
  - Longest dive
  - Shortest dive
  - Average dive length
  - **Total dive time** — formatted as `X min` under 60, or
    `X hr Y min` at 60+, with the `0 min` dropped for exact hours
  - Deepest dive (in the user's current unit system)
  - Average dive depth
  - Number of dive sites
  - Number of countries
- Refreshes automatically when a dive is added, edited, or deleted
  (if the stats window is open)

### Preferences

- **Metric or Imperial units** (View → Units) — persisted to
  `~/.open-dive-log/preferences.json` and honored in every dialog,
  list, and detail view. The DB always stores metric.

## Schema

The DDL lives in `src/open_dive_log/migrations/`:

| File | Schema version | Adds |
|---|---|---|
| `001_init.sql` | v1 | Core tables: `dive`, `site`, `buddy`, `dive_buddy`, `dive_site`, `certification`, plus 9 lookup tables |
| `002_opendivemap.sql` | v2 | Country table, opendivemap site topology/environment, external-id plumbing, 3,123 site rows |
| `003_site_descriptions.sql` | v3 | `site.description` and `site.description_wildlife` (text columns from the upstream tags bag) |
| `004_certifications.sql` | v4 | Cert-agency lookup, `certification` table enhancements |
| `005_dive_conditions.sql` | v5 | `dive.air_temp_c`, `dive.water_temp_c`, `dive.visibility_m` with range checks enforced via INSERT/UPDATE triggers (SQLite 3.45+ compatible) |
| `006_dive_pressure.sql` | v6 | `dive.start_pressure_bar`, `dive.end_pressure_bar` (range 0..350 BAR = 0..5076 PSI, also via triggers) |

Note on the v5/v6 range checks: SQLite 3.53+ supports `ALTER TABLE
... ADD CONSTRAINT ... CHECK (...)` natively, which is what the
original migrations used. We deliberately rewrote these to use
BEFORE INSERT/UPDATE triggers so the project can run on any
SQLite 3.45+ (the GitHub-hosted Ubuntu runner ships 3.45.1).
The trigger pattern is functionally equivalent — every insert and
update is checked, and out-of-range values abort the operation
with a clear `RAISE(ABORT, '... out of range ...')` message.

Key design choices:

- `dive_time_minutes` is INTEGER; `max_depth_m` and `avg_depth_m` are
  REAL. The DB always stores metric.
- Buddies are deduped on a normalized full_name (so "Mike Smith",
  "  mike  smith  ", and "MIKE   SMITH" all resolve to one buddy).
- `dive_site(dive_id, site_id, site_order)` is a many-to-many join
  with a composite primary key on `(dive_id, site_order)` to preserve
  the order of sites on a multi-site dive.
- Lookups are one-table-per-field (not a single shared `lookup`
  table), so each can have its own display_order and seed values.

## Project layout

```
open-dive-log/
├── bin/
│   └── run-app.sh                   # launcher with macOS self-heal
├── data/
│   └── open_dive_log.db             # the SQLite database (created on first run)
├── src/open_dive_log/
│   ├── db.py                        # connect / apply_migrations
│   ├── preferences.py               # units toggle persistence
│   ├── units.py                     # UnitSystem + conversion helpers
│   ├── migrations/                  # numbered SQL files, applied in order
│   ├── repositories/                # one module per aggregate
│   │   ├── sites.py
│   │   ├── dives.py
│   │   ├── buddies.py
│   │   ├── certifications.py
│   │   └── lookups.py
│   ├── sources/
│   │   └── opendivemap.py           # the opendivemap importer
│   └── ui/                          # PySide6 widgets, one file per window
│       ├── main_window.py
│       ├── dive_table_model.py
│       ├── dive_add_edit_dialog.py
│       ├── dive_detail_dialog.py
│       ├── sites_list_window.py
│       ├── site_add_edit_dialog.py
│       ├── buddies_list_window.py
│       ├── cert_list_window.py
│       ├── lookups_list_window.py
│       └── stats_window.py
├── tests/                           # 218 tests; pytest < 9
│   ├── conftest.py                  # autouse live-DB safety net + Qt subprocess helper
│   ├── test_conftest_safety.py      # regression tests for the conftest's safety net
│   ├── test_dive_table_model.py     # the DiveTableModel + DiveRow contract
│   └── ...                          # one test file per repository / module
├── CONTRIBUTING.md                  # dev setup, conventions, PR process
├── CODE_OF_CONDUCT.md               # Contributor Covenant 2.1
└── .github/
    ├── ISSUE_TEMPLATE/
    │   ├── bug_report.md
    │   ├── feature_request.md
    │   └── question.md
    └── PULL_REQUEST_TEMPLATE.md
```

## Testing

```bash
.venv/bin/python -m pytest                        # everything
.venv/bin/python -m pytest tests/test_dives.py    # one module
.venv/bin/python -m pytest -k "create"            # by name
```

Tests that need a real Qt event loop use the `offscreen` platform
plugin and run in a subprocess so a broken `libqcocoa.dylib` doesn't
take down the rest of the suite. There are 218 tests; the 2 that
skip are pre-existing environmental Qt subprocess issues, not
regressions. Every test runs against a tmp-path DB (the
`tests/conftest.py` autouse fixture monkey-patches
`db.DEFAULT_DB_PATH` so a stray `db.connect()` with no arguments
opens a tmp file, not the live `data/open_dive_log.db`).

## Tech notes

### Why PySide6 6.8–6.10 and not 6.11+?

PySide6 6.11.x's Cocoa plugin is incompatible with Qt's plugin
loader on macOS arm64 — the dylib ships but the QFactoryLoader
refuses to load it. The launcher (`bin/run-app.sh`) self-heals the
case where the dylib gets corrupted on disk (e.g. by a bad `cp` that
breaks the codesign identifier), but it can't fix the upstream
incompatibility. Stick with 6.8.x or 6.10.x for now.

### Why Python 3.13 and not 3.14?

Same root cause: PySide6 6.11.x is broken on 3.14, and we want to
avoid the 6.11 plugin loader.

### Why a custom `bin/run-app.sh` instead of a console script?

Pip generates console scripts that exec the venv's Python directly,
but the venv's editable-install `.pth` file isn't processed when
`PYTHONPATH` is set in the environment. Several terminals
(including Hermes) set `PYTHONPATH` by default, so the generated
console script fails with `ModuleNotFoundError`. The wrapper sets
`PYTHONPATH=src` explicitly and strips the inherited value.

## Contributing

Contributions are welcome — bug reports, feature requests, and pull
requests. The full guide lives in
[`CONTRIBUTING.md`](CONTRIBUTING.md); the short version:

- **Open an issue first** for non-trivial changes so the design can
  be agreed before code is written.
- **Conventional Commits** for messages: `feat:`, `fix:`, `docs:`,
  `refactor:`, `test:`, `chore:` — with a scope when useful, e.g.
  `fix(repositories): persist country_code when editing a site`.
- **Sign off your commits** (`git commit -s`); this project uses the
  DCO, not a CLA. One-time setup: `git config format.signOff true`.
- **PRs must include tests** for new behavior. `pytest` and
  `ruff check` both run in CI.
- **Use the issue and PR templates** — they exist to save you and
  the maintainer time. Bug reports without OS / Python / PySide6
  versions will be asked for before investigation starts.
- **Be excellent to each other** — see
  [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## License

Apache 2.0. See [LICENSE](LICENSE).

## Future improvements

The current feature set covers the core logbook workflow. The
following are features that would meaningfully improve the app and
are not yet implemented. Listed roughly in priority order.

### High value, modest effort

- **Dive search and filtering** — a search box on the dive list
  (filter by site, buddy, date range, or free-text on notes) so a
  diver with hundreds of dives can find one quickly. The sites list
  already has this; the dive list does not.
- **CSV / JSON export** — let the user export all their dives (or a
  filtered subset) to a portable file format. Import from the same
  formats would also be valuable. Would make backups trivial and
  enable migration to other logbook tools.
- **Photo attachments per dive** — store images of marine life,
  dive sites, or buddies in a `dive_media` table with FK to dive.
  Display thumbnails in the detail dialog.
- **Gps track import** — read a GPX file from a dive computer and
  plot the dive profile on a depth-vs-time chart.
- **Site map view** — show all sites on a map (e.g. via a Qt WebEngine
  widget with Leaflet, or pyqtgraph). The site table already has
  latitude / longitude columns.
- **Dive profile chart** — render max_depth and bottom_time as a
  sparkline / depth-vs-time chart in the detail dialog. The data is
  in the table; only the visualization is missing.

### Higher effort, longer-term

- **Dive computer integration** — direct import from common dive
  computer manufacturers' desktop software (Shearwater, Suunto,
  Garmin, Oceanic). The export formats are typically CSV, XML, or
  proprietary binary, so each vendor is a separate importer.
- **Multi-user / cloud sync** — let a diver back up their logbook
  to S3 (or similar) and sync between machines. The schema is
  already portable (single SQLite file); a sync layer is what's
  missing.
- **Print a full dive log** — render the entire dive list to a
  printer-friendly PDF, with optional cover page and a per-site
  summary. The certification print pipeline is the existing
  template to follow.
- **Statistics: trends over time** — annual dive count, depth
  progression, deepest dive per year, etc. The data is there
  (timestamps + depths); only the aggregations and chart
  rendering are missing.
- **Markdown notes for dives** — render the notes field as
  Markdown in the detail dialog (currently shown as plain text)
  so divers can structure their dive reports.
- **Configurable unit precision** — let the user pick how many
  decimal places to show for depth, temp, and pressure. Currently
  the formatters use 0–2 decimals based on the value.
- **Bulk import from other logbook apps** — Subsurface, Divelog,
  Diving Log, MacDive. The schemas are documented; importers
  would be one module each.
- **Dive sites without a country** — the inline-create flow lets
  a site be saved with no country, by user choice. A future
  improvement would be a "fill in country from geolocation" prompt
  for sites that have lat/lon but no country.
- **Buddy roles configuration** — the `lookup_buddy_role` table
  is fully editable, but there's no UI hint that adding a new role
  in the Lookups window will immediately make it available in the
  dive form's role dropdown. A one-line help text in the Lookups
  window would help.
- **Site topology editor** — the `site_site_topology` join is
  populated by the opendivemap import, but there's no UI to add
  or remove topologies for a site manually. Editing this would
  let divers tag their own sites with "wreck", "cave", "wall",
  etc.
- **Dark mode** — Qt 6 supports it natively via the Fusion style;
  the app currently uses the system default, which on macOS
  follows the system appearance. A manual "Force Dark" menu
  toggle would be useful for divers using the app at depth (or
  just at night).
- **Internationalization** — the UI is English-only. Qt's
  translation framework (`tr()`, `.ts` files) would make the app
  accessible to non-English-speaking divers.
- **Keyboard shortcuts on the dive list** — `j`/`k` for down/up
  row, `/` to focus the (future) search box, `n` for new dive.
  The toolbar has Ctrl+N/E but list navigation is mouse-only.
- **Backup reminder** — a status-bar hint that surfaces if the
  last backup (or DB modification) is older than N days. Backs
  the "local-first" pitch with a real safety net.
- **Dive count badge on the Sites menu** — show "List Sites…
  (3,134)" in the menu so the user can see at a glance how many
  sites are in the DB without opening the window.
- **Test data generator** — a CLI subcommand that seeds a
  development DB with N synthetic dives across the existing
  opendivemap sites, for UI work and screenshot demos.
  [PR #20](https://github.com/cvitter/open-dive-log/pull/20) is
  in review; it includes a `--force` guard request from this
  reviewer before the safety work above is fully covered.
- **The 6 remaining opendivemap tags** — the importer currently
  pulls `description` and `description_wildlife`. The upstream
  also exposes `average_vis_m`, `average_divetime_min`,
  `average_rating`, `logged_dives`, `source`, and `thumbnail` —
  all of which would be useful site metadata to import.
