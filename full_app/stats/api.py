"""Integrator-registered JSON blueprint with injected visibility and identity."""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from .aggregate import aggregate_players, identity, normalize_jobs, play_order, timestamp, week_start
from .store import VoteConflict


def create_blueprint(store, get_jobs, get_user, *, group_id="friends", clock=None):
    """Callbacks run in request context. get_jobs MUST enforce group visibility.

    get_user returns a trusted authenticated member ID, or None. Never derive it
    from a client-supplied vote body. Use one group namespace per mounted board.
    """
    if not identity(group_id):
        raise ValueError("group_id must be nonempty")
    now = clock or (lambda: datetime.now(timezone.utc))
    bp = Blueprint("player_stats", __name__, url_prefix="/api/stats")

    @bp.before_request
    def authenticate():
        if not identity(get_user()):
            return jsonify(error="authenticated group membership required"), 401

    @bp.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(error=str(exc)), 409 if isinstance(exc, VoteConflict) else 400

    @bp.errorhandler(BadRequest)
    @bp.errorhandler(UnsupportedMediaType)
    def invalid_json(exc):
        return jsonify(error="request body must be a JSON object"), 400

    def selected_week():
        value = request.args.get("week")
        if value is None:
            return week_start(now())
        if len(value) != 10 or week_start(value) != value:
            raise ValueError("week must be a UTC Monday date (YYYY-MM-DD)")
        return value

    def nominations(jobs, week):
        return [p for j in normalize_jobs(jobs) if j["week"] == week for p in j["plays"]]

    @bp.get("/players")
    def players():
        week = selected_week() if "week" in request.args else None
        return jsonify(players=aggregate_players(get_jobs(), week))

    @bp.get("/players/<player_id>")
    def player(player_id):
        week = selected_week() if "week" in request.args else None
        found = next((p for p in aggregate_players(get_jobs(), week) if p["player_id"] == player_id), None)
        return (jsonify(found), 200) if found else (jsonify(error="player not found"), 404)

    @bp.get("/clip-of-the-week")
    def leaderboard():
        week = selected_week()
        counts = store.counts(group_id, week)
        clips = [{**p, "votes": counts.get(p["clip_id"], 0)} for p in nominations(get_jobs(), week)]
        clips.sort(key=lambda p: (-p["votes"], *play_order(p)))
        # Without any votes there is a ranked nomination list, not a winner.
        return jsonify(week=week, clips=clips, winner=clips[0] if clips and clips[0]["votes"] else None)

    @bp.post("/clip-of-the-week/vote")
    def vote():
        data = request.get_json()
        if not isinstance(data, dict) or set(data) != {"clip_id"} or not identity(data.get("clip_id")):
            raise ValueError("body must contain only a nonempty clip_id")
        instant = timestamp(now())
        week = week_start(instant)
        if request.args:
            raise ValueError("votes accept no query parameters; only the current UTC week is open")
        clips = nominations(get_jobs(), week)
        if not any(p["clip_id"] == data["clip_id"] for p in clips):
            return jsonify(error="clip not found in the current week's nominations"), 404
        created = store.vote(group_id, week, identity(get_user()), data["clip_id"], instant.isoformat())
        return jsonify(week=week, clip_id=data["clip_id"], created=created), 201 if created else 200

    return bp
