---
type: Decisions
title: Decisions
description: Decisions and their history live in the shared sp DB (project jev-ultrafast-laya). This file is a pointer and index only.
timestamp: 2026-11-05
tags: [decisions, index]
---

# Decisions

Decision rows and history live in the shared `sp` DB (project `jev-ultrafast-laya`). Each row links to a detail doc.

- Read current rows: `sp tail -r decision --all -n 50` (a later row with the same ID and a higher `@rev` replaces an earlier one).
- Read history: `sp tail -r decision-history --all -n 50`.
- Search: `sp grep "<ID or words>" --all`.
- In code: `grep -rn "A-<id>" jev_ultrafast` finds the `why:` comment for a decision.

## Write

- Row: `sp add -r decision -t decision -- "| ID@rev | rule | YYYY-MM-DD | detail doc |"`. Change = same ID, next `@rev`.
- Replace: new ID, then `sp add -r decision -t decision -- "revoked OLD@rev · why: …"`.
- History: `sp add -r decision-history -t decision -- "- YYYY-MM-DD · OLD@rev → NEW@rev · was: … · now: … · why: …"`.
- ID: a prefix plus 6 random chars from `23456789abcdefghjkmnpqrstuvwxyz`. `A` = agent and architecture.

## Index

| ID | Rule | Detail |
|---|---|---|
| A-es5q8r | Action budget 360, model-call budget 720 | [limits](./ARCHITECTURE/limits.md) |
| A-rgf3qc | Warn the model with `state.notes` before a hard limit | [limits](./ARCHITECTURE/limits.md) |
| A-cd9ngw | Every stop is `blocked` with a reason and `next_step` retry or adjust | [limits](./ARCHITECTURE/limits.md) |
| A-zfbm9k | Only model and browser errors become a stop; bugs still raise | [limits](./ARCHITECTURE/limits.md) |
| A-f6d5hp | An unobserved or interrupted mutation is never marked retry | [limits](./ARCHITECTURE/limits.md) |
| A-euc4qa | DONE needs a success check or a fill/select; 3 rejections stop | [limits](./ARCHITECTURE/limits.md) |
| A-wkphwc | Same control 3 times in a row stops, even when the page changes | [limits](./ARCHITECTURE/limits.md) |
