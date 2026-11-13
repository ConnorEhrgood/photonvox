"""Fails unless every CRITICAL module has 100% line and branch coverage (docs/BUILD-GUIDE §7): anything that decides who may see or do what.
Run after a coverage run:  python tests/check_critical.py /tmp/cov.json   (scripts/remote-test.sh does with COVERAGE=1)."""
import json
import sys

# Add to this list as modules arrive (the document's validation, the compiler, the engine adapter's scoping, the fraud breaker, GDMS signing and
# the push receiver, enrollment, caller-ID choice, vox-agent request signing).
CRITICAL = [
    "app/access.py",            # roles and scopes
    "app/roles.py",             # the role catalog
    "app/deps.py",              # who is signed in, and their context in an organization
    "app/oidc.py",              # token verification
    "app/rls.py",               # who the database thinks it is talking to
    "app/sync.py",              # keeping the directory copy; resolving a first sign-in
    "app/directory/projection.py",   # applying the directory's documents to our copy
    "app/document/validate.py", # whether a phone system may be published (911 first)
    "app/compiler/compile.py",  # the phone system as the engine runs it: routes, caller IDs, the locked 911 route
    "app/compiler/classes.py",  # which numbers each call class allows
    "app/compiler/blocking.py", # which numbers are blocked (decision 29), and that 911 never is
    "app/document/policy.py",   # who may open up calling, change numbers, or reach outside their sites (review H1)
    "app/emergency.py",         # what the carrier is told about where each number is (911, decision 31)
    "app/engine/fusionpbx.py",  # the engine rows: every one in its own domain, call classes anchored, 911 and the block route as built
]

data = json.load(open(sys.argv[1]))["files"]
bad = []
for path in CRITICAL:
    f = data.get(path)
    if f is None:
        bad.append(f"{path}: not measured")
        continue
    s = f["summary"]
    if s["missing_lines"] or s.get("missing_branches", 0) or s.get("num_partial_branches", 0):
        bad.append(f"{path}: {s['percent_covered']:.1f}% (missing lines {f['missing_lines']}, missing branches {f.get('missing_branches')})")
if bad:
    print("CRITICAL modules below 100% branch coverage:\n  " + "\n  ".join(bad))
    sys.exit(1)
print(f"critical modules at 100%: {', '.join(CRITICAL)}")
