"""The rules dreamfeed's code applies on its own, without the sites: what's left out (minors only,
your e621 blacklist), reading cookies and xvideos' lists, post ids, what requests are refused.
Offline and quick. Run in the web image with this checkout's code (tests/check does):

    python3 -m unittest discover -s tests/server
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, "/app")


class Minors(unittest.TestCase):
    """The one rule: words that only mean minors are left out, everywhere; nothing else is."""
    def test_words(self):
        from dreamfeed.core import safety
        from dreamfeed.feed import xvideos as xv
        from dreamfeed.feed.common import place_blocked, text_blocked
        for t in ("underage", "child", "16 yo", "17yo", "loli", "shota", "jailbait", "preteen", "under_age"):
            self.assertTrue(safety.minors(t) and xv.youth(t) and text_blocked(t), t)
        for t in ("teen", "young wife", "18yo", "21 years old", "118yo", "schoolgirl outfit", "barely legal", "canteen", "kidding around", "Youngblood",
                  "petite", "femboy", "trap", "feral", "stepsister", "virgin", "tiny", "sleeping", "forced", "gore", "flat chest"):
            self.assertFalse(safety.minors(t) or xv.youth(t) or text_blocked(t), t)
        for ok in ("femboy", "FemboyHentai", "feral", "petite", "stepsister", "teens"):
            self.assertFalse(place_blocked(ok), ok)
        self.assertTrue(place_blocked("jailbait"))


class XvideosLists(unittest.TestCase):
    def test_lengths_and_counts(self):
        from dreamfeed.feed import xvideos as xv
        self.assertEqual(xv._seconds("1 h 5 min"), 3900)
        self.assertEqual(xv._seconds("20 min"), 1200)
        self.assertEqual(xv._seconds("45 sec"), 45)
        self.assertEqual(xv._num("1,234"), 1234)
        self.assertEqual(xv._num("1.1k"), 1100)
        self.assertEqual(xv._num("2M"), 2_000_000)
        self.assertIsNone(xv._num("lots"))

    def test_uploader_list_addresses(self):
        """An uploader's list gives a click-counting address: read as the video's own."""
        from dreamfeed.feed import xvideos as xv
        v = xv._from_json({"eid": "olkdbla5696", "u": "/prof-video-click/upload/someone/olkdbla5696/a_title", "tf": "A title", "d": "20 min",
                           "i": "https://thumb-cdn77.xvideos-cdn.com/x.jpg", "pn": "Some One", "pu": "/someone", "n": "1k", "r": "99%"})
        self.assertEqual(v["url"], "/video.olkdbla5696/a_title")
        self.assertEqual(v["duration"], 1200)
        self.assertIsNone(xv._from_json({"eid": "olkdbla5696", "u": "/video.olkdbla5696/x", "tf": "underage thing"}))

    def test_search_page(self):
        from dreamfeed.feed import xvideos as xv
        page = ('<div id="video_abcd12345" data-id="1" data-eid="abcd12345" data-is-channel="1" class="frame-block thumb-block">'
                '<img data-src="https://thumb-cdn77.xvideos-cdn.com/a.jpg"><p class="title"><a href="/video.abcd12345/a_title" title="A &amp; title">'
                '</a></p><p class="metadata"><span class="bg"><span class="duration">15 min</span><span><a href="/someone"><span class="name">Some One'
                '</span></a></span></span></p></div>')
        [v] = xv._from_html(page)
        self.assertEqual((v["id"], v["url"], v["title"], v["duration"], v["uploader"], v["uploader_path"], v["channel"]),
                         ("abcd12345", "/video.abcd12345/a_title", "A & title", 900, "Some One", "/someone", True))

    def test_refused(self):
        from dreamfeed.feed import xvideos as xv
        for bad in (("", 0, "", "relevance"), ("x", 0, "15", "relevance"), ("x", 0, "", "newest"), ("underage", 0, "", "relevance")):
            with self.assertRaises(ValueError):
                xv.xv_search(*bad)
        for bad in ("", "../x", "/video.ab/x"):
            with self.assertRaises(ValueError):
                xv.xv_details(bad)


class E621Blacklist(unittest.TestCase):
    """A line hides a post when it has every term: -tag (without it), ~tag (any of those), rating:, *."""
    def test_lines(self):
        from dreamfeed.feed import e621
        tags = {"gore", "male", "solo", "wolf"}
        cases = [(["gore"], True), (["gore", "-solo"], False), (["~gore", "~scat"], True), (["~scat", "~vore"], False),
                 (["rating:e"], True), (["rating:s"], False), (["wol*"], True), (["score:<0"], False), (["male", "wolf"], True),
                 (["male", "fox"], False), (["-fox"], True)]
        for terms, hides in cases:
            self.assertEqual(e621._line_hides(terms, tags, "e"), hides, terms)


class Cookies(unittest.TestCase):
    """Pasted cookies: a cookies.txt, a JSON export or a Cookie header; only the site's, and the ones
    a sign-in needs must be there."""
    def setUp(self):
        self.old = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = tempfile.mkdtemp()

    def tearDown(self):
        os.environ["DATA_DIR"] = self.old or ""

    def test_forms(self):
        from dreamfeed.core import cookies
        later = int(time.time()) + 86400
        netscape = f".x.com\tTRUE\t/\tTRUE\t{later}\tauth_token\ta\n.x.com\tTRUE\t/\tTRUE\t{later}\tct0\tb\n.google.com\tTRUE\t/\tTRUE\t{later}\tSID\tg\n"
        self.assertEqual({c["name"] for c in cookies.parse(netscape, "x")}, {"auth_token", "ct0"})
        js = json.dumps([{"domain": ".x.com", "name": "auth_token", "value": "a", "expirationDate": later},
                         {"domain": ".x.com", "name": "ct0", "value": "b", "expirationDate": later}])
        self.assertEqual(len(cookies.parse(js, "x")), 2)
        self.assertEqual(len(cookies.parse("Cookie: auth_token=a; ct0=b", "x")), 2)
        for bad in ("", "hello", "auth_token=a"):
            with self.assertRaises(ValueError):
                cookies.parse(bad, "x")

    def test_save_is_private(self):
        from dreamfeed.core import cookies
        st = cookies.save("x", "auth_token=a; ct0=b")
        f = cookies.folder() / "x.txt"
        self.assertEqual(st["set"], "dashboard")
        self.assertEqual(oct(f.stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct(f.parent.stat().st_mode & 0o777), "0o700")


class Ids(unittest.TestCase):
    def test_post_ids(self):
        from dreamfeed.feed import livefeeds
        for ok in ("x:1234567", "reddit:abc123", "e621:5", "bsky:z72i7hdynmk6r22z27h6tvur_3n22yg6lg2k2f"):
            self.assertTrue(livefeeds.POST_ID.fullmatch(ok), ok)
        for bad in ("myspace:1", "x:", "x:../etc"):
            self.assertFalse(livefeeds.POST_ID.fullmatch(bad), bad)


class Refusals(unittest.TestCase):
    """Requests the web app refuses before doing anything."""
    def test_import_sites(self):
        from webapp import feed
        for bad in ([], ["myspace"], "x"):
            with self.assertRaises(ValueError):
                feed.import_saved({"sites": bad})

    def test_votes(self):
        from webapp import videos
        for bad in ({"id": "x", "vote": 1}, {"id": "abcd12345", "vote": 5}, {"id": "abcd12345", "vote": 1, "url": "/etc/passwd"}):
            with self.assertRaises(ValueError):
                videos.vote(bad)


class Comics(unittest.TestCase):
    """Drawn work: comics about minors are left out (and nothing else); what's asked is checked."""
    def test_words(self):
        from dreamfeed.feed import comics
        for t in ("loli comic", "young", "cub", "shota", "young_anthro"):
            self.assertTrue(comics.blocked(t), t)
        for t in ("wolf solo", "Youngblood", "big tits", "furry", "feral", "femboy", "bestiality", "rape", "incest"):
            self.assertFalse(comics.blocked(t), t)

    def test_e621_searches(self):
        from dreamfeed.feed import e621
        for ok in ("femboy", "feral", "trap solo", "petite"):
            self.assertEqual(e621.query(ok), ok + " " + e621.SEARCH_NOT)
        for bad in ("young", "cub solo", "loli"):
            with self.assertRaises(ValueError):
                e621.query(bad)

    def test_refused(self):
        from webapp import comics
        for bad in ({"id": "x", "page": 1}, {"id": "e621:1", "page": 0}, {"id": "mp:../x", "page": 2}):
            with self.assertRaises(ValueError):
                comics.progress(bad)
        for bad in ("", "x:1", "e621:abc", "mp:A B"):
            with self.assertRaises(ValueError):
                from dreamfeed.feed import comics as live
                live.comic(bad)


