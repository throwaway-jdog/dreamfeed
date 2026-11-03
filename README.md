# dreamfeed

A private feed of generated images that learns your taste from your X bookmarks and from
your likes and skips. It learns *what kind of content* you like (tags), never *who* is in
it: no bookmarked image is ever shown to the generator or used for training.

Status: **sync**, **tagging**, **age checks** and **nightly generation** work. The feed page
(`web/`) is not built yet; until then the night's picks are in `data/generated/<night>/`.

Chosen models (in `.env`): LUSTIFY V9 for photo, WAI-Illustrious v17 for anime,
FurryVision XL v2 for furry. Civitai downloads that need an account use `CIVITAI_API_KEY`.

## Getting started (tagging only, for now)

1. Export your X cookies from a logged-in browser as a Netscape `cookies.txt` file, e.g.
   with the "Get cookies.txt LOCALLY" extension. Save it outside this folder, readable by
   your user, and set `X_COOKIES_FILE` to its path.
2. `cp .env.example .env` and fill in `PUID`, `PGID`, `TZ`, `X_COOKIES_FILE`, `AGECHECK_THREADS`.
3. `docker compose up -d --build sync agecheck comfyui worker`
4. Follow along: `docker compose logs -f sync worker`. The first sync fetches every
   bookmark, and each file is tagged and deleted within a minute or so of arriving.
5. Look at the result:

       docker compose exec worker python -m dreamfeed report            # mediums, top tags
       docker compose exec worker python -m dreamfeed report --dropped  # what was dropped and why

   Thresholds (`TAG_THRESHOLD`, `YOUTH_TAG_THRESHOLD`, `AGE_THRESHOLD`, `PHOTO_MIN_AGE`,
   `MIN_FACE_PX`, `FURRY_THRESHOLD`) can be set in the worker's environment. Defaults are in
   `worker/dreamfeed/config.py`. The age check errs toward dropping, so a few adult
   bookmarks being dropped is expected.

Generation runs on its own every night inside `GENERATE_WINDOW`. To try it now:

       docker compose exec worker python -m dreamfeed generate --now --images 12 --keep 6

The worker only holds the GPU while it is tagging or generating: each batch runs in a child process
that exits when done, so the miner resumes in between.

## How it works

1. **sync** pulls new bookmarks with gallery-dl (cookies from `X_COOKIES_FILE`).
2. **worker, tag phase** (any time, low VRAM):
   - Sorts each bookmark into a **medium**: `photo`, `anime` or `furry`. This uses CLIP
     zero-shot, with the tagger's furry/anthro tags as a tiebreaker.
   - Tags it with the WD v3 tagger and keeps only its *general* tags (setting, lighting,
     framing, body type, clothing, acts). Character/name tags are discarded.
   - Computes a CLIP embedding for ranking.
   - Deletes the downloaded file. Only medium, tags and embedding stay, in `data/feed.db`.
3. **worker, generate phase** (inside `GENERATE_WINDOW`):
   - Splits `IMAGES_PER_NIGHT` between mediums in proportion to your bookmarks and likes.
     Each medium always gets a small minimum share, so a medium can come back.
   - Builds prompts per medium from that medium's own tag weights, in the prompt style its
     model expects: plain descriptions for photo, booru tags for anime and furry.
   - Has ComfyUI generate one medium at a time with that medium's checkpoint, so only one
     model is loaded.
4. **worker, rank phase**: scores each image against the taste model *for its medium*
   and keeps the top `FEED_KEEP_TOP` overall. The rest are deleted.
5. **web** shows the feed, filterable by medium. Like/skip updates that medium's tag
   weights and taste model, and the medium split for the next night.

## Models (one SDXL checkpoint per medium, ~7 GB each)

| Medium | Kind of model | Prompt style |
|---|---|---|
| photo | photoreal SDXL fine-tune | natural-language description |
| anime | Illustrious- or Pony-based SDXL | booru tags |
| furry | Pony- or furry-trained SDXL | e621-style tags |

A medium whose `CHECKPOINT_*` is empty is skipped. Its bookmarks are still tagged, so
turning it on later starts with a full profile.

GPU: SDXL in ComfyUI needs about 8-10 GB of the 12 GB, so the worker runs phases one at a
time and tells ComfyUI to unload models before tagging. Jellyfin transcodes (~0.4 GB each)
fit alongside. The miner's gpu-yield pauses mining automatically.

## Safety rules (built into the worker, not optional settings)

- **Bookmarks never reach the generator.** No img2img, IP-Adapter, face swap, or LoRA
  training on bookmark media. Bookmarks only contribute tag counts and an embedding.
- **Adults only, in every medium.** Every prompt includes an explicit adult descriptor in
  that medium's style (e.g. `mature female, adult` for anime, `adult, anthro` for
  furry), and every negative prompt includes a fixed per-medium list of youth terms.
  Booru and e621 tags that mean a minor (`loli`, `shota`, `cub`, `child`, `young`,
  `aged_down` and their variants) are never used in prompts. A bookmark carrying any of
  them is dropped and deleted.
- **Real-life age estimates.** Real-life bookmarks go through MiVOLO v2, a dedicated age
  estimator, in the `agecheck` service. If any clearly visible face (at least
  `MIN_FACE_PX`) is estimated under `PHOTO_MIN_AGE` (default 21, never below 18), the
  bookmark is dropped. Body-only estimates are ignored as too unreliable. Photos with
  no clear face fall back to the CLIP check (`AGE_THRESHOLD`), as drawings do.
- **Output check.** Each generated image is tagged again before ranking. Anything with
  youth-related tags is deleted and never reaches the feed. Anime and furry get the
  strictest threshold, since youthful-looking output is most common there.
- **No named characters or people.** Name and character tags are discarded, and prompts
  never contain names. For anime and furry this also keeps out canonically underage
  characters.

## Folder layout

```
dreamfeed/
  docker-compose.yml  .env  .env.example  README.md
  sync/      Dockerfile + loop around gallery-dl
  worker/    Dockerfile + tagger, CLIP, prompt builder, ComfyUI client, ranker
  comfyui/   Dockerfile pinning a ComfyUI release; workflow JSON the worker fills in
  web/       Dockerfile + small Python app using formlogin
  models/    checkpoints/, tagger/, clip/          (downloads, ~15 GB)
  data/      feed.db                               (tags, embeddings, likes; small)
             bookmarks/                            (transient downloads)
             generated/                            (tonight's output and the feed)
             liked/                                (images you liked, copied out)
  state/     login.json, session.key
  logs/
```

## Backup

- **Backed up:** `data/feed.db` (picked up automatically as SQLite), `data/liked/`,
  `state/`, `.env`, and the source folders.
- **Excluded** in `backup/excludes.txt`: `models/` (re-downloadable),
  `data/bookmarks/`, `data/generated/`, and `logs/`.
- **Restore note:** the cookies file lives at `X_COOKIES_FILE`. If it's outside
  ~/docker, re-export it from the browser after a restore.

## Caddy

Add to the `<your domain>` block:

```
handle /dreamfeed* {
	import lan_only
	reverse_proxy dreamfeed-web:8000
}
```
