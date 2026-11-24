from app import lessons


def test_add_writes_a_lesson(tmp_path):
    path = tmp_path / "sub" / "l.jsonl"
    row = lessons.add("k", "p", "f", {"a": 1}, path=path)
    assert row["status"] == "open" and row["seen"] == 1 and row["evidence"] == {"a": 1}
    assert row["id"] and row["ts"]
    assert lessons.all(path=path) == [row]


def test_duplicate_increments_seen_and_replaces_evidence(tmp_path):
    path = tmp_path / "l.jsonl"
    lessons.add("k", "p", "f", {"n": 1}, path=path)
    again = lessons.add("k", "p", "f", {"n": 2}, path=path)
    assert again["seen"] == 2 and again["evidence"] == {"n": 2} and "regressed" not in again
    assert len(lessons.all(path=path)) == 1
    assert len(path.read_text().splitlines()) == 1


def test_same_pattern_other_kind_is_separate(tmp_path):
    path = tmp_path / "l.jsonl"
    lessons.add("k1", "p", "f", {}, path=path)
    lessons.add("k2", "p", "f", {}, path=path)
    assert len(lessons.all(path=path)) == 2


def test_fixed_lesson_seen_again_is_a_regression(tmp_path):
    path = tmp_path / "l.jsonl"
    row = lessons.add("k", "p", "f", {}, path=path)
    fixed = lessons.mark_fixed(row["id"], "tightened", path=path)
    assert fixed["status"] == "fixed" and lessons.open(path=path) == []
    back = lessons.add("k", "p", "f", {"again": True}, path=path)
    assert back["status"] == "open" and back["regressed"] is True and back["seen"] == 2
    assert [r["id"] for r in lessons.open(path=path)] == [row["id"]]


def test_newest_first_and_open_filter(tmp_path):
    path = tmp_path / "l.jsonl"
    a = lessons.add("k", "a", "f", {}, path=path)
    b = lessons.add("k", "b", "f", {}, path=path)
    c = lessons.add("k", "c", "f", {}, path=path)
    lessons.mark_fixed(b["id"], "done", path=path)
    assert [r["id"] for r in lessons.all(path=path)] == [c["id"], b["id"], a["id"]]
    assert [r["id"] for r in lessons.open(path=path)] == [c["id"], a["id"]]


def test_missing_file_is_empty_and_unknown_id_raises(tmp_path):
    path = tmp_path / "none.jsonl"
    assert lessons.all(path=path) == []
    try:
        lessons.mark_fixed("nope", "x", path=path)
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")
