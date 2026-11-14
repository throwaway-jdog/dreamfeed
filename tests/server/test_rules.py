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
