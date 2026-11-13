"""Checks that need nothing running: every Python file compiles, the page has no repeated ids
(two once shared id="profile" and Profile opened an empty layer), every id the script asks for
with $("...") is on the page, no function is declared in two parts (one silently replaced the
other), and the script's parts are the ones the page loads.

    python3 tests/static/check_static.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
problems = []

for f in sorted(list(ROOT.glob("web/**/*.py")) + list(ROOT.glob("worker/**/*.py")) + list(ROOT.glob("tests/**/*.py"))):
    if "node_modules" in f.parts:
        continue
    try:
        compile(f.read_text(), str(f), "exec")
    except SyntaxError as e:
        problems.append(f"{f.relative_to(ROOT)}:{e.lineno}: doesn't compile: {e.msg}")

page = (ROOT / "web/index.html").read_text()
ids = re.findall(r'\sid="([^"]+)"', page)
for i in sorted({i for i in ids if ids.count(i) > 1}):
    problems.append(f"web/index.html: id \"{i}\" is on {ids.count(i)} elements")
parts = sorted((ROOT / "web/static/js").glob("[0-9][0-9]-*.js"))
js = "".join(p.read_text() for p in parts)
for i in sorted(set(re.findall(r'\$\("([\w-]+)"\)', js)) - set(ids)):
    problems.append(f"web/static/js: $(\"{i}\") asks for an id that isn't on the page")
# a function declared twice: the parts are one script, so the later silently wins
seen = {}
for part in parts:
    for name in re.findall(r"^(?:async )?function (\w+)\s*\(", part.read_text(), re.M):
        if name in seen:
            problems.append(f"web/static/js: function {name} is declared in both {seen[name]} and {part.name} (the later wins)")
        seen.setdefault(name, part.name)
if parts and not parts[-1].name.startswith("99-"):
    problems.append("web/static/js: the last part should be 99-start.js (the page starts once every part is read)")
for name in [p.name for p in (ROOT / "web/static/js").glob("*.js")]:
    if not re.fullmatch(r"\d\d-[\w-]+\.js", name):
        problems.append(f"web/static/js/{name}: parts are named NN-name.js (only those are joined into the page)")

print(f"static: {len(problems)} problem{'s' if len(problems) != 1 else ''}")
for p in problems:
    print("  - " + p)
sys.exit(1 if problems else 0)
