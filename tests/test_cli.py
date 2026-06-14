"""End-to-end tests for the command-line interface (:mod:`pqcsched.cli`).

These call ``main([...])`` directly (no subprocess) so failures surface a real
traceback and ``capsys`` can assert on what the user would see. Instances are
kept tiny so CP-SAT proves OPTIMAL in milliseconds and the suite stays fast.

The contract under test (lead's brief §12):
  * ``gen``       writes a JSON file that loads back as an :class:`Instance`.
  * ``solve``     loads that instance, exits 0, and prints a solver status.
  * ``baselines`` prints a comparison table naming every greedy baseline.
"""

from __future__ import annotations

import pytest

from pqcsched import BASELINES, Instance
from pqcsched.cli import main


def _gen(tmp_path, **extra) -> str:
    """Generate a tiny instance via the CLI, returning the JSON path."""
    out = tmp_path / "inst.json"
    argv = [
        "gen", "--size", "14", "--T", "10",
        "--deadline-pressure", "medium", "--t-crqc", "7",
        "--seed", "0", "--out", str(out),
    ]
    for k, v in extra.items():
        argv += [f"--{k}", str(v)]
    assert main(argv) == 0
    return str(out)


# ---------------------------------------------------------------------------
# gen
# ---------------------------------------------------------------------------
def test_gen_writes_loadable_instance(tmp_path, capsys):
    path = _gen(tmp_path)
    # the file exists and round-trips through the locked model contract
    inst = Instance.from_json(path)
    assert isinstance(inst, Instance)
    assert len(inst.assets) == 14
    assert inst.T == 10
    assert len(inst.budget) == inst.T
    out = capsys.readouterr().out
    assert "Generated instance" in out
    assert "assets" in out


def test_gen_deadline_pressure_preset_maps_to_float(tmp_path):
    # "high" must be accepted and recorded as the documented 0.8 preset.
    path = _gen(tmp_path)  # use a fresh instance with an explicit preset below
    out = tmp_path / "hi.json"
    assert main([
        "gen", "--size", "10", "--T", "8", "--deadline-pressure", "high",
        "--out", str(out),
    ]) == 0
    inst = Instance.from_json(str(out))
    assert inst.meta["params"]["deadline_pressure"] == pytest.approx(0.8)


def test_gen_rejects_bad_deadline_pressure(tmp_path):
    # An out-of-range / unparseable preset must be rejected by argparse (SystemExit).
    with pytest.raises(SystemExit):
        main([
            "gen", "--size", "8", "--deadline-pressure", "huge",
            "--out", str(tmp_path / "x.json"),
        ])


# ---------------------------------------------------------------------------
# solve
# ---------------------------------------------------------------------------
def test_solve_instance_exits_zero_and_prints_status(tmp_path, capsys):
    path = _gen(tmp_path)
    rc = main([
        "solve", "--instance", path, "--time-limit", "15", "--workers", "4",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "status" in out
    # tiny instance is solved to proven optimality
    assert "OPTIMAL" in out
    assert "Per-period migration plan" in out


def test_solve_writes_roadmap_out(tmp_path):
    import json

    path = _gen(tmp_path)
    roadmap = tmp_path / "roadmap.json"
    rc = main([
        "solve", "--instance", path, "--time-limit", "15", "--workers", "4",
        "--out", str(roadmap),
    ])
    assert rc == 0
    assert roadmap.exists()
    payload = json.loads(roadmap.read_text(encoding="utf-8"))
    assert payload["status"] == "OPTIMAL"
    assert "schedule" in payload and payload["schedule"]
    assert "summary" in payload and "risk" in payload["summary"]


def test_solve_missing_source_errors(tmp_path):
    # Neither --instance nor --cbom -> argparse's required mutually-exclusive
    # group raises SystemExit before our handler runs.
    with pytest.raises(SystemExit):
        main(["solve", "--time-limit", "5"])


def test_solve_missing_milp_backend_fails_cleanly(tmp_path, capsys, monkeypatch):
    # solve_milp is an *optional* module. Force the import to fail so the guard is
    # exercised whether or not the module is installed: --solver highs must fail
    # with a clear message and a non-zero exit, never a traceback. Setting the
    # sys.modules entry to None is the standard idiom that makes a subsequent
    # `from .solve_milp import ...` raise ImportError (even if it was cached).
    import sys

    monkeypatch.setitem(sys.modules, "pqcsched.solve_milp", None)

    path = _gen(tmp_path)
    rc = main([
        "solve", "--instance", path, "--solver", "highs",
        "--time-limit", "5", "--workers", "4",
    ])
    assert rc == 2
    captured = capsys.readouterr()
    assert "solve_milp" in captured.err
    # the misleading "Solving..." banner must NOT appear before the error
    assert "Solving" not in captured.out


def test_solve_cbom_ingest_runs(capsys):
    # If the optional CBOM module + sample ship, --cbom must load and solve them
    # without error (the result may be INFEASIBLE; that is reported, not crashed).
    import os

    pytest.importorskip("pqcsched.cbom")
    sample = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "benchmark", "sample.cbom.json",
    )
    if not os.path.exists(sample):
        pytest.skip("benchmark/sample.cbom.json not present")
    rc = main([
        "solve", "--cbom", sample, "--periods", "20", "--t-crqc", "13",
        "--time-limit", "15", "--workers", "4",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "status" in out


# ---------------------------------------------------------------------------
# baselines
# ---------------------------------------------------------------------------
def test_baselines_prints_table_with_all_baselines(tmp_path, capsys):
    path = _gen(tmp_path)
    rc = main([
        "baselines", "--instance", path, "--time-limit", "15", "--workers", "4",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    # header columns present
    for col in ("method", "risk", "cost", "feasible", "gap_vs_opt"):
        assert col in out
    # the optimal row plus every greedy baseline appears
    assert "optimal" in out
    for b in BASELINES:
        assert b in out


# ---------------------------------------------------------------------------
# top-level dispatch
# ---------------------------------------------------------------------------
def test_no_command_prints_help_nonzero(capsys):
    rc = main([])
    assert rc == 2
    out = capsys.readouterr().out
    assert "usage" in out.lower()
