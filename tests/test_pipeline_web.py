"""Web voices join the GitHub authors in build_leads: reserved share of the cap, no GitHub or contact lookups."""
import os

os.environ.setdefault("GRAPH_PATH", "/tmp/earshot-test.kuzu")

from app import pipeline, scout_web  # noqa: E402


def _icp():
    s = pipeline.Scored(values=["x"], confidence=0.9)
    return pipeline.ICP(product="P", industries=s, company_size=s, personas=s, triggers=s, pains=["pain one"],
                        negative_signals=[], expansion=[], competitors=[], tracker_fit=True, tracker_fit_reason="ok")


def test_web_voices_get_a_reserved_share(monkeypatch):
    issues = [dict(id=f"o/r#{n}", repo="o/r", url=f"https://github.com/o/r/issues/{n}", title="t", body="b",
                   author=f"gh{n}", created="2026-11-01") for n in range(30)]
    voices = [dict(id=f"web:{n}", repo="reddit.com", url=f"https://reddit.com/r/s/{n}", title="t", body="b",
                   author=f"u{n}", created="", pain="pain one", match=0.5, kind="web") for n in range(12)]
    looked_up = []
    monkeypatch.setattr(pipeline, "gh", lambda path, **k: looked_up.append(path) or {})
    monkeypatch.setattr(pipeline, "fetch_issues", lambda repo: issues)
    monkeypatch.setattr(pipeline, "match_pains", lambda *a: _done({i["id"]: ("pain one", 0.9) for i in issues}))
    monkeypatch.setattr(scout_web, "find_voices", lambda pains, areas: voices)
    monkeypatch.setattr(pipeline.enrich, "enrich", lambda *a: {"email": "", "email_status": "", "steps": ["x"]})
    monkeypatch.setattr(pipeline.billing, "gate", lambda *a: {"allowed": True})
    monkeypatch.setattr(pipeline.billing, "record", lambda *a, **k: None)

    def ask(schema, system, user):
        return _icp() if schema is pipeline.ICP else pipeline.Qualification(
            fit=80, production_user=False, role="r", reason="r", subject="Short subject", body="Short body.")
    monkeypatch.setattr(pipeline, "ask", ask)
    said = []
    _, leads = pipeline.build_leads("a product description long enough", "o/r", say=said.append)
    web = [l for l in leads if l["signals"][0].get("kind") == "web"]
    assert len(leads) == pipeline.MAX_LEADS and len(web) == pipeline.MAX_LEADS // 3
    assert web[0]["login"] == "reddit.com/u/u0" and web[0]["name"] == "u0" and web[0]["url"] == "https://reddit.com/r/s/0"
    assert not any("reddit.com" in p for p in looked_up)  # no GitHub profile lookup for a web lead
    assert any("12 posts on forums and review sites" in s for s in said)


async def _done(v):
    return v
