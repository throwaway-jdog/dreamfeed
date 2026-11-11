# dreamfeed

A private, phone-first page for who you follow and for comics:

- **Feed:** posts from your X Following timeline, your Reddit subscriptions and e621 tag
  searches, read live from the sites when you look (see Following).
- **Live:** the Chaturbate rooms you follow, played in dreamfeed's own player.
- **Comics:** comics made here from **fictional personas** (each with a name, a fixed look and
  a trained style), and comics imported from a link or found with multporn's search, with
  panels animated into loops.
- **Saved:** the generated posts you liked. (A nightly generated feed of the personas' posts
  came first; it no longer runs, and only the liked posts were kept.)
- **Dashboard:** what's running, personas and trained styles.

The page is at `https://<your domain>/dreamfeed/` (behind formlogin).

Models (in `.env`): WAI-Illustrious v17 for anime, FurryVision XL v2 for furry, Wan 2.2
I2V for clips. Civitai downloads that need an account use `CIVITAI_API_KEY`.

## Personas

Add, change, pause and remove them on the Dashboard (**Personas**). The editor covers
everything below, including turning a trained style on or off. Every save is checked with
the worker's own rules first (blocked tags, placeholders, style medium), so a bad edit is
refused with a message instead of breaking the nightly run. Removing a persona takes their
posts out of the timeline; liked posts stay in Liked.

**Build one from a description**: type who they are and what they post, the way you'd
describe a creator you follow ("Chinese femboy. Cosplays, sex with men, wears a face mask",
or "draws and animates furry porn"). The caption model (`CAPTION_MODEL`) drafts the whole
persona in about a minute: name, handle, bio, look or characters, kinds of post with prompts
and captions, emoji and hashtags. It opens in the editor to check and change before you save.
The draft is always fictional and drawn: the real account's handle and name are never reused
(your description is kept only as the private `based_on` note), real-life creators become anime
personas, and it goes through the same checks as any edit. Descriptions with feral or animal
content, or anything young, are refused; blocked tags are swapped for allowed ones; voyeur and
non-consent themes are rejected. It runs as a worker job, so during a night's run it waits for
the run to finish.

They are stored in `data/personas.json`, which is private (it describes whose posting
styles inspired them) and is not in git; you can also edit it by hand. Each dashboard save
keeps the previous version as `data/personas.json.bak`. The format, from
`personas.example.json`:

- `handle`, `name`, `bio`, `medium` (`anime` or `furry`), `look` (tags that keep the
  persona recognisable), `avatar` (extra tags for the profile picture), `emoji`,
  `hashtags`, `video_share` (how much of the nightly video budget favours them), `weight`,
  `negative` (extra negative prompt, e.g. `face, eyes` for a faceless persona), and `lora`
  (`{"file": "style-x.safetensors", "strength": 0.8, "trigger": "x_style"}`; add
  `"female_only": true` for a LoRA trained mostly on women, which otherwise turns male
  characters female: those posts then skip the LoRA). Artist LoRAs can bake in the artist's
  watermark faintly, so give those personas `"negative": "watermark, text, signature"`.
  `"enabled": false` switches the style off and keeps its settings. With a character LoRA
  in `lora`, `art` (same form) adds the artist's style LoRA, applied after it to everyone in
  the picture, so partners are drawn in the artist's style without turning into her.
- `paused`: keeps the profile and posts but makes nothing new, except on **Post now**.
- `based_on`: a private note, never shown or used in prompts.
- `posts`: kinds of post, each with `weight`, `rating` (`explicit`, `questionable`,
  `general`), `prompt` and `captions`. Prompts may use `{outfit}`, `{cosplay}` (generic
  costumes only), `{setting}` and `{character}` (from `characters`, for artist personas
  who draw different people), and `{partner}` (one of `partners`, so duo posts don't always
  show the same man; a faceless male when there are none), `{girlfriend}` (one of
  `girlfriends`, for girl-girl posts) and `{friend}` (one of `friends`, other personas'
  handles: that persona appears as themselves, with both their character LoRAs on and no artist
  style, which keeps both right; girl-girl scenes can be made from such posts). The captions are examples of how
  the persona writes (below).