class ComicLists(unittest.TestCase):
    """multporn's lists (New, Updated, a tag's), read from its page; what's asked is checked first."""
    ROW = ('<td class="col-1"> <div class="views-field views-field-title"> <strong class="field-content"><a href="/comics/{slug}">{title}</a></strong> </div>'
           ' <a href="/comics/{slug}"><img loading="lazy" src="https://multporn.net/sites/default/files/styles/x/public/{slug}.jpg" alt="{title} Porn comic'
           ' Cartoon porn comics on Overwatch, Furry" /></a> <h5> <span>Date: </span> <span>12/11/2026 - 08:37</span> </h5> </td>')

    def test_cards(self):
        from dreamfeed.feed import comics
        page = " ".join(self.ROW.format(slug=s, title=t) for s, t in (("one", "One &amp; Two"), ("two", "Loli thing"), ("one", "One &amp; Two"),
                                                                         ("three", "Three"), ('four?rule44=4', "Four")))
        got = comics._mp_cards(page)
        self.assertEqual([c["id"] for c in got], ["mp:one", "mp:three", "mp:four"], "minors left out, each once, in order (a link's query too)")
        self.assertEqual(got[0]["title"], "One & Two")
        self.assertEqual(got[0]["posted"], "2026-11-12 08:37:00")
        self.assertEqual(got[0]["tags"], ["overwatch", "furry"])
        self.assertTrue(got[0]["cover"].startswith("https://multporn.net/sites/default/files/"))

    def test_refused(self):
        from dreamfeed.feed import comics as live
        from webapp import comics
        for bad in (("x", 0, "", "new", "multporn"), ("new", 0, "", "new", "elsewhere"), ("tag", 0, "", "new", "multporn"),
                    ("new", 0, "", "worst", "multporn"), ("updated", 0, "", "new", "e621"), ("new", -1, "", "new", "multporn")):
            with self.assertRaises(ValueError, msg=str(bad)):
                comics.browse(*bad)
        for bad in ("loli", "young", "../etc", "a/b"):
            with self.assertRaises(ValueError, msg=bad):
                live.multporn_list("tag", 0, bad)
        for bad in ("cub", "shota", "a b c*"):
            with self.assertRaises(ValueError, msg=bad):
                live.e621_pools_tagged(bad)

    def test_browse(self):
        """Two of multporn's pages a page (each once), covers through dreamfeed, the tag's name."""
        from unittest import mock
        from dreamfeed.feed import comics as live
        from webapp import comics
        card = lambda s: {"id": f"mp:{s}", "source": "multporn", "title": s, "cover": f"https://multporn.net/sites/default/files/{s}.jpg", "tags": []}
        pages = {2: {"comics": [card("a"), card("b")], "more": True}, 3: {"comics": [card("b"), card("c")], "more": False}}
        asked = []
        def fake(which, n, tag, sort):
            asked.append((which, n, tag, sort))
            return pages[n]
        with mock.patch.object(live, "multporn_list", fake), mock.patch.object(comics, "_tags_or_none", lambda: [{"tag": "big_tits", "name": "Big Tits"}]):
            d = comics.browse("tag", 1, "Big Tits", "top")
        self.assertEqual(sorted(asked), [("tag", 2, "big_tits", "top"), ("tag", 3, "big_tits", "top")])
        self.assertEqual([c["id"] for c in d["results"]], ["mp:a", "mp:b", "mp:c"])
        self.assertFalse(d["more"])
        self.assertTrue(d["results"][0]["thumb"].startswith("comic-search/thumb?u="))
        self.assertEqual(d["tag"], {"tag": "big_tits", "name": "Big Tits", "site": "multporn"})


