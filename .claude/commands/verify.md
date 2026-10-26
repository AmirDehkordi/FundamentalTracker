---
description: Run full verification and drive it to green without weakening anything
---
Run `make verify`. If anything fails, fix the ROOT CAUSE and re-run until green. Hard rules: never loosen
ruff/mypy config, never lower the coverage gate, never skip/xfail a test, never delete an assertion to pass.
If the correct fix would change behaviour or a frozen contract in api/schemas.py, STOP and ask me first.
When green, summarise in <= 5 lines what was fixed.