- `must_show`: traits every post must show, each a list of tags any of which counts (e.g.
  `[["red hair"], ["hairclip", "hair ornament"]]`); a post the tagger doesn't see one in is
  drawn again, like one with a watermark (up to twice). `must_not_show`: tags that make a post
  off-model the same way (e.g. `["blue fur"]`). With a `{friend}`, theirs count too (except
  tags that are either one's own look). Scenes pick their shots by these as well. Posts that
  aren't explicit keep tops on: nipples are kept out of their prompt, and one showing them anyway
  is drawn again.
- `voice`: the name of a trained style; the persona's captions then sound like that
  artist's own posts instead of its example captions.

The file is re-read every run. A persona with no profile picture gets one on its next run.
Invalid entries or blocked tags stop the run with a clear error instead of being skipped.

## Captions

Every post that reaches the timeline gets a newly written caption. After each night's checks,
a small text model (`CAPTION_MODEL`, Qwen3-4B-Instruct by default: about 8 GB, downloaded once
to `models/hf/`, a second or so per post on the GPU) is given what the tagger sees in the
picture and examples of how the persona writes:

- with a `voice` (chosen under **Captions** in the editor): the post texts of the artist
  behind that style, saved when the style was downloaded (`data/lora/NAME/voice.json`)
- otherwise the persona's example captions

Artist posts are cleaned before the model sees them: business posts (commissions, Patreon,
followers, polls), anything not in English, @handles, links and hashtags are left out, and
names of characters, series and people become `[name]`. Each written caption is checked and
thrown away if it names anyone, mentions ages, school or anything young-sounding, has links
or @mentions, or copies an example; after four failed tries the post keeps one of its
example captions. Empty `CAPTION_MODEL` turns writing off (example captions only).

## Running

1. `cp .env.example .env` and fill it in.
2. `docker compose up -d --build`
3. Add personas on the Dashboard (or `cp personas.example.json data/personas.json`).

Generated posts no longer run every night (the feed is X and Reddit now); a batch can still
be made from the shell:

       docker compose exec worker python -m dreamfeed generate --now --images 12 --keep 6
       docker compose exec worker python -m dreamfeed generate --now --images 8 --keep 3 --persona some_handle

The worker only holds the GPU while it is working: each batch runs in a child process that
exits when done, so the miner resumes in between. SDXL in ComfyUI needs about 8-10 GB of
the 12 GB; Wan 2.2 needs a fresh ComfyUI per clip.

Memory: ComfyUI is capped at `COMFY_MEM_LIMIT` and the worker at `WORKER_MEM_LIMIT`, and
ComfyUI is killed outright if the whole server drops below `COMFY_HOST_MIN_FREE_GB` free (a
video job once pushed the server into swap and froze it). Keep `COMFY_MEM_LIMIT` a few GB
under what `free -g` shows available with ComfyUI stopped. For clips ComfyUI runs with
`--cache-none`, which frees the text encoder and the first half of Wan before the second loads:
about 10 GB of RAM instead of 17+.

## Clips

`VIDEOS_PER_NIGHT` clips are made after each night's images (from your likes first, then the
night's best), and the Dashboard can animate posts on request. Each is a ~5-second Wan 2.2
image-to-video clip:

- **The act.** The picture's tags decide whether it shows a sex act (cowgirl, missionary,
  doggy, blowjob, double blowjob; `worker/dreamfeed/motion.py`). Those clips use a motion
  LoRA trained for these acts (`VIDEO_ACT_LORA_HIGH` / `_LOW`, made for DR34ML4Y v2 from
  Civitai) with the act's trigger word; Wan alone barely knows them. Other clips go without.
- **The motion.** The caption model writes a plain-sentence description of what moves and
  how, from the picture's tags (Wan follows sentences, not booru tags). It is checked like
  a caption; without a text model, a fixed description of the act is used.
- **Sampling.** Three stages: the high-noise half of Wan alone at real CFG for the first
  steps, where the motion is decided, then both halves with the 4-step lightx2v LoRA for
  speed. lightx2v on every step makes clips fast but nearly still. About 5 minutes a clip
  (it was 2.5); in a test, the same picture moved about ten times as much.

