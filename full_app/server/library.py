"""Owner-scoped library adapters and explicit, expiring share-page creation."""
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import g, jsonify, request


def install(app, store, workspace, owned):
    from search import SearchIndex, SearchWindow, create_blueprint as search_blueprint
    from stats import VoteStore, create_blueprint as stats_blueprint
    from sharepage import ShareStore, create_blueprint as share_blueprint

    def jobs():
        return [{**j, 'player_id': g.owner} for j in store.all() if j.get('_owner', 'local') == g.owner]

    class Library:
        def search(self, *args, **kwargs):
            # A request snapshot cannot retain deleted jobs or leak another owner's rows.
            with tempfile.TemporaryDirectory(prefix='search-', dir=workspace) as directory:
                index = SearchIndex(Path(directory) / 'index.sqlite3')
                windows = []
                for job in jobs():
                    for i, clip in enumerate(job.get('clips') or []):
                        windows.append(SearchWindow(video_id=job['id'], window_id=str(clip.get('id', i)),
                            start=clip['start_seconds'], end=clip['end_seconds'], game=job.get('game', 'generic'),
                            recorded_at=datetime.fromtimestamp(job['created_at'], timezone.utc).isoformat(),
                            media_url=f"/api/stream/{job['id']}", caption=clip.get('caption', clip.get('description', '')),
                            labels=[clip.get('type', 'unknown')], ocr_events=clip.get('events', [])))
                index.index_windows(windows)
                return index.search(*args, **kwargs)

    votes = VoteStore(workspace / 'votes.sqlite3')

    class OwnerVotes:
        def vote(self, group, *args):
            return votes.vote(g.owner, *args)

        def counts(self, group, *args):
            return votes.counts(g.owner, *args)

    app.register_blueprint(search_blueprint(Library()))
    app.register_blueprint(stats_blueprint(OwnerVotes(), jobs, lambda: g.owner))
    shares = ShareStore(workspace / 'shares.sqlite3')
    app.register_blueprint(share_blueprint(shares))

    @app.post('/api/jobs/<job_id>/share-page')
    def share_page(job_id):
        job = owned(job_id)
        if job.get('status') != 'done' or not job.get('output'):
            return jsonify(error='Render the montage before sharing'), 409
        poster = Path(job['dir']) / 'share' / 'thumbnail_youtube.jpg'
        if not poster.is_file():
            return jsonify(error='Render with share_kit enabled before creating a link'), 409
        data = request.get_json() or {}
        dimensions = job.get('render_evidence', {}).get('output', job['meta'])
        share_id = shares.create(video_path=job['output'], poster_path=poster,
            width=dimensions['width'], height=dimensions['height'],
            title=data.get('title', 'Gameplay highlights'), description=data.get('description', ''),
            expires_at=time.time()+86400)
        return jsonify(url=f'/s/{share_id}', expires_in=86400), 201
