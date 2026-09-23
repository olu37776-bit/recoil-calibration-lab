from pathlib import Path

from recoil_lab.cli import main
from recoil_lab.contracts import read_json


def test_demo(tmp_path):
    assert main(["demo", "--out", str(tmp_path)]) == 0
    report = read_json(tmp_path / "validation.json")
    assert report["passed"] and not report["game_verified"]
    assert "SIMULATED_REPLAY" in (tmp_path / "report.html").read_text(encoding="utf-8")


def test_public_cli_pipeline(tmp_path):
    assert main(["demo", "--out", str(tmp_path)]) == 0
    trials = tmp_path / "trials"
    response = tmp_path / "cli-response.json"
    p1 = tmp_path / "cli-initial.json"
    p2 = tmp_path / "cli-refined.json"
    assert main(["response", "--trials", *[str(trials / f"response-{i}.json") for i in (10,11,12)],
                 "--out", str(response)]) == 0
    assert main(["fit", "--response", str(response), "--trials",
                 *[str(trials / f"train-{i}.json") for i in (21,22,23)], "--out", str(p1)]) == 0
    assert main(["refine", "--profile", str(p1), "--trials",
                 *[str(trials / f"train-{i}.json") for i in (31,32,33)], "--out", str(p2)]) == 0
    report = tmp_path / "cli-validation.json"
    assert main(["validate", "--profile", str(p2), "--previous", str(p1), "--trials",
                 *[str(trials / f"validation-{i}.json") for i in (41,42,43)], "--out", str(report)]) == 0
    assert main(["replay", "--profile", str(p2), "--out", str(tmp_path / "commands.json")]) == 0
    assert read_json(tmp_path / "commands.json")["mode"] == "recording_only"


def test_cli_missing_input(tmp_path, capsys):
    assert main(["fit", "--response", str(tmp_path / "absent.json"), "--trials",
                 str(tmp_path / "trial.json"), "--out", str(tmp_path / "p.json")]) == 2
    assert "REJECTED" in capsys.readouterr().err
    assert not (tmp_path / "p.json").exists()