- **Smoothing.** Once a clip passes its checks, a frame is made between each two (RIFE 4.25,
  `smooth.py`; optical flow, not a cross-fade), so it plays at 32 fps instead of Wan's 16.
  Scenes are smoothed shot by shot, and comic panel loops too (the wrap included), at 24 fps.
  If smoothing fails, the clip is kept as drawn.

Every clip is checked on at least 8 frames, like images, before it reaches the feed.

From a post with two characters, the viewer's Animate can also make a **scene** of about 40
seconds (`worker/dreamfeed/scene.py`), cut together the way animators do it: a few looping shots,
each a new drawing, building to a climax. Wan makes ~5 seconds at a time and drifts when clips are
chained, so each shot is its own clip:

1. Plan: opening (missionary or blowjob), a position, the same from the side, another position,
   the climax in it, aftermath. The post gives the cast and setting (its tags minus act, position
   and cum); the partner is a faceless male with one look for the whole scene, or, when the post's partner
   is a furry (`furry male` in its prompt), that one. Cum is kept out of
   every shot before the climax.
2. Draw: one picture per shot with the persona's own model and style LoRA, checked like posts; of
   3 candidates, the one showing the intended act and looking most like the post wins. Comic-panel
   layouts are rejected, and the top and bottom 4% are cropped (style LoRAs learn signatures).
3. Animate: each picture becomes a 5-second clip that ends on its own first frame (Wan's
   first-and-last-frame mode), a seamless loop played twice, then a hard cut. The climax stacks the
   position's motion LoRA with a climax LoRA and plays once. Every clip is checked; one that fails
   3 times is left out.

About 30 minutes a scene (4-second shots, each played twice). To judge a plan before any video: `python -m dreamfeed scene-preview
POST_ID` draws the shots and a contact sheet, `scene-render POST_ID [--shots 4,5]` animates them.

Acts can have their own motion LoRA (`motion.ACTS` / `motion.CLIMAXES`, files
`models/loras/NAME-high/-low.safetensors`): reverse cowgirl, and the climaxes creampie, facial
and cumshot, all from Civitai.

## Style LoRAs

A persona can post in a trained artist style. On the Dashboard, **Trained styles** → **Train
a new style**: give it a name, the medium, and the artist's page (an X media page such as
`https://x.com/artist/media`, or any site gallery-dl reads; x.com needs `X_COOKIES_FILE`).
The worker downloads up to the chosen number of images into `data/lora/NAME/raw/`, checks
them, and the `trainer` service trains `models/loras/style-NAME.safetensors` (about half an
hour for 300 images at the normal length). Nightly posts wait while it trains. **Retrain**
fetches the artist's newer images and trains again; **Stop** cancels at any step. The style
then appears in the persona editor for personas of the same medium. The artist's post texts
are saved too, for personas whose captions should sound like them (see Captions).

**From videos** is for artists who only post animations: their videos are downloaded instead,
and 8 frames spread over each become the pictures. A character LoRA can then be made from them
like from any style (`character-prep`).

The checks before training drop photographs (styles learn drawings, never real people), then
anything the strict adult checks, the feral filter or the blocked tags flag, and near-identical
copies (the same picture from two sites, or two frames of one shot); dropped files are deleted
and not downloaded again. A style needs at least 20 images that pass. Signatures are found per
picture: the tagger looks at each corner on its own, and a top or bottom strip with a signature,
watermark or artist name in it is cut off before the checks (a LoRA learns to draw them
otherwise). An artist who always signs in the same strip: `"crop_top": 0.06` (a share of the
height) in `data/lora/NAME/source.json` cuts it off every picture first.

By hand: put images in `data/lora/NAME/raw/`, then

       docker compose exec worker python -m dreamfeed lora-prep NAME --medium furry --trigger namestyle
       docker compose run --rm trainer NAME BASE_CHECKPOINT

### Video LoRAs

A style can also have a video LoRA, trained on the artist's own animations, so clips of
personas in that style move the way the artist animates. Wan 2.2 has two halves, so it's two
files: `models/loras/video-NAME-high.safetensors` (motion) and `-low` (detail), about 300 MB
each. Clips use them automatically, with the trigger word `NAMEanim` (underscores removed)
at `VIDEO_STYLE_LORA_STRENGTH`, on top of the sex-act LoRA when the picture has one.

