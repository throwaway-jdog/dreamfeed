# dreamfeed

A private, Twitter-style timeline of generated anime and furry posts from **fictional
personas**. Each persona has a name, a profile picture, a bio, a fixed look and a few
kinds of post, with captions. Every night they "post": the worker generates their images
(and some 5-second Wan 2.2 clips), checks them, keeps the best and spreads them over the
timeline. Likes make a persona post more, and more like what you liked; skips do the opposite.

The page is at `https://<your domain>/dreamfeed/` (behind formlogin, phone-first): the
timeline, a strip of personas at the top, a profile page per persona with **Post now**,
Liked, and a Dashboard.

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
  `"enabled": false` switches the style off and keeps its settings.
- `paused`: keeps the profile and posts but makes nothing new, except on **Post now**.
- `based_on`: a private note, never shown or used in prompts.
- `posts`: kinds of post, each with `weight`, `rating` (`explicit`, `questionable`,
  `general`), `prompt` and `captions`. Prompts may use `{outfit}`, `{cosplay}` (generic
  costumes only), `{setting}` and `{character}` (from `characters`, for artist personas
  who draw different people). The captions are examples of how the persona writes (below).
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

Generation runs every night inside `GENERATE_WINDOW`. The Dashboard can queue a run, animate
the best posts, edit personas and shows recent runs. From the shell:

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

Every clip is checked on at least 8 frames, like images, before it reaches the feed.

From a post with two characters, the viewer's Animate can also make a **scene** of about a
minute (`worker/dreamfeed/scene.py`), cut together the way animators do it: a few looping shots,
each a new drawing, building to a climax. Wan makes ~5 seconds at a time and drifts when clips are
chained, so each shot is its own clip:

1. Plan: opening (missionary or blowjob), a position, the same from the side, another position,
   the climax in it, aftermath. The post gives the cast and setting (its tags minus act, position
   and cum); the partner is a faceless male with one look for the whole scene. Cum is kept out of
   every shot before the climax.
2. Draw: one picture per shot with the persona's own model and style LoRA, checked like posts; of
   3 candidates, the one showing the intended act and looking most like the post wins. Comic-panel
   layouts are rejected, and the top and bottom 4% are cropped (style LoRAs learn signatures).
3. Animate: each picture becomes a 5-second clip that ends on its own first frame (Wan's
   first-and-last-frame mode), a seamless loop played twice, then a hard cut. The climax stacks the
   position's motion LoRA with a climax LoRA and plays once. Every clip is checked; one that fails
   3 times is left out.

About 35 minutes a scene. To judge a plan before any video: `python -m dreamfeed scene-preview
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

The checks before training drop photographs (styles learn drawings, never real people), then
anything the strict adult checks, the feral filter or the blocked tags flag; dropped files are
deleted and not downloaded again. A style needs at least 20 images that pass.

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
             generated/                            (tonight's output and the feed)
             liked/                                (images you liked, copied out)
  state/     login.json, session.key
  logs/
```

## Backup

- **Backed up:** `data/feed.db` (picked up automatically as SQLite), `data/personas.json`,
  `data/liked/`, `state/`, `.env`, and the source folders.
- **Excluded** in `backup/excludes.txt`: `models/` (re-downloadable; trained styles can be
  retrained from `data/lora/`), `data/generated/`, and `logs/`. `LORA_DATA_DIR` is
  only backed up if it's inside a backed-up folder; outside one, losing it means
  downloading a style's images again before retraining it, and its voice is rebuilt then.

## Caddy

In the public section of the `<your domain>` block (the app has its own sign-in):

```
redir /dreamfeed /dreamfeed/
handle_path /dreamfeed/* {
	reverse_proxy dreamfeed-web:8000
}
```

The Caddyfile is a single-file mount: after editing it, `docker restart caddy` (a reload
alone keeps reading the old file).

## Password

First visit shows a set-password page that needs the one-time setup code from
`docker logs dreamfeed-web`. Or: `docker compose exec web python -m formlogin passwd`.
