"""Append-only ledger of mistakes the simulation found, one JSON object per line."""
import datetime
import json
import pathlib
import uuid

DEFAULT_PATH = "data/lessons.jsonl"


def _read(path) -> list[dict]:
    p = pathlib.Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def _write(path, rows: list[dict]) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


def add(kind: str, pattern: str, fix: str, evidence: dict, *, path=DEFAULT_PATH) -> dict:
    """Record a lesson; the same kind and pattern is counted again, not duplicated."""
    rows = _read(path)
    for row in rows:
        if row["kind"] == kind and row["pattern"] == pattern:
            row["seen"] += 1
            row["evidence"] = evidence
            if row["status"] == "fixed":  # a fixed mistake that came back
                row["status"] = "open"
                row["regressed"] = True
            _write(path, rows)
            return row
    row = {
        "id": uuid.uuid4().hex[:8],
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "kind": kind, "pattern": pattern, "fix": fix, "evidence": evidence,
        "status": "open", "seen": 1,
    }
    _write(path, rows + [row])
    return row


def mark_fixed(lesson_id: str, note: str, *, path=DEFAULT_PATH) -> dict:
    rows = _read(path)
    for row in rows:
        if row["id"] == lesson_id:
            row["status"] = "fixed"
            row["note"] = note
            row.pop("regressed", None)
            _write(path, rows)
            return row
    raise KeyError(f"no lesson with id {lesson_id}")


def all(*, path=DEFAULT_PATH) -> list[dict]:  # noqa: A001 - the ledger's public name
    return _read(path)[::-1]


def open(*, path=DEFAULT_PATH) -> list[dict]:  # noqa: A001
    return [r for r in all(path=path) if r["status"] == "open"]
