# dreamfeed

A private, phone-first page for what you follow and like, read live from the sites:

- **Feed:** your X and Bluesky timelines, your Reddit subscriptions and e621 searches (Following),
  and each site's picks for you (For you), several sites at once or one; Saved keeps what you save.
- **Videos:** long videos from xvideos in dreamfeed's own player, chosen from what you watch.
- **Comics:** read live from e621's pools and multporn, chosen from what you read and follow.
- **Live:** the Chaturbate rooms you follow, in dreamfeed's own player (several at once), with
  your recorder (streamonitor) and your recordings.
- **Dashboard:** Health (whether each part is working), Sign-ins, the Feed's subreddits and searches.

The page is at `https://<your domain>/dreamfeed/` (behind formlogin). Nothing here is generated:
the personas and their generated posts, comics and trained styles were retired, with the
generation pipeline (ComfyUI, the age checks, the trainers), in November 2026.

## Where things are

- `worker/dreamfeed/`: dreamfeed's own code, read by the web app and run by the follow service
  (`python -m dreamfeed follow`):
  - `core/`: sign-ins (`cookies`), the database (`db`), the one rule: nothing about minors (`safety`).
  - `feed/`: the live sites, a module each (`x`, `bsky`, `reddit`, `redgifs`, `e621posts` with
    e621's API in `e621`, `xvideos`, `comics`), mixed by `livefeeds`; Saved's copies (`savedposts`).
  - `live/`: Chaturbate: the follow service (`follow`), your recordings and highlights
    (`cbvideos`, `cbhighlights`), profiles and linking accounts across sites.
- `web/`: the web app. `app.py` answers the requests (and starts its background work), passing
  them to its parts in `webapp/` by area: `common` (settings, the database, the page's security
  policy), `feed` (the live Feed, Saved, More videos), `videos`, `comics`, `live` (Chaturbate:
  Following, Discover, recordings, your recorder, profiles, linking), `signins`, `health`, and
  `retired` (the empty answers the iOS app still asks for). The page is `index.html` with its
  style in `static/app.css` and its script in parts by what they do in `static/js/` (served
  joined, as one `static/app.js`); `dvr.py` talks to your recorder.
- `browserpower/`: starts and stops the server's browser (systemd on the host; Sign-ins).
- `tests/`: the checks: `tests/check` before a deploy, `tests/check --live` after (with the iOS
  app's contract), `--browser URL` for real Firefox (tests/README.md).

## Running

1. `cp .env.example .env` and fill it in.
2. `docker compose up -d --build`
3. Set the sign-ins on the Dashboard (Sign-ins), and `sudo browserpower/install.sh` for the server's browser.

Three services: `web` (the page and its API), `follow` (Chaturbate, your recordings' posters and
highlights, Saved's copies; standard-library Python and ffmpeg) and `browser` (Firefox, only
when needed). Before a deploy `tests/check`, after it `tests/check --live`.

## What's left out

Only content about minors, by its words and tags alone (`worker/dreamfeed/core/safety.py`; no
picture is looked at). Everything else the sites show is shown: femboy, feral, petite, step-family,
non-consent, gore and the rest are yours to filter (your e621 blacklist, when signed in, applies).
- **Everywhere** (posts, comments, subreddits, rooms, videos, searches): words that only mean
  minors (underage, child, loli, shota, ages under 18 ...). Adult-site words like "teen",
  "young" or "schoolgirl" aren't among them.
- **Drawn work** (e621, comics) also: e621's tags for minors (`young`, `cub` ...), in a post's
  tags or a comic's title and tags, since a drawing has no verified age.
- **Live:** rooms Chaturbate doesn't list as age verified, or as under 18.

## Folder layout

```
dreamfeed/
  docker-compose.yml  .env  .env.example  README.md
  worker/    the follow service's image, and dreamfeed's own code (core/, feed/, live/)
  web/       the web app (app.py, webapp/), the page (index.html, static/)
  browserpower/  the server's browser's start and stop (systemd units, installed with sudo)
  tests/     the checks (tests/check)
  data/      feed.db (follows, Saved, what you watch and read, links, sign-ins' state), saved/
             (Saved's copies), cookies/ (sign-ins: readable by dreamfeed only), browser/ (the
             server's browser's profile), generated/ (thumbnails; your old comics)
  state/     login.json, session.key
```

## Comics

A feed like the rest, read live from e621's pools (its comics) and multporn, nothing downloaded
(`worker/dreamfeed/feed/comics.py`, `web/webapp/comics.py`):

- **For you**: chosen from what you read here (how far you get in each, what you follow: their
  tags) and your e621 taste (the artists and species you favorite and vote up, signed in), from
  e621's comics with your kind of posts, its latest updated, multporn's newest and searches for
  your tags; each says why. What you've finished or follow is left out (it shows above).
- **Updated**: comics you follow with new pages since you last read them (looked at every six
  hours; the reader says from which page they're new). **Continue reading**, **Following**.
- **Follow** in the reader; where you are is remembered as you read.
- **Search** multporn or e621's comics by title, artist or character.
- **Your comics**: the ones kept here before (imported, or made), still readable, renamed or
  deleted from their grid of pages. Those imported from multporn are followed there, so their new
  pages come in under Updated.

Drawn work: a comic whose title, tags or categories have anything about minors (e621's tags
for them, minors-only words) is left out; lists judge comics by their cover, and one
that turns out to have such a page is refused when opened and left out after. No picture is
looked at. e621's pictures reach the page through dreamfeed (`/e621-media/`): e621 now turns away
pictures a browser shows on another site.

## Following

Who you follow elsewhere, in one place: the **Feed** has posts from your X Following timeline,
the subreddits you're subscribed to and your e621 searches, and **Live** the Chaturbate rooms
you follow.

### Feed: X, Reddit and e621

The Feed is read live: when you open it (or tap More), the web app asks the sites for their
newest posts and shows them; their pictures and videos load straight from the sites' own
servers (no referrer is sent). Nothing of them is downloaded or kept, and the pictures aren't
looked at by the checks. A page is reused for 2 minutes (switching tabs, coming back). Left out
(What's left out): anything about minors. Open on X/Reddit goes to the post.

**Which sites:** All, or tap the ones you want (X and Reddit, say; tap one again to drop it),
remembered in this browser; Following and For you both take it.

- **Bluesky:** as you (the Dashboard's Sign-ins: your handle and an app password, never your
  own; it signs in once and keeps the session it makes): Following is your timeline; For you
  mixes your own feeds on Bluesky, the ones you pinned (else the ones you saved; Bluesky's own,
  such as Discover, only when they're all there is), up to 10, a page of each taken in turns, each post saying which feed it's from
  (pin adult feeds such as After Dark, 🐾 Hot 🌙 or Hentai Illust on Bluesky to have them here). Posts with pictures or a video
  (Bluesky's own HLS, played and kept like Reddit's), their replies, and profiles (tap a name:
  their posts with media, at `/bsky/HANDLE`). More videos on a Bluesky video: theirs, then
  Bluesky's own Video feed, then your timeline's. Adult posts only come when adult content is on
  in Bluesky's own settings (on its website).
- **X:** with your cookies (the Dashboard's Sign-ins, or `X_COOKIES_FILE`; the same ones styles use), through gallery-dl's
  metadata (`-j`: what a post is and where its files are, nothing downloaded), 30 media files
  a page.
- **Reddit:** through Reddit's API, signed in as you (below): your subscriptions and the
  Dashboard's **Reddit** panel (`r/name`, `u/name`, kept in `data/following.json`) as one
  listing, newest first; pictures, galleries (up to 20 pictures), Reddit's own videos (HLS,
  with sound: Safari plays it itself, other browsers through hls.js) and redgifs clips (asked
  of redgifs' API). Text-only posts are left out.
- **e621:** the Dashboard's **e621** panel's tag searches (an artist, a character,
  `wolf solo`), newest first. A search for minors (`young`, `cub` ...) is refused, and every
  search asks e621 to leave them out too (`e621.NEVER`). `E621_USERNAME` (optional) names you in the user agent.

  **Signed in to e621** (the Dashboard's Sign-ins: your username and an API key from e621's
  Account, Manage API Access; checked before it's kept, or `E621_USERNAME` and `E621_API_KEY`):
  Save on an e621 post favorites it there too (and unsaving unfavorites it); ▲ ▼ on e621 posts
  vote as you (the same again takes it back); your account's blacklist hides what it does here
  too (its lines of tags, `-tag`, `~tag`, `rating:`, `*`; a line with other metatags is left to
  e621's own site), read again each hour; Saved's import brings in your favorites; and For you
  adds your taste: the artists you favorite and vote up most (their week's best) and the species
  (today's best), from your last few hundred favorites and up votes, without what you've already
  favorited, each search taken in turns with the Dashboard's.

The Feed has two parts, each with All, X, Reddit (and e621) to pick from (what you save goes to
the **Saved** tab, below):
- **Following:** your X Following timeline, your subreddits and Reddit people, e621, newest
  first.
- **For you:** the sites' own picks: X's For you timeline and your Reddit front page (Best), in
  each site's own order, taken in turns; never mixed into Following. Something new each time:
  posts you were shown more than 30 minutes ago are passed over (and it reads further down for
  more), here and in More videos, where Reddit's also starts from a different listing of the
  subreddit each time (hot, new, the week's or month's top). Above it, people you might
  like: X accounts you don't follow, from your rooms' bios, mentions by people you follow and
  X's For you (from the last 30 days of your timelines, `x_seen`).
- **Saved** (★ Saved on the Feed page, beside Following and For you, or in the ⋮ menu; at
  `/saved`; newest first): what you tapped Save
  on, kept: the follow service downloads its pictures and
  videos in full quality (X's original pictures and biggest video, e621's original or its
  full-size MP4, Reddit's own videos with sound through ffmpeg, redgifs' HD) into
  `data/saved/<site>/<post>/`, which is backed up. Saved shows those copies once
  they're in (the post says "keeping a full-quality copy…" until then), so a post deleted on
  the site stays. Unsaving deletes them. A Reddit post is saved on Reddit too, as you, at once.
  An X post is kept in dreamfeed only: bookmarking on X would mean faking X's own web client,
  so use Open on X for that.
  **Bring in what you saved on the sites** (at the top of Saved) asks which (the last pick is
  remembered), then adds your X bookmarks, your Bluesky bookmarks, your Reddit saved posts (the
  last 1000 Reddit keeps) and your e621 favorites (the last 1000; signed in to e621) with
  pictures or videos, kept the same
  way; the minors rule leaves some out, and ones you unsaved here stay out. Run it again any
  time for new ones. Reddit's saved list needs the sign-in's `history` permission (signed in
  before it was added: sign in again, below). Unsaving an imported X post doesn't remove the
  bookmark on X.

**Browse now (Reddit).** With Reddit picked, type a subreddit (or tap one on a post) to see it
as it is now: Hot, New or the day's Top, 25 posts a page, More for the next.

**Watching the Feed.** Videos don't play by themselves: tap one to play it (with sound), and
it pauses when you scroll past. A post with several pictures or videos swipes sideways (2 / 7 in the corner). Opened, a
post shows its pictures in full quality; tap one to see it full screen. A site that didn't
answer says so at the top, with Try again. The Feed's mode and site, and Saved's filter, stay as
you left them (in this browser).

**More videos** (on an X, Reddit or e621 video post). On X, it's X's own swipe-up feed, the videos its full-screen player
shows after that one (X's ImmersiveMedia call, read as you through gallery-dl's connection). One
video a screen: swipe or scroll up for the next (↑ ↓ or j k on a keyboard); the one on screen
plays, and Tap for sound keeps sound on for the rest. The next two load while you watch. Each
shows who posted it (tap for their profile), its text, likes and views, 💬 for its replies, Save,
and ↗ to open it on X; Back from those returns to the same place. Its address is
`/videos/POST/HANDLE`. On Reddit (whose own feed only its app can read) it's rebuilt the way the
app does it: more videos from that subreddit (hot, then the week's top), then from your
subscriptions and the Dashboard's subreddits, newest first; Reddit's own videos, RedGifs and
Imgur all play. On e621: more by its artist and the search it came from, then your Dashboard
searches. Their addresses are `/videos/reddit/ID` and `/videos/e621/ID`. X changes that call's id now and then: `X_RELATED_QUERY` in .env overrides
the one that works now.

**Comments.** Tap a post's text or picture, or 💬 (with how many it has), to open it with its
comments, read live from its site: X's replies (nested by what they answer, with their pictures),
Reddit's comments (top first, replies to replies four deep; AutoModerator left out) and e621's.
Comments with words dreamfeed never shows are left out.

**🎲 Random** (next to Browse) opens a random subreddit from a list you keep (`RANDOM_SUBREDDITS_URL`:
an https address of a text file, one name a line; read again each day). The usual subreddit rules
still apply to it; banned, private and empty ones are passed over. 🎲 Another, on the subreddit's
page, swaps it for another one.

**Profiles.** Tap an X name or picture (Following, For you, anywhere) for their profile: their
picture, name, bio and counts, and their latest media posts, read as you open it (More for
older ones). A Reddit name gives their latest posts the same way (Reddit's search by author),
with their picture and karma; a Reddit post's picture is its subreddit's icon (tap it for the
subreddit). An e621 artist's name gives what they drew, newest first, their pages elsewhere as
e621 lists them, and their X posts too when one of those is an X account.

**Sign-ins** (on the Dashboard). How dreamfeed reads the sites as you, set without touching
files or restarting anything; each says when it was set and when it runs out (never the values).
They're kept in `data/cookies/` (readable only by dreamfeed's user, left out of git), and used
first wherever dreamfeed signs in (the Feed, styles, comic imports, the Live tab's follow list).
- **X, Chaturbate and xvideos:** Update, then paste an export of the site's cookies made while signed in
  (cookies.txt or JSON from a browser extension like Cookie-Editor, or a Cookie header copied
  from the developer tools), or pick the file. Only that site's cookies are kept, the ones a
  sign-in needs must be there (X: `auth_token`, `ct0`; Chaturbate: `sessionid`, `csrftoken`),
  and Save checks the site takes them. Until then, the files mounted as `X_COOKIES_FILE` and
  `CHATURBATE_COOKIES_FILE` are used (now optional); Forget goes back to those.
- **Or sign in on the server's browser:** the `browser` service is a Firefox running on your
  server, shown in your own browser (from any device). Sign in on the server's browser opens it:
  go to the site there and sign in yourself (captchas and two-factor codes included), then come
  back and tap Take its cookies, which reads that site's cookies from its profile and checks
  them as above. It stays signed in there, and cookies taken from it are taken again by
  themselves once a day: it's started out of sight, opens the sites (its homepage tabs, which
  freshens their sign-ins), and they're taken and checked; if it's been signed out, the
  Dashboard says so and the cookies you had stay. It runs only when needed: started when you
  open it or for that, and stopped once no one has watched it for 10 minutes. dreamfeed has no
  say over Docker for this: it only leaves a file named `start` or `stop` in
  `data/browser-power`, and systemd on the host runs `browserpower/power.sh` with that fixed
  action (and each minute, to stop it when unused). Install that once with
  `sudo browserpower/install.sh` (it copies the script where only root can change it, with its
  units; `--remove` takes them away; run it again after changing `power.sh`). Your
  proxy serves it beside dreamfeed, letting only someone signed in to dreamfeed through (Caddy:
  `forward_auth` to dreamfeed's `/api/auth-check`, then the browser service on port 5800; its
  address goes in `BROWSER_URL`, e.g. `browser/` for `/dreamfeed/browser/`). Its profile is in
  `data/browser` (its caches can be left out of backups).
- **Reddit:** your own app at reddit.com/prefs/apps. Its redirect uri must be dreamfeed's own
  address, which App keys shows (e.g. `https://<your domain>/dreamfeed/reddit/callback`): set it
  there once. Give App keys its id and secret, then Sign in with Reddit: you approve it on
  reddit.com and come straight back, signed in (your password is never stored; revoke it under
  Reddit's authorized apps). Keys and a sign-in in `.env` (`REDDIT_CLIENT_ID`,
  `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_REFRESH_TOKEN`) still work; Keep here instead
  copies them to the dashboard. Without a sign-in, Reddit is left out of the Feed. (The older
  `follow reddit-login` command still prints a token for `.env`, with the redirect uri
  `http://localhost:6414/`.)

### Videos (xvideos)

The Videos tab: long videos, played in dreamfeed's own player (each video's stream, up to 1080p,
read from xvideos when you open it: no xvideos page, no ads; nothing is downloaded).

- **For you** learns from what you watch here: how far you get, whether you finish one or leave
  in the first 30 seconds, and 👍 / 👎 in the player become weights on its tags and uploaders
  (watching a month ago counts half). It's drawn from the related videos of what you liked,
  more from the uploaders you watch, and your top tags (and, until there's enough to go on, your
  Chaturbate rooms' tags and their linked xvideos accounts), ranked by those weights, at most 3
  from one uploader, each saying why it's there. What you've finished or turned down is left out.
- **In the player**: its views, 👍 / 👎 (and their ratio) and 💬 its comments (xvideos' top 10,
  with a link to the rest on its page). Signed in to xvideos (Sign-ins: on the server's browser,
  then Take its cookies; dreamfeed checks xvideos sees you signed in), 👍 / 👎 here vote on
  xvideos too, as you (taking one back only takes it back here).
- **Continue watching** picks up where you left off; **Up next** (a related video) plays when
  one ends, unless you cancel it.
- **Search**, with a length filter (10+ or 20+ minutes; remembered, and used for For you too).
- Titles and tags with words that only mean minors (underage, child, loli ...) are left out, and
  never searched for; adult-site words like "teen" aren't filtered (nearly every title has one).
- A room profile's xvideos tab plays in the same player, and what you watch there counts too.
- `web/webapp/videos.py` (what you watch is kept in feed.db: `xv_watch`, `xv_videos`,
  `xv_votes`), `worker/dreamfeed/feed/xvideos.py` (reading xvideos' pages). Real people: nothing
  from it goes to training or generation.

### Live: Chaturbate

The rooms you follow: who's live now, with their thumbnail, title and viewers, and the rest
with when they were last live and the hours they're usually live (from 3 days of streams on, in
your own time). Tapping a live room plays it in dreamfeed's own player: the room's video
straight from Chaturbate's video servers (HLS: Safari plays it itself, other browsers through
hls.js, served from `web/vendor/`), muted until you tap for sound, with ‹ › to go through the
live rooms. A private or hidden show says so. Open on Chaturbate goes to the room itself, to
chat or tip as you. The header shows how many are live.

The `follow` service (the worker's image, CPU only) looks every 2 minutes, signed in with your
cookies (the Dashboard's Sign-ins, or the file `CHATURBATE_COOKIES_FILE`; read on each look). Follows and unfollows there show up here
within the hour. If the cookies run out, the page says so.

These are real people, so nothing from here goes into training, styles, comics or generation,
and nothing of a stream is kept: only who you follow, when they were live and each one's last
thumbnail (`data/generated/follow/`). A room Chaturbate doesn't list as age verified is left
out.

**Your recorder, from here.** With `STREAMONITOR_URL` set (streamonitor's web address as the web
service reaches it, e.g. `http://streamonitor:5000` on a Docker network they share; and
`STREAMONITOR_PASSWORD` if it has one), Live shows what it does for each room you follow: ● REC
on a live room it's recording, "Records when they go live", "Recording paused". Record on a live
card (or a profile) asks which: **this stream** only (their next, when they're not live) or **all
streams** (the room on its list, recording each time). This stream only ends itself: once the
recording has stopped for 3 minutes (a short drop isn't the end), the room is paused again, or
taken off the list if it wasn't on it before. Pause (Stop, for one stream) stops it but keeps it
listed; Remove (on the profile) takes it off the list, and the recordings you have stay. Free disk
space shows on the profile. Its recordings show up on the room's profile (below).

**Your own videos of them.** Videos you have of the rooms you follow go in the folder
`CB_VIDEOS_DIR` (mounted into the web and follow services; dreamfeed writes there only for
highlights and deletes, below): a folder per room, named after it (`<room>/...`, subfolders too;
`<room> [CB]/`, as streamonitor names them, too), or loose files whose names start with the
room's (`<room>_2026-11-10.mp4`); the longest room name that fits wins. When your recorder makes
the folders as another user (root), set `CB_VIDEOS_GID` to a group the folder lets write (its
ACL), so highlights and deletes can write there.
MP4, M4V, MOV, WebM and MKV are listed; MP4 plays in every browser. A room with videos says how
many: tap that (or the room, in Not live) for its profile, with the videos newest first, each
with a poster and its length, played in the same player (‹ › go through that room's videos).
The follow service makes the posters (ffmpeg, a frame from 10% in) on each look, up to 30 at a
time, in `data/generated/follow/videos/`, and drops them when the videos go. Only rooms you
follow are shown; nothing from the folder goes to training, styles, comics or generation, and
it isn't in dreamfeed's backup (back it up where it lives).

Under each video:
- **Highlights** cuts it down to where something's happening. Pick how much to keep: Short
  (about 10%), Medium (25%) or Long (50%). The follow service looks through it twice, at two
  looks a second: for motion (how much each small grey frame differs from the last) and for
  sound (how loud). Motion counts three times as much as sound, since chatting is loud but
  still. Each moment is ranked against the rest of the same video and smoothed over about
  5 seconds, and the best share is kept, in stretches with a second either side. Gaps under
  3 seconds are filled and stretches under 4 seconds dropped. It's then encoded as one MP4 in
  the room's folder, `<room>/highlights/<name> [tag].highlights.mp4`, next to the original
  (which isn't changed). It's CPU only, at low priority, one at a time; the profile shows how
  far along it is, and the highlights show up just before their video. A 1-hour 1080p video
  takes some minutes (it's decoded in full twice, and the kept part encoded once).
- **Delete** moves the video to `.trash/` in that folder, with an Undo. The follow service
  deletes what's been there over a week. Highlights are videos of their own, so deleting one
  leaves the other.

### One profile across sites, Discover, Watch several

**Profiles.** Every room has a Profile (under its card, or tap it in Not live): when they're
usually live, their bio, the X and Reddit accounts linked to the room, their latest posts there
(read live), and your videos of them. Accounts get linked by themselves when the performer links them
for free in their Chaturbate bio (the follow service reads a few bios each round, each once a
day; links that cost tokens are left alone), or by you on the profile; × unlinks one (it isn't
linked again). **Their accounts, found across sites** (`live/linking.py`, run by the web app: it has the Reddit and
X sign-ins). From what a room links, dreamfeed follows what the creator publishes themselves: link
pages (Linktree, AllMyLinks) are read and every account on them linked; each account's own profile
is read for more (an X bio and website, a Reddit profile, a RedGifs profile), two steps out. Then
their names (the room's, their OnlyFans, Fansly, X and Reddit names) are looked for on RedGifs and
Reddit: one whose profile links back to an account already theirs is linked ("links back"); a
RedGifs one that doesn't is only suggested (dashed, "same name: theirs?", ✓ or ×), since others
use the same names. Each link says where it was found. A room is looked at when you open it and
again after a week; the rooms you follow, a few each half hour; Look again on the profile does it
now. OnlyFans and Fansly aren't read (paywalled); nothing is guessed from faces or anything else.
A linked RedGifs account gives the profile a RedGifs tab: their clips, newest first, played here.
An xvideos profile works the same way (its address in their bio, or linked by you
as its name or address): the profile then has an xvideos tab next to Posts with their videos,
newest first, played in dreamfeed's own player like everything else (each video's own stream,
up to 1080p, read from xvideos when you open it: no xvideos page, no ads; nothing is downloaded). Tapping a poster's name in the Feed opens their profile too, the room's if
they're linked to one.

**Discover, on Live** (its own page next to Following, which has who you follow, live and not): live rooms you don't follow. For you has rooms sharing the most common
tags of the rooms you follow, Top the most watched, Search a tag or a few words, each for
anyone or for women, men, couples or trans performers. Only rooms Chaturbate lists as age
verified, 18 or over and with no password are shown, and rooms whose tags or title have words
dreamfeed never takes (the same rules as everywhere: teen, petite, schoolgirl and the like)
are left out; searches for those words are refused. They play in the same player.

**Follow and unfollow from here.** Follow on a Discover card or a profile (Following ✓ to
unfollow) follows the room on Chaturbate itself, as you: the follow service sends it the way
the site's own button does (your cookies' session, within seconds of the tap, one at a time),
checks Chaturbate's answer and updates the list here at once. Only when you tap.

**Discover, in the Feed:** X accounts you don't follow (you follow whoever your Following
timeline shows): those linked from the rooms you follow, those people you follow mention or
reply to and those in X's For you, twice or more (from the Feed pages you've looked at in the
last 30 days). Their profile shows their latest posts, read live.

**Watch several:** on Live, pick up to 4 live rooms (yours or from Discover) and watch them
together, each in its own tile at a quality to fit, with its title and viewers (asked again
every minute). All are muted but the one you tap (Mute all mutes that one too); Full opens one in
the player, ✕ drops one (the others keep playing), + Add brings in another live room up to 4: one
of yours that's live, or from Discover (for you, or search a tag or a few words). A tile whose stream stops tries again 10 seconds later. In the player,
+ Several starts this with the room you're watching; Follow follows a room you don't yet, and the
title under the video stays current while you watch.

## Backup

- **Backed up:** `data/feed.db` (picked up automatically as SQLite), `data/saved/`, `state/`,
  `.env`, and the source folders.
- **Excluded:** `data/generated/` (thumbnails; but not your old comics, `comic-*`, which are
  kept), the server's browser's caches, and `logs/`.

## Addresses

Each part of the page has its own address, so links, bookmarks and the Back button work. Opening
one replaces what's on screen (nothing stacks); Close and Back go to the page before, or home when
you came by link:

- tabs: `/feed` (`/feed/foryou`), `/saved` (`/saved/x`, `/saved/reddit` ...), `/vids`, `/live`
  (`/live/discover`), `/comics` (`/comics/ID`: a comic), `/dashboard`; `/` opens the tab you used last
- rooms: `/room/NAME` (profile), `/room/NAME/watch`, `/room/NAME/video/PATH` (one of your videos),
  `/watch/A+B+C` (Watch several)
- people and places: `/x/HANDLE`, `/u/NAME` (Reddit), `/r/SUB` (`/r/SUB/new`, `/r/SUB/top`),
  `/e621/ARTIST`, `/xvideos/ID` (a video)
- posts: `/post/x/ID`, `/post/reddit/ID`, `/post/e621/ID` (your kept copy when you saved it, else
  read again from the site)

Signing in always lands on home (the sign-in page doesn't keep where you were going).

## Caddy

In the public section of the `<your domain>` block (the app has its own sign-in):

```
redir /dreamfeed /dreamfeed/
handle_path /dreamfeed/* {
	reverse_proxy dreamfeed-web:8000 {
		header_up X-Forwarded-Prefix /dreamfeed
	}
}
```

Every part of dreamfeed has its own address under that prefix (`/dreamfeed/saved`,
`/dreamfeed/room/NAME`, `/dreamfeed/post/x/ID` ...: see **Addresses**), so the page needs to know
the prefix the proxy strips: `X-Forwarded-Prefix` says it. Without it the app assumes it's at the
site's root.

The Caddyfile is a single-file mount: after editing it, `docker restart caddy` (a reload
alone keeps reading the old file).

## Password

First visit shows a set-password page that needs the one-time setup code from
`docker logs dreamfeed-web`. Or: `docker compose exec web python -m formlogin passwd`.
