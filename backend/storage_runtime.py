"""Keep the web shell available while catalogue storage is disconnected."""
import logging
import sqlite3
import threading
import time
from . import core

ERRORS = (OSError, sqlite3.Error)
DETAIL = ('Library database storage is unavailable, inaccessible or busy. '
          'Check that the database drive is connected and writable, then retry. '
          'Saved scan checkpoints and annotations are retained.')
_lock = threading.Lock()
_ready = False
_next_retry = 0.0


def initialize(force=False):
    global _ready, _next_retry
    with _lock:
        if force:
            _ready = False
            _next_retry = 0.0
        if _ready:
            return True
        if time.monotonic() < _next_retry:
            return False
        try:
            core.init()
            from . import sync_service
            sync_service.recover_interrupted_runs()
        except ERRORS:
            _next_retry = time.monotonic() + 5
            logging.getLogger(__name__).exception('Database storage is unavailable; web shell remains online')
            return False
        _ready = True
        return True


def health():
    if not initialize():
        return {'server': 'running', 'storage': 'unavailable', 'detail': DETAIL}
    try:
        with core.db() as c:
            c.execute('SELECT revision FROM catalogue_clock WHERE id=1').fetchone()
        return {'server': 'running', 'storage': 'available'}
    except ERRORS:
        return {'server': 'running', 'storage': 'unavailable', 'detail': DETAIL}
