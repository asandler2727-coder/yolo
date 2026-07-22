import os
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).parent.parent
GUARD = ROOT / "scripts" / "guard_paper_launch.sh"


def _run_guard(approved=None):
    env = os.environ.copy()
    env.pop("YOLO_APPROVED_STRATEGY", None)
    if approved is not None:
        env["YOLO_APPROVED_STRATEGY"] = approved
    return subprocess.run(
        ["/bin/sh", str(GUARD), "MemeMomentum", "/usr/bin/true"],
        capture_output=True,
        text=True,
        env=env,
    )


def test_paper_launcher_refuses_without_matching_strategy_approval():
    result = _run_guard()
    assert result.returncode != 0
    assert "no approved strategy" in result.stderr.lower()


def test_paper_launcher_executes_only_with_matching_strategy_approval():
    mismatch = _run_guard("SomeOtherStrategy")
    assert mismatch.returncode != 0

    approved = _run_guard("MemeMomentum")
    assert approved.returncode == 0


def test_paper_config_and_compose_are_fail_closed_by_default():
    config = json.loads((ROOT / "config-paper.json").read_text())
    compose = (ROOT / "docker-compose.yml").read_text()

    assert config["dry_run"] is True
    assert config["initial_state"] == "stopped"
    assert "guard_paper_launch.sh" in compose
    assert "YOLO_APPROVED_STRATEGY=${YOLO_APPROVED_STRATEGY:-}" in compose
    assert "YOLO_APPROVED_STRATEGY=MemeMomentum" not in compose
