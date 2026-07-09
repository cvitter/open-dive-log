## Summary

<!-- 1–3 sentences. What does this PR change, and why? -->

## Related issue

Closes #

<!-- If there's no issue, say so explicitly and explain why a PR
     without an issue is appropriate. -->

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing
      behavior to change)
- [ ] Documentation / repo hygiene (no code change)

## Changes

<!-- Bulleted list. Group related edits; call out anything that
     isn't obvious from the diff. -->

-

## Test plan

<!-- How did you verify this works? What did you run? If you didn't
     run the full suite, explain why. -->

- [ ] `pytest` passes locally
- [ ] `ruff check` passes locally
- [ ] I started the GUI and exercised the changed path
- [ ] I added or updated tests for the change
- [ ] If a migration was added, I tested it on a fresh DB:
      `rm -f data/open_dive_log.db && bin/run-app.sh`

## Screenshots / recordings

<!-- For UI changes. Drag images in, or paste a link. -->

## Checklist

- [ ] My commit messages follow Conventional Commits
      (`type(scope): summary`)
- [ ] My commits are signed off (`git commit -s`)
- [ ] I read `CONTRIBUTING.md`
- [ ] I read `CODE_OF_CONDUCT.md`