Training needs the full-precision Wan 2.2 I2V weights (about 69 GB, read once per run, so a
slow disk is fine) in `VIDEO_TRAIN_MODELS`:

    wan2.2_i2v_high_noise_14B_fp16.safetensors, wan2.2_i2v_low_noise_14B_fp16.safetensors
        from Comfy-Org/Wan_2.2_ComfyUI_Repackaged (split_files/diffusion_models)
    umt5-xxl-enc-bf16.pth (models_t5_umt5-xxl-enc-bf16.pth) and wan2.1_vae.pth (Wan2.1_VAE.pth)
        from Wan-AI/Wan2.1-I2V-14B-720P

Then, on the dashboard, open a trained style's **Video LoRA** row and pick **Train video**
(how many videos to download, and how long to train). It uses the style's source page and
medium, and shows progress through both halves; **Stop** cancels it. One video LoRA trains at
a time, and not while that style's own training runs. By hand, the same steps are:

    docker compose exec worker python -m dreamfeed video-prep NAME
    docker compose run --rm video-trainer NAME both

`video-prep` downloads the artist's videos into `data/lora/NAME/video_raw/`, checks at least
16 frames of each with the same checks as style images (one flagged frame drops the whole
clip, and it's deleted), then converts the rest to 16 fps with a written motion caption.
Training takes about 3 hours per half at the default 1500 steps on a 12 GB GPU, and holds
nightly posts while it runs. It needs about 16 GB of RAM while loading, 13 GB after; `VIDEO_TRAIN_MEM_LIMIT` caps it
with no swap, so if it doesn't fit only the trainer is stopped.

## Safety rules (built into the worker, not optional settings)

- **Style and video LoRAs only learn drawings, never real people.** Training images and
  clips that look like photographs are dropped, and every other one goes through the checks below at the strict
  threshold first; flagged images are deleted.
- **Adults only, in every medium.** Every prompt includes an explicit adult descriptor in
  that medium's style (e.g. `mature female, adult` for anime, `adult, anthro` for
  furry), and every negative prompt includes a fixed per-medium list of youth terms.
  Booru and e621 tags that mean a minor (`loli`, `shota`, `cub`, `child`, `young`,
  `aged_down` and their variants) are never used in prompts: a persona using one is
  refused. A generated image carrying any of them is dropped and deleted.
- **Real-life age estimates.** Any real-life image goes through MiVOLO v2, a dedicated
  age estimator, in the `agecheck` service. If any clearly visible face (at least
  `MIN_FACE_PX`) is estimated under `PHOTO_MIN_AGE` (default 21, never below 18), it is
  dropped. Drawings use the CLIP check (`AGE_THRESHOLD`).
- **Stricter for characters models draw young.** Personas whose look reads as a feminine
  man, androgynous, trans or tomboy are marked strict automatically (a file can turn it on,
  never off). Their prompts get extra adult terms and youth negatives, and their images
  and clips are dropped at a lower youth score (`STRICT_AGE_THRESHOLD`). `otoko no ko`
  and its aliases are never used in prompts.
- **No feral content.** Personas are human or anthro; no sexual content with animals.
- **Output check.** Each generated image is tagged again before ranking. Anything with
  youth-related tags is deleted and never reaches the feed. Anime and furry get the
  strictest threshold, since youthful-looking output is most common there.
- **No named characters or people.** Name and character tags are discarded, and prompts
  never contain names. For anime and furry this also keeps out canonically underage
  characters. Written captions are checked for names the same way, and for ages, school
  and young-sounding words.

## Folder layout

