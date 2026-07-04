# Open Dive Log

An open-source desktop application for logging scuba dives.

## Status

Early scaffold. Not yet functional.

## Tech stack

- Python 3.14
- PySide6 6.8+ (Qt 6 GUI; 6.11.1 verified)
- SQLite 3.53.x (Python's bundled `sqlite3` module)

## Setup

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -e .[dev]
.venv/bin/python -m open_dive_log
```

## Verify SQLite version

```bash
.venv/bin/python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

Should print `3.53.x`.

## License

Apache 2.0. See [LICENSE](LICENSE).
