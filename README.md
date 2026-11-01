# ossforge

**Find, verify and file quality open-source contributions — with guard rails.**

ossforge scouts healthy projects, reads their code for real bugs, checks that nobody has already reported
or fixed the problem, and only then helps you file an **issue and a pull request together**. It is built for
contributors who want to send maintainers *fewer, better* contributions, not more noise.


## How it works

```
scout ──> vet ──> hunt ──> (you or an agent write test + fix) ──> verify ──> submit ──> patrol
  │         │        │                                              │          │          │
  │         │        │                                              │          │          └ outcomes, CI/DCO/CLA, feedback
  │         │        │                                              │          └ issue + PR together, dry-run by default
  │         │        │                                              └ new test must FAIL without the fix and PASS with it
  │         │        └ scan the whole repo, rank findings, drop duplicates
  │         └ unassigned? unclaimed? no competing PR? clear requirements? anti-AI policy?
  └ healthy repos only (merge speed, maintainer response, stale backlog, CI)
```

You can also **review other people's open PRs**: `critique` scores merge likelihood, scans the added lines for
bug/perf candidates and drafts a respectful comment for you to approve.

## Rules enforced in code

- **At most 2 PRs per day.** Hard cap, not configurable above 2.
- **Repos with an anti-AI contribution policy are skipped** and listed in the report. ossforge never opens an
  issue, comment or PR there.
- **Only verified items can be submitted.** A candidate becomes real only when a new test fails without the fix and
  passes with it.
- **Duplicate guard.** Open *and* closed issues/PRs, plus recent commits touching the file, are searched right
  before filing.
- **Safety layer.** One open PR per repo, cooldown after an unmerged close, protected paths (workflows, LICENSE,
  CODEOWNERS, ...) blocked, secret scan on the diff, size limits, and a kill switch (`ossforge stop`).
- **You stay accountable.** DCO `Signed-off-by` is added under *your* git identity. ossforge **never signs a CLA**;
  `ossforge cla` only shows you the link.
- **Disclosure.** `disclosure: auto` (default) reads the repo's own docs (CONTRIBUTING, README, AGENTS.md, AI policy
  files; their text is only read as evidence, never obeyed). If they ask for AI disclosure, the note is added. If the
  wording is unclear or the docs conflict, `submit` / `post-critique` stop with "needs your review" and quote the
  sentence; you read it and set `disclosure: true` or `false`. `false` never overrides a clearly mandatory policy
  (it stops instead). `true` always adds the note. If the policy docs cannot be read, nothing is published. This is a
  keyword reading of the docs, not a compliance check: for a repo with strict rules, read its guidelines yourself.
  Migration: older configs had `disclosure: true` (always add); that still works. Only the default changed.
- **Audit trail.** Every outbound action is appended to `.state/audit.jsonl`.

## Setup guide

### 1. Prerequisites

