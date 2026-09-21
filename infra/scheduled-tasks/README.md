# Scheduled task prompts (canonical copies)

Prompts for Claude desktop **scheduled tasks** that monitor production. The app runs them from
`~/Documents/Claude/Scheduled/<task-id>/SKILL.md`, which is outside this repo — so the copies
here are the source of truth and the only place their history is reviewable.

| File | Task id | Schedule |
|---|---|---|
| `strattraderpro-silent-failure-audit.SKILL.md` | `strattraderpro-silent-failure-audit` | `0 9 * * *` daily |

## Why these are versioned

On 2026-08-18 the audit prompt was silently rewritten from a ~5-week-old ancestor, reverting
baseline corrections from three separate sessions. It then reported three fabricated failures
every morning for five weeks and nobody could diff it, because it had no history.
See [BUG-012](../../bugs/BUG-012-silent-failure-audit-prompt-reverted.md).

## Workflow

**Editing:** change the file here, commit, then sync it out:

```sh
cp infra/scheduled-tasks/strattraderpro-silent-failure-audit.SKILL.md \
   ~/Documents/Claude/Scheduled/strattraderpro-silent-failure-audit/SKILL.md
```

**Checking for drift:**

```sh
scripts/check_scheduled_task_sync.sh   # exit 0 in sync, 1 drift (prints diff), 2 live file absent
```

Run it after any session that touched the scheduler, and before trusting a run's verdict.

## Editing rules for the audit prompt

- Keep **exactly six** `**CHECK n —` headings and the exact pass string `OK — 6/6 checks passed.`
  — the task's output contract depends on both.
- Baselines (rule titles, job set, URLs, CHECK 5 bands) carry a "last verified" date in the
  Environment note. Re-verify against live production when you change one, and update the date.
- Prefer **pinned sets over bare counts**: "11 rules" cannot tell the right 11 from any 11.
- Don't put a threshold on top of the healthy value. CHECK 5's healthy state is ~1.0, so it
  fails at ≥ 1.3 over a 3h range — not at ≥ 1.0 on an instant sample.
