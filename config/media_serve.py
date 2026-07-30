"""Range-aware, access-controlled media serving for development.

``django.views.static.serve`` ignores the HTTP ``Range`` header, so browsers
cannot seek inside long narration WAVs / videos without downloading the whole
file first. This wrapper answers single-range requests with a 206 and streams
only the requested slice; everything else falls through to Django's serve.

It also enforces access. Generated scripts, images, narration and final renders
all live under ``media/videos/<video_id>/``, so a bare static handler makes every
account's output readable by anyone who can guess a path. ``guarded_serve``
resolves the video id out of the path and refuses anything outside the caller's
active account.
"""
import mimetypes
import re
from pathlib import Path

from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.utils._os import safe_join
from django.views.static import serve

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")
_CHUNK = 64 * 1024
# media/videos/<video_id>/... — the only account-owned tree under MEDIA_ROOT.
_VIDEO_PATH_RE = re.compile(r"^videos/(\d+)/")


def _stream(path, start, remaining):
    with open(path, "rb") as f:
        f.seek(start)
        while remaining > 0:
            data = f.read(min(_CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def ranged_serve(request, path, document_root=None):
    match = _RANGE_RE.match(request.META.get("HTTP_RANGE", ""))
    if match is None:
        response = serve(request, path, document_root=document_root)
        response["Accept-Ranges"] = "bytes"
        return response

    fullpath = Path(safe_join(document_root, path))
    if not fullpath.is_file():
        raise Http404(f"'{path}' does not exist")
    size = fullpath.stat().st_size

    start_s, end_s = match.groups()
    if start_s:
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    elif end_s:  # suffix range: last N bytes
        start = max(0, size - int(end_s))
        end = size - 1
    else:
        start, end = 0, size - 1

    if start >= size:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        return response
    end = min(end, size - 1)

    content_type = mimetypes.guess_type(str(fullpath))[0] or "application/octet-stream"
    response = StreamingHttpResponse(
        _stream(fullpath, start, end - start + 1), status=206, content_type=content_type
    )
    response["Content-Length"] = str(end - start + 1)
    response["Content-Range"] = f"bytes {start}-{end}/{size}"
    response["Accept-Ranges"] = "bytes"
    return response


def guarded_serve(request, path, document_root=None):
    """``ranged_serve`` behind a login and an account check.

    404 rather than 403 on a foreign video, matching the video views: whether a
    video exists must not be observable from outside its account.
    """
    # Imported lazily: this module is imported from config.urls, which is loaded
    # before the app registry is ready.
    from django.conf import settings
    from django.contrib.auth.views import redirect_to_login

    from apps.accounts.access import Perm, has_perm
    from apps.videos.services.video_service import VideoService

    if document_root is None:
        document_root = settings.MEDIA_ROOT

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    match = _VIDEO_PATH_RE.match(path.replace("\\", "/"))
    if match is not None:
        if not has_perm(request, Perm.VIDEO_VIEW):
            raise Http404("Not found")
        if VideoService.get_video(int(match.group(1)), request.account) is None:
            raise Http404("Not found")

    return ranged_serve(request, path, document_root=document_root)
