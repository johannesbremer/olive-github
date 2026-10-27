"""Fetch all issues and PRs (with comments, review comments, reviews) of olive-editor/olive."""
import json, subprocess, sys, datetime
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

REPO = "olive-editor/olive"
OUT = sys.argv[1]

def api(path, paginate=False):
    cmd = ["gh", "api", "-H", "Accept: application/vnd.github+json", path]
    if paginate:
        cmd[2:2] = ["--paginate", "--slurp"]
    for attempt in range(5):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            data = json.loads(r.stdout)
            if paginate:
                return [x for page in data for x in page]
            return data
        print(f"retry {attempt} {path}: {r.stderr.strip()[:200]}", file=sys.stderr)
    raise RuntimeError(path)

def prune(v):
    if isinstance(v, dict):
        out = {k: prune(x) for k, x in v.items()}
        return {k: x for k, x in out.items() if x not in (None, "", [], {})}
    if isinstance(v, list):
        out = [prune(x) for x in v]
        return [x for x in out if x not in (None, "", [], {})]
    return v

def log(msg): print(msg, file=sys.stderr, flush=True)

log("issues..."); all_issues = api(f"repos/{REPO}/issues?state=all&per_page=100", True)
log(f"  {len(all_issues)}")
log("issue comments..."); comments = api(f"repos/{REPO}/issues/comments?per_page=100", True)
log(f"  {len(comments)}")
log("review comments..."); review_comments = api(f"repos/{REPO}/pulls/comments?per_page=100", True)
log(f"  {len(review_comments)}")

by_issue = defaultdict(list)
for c in comments:
    by_issue[int(c["issue_url"].rsplit("/", 1)[1])].append(c)
rc_by_pr = defaultdict(list)
for c in review_comments:
    rc_by_pr[int(c["pull_request_url"].rsplit("/", 1)[1])].append(c)

issues = [i for i in all_issues if "pull_request" not in i]
pr_stubs = {i["number"]: i for i in all_issues if "pull_request" in i}
# the issues listing omits PRs by deleted ("ghost") users; the pulls listing has them all
for n in {p["number"] for p in api(f"repos/{REPO}/pulls?state=all&per_page=100", True)} - set(pr_stubs):
    pr_stubs[n] = api(f"repos/{REPO}/issues/{n}")
log(f"{len(issues)} issues, {len(pr_stubs)} PRs; fetching PR details + reviews...")

def fetch_pr(n):
    pr = api(f"repos/{REPO}/pulls/{n}")
    pr["reviews"] = api(f"repos/{REPO}/pulls/{n}/reviews?per_page=100", True)
    return pr

with ThreadPoolExecutor(8) as ex:
    prs = list(ex.map(fetch_pr, sorted(pr_stubs)))

for i in issues:
    i["comments_data"] = sorted(by_issue.get(i["number"], []), key=lambda c: c["created_at"])
for pr in prs:
    stub = pr_stubs[pr["number"]]
    # fields only present on the issue view of a PR
    for k in ("reactions", "comments", "state_reason", "performed_via_github_app", "type"):
        if k in stub and k not in pr:
            pr[k] = stub[k]
    pr["comments_data"] = sorted(by_issue.get(pr["number"], []), key=lambda c: c["created_at"])
    pr["review_comments_data"] = sorted(rc_by_pr.get(pr["number"], []), key=lambda c: c["created_at"])

issues.sort(key=lambda x: x["number"]); prs.sort(key=lambda x: x["number"])
result = prune({
    "repository": REPO,
    "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "issue_count": len(issues),
    "pull_request_count": len(prs),
    "issues": issues,
    "pull_requests": prs,
})
with open(OUT, "w") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
log("done")