```
dreamfeed/
  docker-compose.yml  .env  .env.example  README.md
  worker/    Dockerfile + personas, checks, ComfyUI client, ranker, caption writer, lora-prep
  trainer/   Dockerfile + kohya sd-scripts style-LoRA training, and a watcher for dashboard requests
  comfyui/   Dockerfile pinning a ComfyUI release; workflow JSON the worker fills in
  web/       Dockerfile + small Python app using formlogin
  models/    checkpoints/, loras/, tagger/, clip/  (downloads and trained styles, ~20 GB)
  data/      feed.db                               (posts, embeddings, likes; small)
             personas.json                         (private persona definitions)
             drafts/                               (personas drafted from a description)
             lora/NAME/                            (style training images, captions, the artist's
                                                    post texts (voice.json), progress; mounted
                                                    from LORA_DATA_DIR, which can be a slower disk)
             generated/                            (tonight's output and the feed; follow/:
                                                    the Following page's thumbnails)
             liked/                                (images you liked, copied out)
  state/     login.json, session.key
  logs/
```

## Comics

The **Comics** tab makes comics about two characters: two personas (each with a trained
character style), or a persona and her partner. Give it a story in a few sentences and a page
count (1 to 4, 4 panels a page). The worker (`worker/dreamfeed/comic.py`, also
`python -m dreamfeed comic A B --story "..."`) draws a clean picture of the two of them first,
plans the panels (build-up, then acts, cuddling at the end), has the text model write each page's
lines in their voices from the story, draws all panels like a scene's shots (one cast, one room,
the same checks), and letters them: speech bubbles are drawn by the code where nobody is, with
the tail toward the speaker (the image model can't write). About 6 minutes a page. Stories and
lines are checked like captions, and must be consensual (`safety.story_blocked`). Comics stay
until deleted; they aren't in the feed and don't expire.

**Importing** a comic (the same tab; `comicimport.py`): paste the gallery's link (anything
gallery-dl reads, and multporn comics) and say whether it's furry or anime. Every page gets the
strict adults-only checks; failing pages are dropped, and if more than a fifth fail nothing is
imported. Pages are kept as drawn, to read and animate panels of. (Colouring black-and-white
comics from their cover was tried and taken out: it wasn't good enough.)

**Find a comic** (the same tab) searches multporn or e621 (its pools of the "series" kind) and
lists their comics with covers (the covers come through dreamfeed; an e621 pool whose cover has
a tag dreamfeed never allows is left out); **Import** queues one like a pasted link. A search
with words the dashboard never takes is refused, and results whose title Import would refuse
are left out; the pages get the same checks either way.

**New pages.** Once a day the worker looks at every imported comic's source again (a
`comic_update` job, "New comic pages" on Recent runs): the source's pages are listed without
downloading, and only the ones it hasn't listed before are downloaded, checked like an
import's (one by one: a few failing doesn't stop the rest) and added at the end, with their
panels and outlines. The comic shows "N new pages" for 3 days. **Check for new pages** in the
reader's grid does it for one comic now. Comics imported before this have their pages' names to
go by (a page the checks dropped back then is looked at once more, and dropped again).

**Reading.** A comic opens a page at a time, fitted to the screen: swipe (or the arrows, or the
arrow keys) between pages. **Grid** shows every page small (thumbnails made when the comic is
saved) to jump to one; the comic's delete button is there too. A comic's card in the list has
**Rename** and **Delete**.

**Animated panels.** In the reader, **Animate a panel** shows each page's panels (found when the
comic is saved: cut along the gutters, white, black or coloured; drag a box for panels that
overlap or touch).
Pick one, optionally say what moves, and a job (`comic_animate`, `comicanim.py`) cuts the panel
out and has Wan 2.2 animate it for about four seconds (as asked, or by the act's motion LoRA;
a sex panel with no position thrusts), then cuts it to a cycle within the clip, blended at the
seam, played at 12 fps. The clip gets the video checks (stricter ones for imported comics) and
plays over its panel in the reader, looping; **Remove animation** takes it off again.
Panels can be queued one after another without leaving the picker (queued ones show as such).
Speech bubbles and text never move: `lettering.py` finds them (ogkalu's comic text and bubble
detector, Apache 2.0, on the CPU; each bubble traced to its shape from its box) and the clip
shows the drawing there. The outlines say what moves (one loop per character, reaching past the
panel for a character breaking out of it): only that moves, the rest is the drawing itself.
When a panel is picked, the characters found in it (BiRefNet, less the lettering, worked out
when the comic is saved) are outlined to start with; **Undo**, **Clear**, **Draw around them**
and **Outline the characters** change that. The reader masks the clip to what moves (a PNG
beside it). Works on comics made here and imported ones. `python -m dreamfeed comic-panels`
finds the panels (and makes the thumbnails) of comics saved before they were kept;
`comic-panels --outlines [--cpu]` outlines their characters (`--cpu`: slower, leaves the GPU alone);
`comic-panels --smooth [--cpu]` smooths clips made before smoothing (as new files).

