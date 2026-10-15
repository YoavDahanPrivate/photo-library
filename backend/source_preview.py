"""Bounded directory-entry sampling for registering a new root; no media reads."""
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def scan(root, exclusions=(), *, directory_limit=96, entry_limit=12000,
         per_directory_limit=512, seconds=6, depth_limit=16):
    from .source_management import IMAGES, VIDEOS, SKIP, excluded
    start=time.monotonic()
    root=Path(root)
    if not root.is_absolute():raise ValueError('Choose an absolute server folder path')
    if root.is_symlink() or root.is_junction():raise ValueError('The root must not be a symbolic link or junction')
    if not root.is_dir():raise OSError('Source unavailable: '+str(root))
    root=root.resolve()
    pending=deque([(root,0)])
    files=[];folders=[];observations=[];visited=entries=media=0;reasons=set();warnings=[]
    while pending:
        if visited>=directory_limit:reasons.add('directory limit');break
        if entries>=entry_limit:reasons.add('entry limit');break
        if time.monotonic()-start>=seconds:reasons.add('time limit');break
        directory,depth=pending.popleft();names=[];children=[];candidates=[];count=0
        try:
            with os.scandir(directory) as listing:
                for entry in listing:
                    if count>=per_directory_limit or entries>=entry_limit or time.monotonic()-start>=seconds:
                        reasons.add('directory entry limit' if count>=per_directory_limit else 'entry/time limit');break
                    count+=1;entries+=1
                    if entry.is_symlink() or (getattr(entry,'is_junction',lambda:False)()):continue
                    if entry.is_dir(follow_symlinks=False):
                        relative=(directory/entry.name).relative_to(root).as_posix()
                        if entry.name.casefold() in SKIP or excluded(relative,exclusions):continue
                        names.append(('directory',entry.name))
                        if depth<depth_limit:children.append(directory/entry.name)
                        else:reasons.add('depth limit')
                    elif Path(entry.name).suffix.lower() in IMAGES|VIDEOS and entry.is_file(follow_symlinks=False):
                        # SMB supplies these attributes with its directory listing.
                        # Do not stat/open each file or ask for size/mtime/EXIF.
                        names.append(('media',entry.name));media+=1
                        candidates.append((directory/entry.name).relative_to(root).as_posix())
        except OSError as error:
            if directory==root:raise OSError('Cannot list database folder: '+str(root)) from error
            reasons.add('unreadable subfolder')
            warnings.append('Could not list '+directory.relative_to(root).as_posix()+'. Sync will report access errors.')
            continue
        visited+=1
        folders.append(dict(relative=directory.relative_to(root).as_posix(),direct_media=len(candidates),children=len(children),readable=True))
        observations.append((directory.relative_to(root).as_posix(),sorted(names)))
        # Breadth first: sample across Sources before descending into one branch.
        pending.extend((child,depth+1) for child in sorted(children))
        files.extend({'relative':name} for name in sorted(candidates)[:3])
    fingerprint=hashlib.sha256(json.dumps(sorted(observations),sort_keys=True).encode()).hexdigest()
    folders.extend(dict(relative=directory.relative_to(root).as_posix(),direct_media=None,children=None,readable=None) for directory,depth in pending)
    return dict(root=str(root),files=files,folder_tree=folders,evidence=fingerprint,
                inspection=dict(kind='directory_sample',directories=visited,entries=entries,
                    media_names=media,representative_files=len(files),truncated=bool(reasons),
                    sampled=bool(reasons) or media>len(files),limits=sorted(reasons),
                    elapsed_seconds=round(time.monotonic()-start,3),warnings=warnings[:12]))


def inspect(root, exclusions=()):
    """A stuck NAS call is killed, rather than leaving preview busy forever."""
    from .network_access import ensure_access
    root=Path(root).expanduser()
    if not root.is_absolute():raise ValueError('Choose an absolute server folder path')
    ensure_access(root)
    try:
        result=subprocess.run([sys.executable,'-B','-m','backend.source_preview'],
            input=json.dumps({'root':str(root),'exclusions':exclusions}),text=True,
            encoding='utf-8',capture_output=True,timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
            cwd=Path(__file__).resolve().parents[1])
    except subprocess.TimeoutExpired:
        raise RuntimeError('The folder did not respond within 10 seconds. Check network access and retry the preview.') from None
    except OSError:
        raise RuntimeError('Folder preview could not start. Retry or check the backend installation.') from None
    try:
        payload=json.loads(result.stdout)
        if result.returncode or not isinstance(payload,dict):raise ValueError()
    except (ValueError,TypeError):
        raise RuntimeError('Folder preview could not complete. Check folder access and retry.') from None
    if payload.get('error'):raise OSError(payload['error'])
    return payload




