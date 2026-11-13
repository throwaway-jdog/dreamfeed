# dreamfeed's checks

`tests/check` runs them; each part says `ok` or `FAIL`, and the run fails if any part does.

- **Before a deploy:** `tests/check`. Needs only Docker and the built `dreamfeed-web` image.
  - `static/`: every Python file compiles; the page has no repeated ids, and every id its script asks for exists.
  - `page/`: the page as a browser gets it (`build.py`: index.html with its style and joined script) in jsdom, the
    API answered by each test's own fake (`harness.js`): every address opens without an error, and the Feed, Live,
    Sign-ins and Videos do what they should. Made-up data only.
  - `server/`: the rules the code applies on its own (youth words, your e621 blacklist, pasted cookies, xvideos'
    lists, post ids, refused requests), offline, run on this checkout's code in the web image.
- **After a deploy:** `tests/check --live` adds the **iOS app's contract** (`contract/`): every address the app calls
  exists, and each it reads is asked of the running web app and checked against the app's own types
  (`app_models.json`). When the app changes: `python3 tests/contract/extract.py PATH/TO/dream-feed-ios`, and update
  the address lists in `contract/check.py`.
- `tests/check --live --browser https://YOUR.DOMAIN/dreamfeed` adds **real Firefox** (`browser/`): what jsdom can't
  check, such as drawing, the page's security policy and playing video. What it watches is taken out of what Videos learns from.

Their tools (`node_modules/`) and what they write (`out/`) stay out of git.
