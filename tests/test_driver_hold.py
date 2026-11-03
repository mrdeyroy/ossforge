import json
import sys
from pathlib import Path

import pytest

from ossforge import agent_run, driver, agent_next, evidence
from ossforge.queue import Queue
from test_agent_run import fixture


def test_real_driver_can_hold_unreproducible_task_without_fake_patch(tmp_path, monkeypatch):
    cfg, _ = fixture(tmp_path)  # local contract fixture, not public discovery proof
    script = tmp_path / "qualify.py"
    script.write_text("""import os,json
from pathlib import Path
t=json.loads(Path(os.environ['OSSFORGE_TASK_FILE']).read_text())
r=t['hold_result_schema'];r.update(reason='missing reporter weights and native compiler; no source bug reproduced')
Path(os.environ['OSSFORGE_RESULT_FILE']).write_text(json.dumps(r))
""")
    monkeypatch.setattr(driver.verify, "verify_fix", lambda *a, **k: pytest.fail("hold cannot verify a patch"))
    monkeypatch.setattr(agent_run.submit, "submit", lambda *a, **k: pytest.fail("hold cannot publish"))
    out = agent_run.run(cfg, [sys.executable, str(script)], discover=False, execute=True)
    assert out["status"] == "held" and not out.get("evidence")
    q = Queue(cfg.path("queue.json"))
    assert q.items["a"].status == "held" and not q.items["a"].verification
    assert "missing reporter weights" in q.items["a"].hold_reason
    assert agent_next.next_step(cfg, q, "c.yaml")["status"] == "held_work"
    count = json.loads(cfg.path("driver-attempts.json").read_text())["count"]
    assert agent_run.run(cfg, ["must-not-launch"], discover=False)["status"] == "no_work"
    assert json.loads(cfg.path("driver-attempts.json").read_text())["count"] == count


def test_hold_result_cannot_hide_changed_checkout_or_partial_publication(tmp_path):
    cfg, _ = fixture(tmp_path)
    q = Queue(cfg.path("queue.json"))
    task = driver.task(q)
    result = task["hold_result_schema"]
    result["reason"] = "cannot reproduce"
    path = tmp_path / "r.json"
    path.write_text(json.dumps(result))
    result = driver.parse(path)
    clone = Path(q.items["a"].clone)
    (clone / "calc.py").write_text("unfinished driver edit\n")
    with pytest.raises(evidence.StaleEvidence, match="dirty"):
        driver.complete(q, result)
    assert q.items["a"].status == "clean"


def test_hold_schema_refuses_extra_fields_and_empty_reason(tmp_path):
    cfg, _ = fixture(tmp_path)
    q = Queue(cfg.path("queue.json"))
    r = driver.task(q)["hold_result_schema"]
    p = tmp_path / "r.json"
    for bad in [dict(r, reason=""), dict(r, verified=True), dict(r, schema=True), dict(r, tree="")]:
        p.write_text(json.dumps(bad))
        with pytest.raises(driver.Invalid):
            driver.parse(p)
    q.items["a"].submitted = {"fork_pushed": True}
    with pytest.raises(driver.Invalid, match="partial publication"):
        driver.complete(q, r)
    assert q.items["a"].status == "clean"


def test_driver_changed_committed_tree_cannot_hide_edits_with_hold(tmp_path, monkeypatch):
    cfg, _ = fixture(tmp_path)
    script = tmp_path / "changed.py"
    script.write_text("""import json,os,subprocess
from pathlib import Path
t=json.loads(Path(os.environ['OSSFORGE_TASK_FILE']).read_text())
Path('calc.py').write_text('def f(n): return 0\\n')
subprocess.run(['git','add','calc.py'],check=True)
subprocess.run(['git','commit','-qm','unchecked edit'],check=True)
r=t['hold_result_schema'];r['reason']='cannot reproduce'
Path(os.environ['OSSFORGE_RESULT_FILE']).write_text(json.dumps(r))
""")
    with pytest.raises(driver.Invalid, match="no longer matches"):
        agent_run.run(cfg, [sys.executable, str(script)], discover=False)
    assert Queue(cfg.path("queue.json")).items["a"].status == "clean"
