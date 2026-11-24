"""Intake: from a website address or a GitHub repository to the text Overheard reads to learn the product.

Plain functions with no imports from other app modules. Readers are injectable so tests never touch the network.
Nothing here writes anything; it only reads public web pages and the public GitHub API.
Reasons are fixed sentences: no exception text and no key ever reaches a returned string.
"""
import ipaddress
import os
import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field

MAX_TARGET = 200
MAX_TEXT = 12000
SUBPAGES = ("/pricing", "/docs", "/about")
_REPO = re.compile(r"^[A-Za-z0-9][\w.-]{0,38}/[\w.-]{1,100}$")
_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_LINKED = re.compile(r"github\.com/([A-Za-z0-9][\w-]{0,38})/([A-Za-z0-9_][\w.-]{0,99})", re.I)
# github.com paths that are site sections, not repository owners.
_NOT_OWNERS = {"orgs", "sponsors", "features", "topics", "marketplace", "apps", "login", "settings", "about", "pricing",
               "enterprise", "collections", "explore", "search", "issues", "pulls", "notifications", "security", "readme",
               "users", "organizations", "site", "customer-stories", "resources", "solutions", "join", "contact"}


def _repo_ok(repo: str) -> bool:
    return bool(_REPO.match(repo)) and repo.split("/")[1] not in (".", "..")


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def normalize(target: str) -> dict:
    t = (target or "").strip()
    if not t or len(t) >= MAX_TARGET or re.search(r"\s", t):
        raise ValueError("Enter a website address or a GitHub repository, under 200 characters and without spaces.")
    if "://" not in t and "/" in t and "." not in t.split("/")[0]:  # flexprice/flexprice
        repo = t.removesuffix(".git")
        if not _repo_ok(repo):
            raise ValueError("That does not look like a GitHub repository. Use owner/name.")
        return {"kind": "repo", "url": f"https://github.com/{repo}", "repo": repo}
    p = urlparse(t if "://" in t else "https://" + t)
    if p.scheme not in ("http", "https"):
        raise ValueError("Only http and https addresses are accepted.")
    if p.username is not None or p.password is not None or "@" in p.netloc:
        raise ValueError("Leave credentials out of the address.")
    try:
        port = p.port
    except ValueError:
        port = -1
    if port is not None:
        raise ValueError("Leave the port out of the address.")
    host = (p.hostname or "").lower().rstrip(".")
    if _is_ip(host):
        raise ValueError("Use a website name, not an IP address.")
    labels = host.split(".")
    if (not _HOST.match(host) or host == "localhost" or labels[-1] in ("localhost", "local", "internal")
            or not (labels[-1].isalpha() or labels[-1].startswith("xn--"))):
        raise ValueError("That is not a public website name, for example flexprice.io.")
    if host in ("github.com", "www.github.com"):
        parts = [s for s in p.path.split("/") if s]
        repo = "/".join(parts[:2]).removesuffix(".git")
        if len(parts) < 2 or not _repo_ok(repo):
            raise ValueError("That GitHub address does not name a repository. Use github.com/owner/name.")
        return {"kind": "repo", "url": f"https://github.com/{repo}", "repo": repo}
    return {"kind": "site", "url": f"https://{host}" + p.path.rstrip("/"), "repo": ""}


def _tavily_extract(urls: list[str]) -> list[dict]:
    import tavily  # built at call time so a missing key or package costs nothing
    return tavily.TavilyClient(os.environ["TAVILY_API_KEY"]).extract(urls=urls)["results"]


def _github_repo(repo: str) -> dict:
    import httpx
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    meta = httpx.get(f"https://api.github.com/repos/{repo}", headers=headers, timeout=20)
    meta.raise_for_status()
    m = meta.json()
    rd = httpx.get(f"https://api.github.com/repos/{repo}/readme", headers={**headers, "Accept": "application/vnd.github.raw+json"},
                   timeout=20)
    return {"description": m.get("description") or "", "homepage": m.get("homepage") or "",
            "readme": rd.text if rd.status_code == 200 else ""}


def _pages(extract, urls: list[str]) -> list[tuple[str, str]]:
    try:
        rows = extract(urls) or []
    except Exception:
        return []
    return [(r["url"], r["raw_content"].strip()) for r in rows
            if isinstance(r, dict) and isinstance(r.get("url"), str) and isinstance(r.get("raw_content"), str) and r["raw_content"].strip()]


def _site_urls(url: str) -> list[str]:
    origin = "https://" + urlparse(url).netloc
    return list(dict.fromkeys([origin, *([url] if urlparse(url).path else []), *(origin + s for s in SUBPAGES)]))