class ComicDetails(unittest.TestCase):
    """A multporn comic's details (each a link to its list), its comments (threaded; minors left
    out), gay comics apart, and the lists they open: what's asked is checked first."""
    PAGE = ('<h1 class="title" id="page-title"> A &amp; B </h1>'
            '<div class="field field-name-field-author field-type-taxonomy-term-reference field-label-inline clearfix"><h3 class="field-label">Author: </h3>'
            '<ul class="links inline"><li><a href="/authors_comics/some-one">Some One</a></li></ul></div>'
            '<div class="field field-name-field-com-group field-type-taxonomy-term-reference field-label-inline clearfix"><h3>Section: </h3>'
            '<ul class="links inline"><li><a href="/comics/pokemon">Pokemon</a></li></ul></div>'
            '<div class="field field-name-field-com-pages field-type-image"></div>'
            '<div class="field field-name-field-characters field-type-taxonomy-term-reference clearfix"><ul class="links inline"><li><a href="/characters/nicole">Nicole</a></li></ul></div>'
            '<div class="field field-name-field-category field-type-taxonomy-term-reference clearfix"><ul class="links inline"><li><a href="/category/cum_swallow">Cum Swallow</a></li></ul></div>'
            '<div class="field field-name-field-user-tags field-type-taxonomy-term-reference clearfix"><ul class="links inline"><li><a href="/user_tags/mind_break_tag">Mind Break</a></li></ul></div>'
            "<div class='usr-dis-item'> <div class='usr-dis-text'> <h3>Line one<br/>line two</h3></div></div>"
            '<div class="clearfix fivestar-average-text"> Average: <span>4.7</span> ( <span>7572</span> votes) </div>'
            '<li class="statistics_counter first last"><span>8315233 views</span></li>'
            '{comments}<form id="comment-form"></form>')
    C = ('<a id="comment-{n}"></a> <div id="post-{n}" class="forum-post"> <div class="forum-posted-on onn"> Tue, 17/11/2026 - 16:05 </div>'
         '<a href="/users/u" class="username">{who}</a> <div class="field field-name-comment-body"><div class="field-items"><div class="field-item even"><p>{text}</p> </div></div></div>'
         '<div class="rate-number-up-down-rating positive">4.1</div> </div>')

    def _page(self):
        c = self.C
        return self.PAGE.format(comments=c.format(n=1, who="Ann", text="Good &amp; long<br>really") + '<div class="indented">'
                                + c.format(n=2, who="Bo", text="a reply") + c.format(n=3, who="Cy", text="loli please") + "</div>"
                                + c.format(n=4, who="Di", text="top again") + '<ul class="pager"><li class="pager-next"><a href="?page=0%2C0%2C0%2C1">next</a></li></ul>')

    def test_details_and_comments(self):
        from dreamfeed.feed import comics
        s = self._page()
        a = comics._mp_about(s)
        self.assertEqual(a["author"], [{"list": "author", "slug": "some-one", "name": "Some One"}])
        self.assertEqual(a["section"], [{"list": "section", "slug": "pokemon", "name": "Pokemon"}])
        self.assertEqual([x["list"] for k in ("characters", "tags", "usertags") for x in a[k]], ["character", "tag", "usertag"])
        cm = comics._mp_comments(s)
        self.assertEqual([(x["id"], x["depth"]) for x in cm["comments"]], [("1", 0), ("2", 1), ("4", 0)], "threaded; one about minors left out")
        self.assertEqual(cm["comments"][0]["text"], "Good & long\nreally")
        self.assertEqual(cm["comments"][0]["at"], "2026-11-17 16:05:00")
        self.assertEqual(cm["comments"][0]["score"], 4.1)
        self.assertTrue(cm["more"])
        from unittest import mock
        with mock.patch.object(comics, "_mp_html", lambda kind, slug, q="": s), mock.patch.object(comics, "_cached", lambda k, f, t: f()):
            c = comics.multporn_comic("a_b", "gay_porn_comics")
        self.assertEqual((c["id"], c["title"], c["artists"], c["views"]), ("mpg:a_b", "A & B", ["Some One"], 8315233))
        self.assertEqual(c["rating"], {"average": 4.7, "votes": 7572})
        self.assertEqual(c["description"], "Line one\nline two")
        self.assertIn("cum swallow", c["tags"])
        bad = s.replace("Pokemon", "Shota stuff")
        with mock.patch.object(comics, "_mp_html", lambda kind, slug, q="": bad), mock.patch.object(comics, "_cached", lambda k, f, t: f()):
            with self.assertRaises(LookupError):
                comics.multporn_comic("a_b")

    def test_cards_both_kinds(self):
        from dreamfeed.feed import comics
        row = ('<div class="views-field views-field-title"> <strong class="field-content"><a href="/{kind}/{slug}">{slug}</a></strong> </div>'
               ' <div class="views-field views-field-field-author"> <h5 class="field-content">Meesh</h5> </div>')
        page = row.format(kind="comics", slug="one") + row.format(kind="gay_porn_comics", slug="two") + "<h2>More comics:</h2>" + row.format(kind="comics", slug="random")
        got = comics._mp_cards(page)
        self.assertEqual([(c["id"], c["artists"], c["link"]) for c in got],
                         [("mp:one", ["Meesh"], "https://multporn.net/comics/one"), ("mpg:two", ["Meesh"], "https://multporn.net/gay_porn_comics/two")],
                         "both kinds; not the random ones a page ends with")

    def test_lists(self):
        from unittest import mock
        from dreamfeed.feed import comics as live
        from webapp import comics
        asked = []
        def get(url):
            asked.append(url)
            return '<h1 class="title"> Some One </h1> page=0%2C1"'
        with mock.patch.object(live, "_mp_get", get), mock.patch.object(live, "_cached", lambda k, f, t: f()):
            d = comics.browse("author", 0, "some-one", "popular")
            self.assertEqual(d["tag"], {"tag": "some-one", "name": "Some One", "site": "multporn", "list": "author"})
            self.assertTrue(asked[0].startswith("https://multporn.net/authors_comics/some-one?sort_by=totalcount&sort_order=DESC&page=0%2C0"))
            for which, path in (("section", "comics"), ("gsection", "gay_porn_comics"), ("character", "characters"), ("usertag", "user_tags"), ("gtag", "category_gay")):
                live.multporn_list(which, 0, "x_y", "new")
                self.assertTrue(asked[-1].startswith(f"https://multporn.net/{path}/x_y?"), which)
        for bad in (("author", "../x"), ("section", "a/b"), ("character", "loli"), ("usertag", "cub_tag"), ("nope", "x")):
            with self.assertRaises(ValueError, msg=str(bad)):
                live.multporn_list(bad[0], 0, bad[1])
        for bad in (("author", 0, "x", "new", "e621"), ("section", 0, "", "new", "multporn")):
            with self.assertRaises(ValueError, msg=str(bad)):
                comics.browse(*bad)
        for bad in ("e621:1", "mp:../x", "mpx:a"):
            with self.assertRaises(ValueError, msg=bad):
                comics.comments(bad, 1)


