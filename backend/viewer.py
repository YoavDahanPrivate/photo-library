"""On-demand, full-resolution browser display from original photo files."""
import hashlib, threading, uuid
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from . import core

conversion_lock=threading.Semaphore(2)

def photo_response(row):
    if row['kind']!='photo':raise HTTPException(400,'Not a photo')
    try:path=core.original(row)
    except ValueError:raise HTTPException(403,'Invalid source')
    except (RuntimeError,OSError):raise HTTPException(503,'Network source unavailable or saved access needs updating') from None
    if not path.is_file():raise HTTPException(404,'Original source is offline or missing')
    if path.suffix.lower() in ('.jpg','.jpeg','.png','.webp','.gif','.avif'):
        return FileResponse(path,headers={'Cache-Control':'private, max-age=3600'})
    stat=path.stat()
    key=hashlib.sha256((str(path)+str(stat.st_mtime_ns)+str(stat.st_size)).encode()).hexdigest()
    folder=core.DATA/'display-originals';folder.mkdir(exist_ok=True)
    target=folder/(key+'.jpg')
    with conversion_lock:
        if not target.exists():
            temp=folder/(key+'.'+uuid.uuid4().hex+'.tmp')
            try:
                import pillow_heif
                from PIL import Image,ImageOps
                pillow_heif.register_heif_opener()
                with Image.open(path) as source:
                    image=ImageOps.exif_transpose(source).convert('RGB')
                    image.save(temp,format='JPEG',quality=95,subsampling=0)
                temp.replace(target)
            except Exception:
                temp.unlink(missing_ok=True)
                raise HTTPException(422,'Cannot render this original in the browser; download the original instead')
    return FileResponse(target,media_type='image/jpeg',headers={'Cache-Control':'private, max-age=3600'})
