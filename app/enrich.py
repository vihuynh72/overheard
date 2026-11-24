"""Contact enrichment: company domain (Tavily), email finder and verifier (Hunter).

Every function returns a plain dict with a "status" and never raises. Keys are read
from the environment at call time and never appear in returned text.
"""
import os
import re
from urllib.parse import urlparse

import httpx

HUNTER = "https://api.hunter.io/v2"
SKIP_HOSTS = (
    "linkedin.com", "github.com", "crunchbase.com", "twitter.com", "x.com", "facebook.com",
    "wikipedia.org", "youtube.com", "g2.com", "medium.com", "ycombinator.com",
)
DOMAIN_RE = re.compile(r"^(https?://)?(www\.)?([a-z0-9-]+\.)+[a-z]{2,}(/\S*)?$", re.I)


def _host(url: str) -> str:
    h = urlparse(url if "//" in url else "//" + url).hostname or ""
    return h.lower().removeprefix("www.")


def _skipped(var: str) -> dict:
    return {"status": "skipped", "reason": f"no {var}"}


def _tavily(query: str) -> list[dict]:
    from tavily import TavilyClient

    return TavilyClient(os.environ["TAVILY_API_KEY"]).search(query=query, max_results=5)["results"]


def company_domain(company: str, *, search=None) -> dict:
    company = (company or "").strip()
    if not company:
        return {"status": "skipped", "reason": "no company"}
    if DOMAIN_RE.match(company):
        host = _host(company)
        url = company if "//" in company else "https://" + company
        return {"status": "found", "domain": host, "url": url, "title": "", "source": "profile"}
    if search is None:
        if not os.environ.get("TAVILY_API_KEY"):
            return _skipped("TAVILY_API_KEY")
        search = _tavily
    try:
        results = search(f'"{company}" official website')
    except Exception as e:  # key must not leak via the library's message
        return {"status": "error", "reason": f"search failed ({type(e).__name__})"}
    for r in results or []:
        host = _host(r.get("url") or "")
        if host and not any(host == s or host.endswith("." + s) for s in SKIP_HOSTS):
            return {"status": "found", "domain": host, "url": r["url"],
                    "title": r.get("title") or "", "source": "tavily"}
    return {"status": "not_found"}


def _hunter(path: str, params: dict, client) -> tuple[dict | None, dict | None]:
    """Return (response, None) or (None, skipped/error dict). Never raises."""
    key = os.environ.get("HUNTER_API_KEY")
    if not key:
        return None, _skipped("HUNTER_API_KEY")
    try:
        r = (client or httpx).get(f"{HUNTER}/{path}", params={**params, "api_key": key}, timeout=15)
    except httpx.HTTPError as e:  # str(e) can include the URL, and so the key
        return None, {"status": "error", "reason": type(e).__name__}
    if r.status_code != 200 and r.status_code != 202:
        return None, {"status": "error", "reason": f"HTTP {r.status_code}"}
    return r, None


def find_email(full_name: str, domain: str, *, company: str = "", client: httpx.Client | None = None) -> dict:
    # Hunter accepts a company name in place of a domain, which covers leads whose domain we could not resolve.
    where = {"domain": domain} if domain else {"company": company}
    r, err = _hunter("email-finder", {**where, "full_name": full_name}, client)
    if err:
        return err
    try:
        d = r.json()["data"]
        if not d.get("email"):
            return {"status": "not_found"}
        return {
            "status": "found", "email": d["email"], "score": int(d.get("score") or 0),
            "verification": (d.get("verification") or {}).get("status") or "",
            "position": d.get("position"), "linkedin_url": d.get("linkedin_url"),
            "sources": [s.get("uri") for s in (d.get("sources") or [])[:3]], "source": "hunter",
        }
    except (ValueError, KeyError, TypeError):
        return {"status": "error", "reason": "unexpected Hunter response"}


def verify_email(email: str, *, client: httpx.Client | None = None) -> dict:
    r, err = _hunter("email-verifier", {"email": email}, client)
    if err:
        return err
    if r.status_code == 202:  # Hunter is still verifying; no retry by design
        return {"status": "pending"}
    try:
        d = r.json()["data"]
        return {"status": d["status"], "score": int(d.get("score") or 0),
                "webmail": bool(d.get("webmail")), "disposable": bool(d.get("disposable")),
                "source": "hunter"}
    except (ValueError, KeyError, TypeError):
        return {"status": "error", "reason": "unexpected Hunter response"}


def _why(res: dict) -> str:
    return res.get("reason") or res["status"]


def enrich(name: str, company: str, known_email: str = "", *, search=None, client=None) -> dict:
    steps: list[str] = []
    try:
        if known_email:
            v = verify_email(known_email, client=client)
            steps.append(f"verified known email, {_why(v)}")
            return {"email": known_email, "email_status": v["status"], "domain": "", "steps": steps}

        out = {"email": "", "email_status": "", "domain": "", "position": None,
               "linkedin_url": None, "steps": steps}
        if not (company or "").strip():
            steps.append("no company on profile, skipped")
            return out
        d = company_domain(company, search=search)
        if d["status"] == "found":
            out["domain"] = d["domain"]
            steps.append(f"domain {d['domain']} from "
                         + ("GitHub profile" if d["source"] == "profile" else "web search"))
        else:
            steps.append(f"no domain for {company.strip()} ({_why(d)}), asked Hunter by company name")
        if not (name or "").strip():
            steps.append("no name on profile, skipped email lookup")
            return out
        f = find_email(name, out["domain"], company=company.strip(), client=client)
        if f["status"] != "found":
            steps.append(f"Hunter email lookup: {_why(f)}")
            return out
        out.update(email=f["email"], position=f["position"], linkedin_url=f["linkedin_url"])
        status = f["verification"]
        if not status:
            v = verify_email(f["email"], client=client)
            status = v["status"] if v["status"] in ("valid", "invalid", "accept_all", "webmail",
                                                    "disposable", "unknown", "pending") else ""
        out["email_status"] = status
        steps.append(f"Hunter found an address, score {f['score']}, "
                     + (f"verified {status}" if status else "not verified"))
        return out
    except Exception as e:  # contract: enrich never raises
        steps.append(f"enrichment failed ({type(e).__name__})")
        return {"email": "", "email_status": "", "domain": "", "position": None,
                "linkedin_url": None, "steps": steps}
