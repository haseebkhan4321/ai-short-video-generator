"""Range-aware media serving for development.

``django.views.static.serve`` ignores the HTTP ``Range`` header, so browsers
cannot seek inside long narration WAVs / videos without downloading the whole
file first. This wrapper answers single-range requests with a 206 and streams
only the requested slice; everything else falls through to Django's serve.
"""
import mimetypes
import re
from pathlib import Path

from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.utils._os import safe_join
from django.views.static import serve

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")
_CHUNK = 64 * 1024


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