class Cache(unittest.TestCase):
    """The Feed's page cache: an old page is shown while it's read again; one reading at a time."""
    def test_stale_then_fresh(self):
        import threading
        from dreamfeed.feed import common
        n = {"reads": 0}
        def fetch():
            n["reads"] += 1
            return n["reads"]
        key = "test:stale"
        common.forget(key)
        self.assertEqual(common._cached(key, fetch, 0.05, 60), 1)
        time.sleep(0.1)
        self.assertEqual(common._cached(key, fetch, 0.05, 60), 1, "old, shown at once")
        for _ in range(50):
            if n["reads"] == 2 and not common._reading.get(key):
                break
            time.sleep(0.02)
        self.assertEqual(common._cached(key, fetch, 0.05, 60), 2, "read again behind it")
        common.forget(key)

    def test_one_reading_at_a_time(self):
        import threading
        from dreamfeed.feed import common
        n, go = {"reads": 0}, threading.Event()
        def fetch():
            n["reads"] += 1
            go.wait(2)
            return "page"
        key = "test:once"
        common.forget(key)
        got = []
        threads = [threading.Thread(target=lambda: got.append(common._cached(key, fetch))) for _ in range(5)]
        for t in threads:
            t.start()
        time.sleep(0.2)
        go.set()
        for t in threads:
            t.join(3)
        self.assertEqual((n["reads"], got), (1, ["page"] * 5))
        def broken():
            raise LookupError("down")
        common.forget(key)
        with self.assertRaises(LookupError):
            common._cached(key, broken)
        self.assertEqual(common._cached(key, lambda: "back"), "back", "a failure isn't kept")
        common.forget(key)


