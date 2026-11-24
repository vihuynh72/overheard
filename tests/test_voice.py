import json

import httpx
import pytest

from app import voice as v

KEY = "sekrit-eleven-key"
CTX = {"view": "leads", "open_lead": "Derek Chen", "level": "supervised", "credits": 10, "inbox": 2,
       "leads": [{"name": "Derek Chen", "score": 88, "tier": "A"}, {"name": "Priya Nair", "score": 71, "tier": "B"},
                 {"name": "Marco Silva", "score": 52, "tier": "C"}]}


def fake(**kw):
    kw.setdefault("say", "Okay.")
    return lambda schema, system, user: v.Heard(**kw)


def run(ctx=CTX, text="x", **kw):
    return v.interpret(text, ctx, fake(**kw))


def test_run_ok_and_bad_repo():
    d = "We sell usage billing software to API startups."
    assert run(action="run", description=d, product_repo="flexprice/flexprice")["args"] == {
        "description": d, "product_repo": "flexprice/flexprice"}
    assert run(action="run", description=d, product_repo="not a repo!")["args"]["product_repo"] == ""


def test_run_too_short_is_none():
    r = run(action="run", description="billing")
    assert r["action"] == "none" and r["args"] == {}


def test_show():
    assert run(action="show", view="map")["args"] == {"view": "map"}
    assert run(action="show", view="settings")["action"] == "none"


def test_open_lead_fuzzy():
    assert run(action="open_lead", name="priya")["args"] == {"name": "Priya Nair"}
    assert run(action="open_lead", name="marco silva")["args"] == {"name": "Marco Silva"}
    assert run(action="open_lead", name="Derrick Chen")["args"] == {"name": "Derek Chen"}


def test_open_lead_no_match_names_closest():
    r = run(action="open_lead", name="Zed Quux")
    assert r["action"] == "none" and "Derek Chen" in r["say"]
    assert run({**CTX, "leads": []}, action="open_lead", name="x")["action"] == "none"


def test_approve_reject():
    assert run(action="approve")["action"] == "approve"
    assert run(action="reject", reason="not a fit")["args"] == {"reason": "not a fit"}
    for a in ("approve", "reject"):
        r = run({**CTX, "open_lead": ""}, action=a)
        assert r["action"] == "none" and "Open a lead" in r["say"]


def test_set_policy_filters_and_clamps():
    r = run(action="set_policy", min_score=150, require_verified_email=True, never_say=["guarantee", " "], name="junk")
    assert r["args"] == {"min_score": 100, "require_verified_email": True, "never_say": ["guarantee"]}
    assert run(action="set_policy")["action"] == "none"


def test_autonomy():
    assert run(action="autonomy", level="autopilot")["args"] == {"level": "autopilot"}
    assert run(action="autonomy", level="yolo")["action"] == "none"


def test_explain_none_and_unknown():
    assert run(action="explain", say="Two leads are waiting.") == {"action": "explain", "args": {}, "say": "Two leads are waiting."}
    assert run(action="none", say="")["say"] == v.CAPABILITIES
    r = run(action="delete_everything", name="x")
    assert r["action"] == "none" and r["args"] == {}


def test_caps():
    seen = {}

    def ask(schema, system, user):
        seen["user"] = user
        return v.Heard(action="explain", say="a" * 1000)
    r = v.interpret("b" * 2000, CTX, ask)
    assert len(r["say"]) == v.MAX_SAY and "b" * 500 in seen["user"] and "b" * 501 not in seen["user"]


def test_ask_failure_never_raises():
    def boom(*a):
        raise RuntimeError(f"down {KEY}")
    r = v.interpret("hi", CTX, boom)
    assert r == {"action": "none", "args": {}, "say": "I could not reach the model just now."}
    assert v.interpret(None, None, fake(action="explain"))["action"] == "explain"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice123")


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_speak_request_shape(env):
    seen = {}

    def h(req):
        seen.update(url=str(req.url), key=req.headers["xi-api-key"], accept=req.headers["accept"], body=json.loads(req.content))
        return httpx.Response(200, content=b"mp3")
    assert v.speak("t" * 700, client=client(h)) == b"mp3"
    assert seen["url"] == "https://api.elevenlabs.io/v1/text-to-speech/voice123"
    assert seen["key"] == KEY and seen["accept"] == "audio/mpeg"
    assert seen["body"] == {"text": "t" * 600, "model_id": "eleven_turbo_v2_5"}


@pytest.mark.parametrize("missing", ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"])
def test_speak_unconfigured(env, monkeypatch, missing):
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError, match="voice is not configured"):
        v.speak("hi", client=client(lambda r: httpx.Response(200)))


def test_speak_http_error_and_no_key_leak(env):
    with pytest.raises(RuntimeError, match="ElevenLabs HTTP 500") as e:
        v.speak("hi", client=client(lambda r: httpx.Response(500, text=f"bad {KEY}")))
    assert KEY not in str(e.value)

    def down(req):
        raise httpx.ConnectError(f"no route {KEY}", request=req)
    with pytest.raises(RuntimeError) as e:
        v.speak("hi", client=client(down))
    assert KEY not in str(e.value) and KEY not in repr(e.value)
