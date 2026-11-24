"""The Planner chooses where to listen, and the Scout learns the buyer's own words after the first match."""
import asyncio
import os
from types import SimpleNamespace as NS

os.environ.setdefault("GRAPH_PATH", "/tmp/earshot-test.kuzu")

import pytest  # noqa: E402

from app import pipeline, scout_web  # noqa: E402

ISSUES = [dict(id=f"o/r#{n}", repo="o/r", url=f"https://github.com/o/r/issues/{n}", title=f"title {n}", body="b" * 400,
               author=f"gh{n}", created="2026-11-01") for n in range(10)]


class FakeMoss:
    """Scores per query string: {query: {issue id: score}}. Records every call."""
    table: dict = {}
    calls: list = []

    def __init__(self, *a):
        pass

    async def list_indexes(self):
        return []

    async def create_index(self, name, docs):
        self.calls.append(("create", name))

    async def load_index(self, name):
        self.calls.append(("load", name))

    async def query(self, name, q, opts):
        self.calls.append(("query", q))
        return NS(docs=[NS(id=i, score=s) for i, s in self.table.get(q, {}).items()])

    async def delete_index(self, name):
        self.calls.append(("delete", name))


@pytest.fixture
def moss(monkeypatch):
    monkeypatch.setenv("MOSS_PROJECT_ID", "id")
    monkeypatch.setenv("MOSS_PROJECT_KEY", "key")
    FakeMoss.calls, FakeMoss.table = [], {"one": {"o/r#0": 0.5, "o/r#1": 0.4}, "new": {"o/r#1": 0.8, "o/r#2": 0.6}}
    monkeypatch.setattr(pipeline, "MossClient", FakeMoss)
    return FakeMoss


def test_refine_round_merges_best_score_on_one_index(moss):
    seen = {}

    def refine(best, by_id):
        seen.update(best=dict(best), ids=set(by_id))
        return ["new"]
    best = asyncio.run(pipeline.match_pains(ISSUES, ["one"], "ix", refine))
    assert best == {"o/r#0": ("one", 0.5), "o/r#1": ("new", 0.8), "o/r#2": ("new", 0.6)}
    assert seen["best"] == {"o/r#0": ("one", 0.5), "o/r#1": ("one", 0.4)} and seen["ids"] == {i["id"] for i in ISSUES}
    kinds = [c[0] for c in moss.calls]
    assert kinds.count("create") == 1 and kinds.count("delete") == 1 and kinds[-1] == "delete"
    assert [c[1] for c in moss.calls if c[0] == "query"] == ["one", "new"]


def test_refine_never_lowers_a_round_one_score(moss):
    moss.table["new"] = {"o/r#0": 0.35}
    best = asyncio.run(pipeline.match_pains(ISSUES, ["one"], "ix", lambda b, i: ["new"]))
    assert best["o/r#0"] == ("one", 0.5)


@pytest.mark.parametrize("bad", ["raises", "empty", "none"])
def test_failed_or_empty_refine_keeps_round_one(moss, bad):
    def refine(best, by_id):
        if bad == "raises":
            raise RuntimeError("model down")
        return [] if bad == "empty" else None
    best = asyncio.run(pipeline.match_pains(ISSUES, ["one"], "ix", refine))
    assert best == {"o/r#0": ("one", 0.5), "o/r#1": ("one", 0.4)}
    assert [c[0] for c in moss.calls].count("delete") == 1


def test_a_failing_second_round_query_still_deletes_and_keeps_round_one(moss, monkeypatch):
    real = FakeMoss.query

    async def query(self, name, q, opts):
        if q == "new":
            raise RuntimeError("moss down")
        return await real(self, name, q, opts)
    monkeypatch.setattr(FakeMoss, "query", query)
    best = asyncio.run(pipeline.match_pains(ISSUES, ["one"], "ix", lambda b, i: ["new"]))
    assert set(best) == {"o/r#0", "o/r#1"} and [c[0] for c in moss.calls].count("delete") == 1


def test_no_refine_is_the_old_single_round(moss):
    best = asyncio.run(pipeline.match_pains(ISSUES, ["one"], "ix"))
    assert best == {"o/r#0": ("one", 0.5), "o/r#1": ("one", 0.4)}
    assert [c[1] for c in moss.calls if c[0] == "query"] == ["one"]


def test_learn_pains_sends_eight_best_trimmed_and_drops_repeats(monkeypatch):
    prompts = []

    def ask(schema, system, user):
        prompts.append(user)
        return pipeline.Learned(pains=[" Same one ", "a", "b", "c", "d", ""])
    monkeypatch.setattr(pipeline, "ask", ask)
    best = {i["id"]: ("p", 0.3 + n / 100) for n, i in enumerate(ISSUES)}
    got = pipeline.learn_pains(["same one"], best, {i["id"]: i for i in ISSUES})
    assert got == ["a", "b", "c"]
    assert "title 9" in prompts[0] and "title 2" in prompts[0] and "title 1\n" not in prompts[0]  # eight best only
    assert "b" * 300 in prompts[0] and "b" * 301 not in prompts[0]
    assert pipeline.learn_pains(["x"], {}, {}) == []  # nothing matched: no model call


