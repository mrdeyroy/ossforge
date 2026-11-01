"""Continuous research loop. One pass = patrol -> scout -> hunt -> (draft) -> (submit verified).

Safe by construction: kill switch every pass, daily cap enforced by DailyLimiter,
and nothing is submitted unless an item is already `verified` AND auto_submit is on.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from . import digest, gh, hunt, patrol, safety, scout, submit
from .config import Config
from .limiter import DailyLimiter
from .outcomes import Stats
from .queue import Item, Queue

MAX_REPOS_PER_PASS = 4


def run_once(cfg: Config) -> list[str]:
    notes: list[str] = []
    try:
        safety.kill_switch(cfg)
    except safety.Blocked as e:
        return [f"halted: {e}"]
    gh.configure(cfg.path("cache"), cfg.cache_ttl_seconds)
    q = Queue(cfg.path("queue.json"))
    audit = safety.Audit(cfg.path("audit.jsonl"))
    stats = Stats(cfg.path("stats.json"))
    limiter = DailyLimiter(cfg.path("daily.json"), cfg.cap)

    try:
        _pass(cfg, q, audit, stats, limiter, notes)
    except gh.RateLimited as e:
        notes.append(f"stopped early: GitHub rate limit ({str(e)[:80]}). Progress is saved; the next pass continues after the cooldown.")
    digest.write(cfg.path("digest.md"), digest.render(q, audit, [], notes))
    return notes


def _pass(cfg: Config, q: Queue, audit: safety.Audit, stats: Stats, limiter: DailyLimiter, notes: list[str]) -> None:
    actions = patrol.patrol(audit, stats)
    notes.append(f"patrol: {sum(a.kind not in ('idle',) for a in actions)} open item(s) need attention")

    history = safety.effective_history(audit.read())
    blocked = {r["repo"] for r in history if r.get("repo") and safety.repo_allowed(cfg, r["repo"], history)}

    repos: list[str] = []
    feats: list[scout.Candidate] = []
    day = int(time.time() // 86400)
    for lang in cfg.languages:
        # one label per pass (rotating) keeps the request burst small; features alternate days
        label = cfg.labels[day % len(cfg.labels)]
        for c in scout.scout(cfg, stats, lang, label, 12, skip_repos=blocked):
            if c.verdict.decision == "approve" and c.repo not in repos:
                repos.append(c.repo)
        if day % 2:
            feats += [c for c in scout.scout_features(cfg, stats, lang, 8, blocked) if c.verdict.decision == "approve"]
    notes.append(f"scout: {len(repos)} healthy, open-to-AI repo(s) with approved issues")

    for repo in repos[:MAX_REPOS_PER_PASS]:
        r = hunt.hunt(cfg, repo, q, stats)
        notes.append(f"hunt {repo}: " + (f"skipped (anti-AI in {r['anti_ai']})" if r["anti_ai"]
                                         else f"{r['clean']} clean, {r['duplicate']} duplicate"))
    for c in feats[:3]:
        it = Item(f"{c.repo}#{c.number}:feature", c.repo, "", c.number, "feature", c.title,
                  status="clean", work="feature", notes=[c.url])
        q.add(it)
    q.save()

    if cfg.patch_command:
        for it in sorted(q.by_status("clean"), key=lambda i: -i.rank)[:1]:
            subprocess.run(cfg.patch_command, shell=True, env={**os.environ, "OSSFORGE_ITEM": it.id})
            notes.append(f"patch_command ran for {it.id}; run `ossforge verify` to confirm it")

    if cfg.auto_submit:
        for it in q.by_status("verified"):
            if limiter.remaining() <= 0:
                break
            try:
                res = submit.submit(it, limiter, cfg, audit, execute=True,
                                    save=lambda p, i=it: (q.set(i.id, submitted=p), q.save()))
                q.set(it.id, status="submitted", submitted=res)
                notes.append(f"submitted {res['pr']}")
            except submit.Refused as e:
                notes.append(f"refused {it.id}: {e}")
        q.save()

    digest.write(cfg.path("digest.md"), digest.render(q, audit, actions, notes))


def run_forever(cfg: Config, interval_s: int) -> None:
    while True:
        for n in run_once(cfg):
            print(n, flush=True)
        if Path(cfg.kill_file).exists():
            return
        time.sleep(interval_s)