class E621Files(unittest.TestCase):
    """Only e621's own file paths are passed on (the page's e621 pictures and videos)."""
    def test_paths(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("app_under_test", "/app/app.py")
        src = open("/app/app.py").read()
        import re
        pat = re.compile(re.search(r'E621_FILE = re.compile\(r"(.+?)"\)', src).group(1))
        for ok in ("data/sample/58/bf/58bfd70175a849bdbef85ccefe1ee8e5.jpg", "data/0b/8f/0b8f0b8f0b8f0b8f0b8f0b8f0b8f0b8f.webm",
                   "data/sample/0b/8f/0b8f0b8f0b8f0b8f0b8f0b8f0b8f0b8f_720p.mp4", "data/preview/a4/17/a417d12a5ae2b82f6f8d2db5962e3c03.jpg"):
            self.assertTrue(pat.fullmatch(ok), ok)
        for bad in ("data/../etc/passwd", "data/sample/58/bf/x.jpg", "api/posts.json", "data/58/bf/58bfd70175a849bdbef85ccefe1ee8e5.php"):
            self.assertFalse(pat.fullmatch(bad), bad)


class Mutes(unittest.TestCase):
    """Your mute list: whole words anywhere, an account on a site or any, a subreddit."""
    def setUp(self):
        from webapp import mutes
        with mutes._conn() as conn:
            conn.execute("DELETE FROM mutes")
        mutes._rules["value"] = None

    def test_matching(self):
        from webapp import mutes
        for m in ({"kind": "word", "value": "feet"}, {"kind": "word", "value": "big_belly"}, {"kind": "account", "value": "@Someone", "site": "x"},
                  {"kind": "account", "value": "anywhere_guy"}, {"kind": "subreddit", "value": "r/Pics"}):
            mutes.change(m)
        post = lambda **k: {"source": "x", "author": "nobody", "text": "", "place": "", **k}
        self.assertTrue(mutes.post_muted(post(text="Feet pics")))
        self.assertTrue(mutes.post_muted(post(source="e621", tags=["feet_focus", "male"])), "tags, _ as a space")
        self.assertFalse(mutes.post_muted(post(text="feetish things")), "whole words only")
        self.assertTrue(mutes.post_muted(post(text="a big belly")))
        self.assertTrue(mutes.post_muted(post(author="someone")))
        self.assertFalse(mutes.post_muted(post(source="bsky", author="someone")), "that account is on X only")
        self.assertTrue(mutes.post_muted(post(source="reddit", author="anywhere_guy")))
        self.assertTrue(mutes.post_muted(post(source="reddit", place="pics")))
        self.assertTrue(mutes.video_muted({"title": "x", "uploader_path": "/Anywhere_Guy"}))
        self.assertTrue(mutes.room_muted({"name": "r", "info": {"title": "", "tags": ["feet"]}}))
        self.assertTrue(mutes.comic_muted({"title": "Feet!", "tags": []}))
        self.assertEqual(len(mutes.posts([post(text="feet"), post(text="hands")])), 1)
        mutes.change({"kind": "word", "value": "feet", "remove": True})
        self.assertFalse(mutes.post_muted(post(text="Feet pics")))

    def test_refused(self):
        from webapp import mutes
        for bad in ({"kind": "colour", "value": "x"}, {"kind": "word", "value": ""}, {"kind": "subreddit", "value": "a b"},
                    {"kind": "account", "value": "x", "site": "myspace"}):
            with self.assertRaises(ValueError):
                mutes.change(bad)


class Updates(unittest.TestCase):
    def test_told_once(self):
        from dreamfeed.core import notices
        from webapp import updates
        with updates._conn() as conn:
            conn.execute("DELETE FROM notices")
            self.assertTrue(notices.add(conn, "live", "live:a:1", "a is live"))
            self.assertFalse(notices.add(conn, "live", "live:a:1", "a is live"), "the same thing again isn't told twice")
            with self.assertRaises(ValueError):
                notices.add(conn, "weather", "w", "rain")
        self.assertEqual(updates.unread(), 1)
        updates.mark_read({})
        self.assertEqual(updates.unread(), 0)


class Recordings(unittest.TestCase):
    """A recording counts as done once it stops changing; then it's told, and for a room set so,
    its highlights are asked for (then the original deleted)."""
    def test_after_a_recording(self):
        from dreamfeed.core.db import connect
        from webapp import recordings, updates
        from webapp.common import DB_PATH
        folder = tempfile.mkdtemp()
        os.environ["CB_VIDEOS"] = folder
        os.makedirs(f"{folder}/someroom")
        old = f"{folder}/someroom/someroom-old.mp4"
        open(old, "wb").write(b"x" * 10)
        conn = connect(DB_PATH)
        with conn:
            conn.execute("INSERT OR IGNORE INTO follows (source, name) VALUES ('chaturbate', 'someroom')")
            for t in ("rec_files", "kv", "auto_highlights", "highlights", "notices"):
                conn.execute(f"DELETE FROM {t}") if conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (t,)).fetchone() else None
        recordings.look()                                   # the first look: what's there is known, not new
        self.assertEqual(updates.unread(), 0)
        recordings.set_auto({"name": "someroom", "mode": "delete", "keep": 0.25})
        new = f"{folder}/someroom/someroom-new.mp4"
        open(new, "wb").write(b"y" * 20)
        t = time.time() - 2000
        os.utime(new, (t, t))
        with conn:
            conn.execute("UPDATE auto_highlights SET since = ?", (t - 10,))
        recordings.look()                                   # seen: waits to see it stop changing
        self.assertEqual(updates.unread(), 0)
        recordings.look()                                   # the same: done
        self.assertEqual(updates.unread(), 1)
        job = conn.execute("SELECT room, path, keep, then_delete, auto FROM highlights").fetchall()
        self.assertEqual([tuple(j) for j in job], [("someroom", "someroom/someroom-new.mp4", 0.25, 1, 1)])
        recordings.look()                                   # once only
        self.assertEqual(conn.execute("SELECT count(*) FROM highlights").fetchone()[0], 1)
        os.environ.pop("CB_VIDEOS")


