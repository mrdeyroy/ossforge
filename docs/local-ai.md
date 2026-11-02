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
