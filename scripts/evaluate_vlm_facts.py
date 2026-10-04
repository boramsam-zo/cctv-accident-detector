"""Offline evaluation of saved job results against human-reviewed clip labels.

No network calls, video upload, or model generation. Labels must be independently
reviewed against the original clip rather than copied from model predictions.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.backend.scene_facts import SceneFacts, validate_provenance


def evaluate(job, labels):
    candidates = {item["event_id"]: item for item in job.get("candidates", [])}
    cases, confusion = [], {name: {state: {prediction: 0 for prediction in ("present", "absent", "unknown")}
        for state in ("present", "absent", "unknown")} for name in ["accident_presence", *SceneFacts.model_fields["features"].annotation.model_fields]}
    total = correct = invalid = false_present = 0
    if not labels:
        raise ValueError("human_reviewed_labels_required")
    seen = set()
    for label in labels:
        event_id = label["event_id"]
        if event_id in seen or not label.get("reviewer") or label.get("clip_reviewed") is not True or not label.get("expected"):
            raise ValueError("unique_event_and_human_clip_review_required")
        seen.add(event_id)
        for name, state in label["expected"].items():
            if name not in confusion or state not in ("present", "absent", "unknown"):
                raise ValueError("invalid_expected_feature_or_state")
        candidate = candidates.get(event_id)
        if candidate is None:
            raise ValueError(f"missing_candidate:{event_id}")
        vlm = candidate.get("vlm") or {}
        item = {"event_id": event_id, "reviewer": label["reviewer"], "schema_and_provenance": "failed", "comparisons": []}
        total += len(label["expected"])
        try:
            facts = SceneFacts.model_validate(vlm.get("raw_output"))
            context = (vlm.get("request") or {}).get("input")
            if not context:
                raise ValueError("saved_v2_input_context_required")
            validate_provenance(facts, context)
        except (ValueError, TypeError, KeyError) as exc:
            invalid += 1
            item["error"] = str(exc)
            cases.append(item)
            continue
        item["schema_and_provenance"] = "passed"
        for name, expected in label["expected"].items():
            actual = facts.accident_presence.state if name == "accident_presence" else getattr(facts.features, name).state
            match = actual == expected
            correct += match
            false_present += actual == "present" and expected != "present"
            confusion[name][expected][actual] += 1
            item["comparisons"].append({"feature": name, "expected": expected, "actual": actual, "match": match})
        cases.append(item)
    return {"evaluation_version": "human-clip-facts-v1", "case_count": len(cases),
        "invalid_output_count": invalid, "label_count": total, "correct_count": correct,
        "state_accuracy": correct / total, "false_present_count": false_present,
        "passed": invalid == 0 and correct == total,
        "confusion_by_feature": confusion, "cases": cases,
        "limitations": ["정확도는 사람이 검토한 이 표본에만 해당합니다. 일반 성능이나 문서 근거의 정확도를 뜻하지 않습니다."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True, help="Saved /api/v1/jobs/{id} JSON")
    parser.add_argument("--labels", type=Path, required=True, help="Human-reviewed JSON array")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(json.loads(args.result.read_text(encoding="utf-8-sig")),
                      json.loads(args.labels.read_text(encoding="utf-8-sig")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("case_count", "label_count", "state_accuracy", "false_present_count", "invalid_output_count", "passed")}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
