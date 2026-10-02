"""Inspect a supplied JSONL corpus locally without executing its contents."""

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import statistics


def counts(values):
    return dict(Counter("<null>" if value is None else value for value in values))


def analyze(path: Path, as_of: date) -> dict:
    raw = path.read_bytes()
    rows, errors = [], []
    for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("JSON line must be an object")
            rows.append(row)
        except (ValueError, TypeError) as exc:
            errors.append({"line": line_number, "error": str(exc)})
    ids = {row.get("chunk_id") for row in rows}
    summary = {
        "source_path": str(path.resolve()),
        "as_of": as_of.isoformat(),
        "analysis_scope": "Local structure and integrity checks; source authenticity and current validity not independently verified",
        "encoding": "utf-8-sig",
        "file_bytes": len(raw),
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "chunk_count": len(rows),
        "document_id_count": len({row.get("document_id") for row in rows}),
        "parse_errors": errors,
        "distributions": {},
        "missing_or_empty": {},
        "lengths_characters": {},
        "duplicate_values": {},
        "content_hash_mismatches": [],
        "broken_related_chunk_ids": [],
        "date_issues": [],
        "date_ranges": [],
        "source_inventory": [],
    }
    for field in ("corpus_kind", "audience", "result_group", "text_origin"):
        summary["distributions"][field] = counts(row.get(field) for row in rows)
    for field in ("content_role", "input_collection", "dataset_family", "conditions_status"):
        summary["distributions"][f"metadata.{field}"] = counts(
            row.get("metadata", {}).get(field) for row in rows
        )
    for field in ("report_uses", "agencies", "scenario_tags"):
        summary["distributions"][f"metadata.{field}"] = counts(
            value for row in rows for value in row.get("metadata", {}).get(field, [])
        )
    for field in ("document_id", "chunk_id", "content", "embedding_input", "content_sha256",
                  "source_url", "source_version_url", "effective_from", "effective_to", "retrieved_at"):
        summary["missing_or_empty"][field] = sum(not row.get(field) for row in rows)
    for field in ("content", "embedding_input"):
        lengths = sorted(len(row.get(field) or "") for row in rows)
        if lengths:
            summary["lengths_characters"][field] = {
                "min": min(lengths), "median": statistics.median(lengths),
                "p95_lower_order_statistic": lengths[int((len(lengths) - 1) * .95)],
                "max": max(lengths), "total": sum(lengths),
            }
    for field in ("chunk_id", "content_sha256"):
        summary["duplicate_values"][field] = {
            key: count for key, count in counts(row.get(field) for row in rows).items() if count > 1
        }
    date_ranges = Counter()
    expired, future = [], []
    sources = {}
    for row in rows:
        metadata = row.get("metadata", {})
        chunk_id = row.get("chunk_id")
        content = row.get("content")
        if not isinstance(content, str) or hashlib.sha256(content.encode("utf-8")).hexdigest() != row.get("content_sha256"):
            summary["content_hash_mismatches"].append(chunk_id)
        for related in metadata.get("related_chunk_ids", []):
            if related not in ids:
                summary["broken_related_chunk_ids"].append({"chunk_id": chunk_id, "related_chunk_id": related})
        start, end = row.get("effective_from"), row.get("effective_to")
        date_ranges[(start, end, metadata.get("effective_to_inclusive"))] += 1
        try:
            if start and date.fromisoformat(start) > as_of:
                future.append(chunk_id)
            if end:
                end_date = date.fromisoformat(end)
                if end_date < as_of or (end_date == as_of and metadata.get("effective_to_inclusive") is False):
                    expired.append(chunk_id)
        except ValueError:
            summary["date_issues"].append(chunk_id)
        title = metadata.get("document_title") or row.get("title") or "<untitled>"
        source = sources.setdefault(title, {"title": title, "chunk_count": 0,
            "document_ids": set(), "corpus_kinds": set(), "source_urls": set()})
        source["chunk_count"] += 1
        source["document_ids"].add(row.get("document_id"))
        source["corpus_kinds"].add(row.get("corpus_kind"))
        source["source_urls"].add(row.get("source_url"))
    summary["date_ranges"] = [{"effective_from": key[0], "effective_to": key[1],
        "effective_to_inclusive": key[2], "chunk_count": count} for key, count in date_ranges.items()]
    summary["date_compatibility"] = {"expired_chunk_ids": expired, "future_chunk_ids": future,
        "note": "An absent end date is not proof of current validity; absent bounds remain unknown"}
    for source in sources.values():
        for field in ("document_ids", "corpus_kinds", "source_urls"):
            source[field] = sorted(source[field], key=lambda value: str(value))
        summary["source_inventory"].append(source)
    summary["source_title_count"] = len(sources)
    summary["sample_chunks"] = [{
        field: row.get(field) for field in ("chunk_id", "document_id", "corpus_kind", "title",
            "section", "content", "text_origin", "source_url", "effective_from", "effective_to", "metadata")
    } for term in ("제54조", "SOP225", "도로시설물 복구", "시간대별")
        for row in rows if term in row.get("title", "")][:20]
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = analyze(args.source, args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in (
        "chunk_count", "document_id_count", "source_title_count", "parse_errors",
        "content_hash_mismatches", "broken_related_chunk_ids", "date_issues")}, ensure_ascii=False))
    if summary["parse_errors"] or summary["content_hash_mismatches"] or summary["broken_related_chunk_ids"] or summary["date_issues"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
