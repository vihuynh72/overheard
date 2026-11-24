"""Graph reasoning: derive the spec's edges from what a run already wrote, then ask multi-hop questions.

Every function takes `q` (a Cypher runner returning dicts) so tests and offline checks can point it at
another graph file; the app uses app.store.q.
"""
import logging

CONTACTED = ["Contacted", "Replied", "Meeting Booked"]
REPLIED = ["Replied", "Meeting Booked"]
log = logging.getLogger(__name__)


def product_name(icp: dict) -> str:
    return (icp.get("product") or "").split(":")[0].strip() or "product"


def sync(q, icp: dict) -> None:
    """Idempotent: MERGE only, from Repo.kind, Signal.pain and the icp's product name."""
    prod = product_name(icp)
    q("MERGE (:Product {name: $n})", n=prod)
    q("MATCH (r:Repo {kind: 'competitor'}), (x:Product {name: $n}) MERGE (r)-[:COMPETES_WITH]->(x)", n=prod)
    q("MATCH (p:Person), (x:Product {name: $n}) MERGE (p)-[:MATCHED_TO]->(x)", n=prod)
    q("MATCH (s:Signal) WHERE s.pain <> '' MERGE (:Pain {text: s.pain})")
    q("MATCH (p:Person)-[:RAISED]->(s:Signal), (x:Pain {text: s.pain}) MERGE (p)-[:VOICED]->(x)")


def displacement(q) -> list[dict]:
    """Person -RAISED-> Signal -ABOUT-> Repo -COMPETES_WITH-> Product: people in a competitor's tracker."""
    rows = q("""MATCH (p:Person)-[:RAISED]->(s:Signal)-[:ABOUT]->(r:Repo)-[:COMPETES_WITH]->(:Product)
                RETURN r.name AS competitor, p.login AS login, s.title AS title, s.url AS url, s.match AS match
                ORDER BY s.match DESC""")
    best: dict = {}
    for r in rows:  # rows are strongest first, so the first per (competitor, person) is their strongest signal
        best.setdefault((r["competitor"], r["login"]), r)
    return list(best.values())


def shared_pain(q) -> list[dict]:
    """Person -VOICED-> Pain <-VOICED- Person at a different company."""
    return q("""MATCH (a:Person)-[:VOICED]->(x:Pain)<-[:VOICED]-(b:Person)
                WHERE a.login < b.login AND a.company <> b.company
                RETURN x.text AS pain, a.login AS a_login, a.company AS a_company, b.login AS b_login, b.company AS b_company
                ORDER BY pain, a_login, b_login""")


def account_depth(q) -> list[dict]:
    """Person -WORKS_AT-> Company <-WORKS_AT- Person: accounts with more than one person to reach."""
    return q("""MATCH (a:Person)-[:WORKS_AT]->(c:Company)<-[:WORKS_AT]-(b:Person)
                WHERE a.login <> b.login
                RETURN c.name AS company, collect(DISTINCT a.login) AS people, count(DISTINCT a) AS n
                ORDER BY n DESC, company""")


def coverage(q) -> list[dict]:
    """Per pain: people, companies, and how many have been contacted or replied."""
    return q("""MATCH (p:Person)-[:VOICED]->(x:Pain)
                OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company)
                RETURN x.text AS pain, count(DISTINCT p) AS people, count(DISTINCT c) AS companies,
                       count(DISTINCT CASE WHEN p.stage IN $contacted THEN p.login END) AS contacted,
                       count(DISTINCT CASE WHEN p.stage IN $replied THEN p.login END) AS replied
                ORDER BY people DESC, pain""", contacted=CONTACTED, replied=REPLIED)


def freshest(q) -> list[dict]:
    """Person -RAISED-> Signal, newest first: the evidence that this person has this problem now."""
    rows = q("""MATCH (p:Person)-[:RAISED]->(s:Signal)
                RETURN p.login AS login, s.created AS created, s.title AS title, s.url AS url
                ORDER BY s.created DESC""")
    best: dict = {}
    for r in rows:
        best.setdefault(r["login"], r)
    return list(best.values())


def _title(key: str, rows: list[dict], people: int) -> str:
    if key == "displacement":
        by = {}
        for r in rows:
            by.setdefault(r["competitor"], set()).add(r["login"])
        if not by:
            return "No one was found on a competitor's tracker."
        top = max(by, key=lambda k: len(by[k]))
        n = len({r["login"] for r in rows})
        return f"{n} of the {people} people were found on a competitor's tracker; {len(by[top])} on {top}."
    if key == "shared_pain":
        return (f"{len(rows)} pairs of people at different or unknown companies voiced the same pain." if rows
                else "No two people at different companies voiced the same pain yet.")
    if key == "account_depth":
        return (f"{len(rows)} companies have more than one person in the graph." if rows
                else "No company has more than one person yet, so there is no second way in.")
    if key == "coverage":
        if not rows:
            return "No pain has a person behind it yet."
        top = rows[0]
        return (f"The most voiced pain has {top['people']} people at {top['companies']} companies; "
                f"{top['contacted']} contacted, {top['replied']} replied.")
    if rows:
        return f"The newest evidence is from {rows[0]['created'][:10]}, by {rows[0]['login']}."
    return "No evidence in the graph yet."


QUERIES = {"displacement": displacement, "shared_pain": shared_pain, "account_depth": account_depth,
           "coverage": coverage, "freshest": freshest}
COUNTS = {"people": "MATCH (n:Person) RETURN count(n) AS n", "companies": "MATCH (n:Company) RETURN count(n) AS n",
          "repos": "MATCH (n:Repo) RETURN count(n) AS n", "signals": "MATCH (n:Signal) RETURN count(n) AS n",
          "pains": "MATCH (n:Pain) RETURN count(n) AS n", "edges": "MATCH ()-[e]->() RETURN count(e) AS n"}


def insights(q, icp: dict, on_query=lambda key: None) -> dict:
    """The `graph` block of /api/state. A failing query is logged and left out; the rest still return."""
    try:
        sync(q, icp)
    except Exception:
        log.exception("graph sync failed")
    counts = {}
    for k, cy in COUNTS.items():
        try:
            counts[k] = q(cy)[0]["n"]
        except Exception:
            log.exception("graph count %s failed", k)
    out = []
    for key, fn in QUERIES.items():
        try:
            rows = fn(q)
        except Exception:
            log.exception("graph query %s failed", key)
            continue
        on_query(key)
        out.append({"key": key, "title": _title(key, rows, counts.get("people", 0)), "rows": rows[:10]})
    return {"counts": counts, "insights": out}
