# Open Dive Log

An open-source desktop application for logging scuba dives.

## Status

Early scaffold. Not yet functional.

## Tech stack

- Python 3.14
- PySide6 6.8+ (Qt 6 GUI; 6.11.1 verified)
- SQLite 3.53.x (Python's bundled `sqlite3` module)

## Schema

`dive` is the main fact table. Lookups live in `lookup_<field>` tables (one
per field, app-managed), with seed values applied by migration 001.
Multi-site dives use the `dive_site` join with `site_order` to preserve the
order. Buddies are deduped on a normalized full_name.

The full DDL is in `src/open_dive_log/migrations/001_init.sql`.

## Setup

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest      # 19 tests
.venv/bin/python -m open_dive_log
```

## Verify SQLite version

```bash
.venv/bin/python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

Should print `3.53.x`.

## License

Apache 2.0. See [LICENSE](LICENSE).
