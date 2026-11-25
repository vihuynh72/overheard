import datetime

from app import memory

D = datetime.date


def lead(login, *ids):
    return {"login": login, "signals": [{"id": i} for i in ids]}


def test_sent_and_rejected_people_do_not_come_back_without_new_evidence(tmp_path):
    p = str(tmp_path / "m.jsonl")
    memory.record("Flexprice", lead("ada", "s1"), "sent", path=p, today=D(2026, 11, 1))
    memory.record("flexprice ", lead("bob", "s2"), "rejected", path=p, today=D(2026, 11, 1))
    keep, skipped = memory.split("Flexprice", [lead("ada", "s1"), lead("bob", "s2"), lead("cy", "s3")], path=p, today=D(2026, 11, 2))
    assert [l["login"] for l in keep] == ["cy"] and skipped == {"sent": 1, "rejected": 1}


def test_new_evidence_brings_a_rejected_person_back_at_once_and_a_sent_one_after_the_wait(tmp_path):
    p = str(tmp_path / "m.jsonl")
    memory.record("Flexprice", lead("ada", "s1"), "sent", path=p, today=D(2026, 11, 1))
    memory.record("Flexprice", lead("bob", "s2"), "rejected", path=p, today=D(2026, 11, 1))
    again = [lead("ada", "s1", "s9"), lead("bob", "s2", "s8")]
    keep, skipped = memory.split("Flexprice", again, path=p, today=D(2026, 11, 10))
    assert [l["login"] for l in keep] == ["bob"] and skipped == {"sent": 1, "rejected": 0}
    keep, _ = memory.split("Flexprice", again, path=p, today=D(2026, 12, 1))
    assert [l["login"] for l in keep] == ["ada", "bob"]


def test_memory_is_per_product_and_survives_a_bad_line(tmp_path):
    p = str(tmp_path / "m.jsonl")
    memory.record("Flexprice", lead("ada", "s1"), "rejected", path=p)
    open(p, "a").write("not json\n")
    assert memory.split("Other", [lead("ada", "s1")], path=p)[0] and not memory.split("Flexprice", [lead("ada", "s1")], path=p)[0]
