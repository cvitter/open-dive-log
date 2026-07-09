# Contributing to Open Dive Log

Thanks for your interest in contributing. Open Dive Log is a small
desktop app for logging scuba dives — local-first, single-user, written
in Python + PySide6. Contributions are welcome from divers, developers,
and documentation writers.

## Code of conduct

This project follows the [Contributor Covenant 2.1][cov]. By
participating, you agree to its terms. Report violations to
craig.vitter@gmail.com.

[cov]: https://www.contributor-covenant.org/version/2/1/code_of_conduct/

## Filing issues

Before opening an issue:

1. **Search existing issues** — including closed ones.
2. **Use a template** — GitHub will offer a Bug Report or Feature
   Request form; please fill it out.

For bugs, include:
- macOS / Linux version, Python version (`python3 --version`),
  PySide6 version (`pip show PySide6`).
- The exact command you ran and its full output.
- If UI-related: a screenshot and the steps to reproduce.

For feature requests, describe the **diver's problem**, not the UI
solution. "I can't search my dives by depth range" is better than
"add a depth-range filter dropdown."

## Good first issues

Issues labeled [`good first issue`][gfi] are scoped for new
contributors. They're typically 1–4 hours of work and have clear
acceptance criteria.

[gfi]: https://github.com/cvitter/open-dive-log/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22

## Development setup

Tested on:
- macOS 14+ (Apple Silicon and Intel)
- Linux (Ubuntu 24.04 verified)

### Prerequisites

- **Python 3.13** (3.13.14 from Homebrew is what the project uses).
  Python 3.14 works but is not yet the CI target.
- **PySide6 6.8.x or 6.10.x** — **6.11.x is broken on macOS arm64**;
  its Cocoa plugin cannot be loaded by Qt's plugin loader. Pinned
  in `pyproject.toml` to `<6.11`. Do not bump this without testing
  the GUI launch on a clean venv.
- **pytest 8.x** — pytest 9.0 made `import pygments` unconditional and
  now crashes on a fresh install. Pinned to `<9`.

### First-time setup

```bash
git clone https://github.com/cvitter/open-dive-log.git
cd open-dive-log
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -c "import sqlite3; print(sqlite3.sqlite_version)"  # 3.53.x
```

The first time the app launches it will run any pending migrations and
create `data/open_dive_log.db`.

### Run

```bash
bin/run-app.sh          # the GUI
.venv/bin/pytest        # the tests
.venv/bin/ruff check    # the linter (line-length = 100, see pyproject.toml)
```

> **macOS only:** if the GUI fails with
> `Could not find the Qt platform plugin "cocoa"`, recreate the venv —
> see the **macOS PySide6 caveat** below.

### Pre-commit (recommended)

```bash
.venv/bin/pip install pre-commit
.venv/bin/pre-commit install
```

This runs `ruff` on staged files before each commit. If you skip this,
CI will catch it.

## Project layout

```
src/open_dive_log/
├── app.py                  # QApplication entry point
├── db.py                   # SQLite connect, PRAGMAs, transaction helper
├── models.py               # dataclasses (Dive, Site, Buddy, Certification)
├── preferences.py          # global user prefs (metric/imperial)
├── units.py                # °C↔°F, m↔ft, bar↔psi
├── import_opendivemap.py   # bootstrap loader for OpenDiveMap data
├── migrations/             # 001_init, 002_opendivemap, 003_site_descriptions, …
├── repositories/           # SQL access layer — all DB I/O lives here
├── sources/
│   └── opendivemap.py      # public API client for opendivemap.com
└── ui/                     # PySide6 windows and dialogs

tests/                      # mirrors src/ layout
data/open_dive_log.db       # created on first run, gitignored
bin/run-app.sh              # launcher with macOS PySide6 workarounds
```

### Where to put new code

- **New SQL query** → `repositories/<thing>.py`. UI never calls
  `sqlite3` directly.