class AllRecordings(unittest.TestCase):
    """The Videos tab's Recordings: every followed room's videos, newest first; by room and kind."""
    def test_listing(self):
        from dreamfeed.core.db import connect
        from webapp import live
        from webapp.common import DB_PATH
        folder = tempfile.mkdtemp()
        os.environ["CB_VIDEOS"] = folder
        conn = connect(DB_PATH)
        with conn:
            for r in ("aroom", "broom"):
                conn.execute("INSERT OR IGNORE INTO follows (source, name) VALUES ('chaturbate', ?)", (r,))
        files = {"aroom/aroom-1.mp4": 100, "aroom/aroom-2.mp4": 300, "broom/broom-1.mp4": 200}
        for rel, t in files.items():
            os.makedirs(os.path.dirname(f"{folder}/{rel}"), exist_ok=True)
            open(f"{folder}/{rel}", "wb").write(b"x")
            os.utime(f"{folder}/{rel}", (time.time() - 5000 + t,) * 2)
        d = live.all_recordings()
        mine = [v for v in d["videos"] if v["room"] in ("aroom", "broom")]
        self.assertEqual([v["title"] for v in mine], ["aroom-2", "broom-1", "aroom-1"], "newest first, across rooms")
        self.assertEqual([r["name"] for r in d["rooms"] if r["name"] in ("aroom", "broom")], ["aroom", "broom"])
        one = live.all_recordings("aroom")
        self.assertEqual([v["path"] for v in one["videos"]], [v["path"] for v in live.live_videos("aroom")["videos"]])
        self.assertEqual(live.all_recordings("aroom", "highlights")["total"], 0)
        with self.assertRaises(LookupError):
            live.all_recordings("notfollowed")
        with self.assertRaises(ValueError):
            live.all_recordings("", "weird")


