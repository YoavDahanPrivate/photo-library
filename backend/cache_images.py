"""Generated-image access shared by serving, portraits and cache generation."""
import hashlib
import logging
import os
from email.utils import formatdate
from secrets import token_hex
import threading
import time
import zipfile

from fastapi import HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response
from starlette.responses import MalformedRangeHeader, RangeNotSatisfiable

from . import core
from .packed_cache_reader import CacheImages

_lock = threading.RLock()
_cache = None
_key = None


def close():
    global _cache, _key
    with _lock:
        if _cache is not None:
            _cache.close()
        _cache = _key = None


def get_cache():
    global _cache, _key
    with _lock:
        pack_root = os.environ.get('DAHAN_CACHE_PACKS', '').strip() or None
        key = (str(core.DATA), pack_root)
        if _cache is None or _key != key:
            close()
            _cache = CacheImages(core.DATA, pack_root)
            _key = key
        return _cache


def _call(operation, *args):
    try:
        return getattr(get_cache(), operation)(*args)
    except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile) as error:
        logging.getLogger(__name__).exception('Generated image cache access failed')
        close()
        raise OSError('Generated image cache is unavailable') from error


def read(name):
    return _call('read', name)


def exists(name):
    return _call('exists', name)


def write_path(name):
    return _call('write_path', name)


def write(name, data):
    return _call('write', name, data)


def materialize(name):
    return _call('materialize', name)


def image_response(name, request, missing_detail, headers=None):
    path = _call('existing_path', name)
    if path is not None:
        return FileResponse(path, media_type='image/jpeg', headers=headers)
    data = read(name)
    if data is None:
        raise HTTPException(404, missing_detail)
    cache = get_cache()
    metadata = cache.packed.entries.get(name, (None, {}))[1] if cache.packed is not None else {}
    response_headers = dict(headers or {})
    response_headers.update({'Accept-Ranges': 'bytes', 'ETag': '"' + hashlib.sha256(data).hexdigest() + '"',
                             'Last-Modified': formatdate(metadata.get('mtime_ns', time.time_ns()) / 1e9, usegmt=True)})
    range_header = request.headers.get('range')
    if_range = request.headers.get('if-range')
    if range_header and (if_range is None or if_range in (response_headers['ETag'], response_headers['Last-Modified'])):
        # Reuse the exact parser from the bundled Starlette version. Legacy
        # images still use its FileResponse, preserving their existing behavior.
        try:
            ranges = FileResponse._parse_range_header(range_header, len(data))
        except MalformedRangeHeader as error:
            return PlainTextResponse(error.content, status_code=400)
        except RangeNotSatisfiable:
            return Response(status_code=416, headers={'Content-Range': f'bytes */{len(data)}'})
        if len(ranges) == 1:
            start, end = ranges[0]
            response_headers['Content-Range'] = f'bytes {start}-{end - 1}/{len(data)}'
            return Response(data[start:end], status_code=206, media_type='image/jpeg', headers=response_headers)
        if len(ranges) > 1:
            boundary = token_hex(13)
            def header(start, end):
                return (f'--{boundary}\r\nContent-Type: image/jpeg\r\n'
                        f'Content-Range: bytes {start}-{end - 1}/{len(data)}\r\n\r\n').encode('latin-1')
            body = b''.join(header(start, end) + data[start:end] + b'\r\n' for start, end in ranges)
            body += ('--' + boundary + '--').encode('latin-1')
            response_headers['Content-Type'] = 'multipart/byteranges; boundary=' + boundary
            return Response(body, status_code=206, headers=response_headers)
    return Response(data, media_type='image/jpeg', headers=response_headers)
