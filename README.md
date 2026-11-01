# ossforge

Scout -> vet -> hunt -> verify -> submit, with a daily cap and a safety layer.
Built from the best parts of three projects:

| From | Taken |
|---|---|
| GitSense | repo health radar (`radar.py`), PR merge predictor (`predictor.py`), outcome calibration idea (`outcomes.py`) |
| oss-scout | issue vetting, claim detection, anti-AI policy scan, personalization boost, API budget and cache (`vet.py`, `policy.py`, `gh.py`) |
| ContribAI | consent/guard mindset, protected paths, evidence log, PR patrol (`safety.py`, `patrol.py`) |

## Rules (enforced in code)

- At most **2 PRs/day** (`limiter.py`, not configurable above 2).
- Issue and PR are filed **together**; the PR says `Closes #N`.
- Repos with an **anti-AI policy are skipped and reported**, never contacted.
- Only **verified** items can be submitted: a new test must fail without the fix and pass with it.
- Fresh **duplicate search** (open + closed issues/PRs + recent commits) right before filing.
- One open PR per repo, cooldown after an unmerged close, protected paths (workflows, LICENSE, CODEOWNERS...) blocked,
  secret scan on the diff, size limits, kill switch (`ossforge stop`).
- DCO `Signed-off-by` is applied under **your** git identity. **ossforge never signs a CLA**; `ossforge cla` only shows you the link.
- AI-assistance disclosure on issues, PRs and comments (`disclosure: true`).
- Every outbound action is appended to `.state/audit.jsonl`.

## Commands

```
ossforge scout|features   find vetted fix / feature issues (spam filtered, health gated)
ossforge radar|vet        inspect a repo / one issue
ossforge hunt REPO        clone, scan whole repo (builtin + ruff + JS), rank, drop duplicates, enqueue
ossforge queue            list items
ossforge verify ID ...    run tests without/with the fix in a venv, then mark verified
ossforge reject ID        mark a false positive (updates per-detector precision)
ossforge submit ID [--yes]   dry-run by default; resumes after partial failure
ossforge critique|post-critique   score someone's open PR, draft and (after approval) post a constructive review
ossforge patrol           outcomes + what each open PR needs (DCO, CLA, CI, conflicts, feedback)
ossforge loop [--once]    continuous research; writes .state/digest.md
ossforge stop|resume      kill switch
```

## Honest limits

- Static detectors only produce *candidates*; most are false positives. Only `verify` makes one real.
- Writing the failing test and the patch is done by you or an agent (`patch_command` hook). ossforge does not invent patches.
- `verify` uses a venv with a scrubbed environment (no tokens). That is hygiene, not a sandbox: use Docker for untrusted repos.
- Detectors cover Python deeply and a few JS/TS patterns.
