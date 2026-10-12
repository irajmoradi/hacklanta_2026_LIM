"""Blueprint with expiry-protected media and same-origin anonymous reactions."""
import json

from flask import Blueprint, abort, jsonify, render_template, request, send_file, url_for

from .store import EMOJIS


def create_blueprint(store):
    bp = Blueprint("sharepage", __name__, template_folder="templates",
                   static_folder="static", static_url_path="/s/assets")

    def active(share_id):
        share = store.get(share_id)
        if share is None:
            abort(404)
        return share

    @bp.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; media-src 'self'; connect-src 'self'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
        )
        return response

    @bp.get("/s/<share_id>")
    def page(share_id):
        share = active(share_id)
        return render_template("sharepage/page.html", share=share,
                               counts=store.counts(share_id), emojis=EMOJIS,
                               canonical=url_for("sharepage.page", share_id=share_id, _external=True),
                               video_url=url_for("sharepage.video", share_id=share_id, _external=True),
                               poster_url=url_for("sharepage.poster", share_id=share_id, _external=True),
                               reaction_url=url_for("sharepage.reactions", share_id=share_id))

    def media(share_id, key):
        share = active(share_id)
        try:
            return send_file(share[key], conditional=True)
        except FileNotFoundError:
            abort(404)

    @bp.get("/s/<share_id>/video")
    def video(share_id):
        return media(share_id, "video_path")

    @bp.get("/s/<share_id>/poster")
    def poster(share_id):
        return media(share_id, "poster_path")

    @bp.post("/s/<share_id>/reactions")
    def reactions(share_id):
        active(share_id)
        # Custom header + JSON prevents cross-origin HTML forms from submitting.
        # Do not enable CORS on this endpoint in the host application.
        if (request.headers.get("X-Sharepage-Reaction") != "1" or
                request.headers.get("Sec-Fetch-Site") == "cross-site" or
                request.headers.get("Origin", request.host_url.rstrip("/")) != request.host_url.rstrip("/")):
            abort(403)
        if request.content_length is not None and request.content_length > 1024:
            abort(413)
        # Bound even chunked bodies; avoid the Flask 3.1-only per-request limit
        # setter so this blueprint also supports the project's Flask 3.0 floor.
        raw = request.stream.read(1025)
        if len(raw) > 1024:
            abort(413)
        try:
            data = json.loads(raw) if request.is_json else None
        except (ValueError, UnicodeDecodeError):
            data = None
        if not isinstance(data, dict) or data.get("emoji") not in EMOJIS:
            return jsonify(error="Choose a supported emoji"), 400
        if not store.react(share_id, data["emoji"]):
            abort(404)
        return jsonify(counts=store.counts(share_id))

    return bp
