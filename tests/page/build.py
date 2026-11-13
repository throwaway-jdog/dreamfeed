"""The page as a browser gets it, as one file for jsdom: index.html with its style and its script
(the parts in static/js/, joined in name order, as the web app serves /static/app.js) written in.

    python3 tests/page/build.py web OUT.html
"""
import re
import sys
from pathlib import Path

web, out = Path(sys.argv[1]), Path(sys.argv[2])
page = (web / "index.html").read_text()
js = "".join(p.read_text() for p in sorted((web / "static/js").glob("[0-9][0-9]-*.js")))
page, n = re.subn(r'<script src="static/app\.js"></script>', lambda m: "<script>\n" + js + "</script>", page)
page, k = re.subn(r'<link rel="stylesheet" href="static/app\.css">', lambda m: "<style>\n" + (web / "static/app.css").read_text() + "</style>", page)
if n != 1 or k != 1:
    sys.exit(f"build.py: index.html should load static/app.js and static/app.css once each (found {n}, {k})")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(page.replace("<head>", '<head>\n<base href="/dreamfeed/">', 1))