def discover(root,exclusions=(),progress=lambda value:None):
    """Enumerate the complete accessible tree; retain only three names per folder."""
    from .source_management import IMAGES,VIDEOS,SKIP,excluded
    root=Path(root)
    if not root.is_absolute():raise ValueError('Choose an absolute server folder path')
    if root.is_symlink() or root.is_junction():raise ValueError('The root must not be a symbolic link or junction')
    if not root.is_dir():raise OSError('Source unavailable: '+str(root))
    root=root.resolve();pending=deque([root]);files=[];folders=[];warnings=[]
    visited=entries=media=0;digest=hashlib.sha256();started=last=time.monotonic()
    while pending:
        directory=pending.popleft();relative=directory.relative_to(root).as_posix()
        progress(dict(directories=visited,entries=entries,media_names=media,current=relative))
        children=[];candidates=[];direct_media=0
        try:
            with os.scandir(directory) as listing:
                for entry in listing:
                    entries+=1
                    if entry.is_symlink() or getattr(entry,'is_junction',lambda:False)():continue
                    if entry.is_dir(follow_symlinks=False):
                        child=directory/entry.name;child_rel=child.relative_to(root).as_posix()
                        if entry.name.casefold() in SKIP or excluded(child_rel,exclusions):continue
                        children.append(child);digest.update(('D:'+child_rel+'\n').encode())
                    elif Path(entry.name).suffix.lower() in IMAGES|VIDEOS and entry.is_file(follow_symlinks=False):
                        name=(directory/entry.name).relative_to(root).as_posix()
                        media+=1;direct_media+=1;digest.update(('F:'+name+'\n').encode())
                        candidates.append(name);candidates.sort();del candidates[3:]
                    if time.monotonic()-last>=.5:
                        progress(dict(directories=visited,entries=entries,media_names=media,current=relative));last=time.monotonic()
            visited+=1;pending.extend(sorted(children))
            folders.append(dict(relative=relative,direct_media=direct_media,children=len(children),readable=True))
            files.extend({'relative':name} for name in candidates)
        except OSError:
            warnings.append('Could not list '+relative+'. Check permissions before syncing.')
            folders.append(dict(relative=relative,direct_media=0,children=0,readable=False))
            if directory==root:raise OSError('Cannot list database folder: '+str(root))
    progress(dict(directories=visited,entries=entries,media_names=media,current='Finished'))
    return dict(root=str(root),files=files,folder_tree=folders,evidence=digest.hexdigest(),
                inspection=dict(kind='directory_tree',directories=visited,entries=entries,media_names=media,
                    representative_files=len(files),truncated=bool(warnings),sampled=media>len(files),
                    limits=['unreadable subfolder'] if warnings else [],elapsed_seconds=round(time.monotonic()-started,3),warnings=warnings[:12]))


def watch_parent(pid):
    # A Windows service can be force-stopped. Do not leave its discovery helper
    # orphaned while a NAS call is blocked.
    import threading
    def watch():
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes
            dll=ctypes.WinDLL('kernel32',use_last_error=True)
            dll.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];dll.OpenProcess.restype=wintypes.HANDLE
            dll.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];dll.WaitForSingleObject.restype=wintypes.DWORD
            dll.CloseHandle.argtypes=[wintypes.HANDLE]
            handle=dll.OpenProcess(0x00100000,False,pid)
            if not handle:os._exit(0)
            while dll.WaitForSingleObject(handle,1000)==258:pass
            dll.CloseHandle(handle);os._exit(0)
        else:
            while True:
                try:os.kill(pid,0)
                except OSError:os._exit(0)
                time.sleep(1)
    threading.Thread(target=watch,daemon=True).start()


if __name__=='__main__':
    complete=sys.argv[1:]==['--discover']
    try:
        request=json.load(sys.stdin)
        if complete:
            watch_parent(int(request['parent_pid']))
            def progress(value):print(json.dumps({'progress':value}),flush=True)
            result=discover(request['root'],request.get('exclusions',[]),progress)
        else:result=scan(request['root'],request.get('exclusions',[]))
    except (ValueError,OSError) as error:result={'error':str(error)}
    except Exception:result={'error':'Folder preview could not complete'}
    print(json.dumps({'error':result['error']} if complete and result.get('error') else {'result':result} if complete else result),flush=True)
