# Open Dive Log

An open-source desktop application for logging scuba dives.

## Status

GUI scaffold: dive list, detail popup, sites list, menus, and opendivemap
importer are all in place. New/Edit/Delete of dives and sites are
placeholders — read-only view for now.

## Tech stack

- Python 3.14
- PySide6 6.8+ (Qt 6 GUI; 6.11.1 verified)
- SQLite 3.53.x (Python's bundled `sqlite3` module)

## Run

```bash
PYTHONPATH=src .venv/bin/python3.14 -m open_dive_log          # the GUI
.venv/bin/python -m open_dive_log.import_opendivemap          # the importer
.venv/bin/python -m pytest                                    # 42 tests
```

The `PYTHONPATH=src` prefix works around a Python 3.14 + editable-install
quirk where `.pth` files aren't processed when `PYTHONPATH` is set in the
environment. The console script at `.venv/bin/open-dive-log` already
contains the same workaround and can be used directly.

## GUI

The main window shows a list of dives (Date, Site, Max depth), sorted
newest first. Double-click a row to see the full record in a read-only
detail dialog.

Menus:

* **Dives** — New/Edit/Delete (placeholders, coming soon), List Dives, Quit
* **Sites** — List Sites, Import from opendivemap, New/Edit/Delete (placeholders)
* **Lookups** — Manage Lookups (placeholder)
* **Help** — About

The opendivemap import runs on a background `QThread` so the UI stays
responsive; a confirmation dialog shows the final counts when it finishes.

## Schema

`dive` is the main fact table. Lookups live in `lookup_<field>` tables (one
per field, app-managed), with seed values applied by migration 001.
Multi-site dives use the `dive_site` join with `site_order` to preserve the
order. Buddies are deduped on a normalized full_name.

`site` is connected to opendivemap via the `site_source` +
`site_external_id` multi-source pattern; migration 002 added country,
topology, environment, and the external-id plumbing. Migration 003 added
`site.description` and `site.description_wildlife` from the upstream `tags`
bag.

The full DDL is in `src/open_dive_log/migrations/001_init.sql`,
`002_opendivemap.sql`, and `003_site_descriptions.sql`.

## Setup from scratch

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -c "import sqlite3; print(sqlite3.sqlite_version)"   # 3.53.x
```

## License

Apache 2.0. See [LICENSE](LICENSE).
