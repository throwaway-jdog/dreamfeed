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
