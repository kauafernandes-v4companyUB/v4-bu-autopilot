# Public history remediation — real client data was published

**Status: `UNREACHABLE_GITHUB_OBJECT_STILL_ACCESSIBLE`.**
**Full remote purge: NOT confirmed.**

Last updated: 2026-10-05T17:32:09Z (current-tree security hotfix).
First written: 2026-09-16T05:08:02Z (original local history audit).
Repository: `https://github.com/kauafernandes-v4companyUB/v4-bu-autopilot`
(visibility at last update: **public**).

This document records the incident, what has been done, and what is
still open. It intentionally does **not** reproduce any of the exposed
data, the exposed file contents, or the SHAs of the exposed commits — a
public list of those SHAs would only be a map to the data. The operator
keeps that list privately for the GitHub Support request.

---

## 1. What happened

While this repository was public, real canonical memory of the pilot
client (`clients/<pilot>/**`: identification, evidence, knowledge,
strategy, tasks, Quarter plan/monitoring, history) was committed and
pushed to `main`. The evidence ledger contained real business-identity
data (company registration number, cadastral e-mail, legal
representative's name) plus real operational strategy and media figures.
`private/` (raw sources: WhatsApp exports, PDFs, transcripts) was never
committed.

A later audit (2026-10-05) also found a small amount of real data that
had leaked into engine files themselves, outside `clients/`:

- a test fixture pinned against the pilot client's real media spend and
  planned budget;
- a parser self-test containing a real client contact's name, a real
  message excerpt and a real attachment file name;
- a test pinned against a real BI observation id and real source file
  hash;
- SKILL.md / schema examples quoting a real contact's first name and
  real business context, plus a real task title and real client names in
  generic examples;
- a fragment of the company registration number inside a verification
  command in a previous version of *this* document.

## 2. What has been done

| Step | State |
|---|---|
| Canonical data migrated to the private workspace (SHA-256 verified, path-aware) | done (2026-09-16) |
| `clients/` removed from the current tree; guards in `tests/security/` and `scripts/doctor.py` | done (2026-09-16) |
| Branch history rewritten so no reachable commit contains `clients/**` | done — current `main` has no common ancestor with the pre-rewrite history |
| Real data in engine files (section 1, second list) replaced by synthetic fixtures in the current tree | done (2026-10-05) |
| Content guards (structural patterns + pilot id in code/fixtures) added to `tests/security/test_public_hygiene.py` | done (2026-10-05) |
| GitHub Support request to purge cached/unreachable objects | **not done** |
| Repository visibility changed | **not done** |

## 3. What is still exposed

1. **Unreachable objects on GitHub.** The pre-rewrite commits are no
   longer reachable from any ref (`git branch -a`, `git tag -l`,
   `git show-ref` show only `main`), but GitHub still serves them by SHA
   (verified 2026-10-05 via the REST API: the old commits still resolve).
   A force-push does not delete objects on GitHub; only GitHub's garbage
   collection — triggered for sensitive data through GitHub Support —
   does.
2. **Residual real data in the rewritten branch history.** The rewrite
   removed `clients/**`, but the engine-file leaks listed in section 1
   still exist in earlier commits of the current `main` (they were fixed
   only in the current tree). The worst of them is the
   registration-number fragment in an earlier version of this document.
   Removing them from reachable history would require another history
   rewrite, which is a separate, explicit operator decision.
3. **Clones, forks, caches.** Anyone who cloned, forked or cached the
   repository while it contained the data still has it. This is outside
   the owner's technical control and cannot be undone by any action on
   this repository.

Therefore the correct status is `UNREACHABLE_GITHUB_OBJECT_STILL_ACCESSIBLE`,
**not** `FULL_REMOTE_PURGE_CONFIRMED`. Do not describe this incident as
erased.

## 4. Remaining actions (all require explicit human authorization)

1. **GitHub Support:** request removal of cached views and garbage
   collection of the unreachable pre-rewrite objects (GitHub docs:
   "Removing sensitive data from a repository"). Provide the affected
   SHAs from the operator's private record — not from this file.
2. **Decide on the residual branch-history data** (section 3, item 2):
   accept it, or run a second targeted rewrite (`git filter-repo` on a
   fresh clone, verified locally before any `git push --force`). Every
   rewrite invalidates existing clones and SHAs.
3. **Optionally make the repository private** while the above is
   pending.
4. Only after GitHub confirms the purge **and** a fresh check by SHA
   returns 404 may this document move to `FULL_REMOTE_PURGE_CONFIRMED`.

## 5. How to re-verify (no data printed)

```bash
git branch -a; git tag -l; git show-ref          # only main / origin/main expected
git log --all --name-only --format= | grep -E '^(clients|private|context/generated)/'   # must be empty
gh api repos/<owner>/v4-bu-autopilot/commits/<old-sha> --jq .sha   # 404 = gone; a SHA = still accessible
PYTHONUTF8=1 python -m pytest tests/security -q
```

## 6. Prevention

- Fixtures in this engine are synthetic from the origin (CLAUDE.md 27.1);
  never "lightly anonymize" real data.
- `tests/security/test_public_hygiene.py` fails on: real-tree paths
  (`clients/`, `private/`, `context/generated/`), the pilot client id in
  code/tests/fixtures, and CNPJ/CPF/BR-phone/e-mail-shaped values. The
  guards use structural patterns only — they never contain real PII.
- Structural guards cannot catch partial identifiers, names or business
  figures; reviewing every change that touches fixtures remains required.
