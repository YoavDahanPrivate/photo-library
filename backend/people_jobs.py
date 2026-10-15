"""Face reevaluation workers with progress outside the catalogue database."""
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from . import core

router = APIRouter(prefix='/operations')
_submit_lock = threading.Lock()
_children = {}
ACTIVE = {'queued', 'running'}


class Cancelled(Exception):
    pass


def folder():
    path = core.DATA / 'people-operations'
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_path(identity):
    if not re.fullmatch('[a-f0-9]{32}', identity):
        raise HTTPException(404, 'People operation not found')
    return folder() / (identity + '.json')


def write(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    try:
        # Windows can briefly hold a reader open during replacement.
        for attempt in range(10):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(.01)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    for attempt in range(10):
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except PermissionError:
            if attempt == 9:
                raise HTTPException(503, 'Face operation progress is temporarily unavailable. The worker may still be running; progress will reconnect.')
            time.sleep(.01)


def process_alive(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)  # Query only; never signal the worker.
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read(identity):
    path = job_path(identity)
    try:
        state = read_json(path)
    except FileNotFoundError:
        raise HTTPException(404, 'People operation not found')
    if state['state'] in ACTIVE:
        process = _children.get(identity)
        pid = state.get('pid')
        alive = process.poll() is None if process else True
        if process is None and pid:
            alive = process_alive(pid)
        if not alive or (not pid and time.time()-state['started_at'] > 30):
            # Re-read after process exit: its final write may have just completed.
            state = read_json(path)
            if state['state'] in ACTIVE:
                state.update(state='interrupted', phase='Worker stopped', updated_at=time.time(),
                             error='Face processing stopped before completion. Committed approvals are saved; refresh the review list before restarting.')
                write(path, state)
    if state['state'] not in ACTIVE:
        child = _children.get(identity)
        if child and child.poll() is not None:
            _children.pop(identity, None)
    state['stop_requested'] = state['state'] in ACTIVE and (folder() / (identity + '.cancel')).exists()
    return state


@router.get('/current')
def current():
    try:
        identity = read_json(folder() / 'current.json')['id']
    except FileNotFoundError:
        return None
    return read(identity)


@router.get('/{identity}')
def status(identity: str):
    return read(identity)


@router.post('/reevaluate', status_code=202)
def start():
    return start_operation('reevaluate')


@router.post('/calibrate', status_code=202)
def start_calibration():
    return start_operation('calibrate')


@router.post('/auto-approve', status_code=202)
def start_auto_approve():
    return start_operation('auto-approve')


def start_operation(kind):
    with _submit_lock:
        existing = current()
        if existing and existing['state'] in ACTIVE:
            if existing.get('kind', 'reevaluate') != kind:
                raise HTTPException(409, 'Another face operation is running. Stop it or wait for it to finish before starting this operation.')
            return existing
        identity = uuid.uuid4().hex
        state = dict(id=identity, kind=kind, state='queued', phase='Starting calibration' if kind=='calibrate' else 'Starting automatic approval' if kind=='auto-approve' else 'Starting reevaluation',
                     round=0, rounds_completed=0, approved_total=0, review_revision=0,
                     started_at=time.time(), updated_at=time.time(), processed=None, total=None)
        write(job_path(identity), state)
        write(folder() / 'current.json', {'id': identity})
        env = os.environ.copy()
        env.update(DAHAN_DATA=str(core.DATA), PYTHONUTF8='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
        flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 0
        try:
            with (folder() / (identity + '.log')).open('ab') as log:
                child = subprocess.Popen([sys.executable, '-B', '-m', 'backend.people_jobs', identity],
                                         cwd=Path(__file__).resolve().parents[1], env=env,
                                         stdout=log, stderr=log, creationflags=flags)
            _children[identity] = child
        except Exception:
            state.update(state='failed', phase='Could not start reevaluation', updated_at=time.time(),
                         error='The face matching worker could not start. Check server logs, then retry.')
            write(job_path(identity), state)
            raise
        return state


@router.post('/{identity}/cancel')
def cancel(identity: str):
    state = read(identity)
    if state['state'] in ACTIVE:
        (folder() / (identity + '.cancel')).touch()
        state['stop_requested'] = True
    return state


def work(identity):
    import logging
    import sqlite3
    from .people_review import reevaluate
    path = job_path(identity)
    state = read_json(path)
    state.update(pid=os.getpid(), state='running')
    cancelled = folder() / (identity + '.cancel')
    last_write = 0
    automatic = state.get('kind') == 'auto-approve'

    def check_stop():
        if cancelled.exists():
            raise Cancelled()

    def save():
        nonlocal last_write
        state['updated_at'] = time.time()
        write(path, state)
        last_write = state['updated_at']

    def progress(phase, processed=None, total=None, unit=None):
        nonlocal last_write
        now = time.time()
        changed = state.get('phase') != phase
        due = changed or now-last_write >= .25 or (total is not None and processed == total)
        if (due or phase == 'Saving suggestions') and cancelled.exists():
            raise Cancelled()
        if due:
            state.update(phase=phase, processed=processed, total=total, unit=unit, updated_at=now)
            write(path, state)
            last_write = now

    try:
        if state.get('kind') == 'calibrate':
            from .face_calibration import analyze
            result = analyze(progress=progress)
        elif automatic:
            from .automatic_review import run
            result = run(state, progress, save, check_stop)
        else:
            progress('Reading saved faces')
            result = reevaluate(progress=progress)
        state.update(state='completed', phase='Calibration ready to review' if state.get('kind')=='calibrate' else 'Auto approval finished' if automatic else 'Matches ready for review', result=result, updated_at=time.time())
    except Cancelled:
        state.update(state='cancelled', phase='Auto approval stopped' if automatic else 'Reevaluation stopped', processed=None, total=None, updated_at=time.time())
    except HTTPException as error:
        state.update(state='failed', phase='Auto approval stopped' if automatic else 'Reevaluation stopped', error=str(error.detail), updated_at=time.time())
    except (sqlite3.Error, OSError):
        logging.exception('People reevaluation storage failure')
        state.update(state='failed', phase='Storage unavailable', updated_at=time.time(),
                     error='The library drive is unavailable or busy. Existing assignments are saved; reconnect the drive before retrying.')
    except Exception:
        logging.exception('People reevaluation failed')
        state.update(state='failed', phase='Auto approval failed' if automatic else 'Reevaluation failed', updated_at=time.time(),
                     error='Face processing failed. Committed approvals are saved; check the worker log before restarting.')
    finally:
        state['finished_at'] = time.time()
        write(path, state)
        cancelled.unlink(missing_ok=True)


if __name__ == '__main__':
    work(sys.argv[1])
