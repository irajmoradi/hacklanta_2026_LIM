"""Opt-in upload scaffolding for EXT-14 share kits. No network on import."""
import json
from pathlib import Path
import re

from .common import PublishError, expect, json_body, request, upload_url
from .oauth import OAuth
from .tokens import TokenStore

__all__ = ["YouTube", "TikTok", "OAuth", "TokenStore", "PublishError"]


def _kit(directory, platform):
    root = Path(directory).resolve(strict=True)
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))

    def file(name):
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Share kit file must be inside its directory")
        return path

    video = file(metadata["video"])
    if not video.stat().st_size:
        raise ValueError("Video is empty")
    copy = metadata["platforms"][platform]
    title, description = copy["titles"][0], copy["description"]
    if not isinstance(title, str) or not title.strip() or not isinstance(description, str):
        raise ValueError("Invalid share kit copy")
    tags = copy.get("hashtags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError("Invalid hashtags")
    if platform == "shorts" and not any(t.lower() == "#shorts" for t in tags):
        tags = [*tags, "#Shorts"]
    missing = [tag for tag in tags if tag not in description]
    description = (description + "\n" + " ".join(missing)).strip()
    if len(title) > (100 if platform == "shorts" else 150) or len(description.encode()) > 5000:
        raise ValueError("Share kit copy exceeds upload limits")
    thumbnail = metadata.get("thumbnails", {}).get("vertical", {}).get("file")
    return video, dict(title=title, description=description, hashtags=tags,
                       thumbnail=str(file(thumbnail)) if thumbnail else None)


class _Adapter:
    def __init__(self, oauth=None, client=None):
        self.oauth, self.client = oauth, client

    def _authorization(self, confirmed):
        if confirmed is not True:
            raise PublishError("Actual upload requires confirm=True")
        if self.oauth is None or self.client is None:
            raise PublishError("Configure OAuth and an HTTP client for upload")
        return {"Authorization": "Bearer " + self.oauth.access_token()}


class YouTube(_Adapter):
    def _thumbnail(self, copy, video_id, auth):
        if not copy["thumbnail"]:
            return "not provided"
        try:
            thumbnail = Path(copy["thumbnail"])
            if thumbnail.stat().st_size > 50_000_000:
                return "manual: thumbnail exceeds API size limit"
            expect(request(self.client, "POST", "https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
                params={"videoId": video_id, "uploadType": "media"},
                headers={**auth, "Content-Type": "image/jpeg"}, content=thumbnail.read_bytes()), {200})
            return "uploaded"
        except (PublishError, OSError):
            # The video already exists: keep its ID so callers do not duplicate it.
            return "manual: thumbnail failed; video upload succeeded"

    def upload(self, kit, *, dry_run=True, confirm=False, privacy="private", chunk_size=8 * 1024 * 1024):
        if privacy not in ("private", "unlisted", "public"):
            raise ValueError("Invalid privacy status")
        if chunk_size <= 0 or chunk_size % (256 * 1024):
            raise ValueError("YouTube chunks must be multiples of 256 KiB")
        video, copy = _kit(kit, "shorts")
        result = dict(platform="youtube", dry_run=bool(dry_run), privacy=privacy, metadata=copy)
        if dry_run:
            return result
        auth = self._authorization(confirm)
        size = video.stat().st_size
        body = {"snippet": {"title": copy["title"], "description": copy["description"],
                            "tags": [t.lstrip("#") for t in copy["hashtags"]]},
                "status": {"privacyStatus": privacy}}
        response = expect(request(self.client, "POST",
            "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
            headers={**auth, "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
            json=body), {200, 201})
        url = upload_url(response.headers.get("Location"), "googleapis.com")
        offset, failures = 0, 0
        with video.open("rb") as stream:
            while offset < size:
                stream.seek(offset)
                chunk = stream.read(min(chunk_size, size - offset))
                try:
                    response = request(self.client, "PUT", url, headers={**auth,
                        "Content-Type": "video/mp4", "Content-Range": f"bytes {offset}-{offset + len(chunk) - 1}/{size}"}, content=chunk)
                except PublishError:
                    response = None
                if response is None or response.status_code in (429, 500, 502, 503, 504):
                    failures += 1
                    if failures > 3:
                        raise PublishError("Upload interrupted; retry budget exhausted; outcome may be unknown")
                    response = request(self.client, "PUT", url, headers={**auth,
                        "Content-Range": f"bytes */{size}"}, content=b"")
                expect(response, {200, 201, 308})
                if response.status_code in (200, 201):
                    video_id = json_body(response).get("id")
                    if not isinstance(video_id, str) or not video_id:
                        raise PublishError("Upload completed without a video ID; do not blindly retry")
                    return {**result, "video_id": video_id, "status": "uploaded",
                            "thumbnail_status": self._thumbnail(copy, video_id, auth)}
                match = re.fullmatch(r"bytes=0-(\d+)", response.headers.get("Range", ""))
                next_offset = int(match[1]) + 1 if match else 0
                if response.headers.get("Range") and not match:
                    raise PublishError("Invalid resumable upload range")
                if next_offset < offset or next_offset > offset + len(chunk) or next_offset >= size:
                    raise PublishError("Unexpected resumable upload range")
                if next_offset == offset:
                    failures += 1
                    if failures > 3:
                        raise PublishError("Resumable upload made no progress")
                offset = next_offset
        raise PublishError("Upload did not complete")


class TikTok(_Adapter):
    def upload(self, kit, *, dry_run=True, confirm=False, chunk_size=10_000_000):
        if not 5_000_000 <= chunk_size <= 64_000_000:
            raise ValueError("TikTok chunk size must be 5-64 MB")
        video, copy = _kit(kit, "tiktok")
        size = video.stat().st_size
        if size > 4_000_000_000:
            raise ValueError("TikTok video exceeds 4 GB")
        chunk_size = min(size, chunk_size)
        count = max(1, size // chunk_size)
        result = dict(platform="tiktok", dry_run=bool(dry_run), metadata=copy,
                      manual_steps="Open TikTok inbox, apply share kit copy and select a cover, then review and post")
        if dry_run:
            return result
        auth = self._authorization(confirm)
        response = expect(request(self.client, "POST", "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",
            headers=auth, json={"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                                "chunk_size": chunk_size, "total_chunk_count": count}}), {200})
        body = json_body(response)
        if body.get("error", {}).get("code") != "ok":
            raise PublishError("TikTok draft initialization failed")
        data = body.get("data", {})
        publish_id = data.get("publish_id")
        if not isinstance(publish_id, str) or not publish_id:
            raise PublishError("TikTok did not return a publish ID")
        url = upload_url(data.get("upload_url"), "tiktokapis.com")
        with video.open("rb") as stream:
            offset = 0
            for index in range(count):
                chunk = stream.read(size - offset if index == count - 1 else chunk_size)
                # Signed transfer URL authorizes the transfer; never send OAuth to it.
                expect(request(self.client, "PUT", url, headers={"Content-Type": "video/mp4",
                    "Content-Range": f"bytes {offset}-{offset + len(chunk) - 1}/{size}"}, content=chunk),
                    {201} if index == count - 1 else {206})
                offset += len(chunk)
        return {**result, "publish_id": publish_id, "status": "draft_uploaded"}
