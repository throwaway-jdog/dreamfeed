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

They live in `data/personas.json`, which is private (it describes whose posting styles
inspired them) and is not in git. Start from `personas.example.json`:

- `handle`, `name`, `bio`, `medium` (`anime` or `furry`), `look` (tags that keep the
  persona recognisable), `avatar` (extra tags for the profile picture), `emoji`,
  `hashtags`, `video_share` (how much of the nightly video budget favours them), `weight`,
  `negative` (extra negative prompt, e.g. `face, eyes` for a faceless persona), and `lora`
  (`{"file": "style-x.safetensors", "strength": 0.8, "trigger": "x_style"}`).
- `posts`: kinds of post, each with `weight`, `rating` (`explicit`, `questionable`,
  `general`), `prompt` and `captions`. Prompts may use `{outfit}`, `{cosplay}` (generic
  costumes only), `{setting}` and `{character}` (from `characters`, for artist personas
  who draw different people).

The file is re-read every run. A persona with no profile picture gets one on its next run.
Invalid entries or blocked tags stop the run with a clear error instead of being skipped.

## Running

1. Export your X cookies (Netscape `cookies.txt`) and set `X_COOKIES_FILE`; bookmarks are
   still synced into `BOOKMARK_COPY_DIR` and age-checked, but no longer steer generation.
2. `cp .env.example .env`, fill it in, and `cp personas.example.json data/personas.json`.
3. `docker compose up -d --build`

Generation runs every night inside `GENERATE_WINDOW`. The Dashboard can queue a run, animate
the best posts, scan bookmarks and shows recent runs. From the shell:

       docker compose exec worker python -m dreamfeed generate --now --images 12 --keep 6
       docker compose exec worker python -m dreamfeed generate --now --images 8 --keep 3 --persona some_handle

The worker only holds the GPU while it is working: each batch runs in a child process that
exits when done, so the miner resumes in between. SDXL in ComfyUI needs about 8-10 GB of
the 12 GB; Wan 2.2 needs a fresh ComfyUI per clip (capped by `COMFY_MEM_LIMIT`).

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
