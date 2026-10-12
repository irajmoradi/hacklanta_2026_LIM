---
id: EXT-25
branch: ext/EXT-25
allowed_paths: [full_app/sharepage/**, full_app/tests/**, docs/sharepage.md]
---
# EXT-25: Shareable montage page
Build `full_app/sharepage/`: a Flask blueprint (registered by the integrator) serving `/s/<share_id>`: a fast, mobile-friendly page with the montage
player (vertical and landscape), poster thumbnail, title/description, chapters list (click to seek), friend emoji reactions stored in SQLite, and Open
Graph / Twitter card tags so links unfurl nicely in Discord/iMessage. Unguessable share ids, optional expiry, no auth needed to view. Tests: route renders,
OG tags present, reactions persist, expired links 404. Write docs/sharepage.md.
