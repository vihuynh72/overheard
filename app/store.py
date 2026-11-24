"""Knowledge graph (Kùzu, embedded). One place for every read and write."""
import datetime
import os
import threading
import uuid

import kuzu

os.makedirs("data", exist_ok=True)
_db = kuzu.Database(os.getenv("GRAPH_PATH", "data/graph.kuzu"))
_conn = kuzu.Connection(_db)
_lock = threading.Lock()  # one connection shared by the API and the pipeline thread

STAGES = ["Matched", "Contacted", "Replied", "Meeting Booked", "Closed/Lost"]

SCHEMA = [
    """CREATE NODE TABLE IF NOT EXISTS Person(login STRING PRIMARY KEY, name STRING, url STRING,
       company STRING, email STRING, blog STRING, bio STRING, location STRING, followers INT64,
       role STRING, fit INT64, production BOOLEAN, reason STRING, score INT64, tier STRING,
       stage STRING, stage_actor STRING, subject STRING, body STRING, draft_status STRING,
       email_status STRING, domain STRING, linkedin_url STRING, position STRING, enrich STRING, newest STRING)""",
    "CREATE NODE TABLE IF NOT EXISTS Company(name STRING PRIMARY KEY)",
    "CREATE NODE TABLE IF NOT EXISTS Repo(name STRING PRIMARY KEY, kind STRING)",
    """CREATE NODE TABLE IF NOT EXISTS Signal(id STRING PRIMARY KEY, url STRING, title STRING,
       excerpt STRING, created STRING, pain STRING, match DOUBLE)""",
    """CREATE NODE TABLE IF NOT EXISTS Event(id STRING PRIMARY KEY, ts STRING, login STRING,
       actor STRING, action STRING, detail STRING)""",
    "CREATE REL TABLE IF NOT EXISTS WORKS_AT(FROM Person TO Company)",
    "CREATE REL TABLE IF NOT EXISTS RAISED(FROM Person TO Signal)",
    "CREATE REL TABLE IF NOT EXISTS ABOUT(FROM Signal TO Repo)",
    # Derived by app/graphq.sync from the tables above; additive, so an existing graph file keeps working.
    "CREATE NODE TABLE IF NOT EXISTS Product(name STRING PRIMARY KEY)",
    "CREATE NODE TABLE IF NOT EXISTS Pain(text STRING PRIMARY KEY)",
    "CREATE REL TABLE IF NOT EXISTS COMPETES_WITH(FROM Repo TO Product)",
    "CREATE REL TABLE IF NOT EXISTS MATCHED_TO(FROM Person TO Product)",
    "CREATE REL TABLE IF NOT EXISTS VOICED(FROM Person TO Pain)",
]
for ddl in SCHEMA:
    _conn.execute(ddl)


def q(cypher: str, **params) -> list[dict]:
    with _lock:
        res = _conn.execute(cypher, params)
        cols = res.get_column_names()
        rows = []
        while res.has_next():
            rows.append(dict(zip(cols, res.get_next())))
        return rows


def _node(n: dict) -> dict:
    return {k: v for k, v in n.items() if not k.startswith("_")}


def upsert(label: str, key: str, props: dict) -> None:
    props = {k: ("" if v is None else v) for k, v in props.items()}
    sets = ", ".join(f"n.{k} = ${k}" for k in props if k != key)
    q(f"MERGE (n:{label} {{{key}: ${key}}})" + (f" SET {sets}" if sets else ""), **props)


def link(a_label, a_key, a, rel, b_label, b_key, b) -> None:
    q(f"MATCH (a:{a_label} {{{a_key}: $a}}), (b:{b_label} {{{b_key}: $b}}) MERGE (a)-[:{rel}]->(b)", a=a, b=b)


def log(login: str, actor: str, action: str, detail: str = "") -> None:
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    upsert("Event", "id", dict(id=uuid.uuid4().hex, ts=ts, login=login, actor=actor, action=action, detail=detail))


def reset() -> None:
    q("MATCH (n) DETACH DELETE n")


def leads() -> list[dict]:
    people = {r["p"]["login"]: {**_node(r["p"]), "signals": []} for r in q("MATCH (p:Person) RETURN p")}
    for r in q("MATCH (p:Person)-[:RAISED]->(s:Signal)-[:ABOUT]->(r:Repo) RETURN p.login AS login, s, r.name AS repo"):
        people[r["login"]]["signals"].append({**_node(r["s"]), "repo": r["repo"]})
    return sorted(people.values(), key=lambda p: -p["score"])


def events() -> list[dict]:
    return [_node(r["e"]) for r in q("MATCH (e:Event) RETURN e ORDER BY e.ts DESC LIMIT 200")]
