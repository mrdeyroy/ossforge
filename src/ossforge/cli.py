from __future__ import annotations

import argparse
from pathlib import Path

from . import audit as audit_mod
from . import comment, critique, digest, doctor, gh, hunt, loop, patrol, profile, radar, safety, scout, submit, vet, verify
from .config import Config, load
from .limiter import DailyLimiter
from .outcomes import Stats
from .queue import Queue


def _ctx(cfg: Config):
    gh.configure(cfg.path("cache"), cfg.cache_ttl_seconds)
    return (Queue(cfg.path("queue.json")), safety.Audit(cfg.path("audit.jsonl")),
            Stats(cfg.path("stats.json")), DailyLimiter(cfg.path("daily.json"), cfg.cap))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser("ossforge")
    ap.add_argument("--config", default="ossforge.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help_, *args, **flags):
        p = sub.add_parser(name, help=help_)
        for a in args:
            p.add_argument(a)
        for f, kw in flags.items():
            p.add_argument("--" + f.replace("_", "-"), **kw)
        return p

    add("radar", "score a repo's health", "repo")
    v = add("vet", "vet one issue", "repo")
    v.add_argument("number", type=int)
    add("scout", "find vetted fix issues", language={}, label={"default": "help wanted"}, limit={"type": int, "default": 20})
    add("features", "find vetted feature issues", language={}, limit={"type": int, "default": 15})
    c = add("critique", "score an open PR and draft (not post) a review", "repo")
    c.add_argument("number", type=int)
    pc = add("post-critique", "post an approved critique comment (dry run unless --yes)", "repo")
    pc.add_argument("number", type=int)
    pc.add_argument("body_file")
    pc.add_argument("--yes", action="store_true")
    add("audit", "scan a repo for bug/perf candidates", "repo")
    add("hunt", "scan, rank, de-duplicate and enqueue", "repo")
    add("queue", "list queue items")
    vf = add("verify", "run the repo's tests with/without the fix, then mark verified", "id")
    vf.add_argument("--branch", required=True)
    vf.add_argument("--tests", nargs="+", required=True, help="pytest args selecting the new test")
    vf.add_argument("--issue-title", required=True)
    vf.add_argument("--issue-body-file", required=True)
    vf.add_argument("--pr-title", required=True)
    vf.add_argument("--pr-body-file", required=True)
    vf.add_argument("--install", nargs="*", default=["."], help="paths to pip install -e in the venv")
    rj = add("reject", "mark an item as a false positive (feeds detector precision)", "id")
    rj.add_argument("--reason", default="")
    sm = add("submit", "file issue + PR together (dry run unless --yes)", "id")
    sm.add_argument("--yes", action="store_true")
    cl = add("cla", "show the CLA bot comment on a PR (you sign it yourself)", "repo")
    cl.add_argument("pr", type=int)
    add("patrol", "check our open PRs and say what each needs")
    add("digest", "write and print the daily digest")
    lp = add("loop", "run the research loop", once={"action": "store_true"}, interval_hours={"type": float, "default": 6})
    lp.set_defaults()
    add("doctor", "check git, gh, ruff and config before the first run")
    add("bootstrap", "import your merged/closed PR history to personalise scouting")
    add("stop", "create the kill switch file")
    add("resume", "remove the kill switch file")
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    cfg = load(a.config)
    q, audit, stats, limiter = _ctx(cfg)

    if a.cmd == "stop":
        Path(cfg.kill_file).parent.mkdir(parents=True, exist_ok=True)
        Path(cfg.kill_file).write_text("stopped\n")
        print("kill switch on:", cfg.kill_file)
    elif a.cmd == "resume":
        Path(cfg.kill_file).unlink(missing_ok=True)
        print("kill switch off")
    elif a.cmd == "doctor":
        results = doctor.check(cfg)
        for name, ok, detail in results:
            print(f"[{'ok' if ok else 'FIX'}] {name}: {detail}")
        return 0 if all(ok for _, ok, _ in results) else 1
    elif a.cmd == "bootstrap":
        r = profile.bootstrap(stats, cfg.github_user)
        print(f"{r['user']}: merged PRs in {r['merged_repos']} repos, closed unmerged in {r['closed_repos']} repos")
        for repo, n in sorted(r["merged"].items(), key=lambda kv: -kv[1]):
            print(f"  merged x{n}: {repo}")
    elif a.cmd == "radar":
        x = radar.analyze(a.repo)
        print(f"{x.repo}: {x.score}/100 {x.recommendation} flags={x.flags}")
        for n in x.notes:
            print("  -", n)
    elif a.cmd == "vet":
        x = vet.vet_issue(a.repo, a.number)
        print(x.issue, x.decision, "; ".join(x.reasons))
    elif a.cmd in ("scout", "features"):
        fn = (lambda: scout.scout(cfg, stats, a.language, a.label, a.limit)) if a.cmd == "scout" else \
             (lambda: scout.scout_features(cfg, stats, a.language, a.limit))
        for c_ in fn():
            print(f"[{c_.verdict.decision:7}] {c_.repo}#{c_.number} repo={c_.repo_score} {c_.title}")
            print(f"          {'; '.join(c_.verdict.reasons)}\n          {c_.url}")
    elif a.cmd == "critique":
        x = critique.critique(a.repo, a.number)
        print(f"{x.repo}#{x.number} by {x.author}: merge likelihood {x.prediction.score} ({x.prediction.label})")
        print("  signals:", "; ".join(x.prediction.notes))
        for f in x.findings:
            print(f"  [{f.severity}] {f.path}:{f.line} {f.kind}: {f.detail}")
        print("\n--- DRAFT (not posted) ---\n" + x.draft)
    elif a.cmd == "post-critique":
        try:
            print(comment.post(cfg, audit, a.repo, a.number, Path(a.body_file).read_text(encoding="utf-8"), a.yes))
        except comment.Refused as e:
            print("REFUSED:", e)
            return 1
    elif a.cmd == "audit":
        dest = hunt.clone(cfg, a.repo)
        pol = hunt.policy_of(dest)
        if pol.anti_ai:
            print(f"SKIP {a.repo}: anti-AI policy in {pol.source}. No findings produced.")
            return 0
        for f in sorted(audit_mod.scan_tree(dest), key=lambda x: (x.severity, x.path, x.line)):
            print(f"  [{f.severity}] {f.path}:{f.line} {f.kind}: {f.detail}")
    elif a.cmd == "hunt":
        r = hunt.hunt(cfg, a.repo, q, stats)
        print(f"SKIP {a.repo}: anti-AI policy in {r['anti_ai']}" if r["anti_ai"]
              else f"{a.repo}: {r['clean']} clean (need verification), {r['duplicate']} duplicate")
    elif a.cmd == "queue":
        for i in sorted(q.items.values(), key=lambda i: -i.rank):
            print(f"[{i.status:9}] {i.rank:.2f} {i.id}  {i.detail}")
            for n in i.notes:
                print("              ", n)
    elif a.cmd == "verify":
        it = q.items[a.id]
        clone = Path(it.clone)
        py = verify.venv_python(Path(cfg.work_dir), it.repo)
        rc, out = verify.install_project(py, clone, a.install)
        if rc:
            print("install failed:\n", out)
            return 1
        base = submit._run(["git", "merge-base", "HEAD", "origin/HEAD"], str(clone))
        r = verify.verify_fix(clone, base, py, a.tests)
        print("failed without fix:", r.failed_without_fix, "| passed with fix:", r.passed_with_fix, "| lint ok:", r.lint_ok)
        stats.record_kind(it.kind, r.ok)
        stats.save()
        if not r.ok:
            print("\n".join(r.log))
            return 1
        q.set(a.id, status="verified", branch=a.branch, issue_title=a.issue_title, pr_title=a.pr_title,
              issue_body=Path(a.issue_body_file).read_text(encoding="utf-8"),
              pr_body=Path(a.pr_body_file).read_text(encoding="utf-8"))
        q.save()
        print("verified:", a.id)
    elif a.cmd == "reject":
        it = q.set(a.id, status="rejected", notes=[a.reason] if a.reason else [])
        stats.record_kind(it.kind, False)
        stats.save()
        q.save()
        print("rejected:", a.id)
    elif a.cmd == "submit":
        try:
            res = submit.submit(q.items[a.id], limiter, cfg, audit, execute=a.yes,
                                save=lambda p: (q.set(a.id, submitted=p), q.save()))
        except submit.Refused as e:
            print("REFUSED:", e)
            return 1
        if a.yes:
            q.set(a.id, status="submitted", submitted=res)
            q.save()
        print(res)
    elif a.cmd == "cla":
        url = submit.cla_status(a.repo, a.pr)
        print(url or "No CLA bot comment yet.", "\nOpen it and sign as yourself; ossforge never signs a CLA.")
    elif a.cmd == "patrol":
        for x in patrol.patrol(audit, stats):
            print(f"{x.repo}#{x.pr} [{x.kind}] {x.detail}")
    elif a.cmd == "digest":
        print(digest.render(q, audit, patrol.patrol(audit, stats)))
    elif a.cmd == "loop":
        if a.once:
            print("\n".join(loop.run_once(cfg)))
        else:
            loop.run_forever(cfg, int(a.interval_hours * 3600))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
