---
name: Bug report
about: Something is broken
title: ''
labels: bug
assignees: ''
---

**Describe the bug**
A clear, concise description of what went wrong.

**To reproduce**
Steps; numbered; one per line.

1. …
2. …
3. …

**Expected behavior**
What you expected to happen.

**Actual behavior**
What actually happened. Paste the full error output here (don't
summarize — copy the traceback verbatim).

**Environment**
- OS + version (e.g. macOS 14.5, Ubuntu 24.04):
- Python version (`python3 --version`):
- PySide6 version (`pip show PySide6`):
- open-dive-log version or commit (`git rev-parse HEAD`):
- Installed via `pip install -e ".[dev]"` or a system package?:

**Did the migrations run cleanly?**
`data/open_dive_log.db` may need to be rebuilt to test against the
current schema. Try this and note whether it changed the behavior:

```bash
rm -f data/open_dive_log.db && bin/run-app.sh
```

**Logs / screenshots**
Drag images in, or paste terminal output between triple backticks:

```
<output here>
```

**Additional context**
Anything else that might be relevant (other apps open, system locale,
recent OS upgrade, etc.).
