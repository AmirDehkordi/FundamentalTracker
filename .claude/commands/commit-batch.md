---
description: Split the working tree into small conventional commits and land them
argument-hint: optional context note, e.g. "P4 metrics"
---
Context: $ARGUMENTS
1 Inspect `git status` and `git diff` (and `git diff --staged`).
2 Group changes by single concern (a feature slice, its tests may ride along; config separate; docs separate).
3 Propose the commit plan first: ordered list of `type: subject` (lowercase, imperative, <= 60 chars, types
  feat|fix|test|docs|chore|refactor|ci, no ticket codes) with the files per commit. Wait for my OK.
4 On OK: stage per group (use `git add -p` when a file spans concerns) and commit sequentially. Do not
  commit if `make verify` was not green this session.
5 Show `git log --oneline -8` when done. Never: "wip", "updates", mixed concerns, force pushes.
