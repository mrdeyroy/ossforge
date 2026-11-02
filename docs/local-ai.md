# Local AI contribution workflow

This is a public contract for Claude Code or another local coding assistant. It
makes no model calls and requires no API key in ossforge. Use your own assistant's
normal authentication. A provider subscription and usage limits are separate.

A starting prompt:

> Use ossforge in this checkout to look for a genuine, useful contribution. Read
> the repository's documentation first. Run discovery and hunt on promising,
> policy-compatible targets; a candidate is not a confirmed bug. Request
> `ossforge agent-task` for a structured local candidate. Read the target's own
> contribution instructions and existing issues/PRs, reproduce a real problem,
> and make a minimal source change with a regression test on a new local branch.
> Produce the schema-1 result JSON described by the task and run
> `ossforge agent-verify result.json`. Tests must fail for the relevant reason
> without the source fix and pass with it. Inspect the logs and run required
> repository checks. Do not use paid tools, sign legal agreements, change account
> credentials, merge upstream or bypass a refusal. If no useful candidate is
> found, report no work instead of inventing an issue. After verification, run
> `ossforge submit ID` as a dry run. Only use `--yes` if the account owner has
> authorized the exact kind of publication, identity and audience. Report actual
> issue/PR URLs or the blocking reason. A verified local test is not proof of
> upstream acceptance.

The prompt is guidance for an external assistant, not a persistent process,
security boundary or guarantee it will finish without intervention. Your assistant
must have a working terminal and respect your authority and repository rules.
No actual Claude Code run is established by the controlled tests in this project.

## Contract

- `agent-task [--item ID]` emits schema-1 JSON with a clean cloned candidate,
  base revision, requirements and the exact result shape. If there is no such
  candidate, it emits `status: no_work` rather than silently starting a model.
- The assistant creates commits locally and supplies a result file, not a claim
  that tests passed. Unknown fields, shell-string commands and unsupported schema
  versions are refused. Titles and bodies are proposals for later publication.
- `agent-verify RESULT.json` rechecks task base/active branch/clean tree and runs
  existing fail-before/pass-after verification with native argv. Only its actual
  successful result updates the local queue to verified. It never publishes.
- `submit` remains the existing separately authorized action, dry-run by default.
  Its policy, duplicate, identity, exact-tree and optional maintainer admission
  checks are not skipped by the driver contract.

Commands execute local repository code. A scrubbed environment is not a sandbox;
use a separately provisioned isolated environment for untrusted repositories. The
assistant and repository processes with filesystem/account access can bypass or
alter local state. This contract is not a signed attestation or credential boundary.
The current hook and CLI do not provide automated model retry, accounting,
container provisioning, fixed whole-run deadline or robust arbitrary check setup.

## Optional bounded local command runner

`ossforge agent-run --command '/absolute/path/to/your-driver'` runs one discovery
pass, assigns at most one clean cloned candidate, invokes an operator-provided
local driver without a shell, validates its result and reruns verification. It
retains a verified patch without publishing by default. `--publish` explicitly
opts into the existing submit path and its gates, only with owner authorization.
`--skip-discovery` works from the current queue, including a verified item waiting
for submission. This is one bounded invocation, not an always-on daemon.

The driver receives `OSSFORGE_TASK_FILE` and `OSSFORGE_RESULT_FILE`, absolute paths
to schema-1 JSON. It reads the former, performs permitted local work, then writes
the latter. Invocation uses the clone as working directory. Environment variables
are scrubbed; provider and GitHub tokens are not forwarded. Driver stdout/stderr
are discarded, so progress should be written to operator-owned local logs without
secrets. A wrapper must deliberately handle its assistant's normal local auth and
permissions. No Claude-specific wrapper or user's installed driver has been
validated here; do not copy subscription tokens into this interface.

`--timeout` defaults to 900 seconds and allows 1..3600; the driver process group is
killed on timeout. This is not a whole-run deadline: discovery, verification and
publication have their own operations. `--daily-attempts` defaults to 2, allows
1..20 and reserves an attempt before launching, including failed/crashed launches.
The counter uses the host's local date and the chosen state directory. It is not a
money/token cap, security control or global account quota. Choosing a higher value
or another state directory changes that limit. Persist the state directory.

A verified queued patch is resumed without rerunning the driver. Refused submit
keeps it verified and retains any remote progress saved by the submit path. An
interrupted unverified checkout is not reset or blindly rewritten: inspect it
before retry; dirty work prevents trusted verification. The runner does not
provision containers, hide home-directory credentials or isolate a malicious
assistant/repository. Use trusted commands and separately prepared isolation.
No real external-model autonomous contribution has yet been validated.

If discovery stops early and there is no usable queued candidate, `agent-run`
returns `discovery_incomplete` (nonzero CLI exit), not a successful `no_work`.
The reason names the discovery stop. It consumes no driver attempt and starts no
model. An already queued candidate can still be processed with normal checks;
partial discovery is not proof that no useful opportunity exists.