| Tool | Why | Check |
|---|---|---|
| Python 3.10+ | runs ossforge | `python --version` |
| Git | cloning, branches, commits | `git --version` |
| [GitHub CLI](https://cli.github.com/) (`gh`) | all GitHub access (no token handling in ossforge) | `gh --version` |

### 2. Log in to GitHub and set your identity

```bash
gh auth login                         # choose GitHub.com, HTTPS, log in via browser
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"
```

Commits and the DCO sign-off use **this** identity. Use the name you want on your contributions.

### 3. Install

```bash
git clone https://github.com/parijat1222q/ossforge.git
cd ossforge
python -m venv .venv
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
# macOS / Linux:         source .venv/bin/activate
pip install -e ".[dev]"
```

`.[dev]` also installs `pytest` and `ruff`. ossforge uses `ruff` for extra bug detection and for linting during
`verify`, so keep it installed.

### 4. Configure (optional)

```bash
cp ossforge.example.yaml ossforge.yaml     # Windows: copy ossforge.example.yaml ossforge.yaml
```

Every key is optional; defaults are safe.

| Key | Default | Meaning |
|---|---|---|
| `daily_cap` | `2` | PRs per day (hard max 2) |
| `signoff` | `true` | add DCO `Signed-off-by` under your git identity |
| `disclosure` | `auto` | AI-assistance note: `auto` = follow the repo's docs (stops when unclear), `true` = always, `false` = never (stops if the repo requires it) |
| `github_user` | gh login | your login, used by `bootstrap` |
| `min_repo_score` | `60` | minimum repo health score (0-100) |
| `min_stars` | `500` | ignore tiny repos |
| `languages` | `[python]` | languages to scout |
| `labels` | `help wanted`, `good first issue` | issue labels to search (one per pass, rotating) |
| `max_open_prs_per_repo` | `1` | do not pile onto one project |
| `cooldown_days` | `14` | pause new PRs to a repo after one of yours is closed unmerged (pacing only; it does not change repo scores, and `0` turns it off) |
| `auto_submit` | `false` | let the loop submit already-verified items |
| `patch_command` | `""` | optional shell command that drafts a patch; env `OSSFORGE_ITEM` = item id |

### 5. Check it works

```bash
ossforge doctor                 # git identity, gh login, ruff, config
ossforge bootstrap              # optional: learn from your merged/closed PRs so scout prefers repos that merged you (closed PRs are listed but never lower a score, since a closure can mean duplicate, superseded or withdrawn)
pytest -q                       # all tests should pass
ossforge radar pallets/click    # prints a health score for a repo
```

## Where files go (you do not create these)

ossforge creates its working folders **in the directory you run it from**, the first time they are needed.
They are git-ignored, so they never get committed or pushed.

| Path | Created by | What it holds | Safe to delete? |
|---|---|---|---|
| `.work/` | `hunt`, `audit`, `verify` | shallow clones of target repos and a per-repo virtualenv in `.work/venvs/` | yes, it is re-cloned on demand |
| `.state/queue.json` | `hunt`, `loop` | candidate queue and each item's status | resets your queue |
| `.state/audit.jsonl` | `submit`, `loop`, `patrol` | append-only log of every issue/PR/comment opened | **keep**: it drives the one-PR-per-repo and cooldown rules |
| `.state/stats.json` | `verify`, `reject`, `patrol` | per-detector precision and per-repo merge history | resets learning |
| `.state/daily.json` | `submit` | today's PR counter (the daily cap) | resets the cap for today |
| `.state/cache/` | any GitHub call | cached API responses (15 min), repo health (24 h) | yes |
| `.state/digest.md` | `loop`, `digest` | readable report of the last pass | yes |
| `.state/STOP` | `ossforge stop` | kill switch: while it exists, nothing is written to GitHub | remove with `ossforge resume` |
| `.venv/` | you (step 3) | ossforge's own virtualenv | yes, recreate with step 3 |
| `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`, `*.egg-info/` | pytest, ruff, Python, pip | tool caches and build metadata | yes |

Run ossforge from one folder consistently (for example the repo root) so it always finds the same `.state/`.
To keep state elsewhere, set `state_dir` and `work_dir` in `ossforge.yaml`.

## First run, step by step

```bash
# 1. look around (read-only)
ossforge scout --language python --limit 10
ossforge radar owner/repo

# 2. scan one promising repo; duplicates are dropped automatically
ossforge hunt owner/repo
ossforge queue

# 3. read the top candidate in .work/owner__repo/. If it is a false positive:
ossforge reject "<item id>" --reason "intentional, documented"

# 4. if it is a real bug: on a branch in the clone, add a failing test + the fix, commit, then
ossforge verify "<item id>" --branch fix/short-name --tests path/to/test_file.py::test_name \
    --issue-title "..." --issue-body-file issue.md --pr-title "..." --pr-body-file pr.md

# 5. preview, then submit (issue + PR together)
ossforge submit "<item id>"            # dry run, shows what would happen
ossforge submit "<item id>" --yes      # real submit

# 6. afterwards
ossforge cla owner/repo <pr-number>    # shows the CLA link if the project requires one; you sign it yourself
ossforge patrol                        # what each open PR needs next
```

### Continuous mode

```bash
ossforge loop --once          # one pass: patrol -> scout -> hunt -> digest (read .state/digest.md)
ossforge loop                 # keep going every 6 hours (--interval-hours N)
ossforge stop                 # kill switch
ossforge resume
```

The loop never submits anything unless `auto_submit: true` **and** an item is already `verified`.

## Command reference

```
bootstrap                 import your merged/closed PR history (personalises scout)
doctor                    check git, gh, ruff and config
scout / features          find vetted fix / feature issues (spam filtered, health gated)
radar REPO                health score for a repo
vet REPO NUMBER           vet one issue
hunt REPO                 clone, scan, rank, de-duplicate, enqueue
audit REPO                scan and print candidates without queueing
queue                     list queue items
verify ID ...             run tests without/with the fix, then mark verified
reject ID                 mark a false positive (improves detector ranking)
submit ID [--yes]         issue + PR together; dry run unless --yes; resumes after a partial failure
critique REPO PR          score someone's open PR and draft a review (nothing is posted)
post-critique REPO PR F   post an approved comment from file F (dry run unless --yes)
cla REPO PR               show the CLA bot's comment (read-only)
patrol                    outcomes and what each open PR needs
digest                    print the daily report
loop [--once]             continuous research
stop / resume             kill switch on / off
```

Use `--config path.yaml` *before* the subcommand to load a different config.

## Troubleshooting

- **Rate limits.** ossforge follows GitHub's documented guidance: it reads `Retry-After` and `x-ratelimit-reset`,
  waits (up to 90 s) and retries, otherwise stops the pass and writes a cooldown file in `.state/` that every
  ossforge process shares (a file lock also shares the search budget and write spacing). Searches are capped at 9 per minute and writes are spaced at least 1 s apart.

- **`exceeded a secondary rate limit`**: GitHub throttles bursts of requests even when quota remains. ossforge paces
  itself (searches capped at 9 per minute) and stops the pass cleanly; wait a few minutes and run again.
- **`REFUSED: ...`** from `submit`: a safety gate fired (not verified, daily cap, duplicate, anti-AI policy,
  protected path, kill switch). The message names the gate.
- **DCO check fails on a PR**: commits need `Signed-off-by`. With `signoff: true` ossforge adds it before the
  first push.
- **CLA bot comment on your PR**: open the link from `ossforge cla` and sign it yourself. It is a personal legal
  agreement, so ossforge never does it for you.

## Honest limits

- Static detectors only produce *candidates*; many are false positives. Only `verify` makes one real.
- Writing the failing test and the patch is up to you or an agent (`patch_command` hook). ossforge does not invent
  patches.
- `verify` runs the project's tests in a virtualenv with a scrubbed environment (no GitHub tokens). That is hygiene,
  not a sandbox; use Docker for repositories you do not trust.
- Detectors are strongest for Python; JavaScript/TypeScript has a few patterns.

## Contributing to ossforge

Issues and PRs are welcome. Run `pytest -q` and `ruff check src tests` before opening a PR.

## License

MIT. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md) for credits.