def _icp(**kw):
    s = pipeline.Scored(values=["x"], confidence=0.9)
    base = dict(product="Acme Billing", industries=s, company_size=s, personas=s, triggers=s, pains=["pain one"],
                negative_signals=[], expansion=[], tracker_fit=True, tracker_fit_reason="ok",
                competitors=[pipeline.Competitor(name="Rival Co", category="direct", positioning="p", github_repo="")],
                channels=[pipeline.Channel(domain="https://www.news.ycombinator.com/x", kind="forum", why="engineers"),
                          pipeline.Channel(domain="linkedin.com", kind="social", why="login wall"),
                          pipeline.Channel(domain="reddit.com", kind="community", why="r/saas"),
                          pipeline.Channel(domain="g2.com", kind="reviews", why="buyers review")],
                process_areas=["chasing invoices", "month-end close"])
    return pipeline.ICP(**{**base, **kw})


def test_build_leads_carries_channels_learned_pains_and_says_so(moss, monkeypatch):
    moss.table = {"pain one": {i["id"]: 0.6 for i in ISSUES}, "in their words": {"o/r#3": 0.9}}
    voices = [dict(id=f"web:{n}", repo="reddit.com", url=f"https://reddit.com/r/s/{n}", title="t", body="b",
                   author=a, created="", pain="pain one", match=0.5, kind="web")
              for n, a in enumerate(["buyer", "AcmeSupport", "rival_co_hq"])]
    got = {}

    def find_voices(pains, areas, domains=None):
        got.update(areas=areas, domains=domains)
        return voices
    monkeypatch.setattr(pipeline, "gh", lambda path, **k: {})
    monkeypatch.setattr(pipeline, "fetch_issues", lambda repo: ISSUES)
    monkeypatch.setattr(scout_web, "find_voices", find_voices)
    monkeypatch.setattr(pipeline.enrich, "enrich", lambda *a: {"email": "", "email_status": "", "steps": ["x"]})
    monkeypatch.setattr(pipeline.billing, "gate", lambda *a: {"allowed": True})
    monkeypatch.setattr(pipeline.billing, "record", lambda *a, **k: None)

    def ask(schema, system, user):
        if schema is pipeline.ICP:
            return _icp()
        if schema is pipeline.Learned:
            return pipeline.Learned(pains=["in their words"])
        return pipeline.Qualification(fit=80, production_user=False, role="r", reason="r", subject="Short subject",
                                      body="Short body.")
    monkeypatch.setattr(pipeline, "ask", ask)
    said = []
    icp, leads = pipeline.build_leads("a product description long enough", "o/r", say=said.append)

    assert icp["learned_pains"] == ["in their words"]
    assert [c["domain"] for c in icp["channels"]][0] == "https://www.news.ycombinator.com/x" and len(icp["channels"]) == 4
    assert icp["process_areas"] == ["chasing invoices", "month-end close"]
    assert got["domains"] == ["news.ycombinator.com", "reddit.com", "g2.com"]  # validated; LinkedIn dropped
    assert got["areas"] == ["chasing invoices", "month-end close"]
    assert "Planner → Scout: listening on news.ycombinator.com, reddit.com and g2.com" in said
    assert "Scout: learned how these people phrase it: in their words" in said
    assert any("dropped 2 posts" in s for s in said)
    assert [l["login"] for l in leads if l["signals"][0].get("kind") == "web"] == ["reddit.com/u/buyer"]
    assert next(l for l in leads if l["login"] == "gh3")["signals"][0]["pain"] == "in their words"
    assert [c[0] for c in moss.calls].count("create") == 1


def test_build_leads_without_channels_falls_back_and_learns_nothing_when_refine_fails(moss, monkeypatch):
    moss.table = {"pain one": {"o/r#0": 0.6}}
    got = {}
    monkeypatch.setattr(pipeline, "gh", lambda path, **k: {})
    monkeypatch.setattr(pipeline, "fetch_issues", lambda repo: ISSUES)
    monkeypatch.setattr(scout_web, "find_voices", lambda pains, areas, domains=None: got.update(a=areas, d=domains) or [])
    monkeypatch.setattr(pipeline.enrich, "enrich", lambda *a: {"email": "", "email_status": "", "steps": ["x"]})
    monkeypatch.setattr(pipeline.billing, "gate", lambda *a: {"allowed": True})
    monkeypatch.setattr(pipeline.billing, "record", lambda *a, **k: None)

    def ask(schema, system, user):
        if schema is pipeline.ICP:
            return _icp(channels=[], process_areas=[])
        if schema is pipeline.Learned:
            raise RuntimeError("model down")
        return pipeline.Qualification(fit=80, production_user=False, role="r", reason="r", subject="Short subject",
                                      body="Short body.")
    monkeypatch.setattr(pipeline, "ask", ask)
    said = []
    icp, leads = pipeline.build_leads("a product description long enough", "o/r", say=said.append)
    assert icp["learned_pains"] == [] and got == {"a": scout_web.PROCESS_AREAS, "d": []} and leads
    assert not any("listening on" in s or "learned how" in s for s in said)


def test_no_gh_cli_and_no_token_reads_unauthenticated(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(pipeline.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("gh")))
    seen = {}
    monkeypatch.setattr(pipeline.httpx, "get", lambda url, **k: seen.update(k["headers"]) or type("R", (), {"status_code": 404})())
    assert pipeline.gh("/x") is None and "Authorization" not in seen
