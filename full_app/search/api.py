"""Read-only Flask adapter; the integrator explicitly registers this blueprint."""
from flask import Blueprint, jsonify, request


def create_blueprint(index):
    blueprint = Blueprint("clip_search", __name__)

    @blueprint.get("/api/search")
    def search():
        try:
            result = index.search(
                request.args.get("q", ""), game=request.args.get("game"),
                date_from=request.args.get("date_from"), date_to=request.args.get("date_to"),
                labels=request.args.getlist("label"),
                limit=int(request.args.get("limit", "20")), offset=int(request.args.get("offset", "0")))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(result)

    return blueprint
