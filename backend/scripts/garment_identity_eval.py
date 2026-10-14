"""Evaluate cross-event garment-identity proposals without reading photographs.

Inputs are locally prepared JSONL annotations and pair similarities. The report
contains only aggregate metrics; neither the input names nor their IDs are output.
No network, model or image dependencies.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


@dataclass(frozen=True)
class Observation:
    observation_id: str
    garment_id: str
    person_id: str
    event_id: str
    category: str


def _text_field(row: Mapping[str, Any], name: str, line: int) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"annotations line {line}: {name} must be a nonempty trimmed string")
    return value


def _json_rows(path: Path, source: str) -> Iterator[tuple[int, dict[str, Any]]]:
    # Input can contain sensitive IDs; do not echo malformed lines or paths.
    with path.open("r", encoding="utf-8") as stream:
        for line, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{source} line {line}: invalid JSON") from None
            if not isinstance(row, dict):
                raise ValueError(f"{source} line {line}: expected object")
            yield line, row


def load_observations(path: Path) -> dict[str, Observation]:
    result: dict[str, Observation] = {}
    categories: dict[tuple[str, str], str] = {}
    required = set(Observation.__dataclass_fields__)
    for line, row in _json_rows(path, "annotations"):
        if set(row) != required:
            expected = ", ".join(sorted(required))
            raise ValueError(f"annotations line {line}: expected exactly {expected}")
        obs = Observation(**{key: _text_field(row, key, line) for key in required})
        if obs.observation_id in result:
            raise ValueError(f"annotations line {line}: duplicate observation ID")
        key = (obs.person_id, obs.garment_id)
        previous = categories.setdefault(key, obs.category)
        if previous != obs.category:
            raise ValueError(f"annotations line {line}: inconsistent category for garment")
        result[obs.observation_id] = obs
    if not result:
        raise ValueError("annotations: no observations supplied")
    return result


def _pairs_across_events(counts: Counter[str]) -> int:
    n = sum(counts.values())
    return n * (n - 1) // 2 - sum(v * (v - 1) // 2 for v in counts.values())


def evaluate(
    observations: Mapping[str, Observation],
    scores_path: Path,
    person_id: str,
    threshold: float,
) -> dict[str, Any]:
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (float, int))
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise ValueError("threshold must be a finite number in [0, 1]")
    if not person_id:
        raise ValueError("person_id must be nonempty")

    groups: dict[str, Counter[str]] = {}
    garments: dict[tuple[str, str], Counter[str]] = {}
    target_count = 0
    for obs in observations.values():
        if obs.person_id != person_id:
            continue
        target_count += 1
        groups.setdefault(obs.category, Counter())[obs.event_id] += 1
        garments.setdefault((obs.category, obs.garment_id), Counter())[obs.event_id] += 1

    total_pairs = sum(_pairs_across_events(counts) for counts in groups.values())
    positives = sum(_pairs_across_events(counts) for counts in garments.values())
    negatives = total_pairs - positives
    if target_count == 0:
        raise ValueError("no observations for requested subject")

    tp = fp = scored_true = scored_valid = 0
    blocked_person = blocked_category = blocked_same_event = 0
    unsafe_cross_person = 0
    seen: set[tuple[str, str]] = set()
    for line, row in _json_rows(scores_path, "scores"):
        if set(row) != {"left", "right", "similarity"}:
            raise ValueError(f"scores line {line}: expected left, right, similarity")
        left_id, right_id = row["left"], row["right"]
        if not isinstance(left_id, str) or not isinstance(right_id, str):
            raise ValueError(f"scores line {line}: IDs must be strings")
        if left_id == right_id:
            raise ValueError(f"scores line {line}: cannot match an observation to itself")
        if left_id not in observations or right_id not in observations:
            raise ValueError(f"scores line {line}: unknown observation ID")
        pair = tuple(sorted((left_id, right_id)))
        if pair in seen:
            raise ValueError(f"scores line {line}: duplicate unordered pair")
        seen.add(pair)
        similarity = row["similarity"]
        if (
            isinstance(similarity, bool)
            or not isinstance(similarity, (int, float))
            or not math.isfinite(similarity)
            or not 0 <= similarity <= 1
        ):
            raise ValueError(f"scores line {line}: similarity must be finite in [0, 1]")

        a, b = observations[left_id], observations[right_id]
        if a.person_id != person_id or b.person_id != person_id:
            blocked_person += 1
            if similarity >= threshold:
                unsafe_cross_person += 1
            continue
        if a.category != b.category:
            blocked_category += 1
            continue
        if a.event_id == b.event_id:
            blocked_same_event += 1
            continue
        scored_valid += 1
        same_garment = a.garment_id == b.garment_id
        if same_garment:
            scored_true += 1
        if similarity >= threshold:
            if same_garment:
                tp += 1
            else:
                fp += 1

    return {
        "scope": "cross-event, selected-person, same-category",
        "threshold": threshold,
        "observations": target_count,
        "eligible_pairs": total_pairs,
        "positive_pairs": positives,
        "negative_pairs": negatives,
        "scored_eligible_pairs": scored_valid,
        "scored_positive_pairs": scored_true,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": positives - tp,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / positives if positives else None,
        "false_merge_rate": fp / negatives if negatives else None,
        "candidate_positive_coverage": scored_true / positives if positives else None,
        "blocked_other_person": blocked_person,
        "unsafe_other_person_high_score": unsafe_cross_person,
        "blocked_different_category": blocked_category,
        "blocked_same_event": blocked_same_event,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Private, annotation-only garment identity evaluation"
    )
    parser.add_argument(
        "--observations", type=Path, required=True, help="private JSONL annotations"
    )
    parser.add_argument(
        "--scores", type=Path, required=True, help="private JSONL similarity proposals"
    )
    parser.add_argument("--subject", required=True, help="opaque selected person ID (not printed)")
    parser.add_argument(
        "--threshold", type=float, default=0.9, help="predeclared similarity cutoff"
    )
    args = parser.parse_args(argv)
    try:
        observations = load_observations(args.observations)
        report = evaluate(observations, args.scores, args.subject, args.threshold)
    except (OSError, ValueError) as exc:
        # Exception strings from OSError can contain private paths. Only show
        # generic errors for failures that are not controlled validation.
        if isinstance(exc, OSError):
            print("Unable to access private input file", file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