class XBookmark(unittest.TestCase):
    """Saving an X post bookmarks it on X: X's answers read (done, already so, gone, failed); nothing sent here."""
    def test_answers(self):
        from unittest import mock
        from dreamfeed.feed import x
        def answer(body, status=200):
            out = mock.Mock(stdout=json.dumps({"status": status, "body": json.dumps(body)}), stderr="")
            return mock.patch.object(x.subprocess, "run", return_value=out)
        with mock.patch.object(x, "x_cookies", return_value="/cookies.txt"):
            with answer({"data": {"tweet_bookmark_put": "Done"}}) as run:
                x.x_bookmark("1234567890", True)
                self.assertIn("CreateBookmark", run.call_args[0][0])
            with answer({"errors": [{"message": "You have already bookmarked this Tweet."}]}):
                x.x_bookmark("1234567890", True)
            with answer({"errors": [{"message": "_Missing: Tweet record for tweetId: '1234567890' not found"}]}):
                x.x_bookmark("1234567890", False)
                with self.assertRaises(LookupError):
                    x.x_bookmark("1234567890", True)
            with answer({"errors": [{"message": "Could not authenticate you"}]}, 401), self.assertRaises(LookupError):
                x.x_bookmark("1234567890", False)
            with self.assertRaises(ValueError):
                x.x_bookmark("12; rm", True)