## Following

Who you follow elsewhere, in one place: the **Feed** has posts from your X Following timeline,
the subreddits you're subscribed to and your e621 searches, and **Live** the Chaturbate rooms
you follow.

### Feed: X, Reddit and e621

The Feed is read live: when you open it (or tap More), the web app asks the sites for their
newest posts and shows them; their pictures and videos load straight from the sites' own
servers (no referrer is sent). Nothing of them is downloaded or kept, and the pictures aren't
looked at by the checks. A page is reused for 2 minutes (switching tabs, coming back). What's
still left out, by the rules alone: e621 posts with a tag dreamfeed never allows (e621 hosts
those on purpose, so its own moderation doesn't remove them), subreddits whose names have words
dreamfeed never takes (young, feral and the like) and posts whose text does. Real people's
posts never go to training, styles, comics or generation. Open on X/Reddit goes to the post.

- **X:** with your cookies (`X_COOKIES_FILE`, the same export styles use), through gallery-dl's
  metadata (`-j`: what a post is and where its files are, nothing downloaded), 30 media files
  a page.
- **Reddit:** through Reddit's API, signed in as you (below): your subscriptions and the
  Dashboard's **Reddit** panel (`r/name`, `u/name`, kept in `data/following.json`) as one
  listing, newest first; pictures, galleries (up to 20 pictures), Reddit's own videos (HLS,
  with sound: Safari plays it itself, other browsers through hls.js) and redgifs clips (asked
  of redgifs' API). Text-only posts are left out.
- **e621:** the Dashboard's **e621** panel's tag searches (an artist, a character,
  `wolf solo`), newest first. A search with one of the never-allowed tags is refused, and every
  search asks e621 to leave them out too (`e621.NEVER`: the youth tags such as `young` and
  `cub`, `feral`, `bestiality`). `E621_USERNAME` (optional) names you in the user agent.

The Feed has two parts, each with All, X, Reddit (and e621) to pick from (what you save goes to
the **Saved** tab, below):
- **Following:** your X Following timeline, your subreddits and Reddit people, e621, newest
  first.
- **For you:** the sites' own picks: X's For you timeline and your Reddit front page (Best), in
  each site's own order, taken in turns; never mixed into Following. Above it, people you might
  like: X accounts you don't follow, from your rooms' bios, mentions by people you follow and
  X's For you (from the last 30 days of your timelines, `x_seen`).
- **Saved** (its own tab, with the persona posts you liked, newest first): what you tapped Save
  on, kept: the follow service downloads its pictures and
  videos in full quality (X's original pictures and biggest video, e621's original or its
  full-size MP4, Reddit's own videos with sound through ffmpeg, redgifs' HD) into
  `data/saved/<site>/<post>/`, which is backed up like `liked/`. Saved shows those copies once
  they're in (the post says "keeping a full-quality copy…" until then), so a post deleted on
  the site stays. Unsaving deletes them. A Reddit post is saved on Reddit too, as you, at once.
  An X post is kept in dreamfeed only: bookmarking on X would mean faking X's own web client,
  so use Open on X for that.
  **Bring in what you saved on X and Reddit** (at the top of Saved) adds your X bookmarks and
  your Reddit saved posts (the last 1000 Reddit keeps) with pictures or videos, kept the same
  way; the same word rules leave some out, and ones you unsaved here stay out. Run it again any
  time for new ones. Reddit's saved list needs the sign-in's `history` permission (signed in
  before it was added: sign in again, below). Unsaving an imported X post doesn't remove the
  bookmark on X.

**Browse now (Reddit).** With Reddit picked, type a subreddit (or tap one on a post) to see it
as it is now: Hot, New or the day's Top, 25 posts a page, More for the next.

**Watching the Feed.** Videos play (muted) while they're on screen and pause when you scroll
past. A post with several pictures or videos swipes sideways (2 / 7 in the corner). Opened, a
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

**Signing in to Reddit.** Make your own app, a "personal use script" at reddit.com/prefs/apps,
with the redirect uri `http://localhost:6414/`; its id and secret go in `REDDIT_CLIENT_ID` and
`REDDIT_CLIENT_SECRET` (and your username in `REDDIT_USERNAME`, for its user agent). Run
`docker compose exec follow python -m dreamfeed follow reddit-login`, open the address it prints
and allow it, then run the same with the address your browser lands on (it won't load) in quotes
after it. The token it prints goes in `REDDIT_REFRESH_TOKEN` (your password is never stored;
revoke it under Reddit's authorized apps), and `docker compose up -d web`. Without it, Reddit is
left out of the Feed.

### Live: Chaturbate

The rooms you follow: who's live now, with their thumbnail, title and viewers, and the rest
with when they were last live and the hours they're usually live (from 3 days of streams on, in
your own time). Tapping a live room plays it in dreamfeed's own player: the room's video
straight from Chaturbate's video servers (HLS: Safari plays it itself, other browsers through
hls.js, served from `web/vendor/`), muted until you tap for sound, with ‹ › to go through the
live rooms. A private or hidden show says so. Open on Chaturbate goes to the room itself, to
chat or tip as you. The header shows how many are live.

The `follow` service (the worker's image, CPU only) looks every 2 minutes, signed in with your
cookies (`CHATURBATE_COOKIES_FILE`: export them from your browser as a Netscape cookies.txt and
copy them over that file; it's read on each look). Follows and unfollows there show up here
within the hour. If the cookies run out, the page says so.

These are real people, so nothing from here goes into training, styles, comics or generation,
and nothing of a stream is kept: only who you follow, when they were live and each one's last
thumbnail (`data/generated/follow/`). A room Chaturbate doesn't list as age verified is left
out.

**Your recorder, from here.** With `STREAMONITOR_URL` set (streamonitor's web address as the web
service reaches it, e.g. `http://streamonitor:5000` on a Docker network they share; and
`STREAMONITOR_PASSWORD` if it has one), Live shows what it does for each room you follow: ● REC
on a live room it's recording, "Records when they go live", "Recording paused". Record on a live
card (or a profile) adds the room to its list or starts it again; Pause stops it but keeps it
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
linked again). **Their accounts, found across sites** (`linking.py`, run by the web app: it has the Reddit and
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
newest first, played in xvideos' own player inside dreamfeed (nothing is downloaded). Tapping a poster's name in the Feed opens their profile too, the room's if
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
the player, ✕ drops one (the others keep playing), + Add brings in another live room (yours, then
Discover's) up to 4. A tile whose stream stops tries again 10 seconds later. In the player,
+ Several starts this with the room you're watching; Follow follows a room you don't yet, and the
title under the video stays current while you watch.

## Backup

- **Backed up:** `data/feed.db` (picked up automatically as SQLite), `data/personas.json`,
  `data/liked/`, `state/`, `.env`, and the source folders.
- **Kept from `models/`:** only the LoRAs trained here (`models/loras/style-*`, `video-*`):
  they take hours of GPU time to make again.
- **Excluded:** the rest of `models/`, `data/generated/` and `logs/`. Motion LoRAs from
  Civitai are listed in `models.json` with their hashes; `python3 fetch-models.py`
  downloads any that are missing (`--check` only lists them; needs `CIVITAI_API_KEY`).
  `LORA_DATA_DIR`'s pictures aren't kept (they download again), but each source's small
  files are: settings (`source.json`), what was kept, voices (`voice.json`) and download
  archives.

## Addresses

Each part of the page has its own address, so links, bookmarks and the Back button work. Opening
one replaces what's on screen (nothing stacks); Close and Back go to the page before, or home when
you came by link:

- tabs: `/feed` (`/feed/foryou`), `/saved` (`/saved/x`, `/saved/reddit` ...), `/live`
  (`/live/discover`), `/comics` (`/comics/ID`: a comic), `/dashboard`; `/` opens the tab you used last
- personas: `/personas` (everyone's posts), `/p/HANDLE`, `/item/ID` (one post, in the viewer)
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
