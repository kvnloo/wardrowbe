"""Synthetic fixtures only: no private photo identifiers or pixels."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.garment_identity_eval import evaluate, load_observations, main


def write_rows(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def obs(
    oid: str,
    garment: str,
    event: str,
    person: str = "selected",
    category: str = "top",
) -> dict[str, str]:
    return {
        "observation_id": oid,
        "garment_id": garment,
        "person_id": person,
        "event_id": event,
        "category": category,
    }


def scored(left: str, right: str, score: float) -> dict[str, object]:
    return {"left": left, "right": right, "similarity": score}


def fixture(tmp_path: Path) -> tuple[dict, Path]:
    # Two similar blue shirts across two events: the wrong shirt is a hard
    # negative, not another sighting of the same physical garment.
    observations = load_observations(write_rows(tmp_path / "a.jsonl", [
        obs("a1", "shirt_one", "trip_a"),
        obs("a2", "shirt_one", "trip_b"),
        obs("b1", "shirt_two", "trip_a"),
        obs("b2", "shirt_two", "trip_b"),
        obs("c1", "shirt_one", "trip_c", person="bystander"),
        obs("d1", "sneakers", "trip_c", category="footwear"),
    ]))
    return observations, tmp_path / "scores.jsonl"


def test_hard_negatives_and_held_out_event_pairs(tmp_path: Path) -> None:
    observations, path = fixture(tmp_path)
    write_rows(path, [scored("a1", "a2", 0.95), scored("b1", "b2", 0.80), scored("a1", "b2", 0.93)])
    result = evaluate(observations, path, "selected", threshold=0.9)
    assert result["eligible_pairs"] == 4
    assert result["positive_pairs"] == 2
    assert result["negative_pairs"] == 2
    assert result["true_positive"] == 1
    assert result["false_positive"] == 1
    assert result["false_negative"] == 1
    assert result["precision"] == 0.5
    assert result["recall"] == 0.5
    assert result["false_merge_rate"] == 0.5
    assert result["candidate_positive_coverage"] == 1.0


def test_missing_candidate_is_counted_as_false_negative(tmp_path: Path) -> None:
    observations, path = fixture(tmp_path)
    write_rows(path, [scored("a1", "a2", 0.98)])
    result = evaluate(observations, path, "selected", 0.9)
    assert result["false_negative"] == 1
    assert result["candidate_positive_coverage"] == 0.5
    assert result["precision"] == 1.0


def test_person_category_and_same_event_gates(tmp_path: Path) -> None:
    observations, path = fixture(tmp_path)
    write_rows(path, [
        scored("a1", "c1", 1.0),  # different person, high score (unsafe)
        scored("a1", "d1", 1.0),  # category mismatch
        scored("a1", "b1", 1.0),  # same event
        scored("a1", "a2", 0.99),
    ])
    result = evaluate(observations, path, "selected", 0.9)
    assert result["blocked_other_person"] == 1
    assert result["unsafe_other_person_high_score"] == 1
    assert result["blocked_different_category"] == 1
    assert result["blocked_same_event"] == 1
    assert result["true_positive"] == 1
    assert result["false_positive"] == 0
    assert result["scored_eligible_pairs"] == 1


def test_no_predictions_has_unknown_precision(tmp_path: Path) -> None:
    observations, path = fixture(tmp_path)
    write_rows(path, [])
    result = evaluate(observations, path, "selected", 0.9)
    assert result["precision"] is None
    assert result["recall"] == 0
    assert result["false_negative"] == 2


def test_zero_positive_works(tmp_path: Path) -> None:
    observations = load_observations(write_rows(tmp_path / "o.jsonl", [
        obs("1", "shirt_one", "a"), obs("2", "shirt_two", "b")
    ]))
    path = write_rows(tmp_path / "s.jsonl", [scored("1", "2", 0.99)])
    result = evaluate(observations, path, "selected", 0.9)
    assert result["recall"] is None
    assert result["false_merge_rate"] == 1
    assert result["false_positive"] == 1


def test_invalid_input_rejected(tmp_path: Path) -> None:
    observations, path = fixture(tmp_path)
    for row in [scored("a1", "a1", 0.9), scored("a1", "not-present", 0.9),
                scored("a1", "a2", float("nan")), scored("a1", "a2", True),
                scored("a1", "a2", 2.0)]:
        write_rows(path, [row])
        with pytest.raises(ValueError):
            evaluate(observations, path, "selected", 0.9)
    with pytest.raises(ValueError):
        evaluate(observations, path, "selected", 1.1)


def test_unordered_duplicate_candidate_rejected(tmp_path: Path) -> None:
    observations, path = fixture(tmp_path)
    write_rows(path, [scored("a1", "a2", 0.95), scored("a2", "a1", 0.94)])
    with pytest.raises(ValueError, match="duplicate unordered pair"):
        evaluate(observations, path, "selected", 0.9)


def test_same_garment_must_have_consistent_category(tmp_path: Path) -> None:
    path = write_rows(tmp_path / "o.jsonl", [
        obs("a1", "physical_item", "a"),
        obs("a2", "physical_item", "b", category="footwear"),
    ])
    with pytest.raises(ValueError, match="inconsistent category"):
        load_observations(path)


def test_duplicate_and_extra_annotation_fields_rejected(tmp_path: Path) -> None:
    path = write_rows(tmp_path / "o.jsonl", [obs("a", "x", "1"), obs("a", "y", "2")])
    with pytest.raises(ValueError, match="duplicate observation"):
        load_observations(path)
    path = write_rows(tmp_path / "o.jsonl", [obs("a", "x", "1") | {"gps": "private"}])
    with pytest.raises(ValueError, match="expected exactly"):
        load_observations(path)


def test_cli_does_not_emit_ids_or_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    obs_path = write_rows(tmp_path / "my-private-trip.jsonl", [
        obs("private_scene_1", "private_green_shirt", "mytrip1", person="private_user_42"),
        obs("private_scene_2", "private_green_shirt", "mytrip2", person="private_user_42"),
    ])
    score_path = write_rows(tmp_path / "very-personal.jsonl", [
        scored("private_scene_1", "private_scene_2", 0.95),
    ])
    argv = [
        "--observations", str(obs_path), "--scores", str(score_path),
        "--subject", "private_user_42",
    ]
    assert main(argv) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["true_positive"] == 1
    assert "private_scene_1" not in captured.out
    assert "mytrip" not in captured.out
    assert str(tmp_path) not in captured.out
    assert "private_user_42" not in captured.out