class BskyBookmark(unittest.TestCase):
    """Saving a Bluesky post bookmarks it there (with its cid), unsaving takes it away; nothing sent here."""
    def test_calls(self):
        from unittest import mock
        from dreamfeed.feed import bsky
        pid = "a" * 24 + "_" + "b" * 13
        calls = []
        def fake(method, params=None, data=None):
            calls.append((method, params, data))
            return {"posts": [{"cid": "bafyx"}]} if method == "app.bsky.feed.getPosts" else {}
        with mock.patch.object(bsky, "_bsky", side_effect=fake):
            bsky.bsky_bookmark(pid, True)
            bsky.bsky_bookmark(pid, False)
        uri = f"at://did:plc:{'a' * 24}/app.bsky.feed.post/{'b' * 13}"
        self.assertEqual(calls[1], ("app.bsky.bookmark.createBookmark", None, {"uri": uri, "cid": "bafyx"}))
        self.assertEqual(calls[2], ("app.bsky.bookmark.deleteBookmark", None, {"uri": uri}))
        with mock.patch.object(bsky, "_bsky", return_value={"posts": []}), self.assertRaises(LookupError):
            bsky.bsky_bookmark(pid, True)                   # gone from Bluesky
        with self.assertRaises(ValueError):
            bsky.bsky_bookmark("nope", True)


class History(unittest.TestCase):
    def test_entries(self):
        from webapp import history
        history.remove({"all": True})
        history.add({"kind": "post", "key": "x:1", "title": "a post", "link": "post/x/1", "thumb": "https://pbs.twimg.com/a.jpg"})
        history.add({"kind": "room", "key": "someroom", "title": "someroom", "link": "room/someroom/watch", "thumb": "cb-thumb/someroom.jpg?t=5"})
        history.add({"kind": "post", "key": "x:1", "title": "a post", "link": "post/x/1"})         # (again: to the top, once)
        got = history.listing("", 0)["items"]
        self.assertEqual([i["key"] for i in got], ["x:1", "someroom"])
        self.assertEqual([i["key"] for i in history.listing("", 0, "some")["items"]], ["someroom"])
        for bad in ({"kind": "post", "key": "x", "title": "", "link": "https://evil.example/"}, {"kind": "post", "key": "x", "link": "/abs"},
                    {"kind": "post", "key": "x", "link": "../up"}, {"kind": "video", "key": "x", "link": "xvideos/x"},
                    {"kind": "room", "key": "Bad Room", "link": "room/x"}):
            with self.assertRaises(ValueError):
                history.add(bad)

    def test_search_refuses_minors(self):
        from webapp import search
        for bad in ("", "loli", "x" * 101):
            with self.assertRaises(ValueError):
                search.yours(bad)


class Contract(unittest.TestCase):
    """The app-contract checker itself finds what's wrong."""
    def test_finds_problems(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "contract"))
        import check
        check.problems.clear()
        check.check({"rooms": [{"name": "a", "live": True, "info": {}, "times": [[1, 2]]}]}, "Following", "Following", "x")
        self.assertEqual(check.problems, [])
        check.check({"rooms": [{"name": "a", "info": {}, "times": [[1, 2]]}]}, "Following", "Following", "x")
        self.assertTrue(any("live: missing" in p for p in check.problems), check.problems)
        check.problems.clear()
        check.check({"rooms": [{"name": 5, "live": True, "info": {}, "times": []}]}, "Following", "Following", "x")
        self.assertTrue(any("name: int where the app needs String" in p for p in check.problems), check.problems)


if __name__ == "__main__":
    unittest.main()
