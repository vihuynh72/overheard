"""Contact enrichment: company domain (GitHub profile, else Tavily), email finder, domain search and verifier (Hunter).

Every function returns a plain dict with a "status" and never raises. Keys are read
from the environment at call time and never appear in returned text.
"""
import os
import re
import unicodedata
from urllib.parse import urlparse

import httpx

HUNTER = "https://api.hunter.io/v2"
SKIP_HOSTS = (
    "linkedin.com", "github.com", "crunchbase.com", "twitter.com", "x.com", "facebook.com",
    "wikipedia.org", "youtube.com", "g2.com", "medium.com", "ycombinator.com",
)
# A blog on these hosts names the host, not the person's own domain, so it says nothing about their email.
HOSTED_BLOGS = ("github.io", "medium.com", "substack.com", "wordpress.com", "blogspot.com", "notion.site",
                "vercel.app", "netlify.app", "dev.to", "hashnode.dev", "linktr.ee", "about.me", "gitlab.io")
MAX_HUNTER_CALLS = 3  # per lead: finder, then one domain search, then one verification of a pattern guess
DOMAIN_RE = re.compile(r"^(https?://)?(www\.)?([a-z0-9-]+\.)+[a-z]{2,}(/\S*)?$", re.I)


def _host(url: str) -> str:
    h = urlparse(url if "//" in url else "//" + url).hostname or ""
    return h.lower().removeprefix("www.")


def _skipped(var: str) -> dict:
    return {"status": "skipped", "reason": f"no {var}"}


def _tavily(query: str) -> list[dict]:
    from tavily import TavilyClient

    return TavilyClient(os.environ["TAVILY_API_KEY"]).search(query=query, max_results=5)["results"]


LEGAL = {"inc", "ltd", "llc", "corp", "gmbh", "the", "and", "company", "group", "technologies", "labs", "limited", "co"}


def _name_words(company: str) -> list[str]:
    return [w for w in (_ascii(t) for t in re.split(r"[\s,.&/-]+", company)) if len(w) >= 3 and w not in LEGAL]


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
    words = _name_words(company)
    for r in results or []:
        host = _host(r.get("url") or "")
        # Directory pages (tavily.com/knowledge, leadiq.com) rank above the company's own site: the host must carry its name.
        if words and not any(w in host.replace("-", "") for w in words):
            continue
        if host and not any(host == s or host.endswith("." + s) for s in SKIP_HOSTS):
            return {"status": "found", "domain": host, "url": r["url"],
                    "title": r.get("title") or "", "source": "tavily"}
    return {"status": "not_found"}


def blog_domain(blog: str) -> str:
    """The person's own domain from their GitHub `blog` field, or "" when it is a directory or hosted blog."""
    blog = (blog or "").strip()
    if not blog or not DOMAIN_RE.match(blog):
        return ""
    host = _host(blog)
    return "" if any(host == s or host.endswith("." + s) for s in SKIP_HOSTS + HOSTED_BLOGS) else host


def _ascii(s: str) -> str:
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower())


def from_pattern(pattern: str, full_name: str, domain: str) -> str:
    """Fill a Hunter pattern such as "{first}.{last}" with a two-part name; "" when either part is missing."""
    parts = [_ascii(p) for p in (full_name or "").split()]
    parts = [p for p in parts if p]
    if len(parts) < 2 or len(parts[0]) < 2 or len(parts[-1]) < 2 or not pattern or not domain:  # "Nils T" is no surname
        return ""
    first, last = parts[0], parts[-1]
    local = pattern.replace("{first}", first).replace("{last}", last).replace("{f}", first[0]).replace("{l}", last[0])
    return f"{local}@{domain}" if re.fullmatch(r"[a-z0-9._-]+", local) else ""


def domain_search(domain: str, full_name: str, *, client=None) -> dict:
    """One Hunter domain search: the person's own listed address if Hunter has it, else the domain's pattern."""
    r, err = _hunter("domain-search", {"domain": domain, "limit": 10}, client)
    if err:
        return err
    try:
        d = r.json()["data"]
        first, last = (_ascii(full_name.split()[0]), _ascii(full_name.split()[-1])) if full_name.split() else ("", "")
        for row in d.get("emails") or []:
            if first and last and _ascii(row.get("first_name") or "") == first and _ascii(row.get("last_name") or "") == last:
                return {"status": "found", "email": row["value"], "verification": (row.get("verification") or {}).get("status") or "",
                        "position": row.get("position"), "linkedin_url": row.get("linkedin"), "source": "hunter-domain"}
        return {"status": "pattern" if d.get("pattern") else "not_found", "pattern": d.get("pattern") or ""}
    except (ValueError, KeyError, TypeError, AttributeError):
        return {"status": "error", "reason": "unexpected Hunter response"}


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


def enrich(name: str, company: str, known_email: str = "", *, blog: str = "", search=None, client=None) -> dict:
    """Sources in order: public profile email, then the profile's own domain (company or blog field), then a web
    search for the company, then Hunter finder, then one Hunter domain search (the person, else the pattern,
    verified once). At most MAX_HUNTER_CALLS Hunter calls per lead."""
    steps: list[str] = []
    try:
        if known_email:
            v = verify_email(known_email, client=client)
            steps.append(f"verified known email, {_why(v)}")
            return {"email": known_email, "email_status": v["status"], "domain": "", "steps": steps}

        out = {"email": "", "email_status": "", "domain": "", "position": None,
               "linkedin_url": None, "steps": steps}
        company, own = (company or "").strip(), blog_domain(blog)
        if not company and not own:
            steps.append("no company on profile, skipped")
            return out
        if company and DOMAIN_RE.match(company):
            d = company_domain(company)
        elif own:
            d = {"status": "found", "domain": own, "source": "blog"}
        else:
            d = company_domain(company, search=search)
        if d["status"] == "found":
            out["domain"] = d["domain"]
            steps.append(f"domain {d['domain']} from " + {"profile": "GitHub profile", "blog": "GitHub profile website"}.get(
                d["source"], "web search"))
        else:
            steps.append(f"no domain for {company} ({_why(d)}), asked Hunter by company name")
        if not (name or "").strip():
            steps.append("no name on profile, skipped email lookup")
            return out
        f = find_email(name, out["domain"], company=company, client=client)
        if f["status"] != "found" and out["domain"]:
            steps.append(f"Hunter email lookup: {_why(f)}")
            f = domain_search(out["domain"], name, client=client)
            if f["status"] == "pattern":
                guess = from_pattern(f["pattern"], name, out["domain"])
                if not guess:
                    steps.append(f"Hunter domain search: pattern {f['pattern']} but no two-part name to fill it")
                    return out
                v = verify_email(guess, client=client)
                if v["status"] not in ("valid", "accept_all"):
                    steps.append(f"Hunter domain search: pattern guess {guess} came back {_why(v)}, not used")
                    return out
                out.update(email=guess, email_status=v["status"])
                steps.append(f"Hunter domain pattern {f['pattern']} gave {guess}, verified {v['status']}")
                return out
            if f["status"] != "found":
                steps.append(f"Hunter domain search: {_why(f)}")
                return out
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
        steps.append(("Hunter domain search listed this person" if f["source"] == "hunter-domain"
                      else f"Hunter found an address, score {f.get('score', 0)}") + ", "
                     + (f"verified {status}" if status else "not verified"))
        return out
    except Exception as e:  # contract: enrich never raises
        steps.append(f"enrichment failed ({type(e).__name__})")
        return {"email": "", "email_status": "", "domain": "", "position": None,
                "linkedin_url": None, "steps": steps}
