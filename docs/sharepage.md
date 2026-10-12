# Shareable montage page (EXT-25)

`full_app/sharepage` is an opt-in Flask blueprint. The integrator registers it;
this task does not modify the application factory or upload/render pipeline.
It needs only existing Flask/Python dependencies. No Gemini calls are used.

## Integration

From code running with `full_app` on the Python import path:

```python
from pathlib import Path
from time import time
from sharepage import ShareStore, create_blueprint

# After creating the Flask app, before serving requests:
store = ShareStore(Path(app.config['WORKSPACE']) / 'shares.sqlite3')
app.register_blueprint(create_blueprint(store))
app.extensions['share_store'] = store  # optional convenience for job completion

# After a successful render, in trusted server code:
share_id = store.create(
    video_path='/absolute/persistent/path/final_edit.mp4',
    poster_path='/absolute/persistent/path/thumbnail.jpg',
    title='Last-second clutch',
    description='Our best moments from tonight.',
    width=1080, height=1920,  # actual rendered dimensions; landscape also works
    chapters=[{'start': 0, 'title': 'Opening'}, {'start': 12.5, 'title': 'Clutch'}],
    expires_at=time() + 7 * 24 * 3600,  # omit for no expiry
)
# Share /s/<share_id> on the public HTTPS origin.
```

There is deliberately no anonymous HTTP creation API. Creation takes trusted
local file paths: MP4 video and JPEG/PNG/WebP poster. Generate the poster in the
render/export pipeline (the existing social thumbnail tools can supply one).
Files are referenced, not copied; retain them while the link is active. Do not
overwrite a published asset. Missing media returns 404. Chapters are sorted by
start seconds on the **rendered montage**, not source timestamps; the caller
must supply chapters within the rendered duration. Title/description/chapter
text is escaped in HTML. The responsive player preserves either orientation,
supports byte-range seeking, and uses `playsinline` on mobile. Native controls
and chapter media links work without JavaScript; reactions require JavaScript.

## Routes and persistence

- `GET /s/<share_id>`: public page with poster, player, chapters, reaction counts,
  canonical URL, Open Graph video/image tags and Twitter large-image card.
- `GET /s/<share_id>/video` and `/poster`: expiry-checked local media delivery.
- `POST /s/<share_id>/reactions`: JSON `{"emoji":"🔥"}` with
  `X-Sharepage-Reaction: 1`. Returns `{"counts": { ... }}` for 🔥 😂 👏 ❤️ 😮.
- `/s/assets/page.css` and `/s/assets/page.js`: small local frontend assets.

SQLite creates its schema automatically and commits each reaction atomically,
including concurrent requests and process restarts. Connections are short lived.
Keep the database on persistent local storage with its containing directory
writable. Back up the database and published media together. Anonymous reactions
are cumulative taps, **not unique-person votes**; repeated taps are allowed.
No cookies, account, secret signing key, or external scripts are needed.

## Deployment and limitations

IDs have 256 bits of cryptographic randomness. Possession of a link grants access;
do not include private footage you do not intend to share. Optional expiry is a
UTC Unix timestamp and applies to the page, media, and new reactions (404 at the
deadline). Responses use `Cache-Control: no-store`; expiry cannot retract files
already downloaded or third-party unfurl caches. Expired records and media are
not automatically deleted; retention/cleanup belongs to the host application.

Use a public HTTPS origin reachable by Discord/iMessage crawlers. Absolute card
URLs are built with Flask `url_for`; configure the trusted host and, if behind a
proxy, trusted forwarded host/scheme handling in the integrator. Never trust
arbitrary forwarded headers. Platforms decide whether/how to unfurl cards;
metadata does not guarantee autoplay or a fresh preview after an edit.

Do not enable cross-origin CORS for reaction routes. They reject foreign Origins,
cross-site fetches and requests without the custom header. The host should apply
rate limits if public traffic warrants it; anonymous counts are not abuse-proof.
Creation is only for trusted server code because it can publish local media.
This package does not register itself, create thumbnails, or extend job retention.

## Offline verification

From the worktree root:

```sh
tools/remote_run.sh "cd full_app && python -m pytest -q tests/test_sharepage.py"
```

Tests create a synthetic MP4 with ffmpeg and a poster with Pillow, and cover both
orientations, tags, assets/ranges, sorted chapter links, escaped metadata,
durability, concurrent increments, invalid input, and expiry on every route.
No paid API calls or downloaded media are involved. For a manual check after
registration, create a share with the Python API, open its link on desktop and
mobile, seek a chapter, tap an emoji, then reload to check the saved count.
