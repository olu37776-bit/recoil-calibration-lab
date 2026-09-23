"""Re-run local evidence. Never equates local tests with remote/game validation."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def source_manifest() -> dict[str, str]:
    candidates = [ROOT / x for x in ("pyproject.toml", "README.md", "AGENTS.md", ".gitignore")]
    for directory in ("src", "tests", "tools", "docs", "examples", ".github"):
        candidates.extend(p for p in (ROOT / directory).rglob("*")
                          if p.is_file() and "__pycache__" not in p.parts and ".egg-info" not in str(p))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(candidates) if p.is_file() and p.suffix not in {".pyc", ".pyo"}}


def main() -> int:
    out = ROOT / "evidence"
    out.mkdir(exist_ok=True)
    initial_manifest = source_manifest()
    # Invalidate old PASS immediately, including when the process is killed.
    (out / "verification.json").write_text(json.dumps({
        "status": "RUNNING", "source_files": initial_manifest,
        "generated_utc": datetime.now(timezone.utc).isoformat()
    }, indent=2), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    commands = [
        [sys.executable, "-m", "pytest", "-q", "--junitxml=evidence/junit.xml", "--cov=recoil_lab",
         "--cov-report=term-missing", "--cov-report=json:evidence/coverage.json"],
        [sys.executable, "-m", "recoil_lab", "demo", "--out", "evidence/demo"],
    ]
    logs = []
    for index, command in enumerate(commands):
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=180)
            text = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(command, 124)
            text = "FAILED: verification command exceeded 180-second timeout\n"
        filename = "test-output.txt" if index == 0 else "demo-output.txt"
        (out / filename).write_text(text, encoding="utf-8")
        print(text, end="")
        logs.append({"command": command, "exit_code": result.returncode, "log": filename})
        if result.returncode:
            break
    packages = {}
    for package in ("numpy", "opencv-python-headless", "opencv-python", "pytest", "pytest-cov", "pillow"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            pass
    manifest = source_manifest()
    tree_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    complete = len(logs) == 2 and all(x["exit_code"] == 0 for x in logs) and manifest == initial_manifest
    report = {"generated_utc": datetime.now(timezone.utc).isoformat(),
              "status": "PASS" if complete else "FAIL",
              "source_unchanged_during_run": manifest == initial_manifest,
              "scope": "local automated tests and synthetic replay only",
              "python": sys.version, "platform": platform.platform(), "packages": packages,
              "commands": logs, "source_tree_sha256": tree_hash, "source_files": manifest,
              "remote_status": "not assessed by local runner",
              "windows_tested": platform.system() == "Windows", "game_tested": False,
              "driver_tested": False, "publish_script_executed": False,
              "independent_reviewer": None}
    (out / "verification.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
