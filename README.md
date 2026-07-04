# Open Dive Log

An open-source desktop application for logging scuba dives.

## Status

GUI scaffold: dive list, detail popup, sites list, menus, and opendivemap
importer are all in place. New/Edit/Delete of dives and sites are
placeholders — read-only view for now.

## Tech stack

- Python 3.13
- PySide6 6.8+ (Qt 6 GUI; 6.8.3 verified — 6.11.x ships a Cocoa plugin that Qt's plugin loader can't load on macOS arm64)
- SQLite 3.53.x (Python's bundled `sqlite3` module)

## Run

```bash
bin/run-app.sh                                   # the GUI
.venv/bin/python -m open_dive_log.import_opendivemap   # the importer
.venv/bin/python -m pytest                            # 42 tests
```

`bin/run-app.sh` is a shell wrapper that sets `PYTHONPATH=src` and
launches the venv's Python. This works around a Python 3.14 + Hermes
quirk where the venv's editable-install `.pth` file isn't processed
when `PYTHONPATH` is set in the environment — `python3.14 -m
open_dive_log` from a Hermes terminal fails with `ModuleNotFoundError`.
The shell wrapper sidesteps that without fighting pip's console-script
template. If you'd rather invoke it directly, the same fix is:

```bash
PYTHONPATH=src .venv/bin/python3.14 -m open_dive_log
```

## GUI

The main window shows a list of dives (Date, Site, Max depth), sorted
newest first. Double-click a row to see the full record in a read-only
detail dialog.

Menus:

* **Dives** — New/Edit/Delete (placeholders, coming soon), List Dives, Quit
* **Sites** — List Sites, Import from opendivemap, New/Edit/Delete (placeholders)
* **Certifications** — List Certifications… (opens the certs list window with add / edit / delete / print)
* **Lookups** — Manage Lookups (placeholder)
* **Help** — About

The opendivemap import runs on a background `QThread` so the UI stays
responsive; a confirmation dialog shows the final counts when it finishes.

The Certifications window supports adding, editing, and deleting dive
certifications. "Print Selected" and "Print All" use Qt's
`QTextDocument` + `QPrinter` pipeline (standard macOS print sheet, with
PDF export as a freebie). The cert "card" is rendered as HTML
(centered title, structured key-value table, optional notes, and a
"Generated from Open Dive Log" footer).

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
`002_opendivemap.sql`, `003_site_descriptions.sql`, and
`004_certifications.sql`.

## Setup from scratch

```bash
brew install python@3.13
python3.13 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -c "import sqlite3; print(sqlite3.sqlite_version)"   # 3.53.x
```

## License

Apache 2.0. See [LICENSE](LICENSE).