def _find_repo(text: str, label: str) -> str:
    """The GitHub repository a site links: one whose owner or name contains the site's name wins, the most
    linked first. Without such a match a repo is returned only when the site links exactly one."""
    seen: dict[str, list] = {}
    for owner, name in _LINKED.findall(text):
        name = name.removesuffix(".git").rstrip(".")
        if owner.lower() in _NOT_OWNERS or not name or not _repo_ok(f"{owner}/{name}"):
            continue
        seen.setdefault(f"{owner}/{name}".lower(), [f"{owner}/{name}", 0])[1] += 1
    found = list(seen.values())  # dicts keep first-seen order, and max() keeps the first on ties
    near = [f for f in found if label and (label in f[0].split("/")[0].lower() or label in f[0].split("/")[1].lower())]
    if near:
        return max(near, key=lambda f: f[1])[0]
    return found[0][0] if len(found) == 1 else ""


def read_product(target: str, *, extract=None, fetch_repo=None) -> dict:
    fail = lambda why: {"status": "error", "reason": why}  # noqa: E731
    try:
        n = normalize(target)
    except ValueError as e:
        return fail(str(e))
    try:
        if extract is None and os.environ.get("TAVILY_API_KEY"):
            extract = _tavily_extract
        pages: list[tuple[str, str]] = []
        repo = n["repo"]
        if n["kind"] == "repo":
            info = {}
            try:
                info = (fetch_repo or _github_repo)(repo) or {}
            except Exception:
                return fail("could not read that GitHub repository")
            body = "\n\n".join(s for s in (info.get("description") or "", info.get("readme") or "") if s.strip())
            if body.strip():
                pages.append((n["url"], body))
            home = info.get("homepage") or ""
            if home and extract:
                try:
                    h = normalize(home)
                    if h["kind"] == "site":
                        pages += _pages(extract, _site_urls(h["url"]))
                except ValueError:
                    pass
            name_hint = repo.split("/")[1]
        else:
            if extract is None:
                return fail("no page reader is configured, so Overheard cannot read websites yet")
            pages = _pages(extract, _site_urls(n["url"]))
            name_hint = (urlparse(n["url"]).hostname or "").removeprefix("www.").split(".")[0]
        if not pages:
            return fail("could not read that site" if n["kind"] == "site" else "could not read anything from that repository")
        cap = -(-MAX_TEXT // len(pages))  # shortcut: equal shares per page; unused share of a short page is not redistributed
        text = "\n\n".join(f"{u}\n{t[:cap]}" for u, t in pages)[:MAX_TEXT]
        if n["kind"] == "site":
            repo = _find_repo("\n".join(t for _, t in pages), name_hint.lower())  # all of the text, not just what is kept
        return {"status": "ok", "source_text": text, "sources": [u for u, _ in pages], "repo": repo, "name_hint": name_hint}
    except Exception:  # never raise out of the public function
        return fail("could not read that address")


# --- which product: the site may sell several things, so the reading is shown to the founder before a run ---

class Offering(BaseModel):
    name: str
    one_liner: str


class Understanding(BaseModel):
    product_name: str
    category: str = Field(description="two to four plain words naming the kind of product, lower case, e.g. usage-based billing")
    one_liner: str = Field(description="one plain sentence, at most 25 words: what it is, for whom")
    offerings: list[Offering] = Field(description="every distinct thing this site appears to sell, at most 5; a single-product company has exactly one")
    primary: int = Field(description="index into offerings of the one the site emphasises most; 0 when offerings is empty")
    confidence: float = Field(description="0 to 1: how sure that offerings[primary] is THE product to take to market")
    ambiguity: str = Field(description="one short sentence saying what is unclear, or empty")
    buyers_guess: str = Field(description="one short phrase: who buys it")


UNDERSTAND_SYSTEM = """You read the pages of one website and say what it sells, so its founder can confirm it.
Describe only what the pages say. Never invent a product, a feature or a buyer.
List every distinct thing the site appears to sell (a platform and its add-ons, separate products, a services arm),
at most five; a company with one product has exactly one offering. `primary` is the one the site emphasises most.
`confidence` is how sure you are that the primary offering is the one product to find customers for: high when the
site sells one thing, low when it sells several comparable things or the pages talk about a mission, not a product.
When the site is a portfolio, an agency, a personal page, or too vague to name a product, say so in `ambiguity`,
leave `offerings` empty and set `confidence` low. Plain words, no marketing language."""


def understand(source_text: str, ask) -> dict:
    """One small model call; `ask` is pipeline.ask, passed in so this module imports nothing from the app."""
    u = ask(Understanding, UNDERSTAND_SYSTEM, source_text).model_dump()
    u["offerings"] = u["offerings"][:5]
    u["primary"] = min(max(u["primary"], 0), max(len(u["offerings"]) - 1, 0))
    u["confidence"] = min(max(u["confidence"], 0.0), 1.0)
    return u
