"""Tests for pipeline.labels + scripts.rate + leaderboard CSV mirror.

WEDGE Step 4 of the plan. Pins four contracts:

  1. labels.append validates rating in {+2,+1,-1,-2}; rejects empties.
  2. labels.read_since filters by ISO timestamp cutoff.
  3. labels.latest_by_run_id returns most-recent row per run_id (later
     rating wins on the same run -- intent: re-rating reflects updated
     taste).
  4. leaderboard.write_csv mirrors the most recent rating + note into
     the previously-dead operator_rating + operator_notes columns.

scripts/rate.py is a thin CLI wrapper -- exercised end-to-end via
subprocess in test_rate_cli_appends_to_log.
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pipeline import labels
from pipeline.leaderboard import CompRef, LeaderboardRow, write_csv


@pytest.fixture
def tmp_labels_path(tmp_path: Path) -> Path:
    p = tmp_path / "data" / "labels.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class TestLabelsAppend:
    def test_round_trip_one_row(self, tmp_labels_path: Path) -> None:
        row = labels.append(
            run_id="evolve-test-001",
            rating=2,
            note="Loved it",
            goal_sha="abc123",
            path=tmp_labels_path,
        )
        assert row["run_id"] == "evolve-test-001"
        assert row["rating"] == 2
        rows = labels.read_all(tmp_labels_path)
        assert len(rows) == 1
        assert rows[0]["rating"] == 2
        assert rows[0]["note"] == "Loved it"
        assert rows[0]["goal_sha"] == "abc123"

    def test_rejects_invalid_rating(self, tmp_labels_path: Path) -> None:
        with pytest.raises(ValueError, match="rating must be one of"):
            labels.append(run_id="x", rating=0, path=tmp_labels_path)
        with pytest.raises(ValueError, match="rating must be one of"):
            labels.append(run_id="x", rating=3, path=tmp_labels_path)
        assert not tmp_labels_path.exists()

    def test_rejects_empty_run_id(self, tmp_labels_path: Path) -> None:
        with pytest.raises(ValueError, match="run_id"):
            labels.append(run_id="", rating=1, path=tmp_labels_path)

    def test_read_all_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert labels.read_all(tmp_path / "nope.jsonl") == []

    def test_read_all_skips_malformed_rows(self, tmp_labels_path: Path) -> None:
        tmp_labels_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_labels_path.write_text(
            '{"run_id":"a","rating":1,"ts":"2026-05-26T00:00:00+00:00"}\n'
            "not-valid-json\n"
            '{"run_id":"b","rating":-1,"ts":"2026-05-27T00:00:00+00:00"}\n'
        )
        rows = labels.read_all(tmp_labels_path)
        assert len(rows) == 2
        assert {str(r["run_id"]) for r in rows} == {"a", "b"}


class TestReadSince:
    def test_filter_by_cutoff(self, tmp_labels_path: Path) -> None:
        t1 = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
        t2 = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
        t3 = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
        labels.append("a", 1, path=tmp_labels_path, ts=t1.isoformat())
        labels.append("b", 2, path=tmp_labels_path, ts=t2.isoformat())
        labels.append("c", -1, path=tmp_labels_path, ts=t3.isoformat())

        recent = labels.read_since(t2, path=tmp_labels_path)
        assert {str(r["run_id"]) for r in recent} == {"b", "c"}

        nothing = labels.read_since(t3 + timedelta(days=1), path=tmp_labels_path)
        assert nothing == []


class TestLatestByRunId:
    def test_most_recent_wins_for_same_run_id(self, tmp_labels_path: Path) -> None:
        t1 = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
        t2 = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
        labels.append("a", -1, "first take", path=tmp_labels_path, ts=t1.isoformat())
        labels.append("a", 2, "re-read, actually great", path=tmp_labels_path, ts=t2.isoformat())
        labels.append("b", 1, path=tmp_labels_path, ts=t1.isoformat())

        latest = labels.latest_by_run_id(path=tmp_labels_path)
        assert set(latest.keys()) == {"a", "b"}
        assert latest["a"]["rating"] == 2
        assert latest["a"]["note"] == "re-read, actually great"
        assert latest["b"]["rating"] == 1


class TestRateCLI:
    def test_rate_cli_appends_to_log(self, tmp_path: Path) -> None:
        """End-to-end: invoke scripts/rate via subprocess; verify the row landed."""
        labels_path = tmp_path / "data" / "labels.jsonl"
        goal_path = tmp_path / "config" / "goal.json"
        # Goal file is optional for the CLI; we pass --goal-path pointing at
        # a missing file so Goal.load() falls back to default_v4 (its sha is
        # deterministic).
        result = subprocess.run(  # noqa: S603 -- inputs are test-controlled
            [
                sys.executable,
                "-m",
                "scripts.rate",
                "evolve-cli-test",
                "+2",
                "via CLI",
                "--labels-path",
                str(labels_path),
                "--goal-path",
                str(goal_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        assert "rated evolve-cli-test +2" in result.stdout

        rows = labels.read_all(labels_path)
        assert len(rows) == 1
        assert rows[0]["run_id"] == "evolve-cli-test"
        assert rows[0]["rating"] == 2
        assert rows[0]["note"] == "via CLI"
        assert rows[0]["goal_sha"]  # populated from the default goal

    def test_rate_cli_rejects_invalid_rating(self, tmp_path: Path) -> None:
        labels_path = tmp_path / "labels.jsonl"
        result = subprocess.run(  # noqa: S603 -- inputs are test-controlled
            [
                sys.executable,
                "-m",
                "scripts.rate",
                "x",
                "5",
                "--labels-path",
                str(labels_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        assert result.returncode != 0
        assert "rating must be one of" in result.stderr
        assert not labels_path.exists()


def _stub_leaderboard_row(run_id: str) -> LeaderboardRow:
    """Minimal LeaderboardRow for CSV-mirror testing."""
    return LeaderboardRow(
        run_id=run_id,
        produced_at="2026-05-27T12:00:00Z",
        top1_logline="A test logline",
        som_y1_usd=200_000_000.0,
        crystallization_score=0.7,
        genius_score=0.8,
        cluster_label="institutional",
        axes_triple=("MF_01", "DE_01", "SW_01"),
        winners_path="runs/test/winners.json",
        world="urban",
        moral_wager="loyalty vs truth",
        protagonist="lawyer",
        antagonist="firm",
        wound="autonomy",
        conflict="liberty vs protection",
        compression="48 hours",
        divisiveness="audience splits",
        top_comps=(CompRef(title="A.I.", similarity=0.8, ww_gross_usd=300_000_000.0),),
    )


class TestLeaderboardMirror:
    def test_csv_mirrors_latest_rating(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """write_csv must populate operator_rating + operator_notes from the
        most recent rating per run_id in data/labels.jsonl."""
        labels_path = tmp_path / "data" / "labels.jsonl"
        csv_path = tmp_path / "data" / "leaderboard.csv"
        labels_path.parent.mkdir(parents=True, exist_ok=True)

        # Redirect the lazy import in write_csv to our temp labels.jsonl.
        monkeypatch.setattr(labels, "DEFAULT_LABELS_PATH", labels_path)

        labels.append("evolve-A", 2, "absolutely write this", path=labels_path)
        labels.append("evolve-A", -1, "wait, no, too derivative", path=labels_path)
        labels.append("evolve-B", 1, path=labels_path)
        # Run C has no rating -- CSV cell stays blank.

        rows = [
            _stub_leaderboard_row("evolve-A"),
            _stub_leaderboard_row("evolve-B"),
            _stub_leaderboard_row("evolve-C"),
        ]
        write_csv(rows, path=csv_path)

        with open(csv_path) as f:
            data = list(csv.DictReader(f))
        by_run = {r["run_id"]: r for r in data}

        # Most recent rating wins -- A's later -1 overrides earlier +2.
        assert by_run["evolve-A"]["operator_rating"] == "-1"
        assert by_run["evolve-A"]["operator_notes"] == "wait, no, too derivative"
        assert by_run["evolve-B"]["operator_rating"] == "+1"
        assert by_run["evolve-B"]["operator_notes"] == ""
        # Unrated run stays blank.
        assert by_run["evolve-C"]["operator_rating"] == ""
        assert by_run["evolve-C"]["operator_notes"] == ""

    def test_csv_mirror_blank_when_no_labels_log(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pre-Step-4 behaviour preserved: if no labels.jsonl exists, the
        operator columns ship blank rather than crash."""
        labels_path = tmp_path / "nope.jsonl"
        monkeypatch.setattr(labels, "DEFAULT_LABELS_PATH", labels_path)
        csv_path = tmp_path / "leaderboard.csv"
        rows = [_stub_leaderboard_row("evolve-X")]
        write_csv(rows, path=csv_path)
        with open(csv_path) as f:
            data = list(csv.DictReader(f))
        assert data[0]["operator_rating"] == ""
        assert data[0]["operator_notes"] == ""


# Silence unused-import warnings for io / json that are imported in the
# event a future test wants them.
_ = io
_ = json