- **New window or dialog** → `ui/`, one file per window.
- **New business object** → `models.py` (a dataclass). Wire it through
  a repository before exposing it in the UI.
- **New unit conversion** → `units.py`. All conversions go through
  this module so the metric/imperial toggle stays correct.
- **New migration** → `migrations/NNN_short_name.sql`. Never edit
  a shipped migration — add a new one.
- **New test** → `tests/test_<module>.py`, mirroring the source path.

## Coding style

- **Line length: 100** (enforced by `ruff`; configured in
  `pyproject.toml`).
- **Target: Python 3.13.** `from __future__ import annotations` is
  used at the top of most modules — please keep it.
- **Type hints** on public functions. Internal helpers are fine
  without.
- **No `print()` for diagnostics** in shipped code. Use `logging`.
- **Docstrings** on every public function and class. One-line
  summaries are fine for trivial helpers; otherwise follow PEP 257.
- **Comments explain "why," not "what."** The code shows what it
  does; comments should explain the surprising choices.

## Tests

- **Every PR must include tests** for new behavior. Bug fixes
  should include a regression test that fails without the fix.
- Prefer **`pytest` with plain functions** over class-based tests
  unless shared fixtures demand otherwise.
- **Repositories get full unit tests** in isolation — UI tests are
  thinner and slower, used for the user-facing wiring only.
- Run the full suite before opening a PR:
  ```bash
  .venv/bin/pytest
  ```
- If your change touches a SQL migration, run the tests on a fresh
  `data/open_dive_log.db` to confirm migrations apply cleanly:
  ```bash
  rm -f data/open_dive_log.db && bin/run-app.sh  # exits after first launch
  .venv/bin/pytest
  ```

## macOS PySide6 caveat

PySide6 6.10.3 (and some 6.8.x) on macOS arm64 may tag the Qt dylib
with a `com.apple.provenance` xattr that breaks the next launch —
you'll see `qt.qpa.plugin: Could not find the Qt platform plugin
"cocoa"`. The current workaround is a clean venv rebuild:

```bash
rm -rf .venv
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

If you hit this in CI or in a way the rebuild doesn't fix, please
open an issue with the exact Python + PySide6 versions and the
output of `xattr .venv/lib/python3.13/site-packages/PySide6/plugins/platforms/libqcocoa.dylib`.

## Commit messages

This project follows [Conventional Commits 1.0.0][cc]. Format:

```
<type>(<scope>): <short summary>

<body — wrap at 72 chars; explain what and why, not how>

<footer — reference issues, breaking changes>
```

Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`,
`build`, `ci`. Example: `fix(repositories): persist country_code
when editing a site`.

Sign-off your commits (`git commit -s`) — this project uses the
[DCO][dco], not a CLA. Your sign-off certifies the
[Developer Certificate of Origin 1.1][dco11].

[cc]: https://www.conventionalcommits.org/en/v1.0.0/
[dco]: https://developercertificate.org/
[dco11]: https://developercertificate.org/

To enable sign-off by default:

```bash
git config format.signOff true
```

## Pull requests

1. **Open an issue first** for non-trivial changes. It saves
   everyone time if the design is agreed before code is written.
2. **One logical change per PR.** Squash fixup commits locally; the
   merged history should read like a coherent narrative.
3. **Fill out the PR template.** It links back to the issue and
   lists the acceptance criteria.
4. **CI must be green.** Lint (`ruff`) and tests (`pytest`) run on
   every PR.
5. **Maintainer will squash-merge** unless you ask for a rebase
   merge. Your branch will be deleted automatically.

## Releases

Versions follow [Semantic Versioning][semver]: `MAJOR.MINOR.PATCH`.
Tags are `vX.Y.Z`. The current version is in `pyproject.toml`.
Releases are cut from `main` by the maintainer; the changelog is
generated from conventional commit messages.

[semver]: https://semver.org/
