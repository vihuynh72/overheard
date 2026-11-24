# Security checks

The specification asks for Snyk SAST and SCA in CI. We have no Snyk account token, so Snyk itself has not run.
We run the open equivalents instead, in CI and locally, and the workflow has a Snyk job that turns on by itself
once a `SNYK_TOKEN` repository secret is added.

## What runs in CI

`.github/workflows/security.yml`, on every push and pull request, with `contents: read` only.

| Job | Tool | Kind | Fails the build when |
|---|---|---|---|
| sca | pip-audit 2.10.1 | Dependency vulnerabilities (SCA) | any known vulnerability in `requirements.txt` |
| sast | bandit 1.9.4 | Python code (SAST) | a medium or high severity finding in `app/` or `scripts/` |
| secrets | gitleaks action 2.3.9 | Secrets in the full git history | any match |
| snyk | Snyk `test` and `code test` | SCA and SAST | high severity; skipped with a message when `SNYK_TOKEN` is unset |

Actions are pinned to release tags, not commit hashes. Pinning to hashes is the stronger step and is not done yet.

## What ran locally on 2026-11-24

Tools were installed in a throwaway venv under `data/eval/`, not in the project venv or `requirements.txt`.

**pip-audit.** `pip-audit -r requirements.txt` could not build its temporary venv on this machine (ensurepip
aborted). We audited the installed project environment instead with `pip-audit --path .venv/lib/python3.12/site-packages`,
which covers all 52 installed packages, including transitive ones. Result: no known vulnerabilities found.
CI runs the `-r requirements.txt` form.

**bandit** (`bandit -r app scripts`, 3,170 lines): 1 high, 0 medium, 11 low. None are suppressed.

| Severity | Rule | Where | Owner file | Assessment |
|---|---|---|---|---|
| High | B324 weak SHA1 | `app/scout_web.py:162` | app/scout_web.py | SHA1 makes a short id for a web lead from its URL. It is not used for security. Fix: `hashlib.sha1(..., usedforsecurity=False)`. Not fixed here because another worker owns the file today. **CI's sast job fails until this is fixed.** |
| Low | B105 hardcoded password | `app/gmail.py:16` | app/gmail.py | False positive: the constant is Google's public token URL, not a secret. |
| Low | B404, B603, B607 subprocess | `app/pipeline.py:7,165` | app/pipeline.py | Runs `gh auth token` with a fixed argument list and no shell. No user input reaches it. Acceptable. |
| Low | B110 try/except/pass | `app/pipeline.py:226` | app/pipeline.py | Deliberate: an optional refinement round may fail without failing the run. A log line would be better. |
| Low | B112 try/except/continue | `app/scout_web.py:149` | app/scout_web.py | Skips one failed web query. A count of failures is kept. Acceptable. |
| Low | B404, B603, B607 subprocess (5) | `scripts/eval_tools.py:15,227,228` | scripts/eval_tools.py | Evaluation script, fixed argument lists, no shell. Acceptable. |

**gitleaks** (`gitleaks git .` over 14 commits, and `gitleaks dir .`), output redacted:

| Where | Tracked in git | Assessment |
|---|---|---|
| `tests/test_billing.py:8` | yes | False positive: a made-up test key (`fp-secret-...`). **CI's secrets job fails on it** until the test uses an obviously fake value gitleaks ignores, or a `.gitleaksignore` entry with its fingerprint is added. Neither was done here: the file is not owned by this change. |
| `data/server.log` | no (`data/` is gitignored) | Something in the local server log matches an API key pattern. It is not in the repo. The owner should check the log and stop logging that value. |

No real secret was found in tracked files or history. `.env` is gitignored.

## What we fixed

Nothing in this change. The one real finding (B324) and the CI-blocking false positive are in files owned by
other work today; both are listed above with the exact fix.

## What we do not claim

- Snyk has not been run. The job exists and is skipped without a token.
- No dynamic testing, dependency licence review or container scan.
- The API has no sign-in (stated at the top of `app/main.py`); the run budget in `app/main.py` limits spend, not access.
