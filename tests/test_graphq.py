"""Graph reasoning: the derived edges and each multi-hop query, on a tiny graph of our own."""
import os

os.environ.setdefault("GRAPH_PATH", "/tmp/earshot-test-graphq.kuzu")

import kuzu  # noqa: E402
import pytest  # noqa: E402

from app import graphq, main, pipeline, store  # noqa: E402

ICP = {"product": "Flexprice: billing"}
PAIN_A, PAIN_B = "credits do not fit metered billing", "invoices do not match"


@pytest.fixture
def q(tmp_path):
    conn = kuzu.Connection(kuzu.Database(str(tmp_path / "g.kuzu")))

    def run(cypher, **params):
        res = conn.execute(cypher, params)
        cols, rows = res.get_column_names(), []
        while res.has_next():
            rows.append(dict(zip(cols, res.get_next())))
        return rows
    for ddl in store.SCHEMA:
        run(ddl)
    for name, kind in [("flexprice/flexprice", "product"), ("getlago/lago", "competitor")]:
        run("CREATE (:Repo {name: $n, kind: $k})", n=name, k=kind)
    people = [("ann", "Acme", "Contacted"), ("bob", "Acme", "Matched"), ("cid", "Beta", "Replied")]
    for login, company, stage in people:
        run("CREATE (:Person {login: $l, company: $c, stage: $s, score: 50})", l=login, c=company, s=stage)
        run("MERGE (:Company {name: $c})", c=company)
        run("MATCH (p:Person {login: $l}), (c:Company {name: $c}) CREATE (p)-[:WORKS_AT]->(c)", l=login, c=company)
    signals = [("s1", "ann", "getlago/lago", PAIN_A, "2026-01-01", 0.9),
               ("s2", "ann", "getlago/lago", PAIN_A, "2026-03-01", 0.5),
               ("s3", "cid", "getlago/lago", PAIN_A, "2025-05-01", 0.7),
               ("s4", "bob", "flexprice/flexprice", PAIN_B, "2026-02-01", 0.8)]
    for sid, login, repo, pain, created, match in signals:
        run("CREATE (:Signal {id: $i, url: $u, title: $i, pain: $p, created: $c, match: $m})",
            i=sid, u=f"https://x/{sid}", p=pain, c=created, m=match)
        run("MATCH (p:Person {login: $l}), (s:Signal {id: $i}) CREATE (p)-[:RAISED]->(s)", l=login, i=sid)
        run("MATCH (s:Signal {id: $i}), (r:Repo {name: $r}) CREATE (s)-[:ABOUT]->(r)", i=sid, r=repo)
    graphq.sync(run, ICP)
    return run


def test_sync_is_idempotent(q):
    edges = q("MATCH ()-[e]->() RETURN count(e) AS n")[0]["n"]
    graphq.sync(q, ICP)
    assert q("MATCH ()-[e]->() RETURN count(e) AS n")[0]["n"] == edges
    assert q("MATCH (r:Repo)-[:COMPETES_WITH]->(:Product {name: 'Flexprice'}) RETURN r.name AS r") == [{"r": "getlago/lago"}]
    assert q("MATCH (:Person)-[e:MATCHED_TO]->(:Product) RETURN count(e) AS n")[0]["n"] == 3
    assert q("MATCH (:Person)-[e:VOICED]->(:Pain) RETURN count(e) AS n")[0]["n"] == 3  # ann's two signals, one pain


def test_displacement_keeps_each_persons_strongest_competitor_signal(q):
    rows = graphq.displacement(q)
    assert [(r["login"], r["title"]) for r in rows] == [("ann", "s1"), ("cid", "s3")]


def test_shared_pain_pairs_people_at_different_companies(q):
    assert [(r["a_login"], r["b_login"]) for r in graphq.shared_pain(q)] == [("ann", "cid")]


def test_account_depth_finds_companies_with_two_people(q):
    rows = graphq.account_depth(q)
    assert [(r["company"], sorted(r["people"])) for r in rows] == [("Acme", ["ann", "bob"])]


def test_coverage_counts_people_companies_and_stage(q):
    top = graphq.coverage(q)[0]
    assert top == {"pain": PAIN_A, "people": 2, "companies": 2, "contacted": 2, "replied": 1}


def test_freshest_gives_each_persons_newest_signal(q):
    assert [(r["login"], r["created"]) for r in graphq.freshest(q)] == [
        ("ann", "2026-03-01"), ("bob", "2026-02-01"), ("cid", "2025-05-01")]


def test_insights_meters_each_query_once_and_survives_a_failing_one(q, monkeypatch):
    monkeypatch.setitem(graphq.QUERIES, "shared_pain", lambda q: 1 / 0)
    seen = []
    g = graphq.insights(q, ICP, on_query=seen.append)
    assert seen == ["displacement", "account_depth", "coverage", "freshest"]
    assert g["counts"]["people"] == 3 and g["counts"]["pains"] == 2
    assert g["insights"][0]["title"] == "2 of the 3 people were found on a competitor's tracker; 2 on getlago/lago."


def test_state_carries_graph_cached_per_run_and_never_breaks(q, monkeypatch):
    monkeypatch.setattr(main.store, "q", q)
    monkeypatch.setitem(pipeline.state, "running", False)
    recorded = []
    monkeypatch.setattr(main.billing, "record", lambda event, **kw: recorded.append((event, kw["query"])))
    main._graph.clear()
    g = main.graph_insights()
    assert {i["key"] for i in g["insights"]} == set(graphq.QUERIES)
    main.graph_insights()  # a second poll in the same run is served from the cache
    assert len(recorded) == len(graphq.QUERIES) and recorded[0] == ("graph.query", "displacement")

    main._graph.clear()
    monkeypatch.setattr(main.graphq, "insights", lambda *a, **k: 1 / 0)
    assert main.graph_insights()["insights"] == []
    assert "graph" in main.state()
    main._graph.clear()
