"""Read verified image-cache packs with loose-file and writable-overlay support.

Existing loose cache remains readable. New generated images use a small-folder
overlay when an explicitly configured, verified cache pack is enabled.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import threading
import uuid
import zipfile

MAX_IMAGE = 64 * 1024**2


def cache_name(name):
    if not isinstance(name, str) or '\\' in name or ':' in name:
        raise ValueError('Invalid cache name')
    p = PurePosixPath(name)
    if p.is_absolute() or len(p.parts) != 2 or '..' in p.parts or p.as_posix() != name:
        raise ValueError('Invalid cache name')
    if p.parts[0] not in ('thumbs', 'faces', 'frames') or p.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
        raise ValueError('Only generated cache images are supported')
    return p


class PackedImages:
    """Read directly from ZIP_STORED members; never extract entire archives."""

    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        index_bytes = (self.root / 'cache-index.json').read_bytes()
        receipt = json.loads((self.root / 'verification.json').read_text(encoding='utf-8-sig'))
        index = json.loads(index_bytes)
        owner = json.loads((self.root / 'pack-owner.json').read_text(encoding='utf-8-sig'))
        if index.get('schema') != 1 or not receipt.get('passed') or receipt.get('index_sha256') != hashlib.sha256(index_bytes).hexdigest():
            raise RuntimeError('Cache pack has not passed verification')
        if any(owner.get(key) != index.get(key) or receipt.get(key) != index.get(key) for key in ('job_id', 'pack_id')):
            raise RuntimeError('Cache pack ownership mismatch')
        self.entries = {}
        self.archives = {}
        self.lock = threading.RLock()
        names = set()
        total = 0
        for archive in index['archives']:
            filename = archive['file']
            if not re.fullmatch(r'cache-\d{5}\.zip', filename) or filename in names:
                raise ValueError('Invalid or duplicate archive filename')
            names.add(filename)
            archive_path = self.root / filename
            if not archive_path.resolve(strict=True).is_relative_to(self.root) or archive_path.stat().st_size != archive['bytes']:
                raise RuntimeError('Cache archive is missing, outside its root or has changed size')
            for member in archive['members']:
                key = cache_name(member['relative']).as_posix()
                if key in self.entries or not 0 <= member['size'] <= MAX_IMAGE or not re.fullmatch('[0-9a-f]{64}', member['sha']):
                    raise ValueError('Invalid archive member metadata')
                self.entries[key] = (filename, member)
                total += member['size']
        if len(self.entries) != index['image_files'] or total != index['image_bytes'] or len(self.entries) != receipt['images'] or total != receipt['bytes']:
            raise ValueError('Cache image coverage mismatch')

    def contains(self, name):
        return cache_name(name).as_posix() in self.entries

    def read(self, name):
        name = cache_name(name).as_posix()
        item = self.entries.get(name)
        if item is None:
            return None
        filename, member = item
        with self.lock:
            if filename not in self.archives:
                path = self.root / filename
                if not path.resolve(strict=True).is_relative_to(self.root):
                    raise RuntimeError('Archive path escaped its root')
                self.archives[filename] = zipfile.ZipFile(path, 'r')
            archive = self.archives[filename]
            info = archive.getinfo(name)
            if info.file_size != member['size'] or info.compress_type != zipfile.ZIP_STORED:
                raise RuntimeError('Unexpected cache archive entry')
            # ZIP CRC and expected SHA both validate the returned image.
            data = archive.read(name)
        if len(data) != member['size'] or hashlib.sha256(data).hexdigest() != member['sha']:
            raise RuntimeError('Cache image checksum mismatch')
        return data

    def close(self):
        with self.lock:
            for archive in self.archives.values():
                archive.close()
            self.archives.clear()


class CacheImages:
    """Explicit adapter for generated images, not original media or databases.

    Constructing this class does not enable it in the application. Backend
    callers must be deliberately integrated and tested before activation.
    """

    def __init__(self, data_root, verified_pack_root=None):
        self.data = Path(data_root).resolve(strict=True)
        self.overlay = self.data / 'cache-image-overrides'
        self.packed = PackedImages(verified_pack_root) if verified_pack_root is not None else None

    def _overlay_path(self, name):
        p = cache_name(name)
        # At most 256 subfolders per image category for the usual hex IDs.
        prefix = hashlib.sha256(p.name.encode()).hexdigest()[:2]
        return self.overlay / p.parts[0] / prefix / p.name

    def exists(self, name):
        p = cache_name(name)
        if self.packed is not None:
            if self._overlay_path(name).is_file() or self.packed.contains(name):
                return True
        return (self.data / Path(p.as_posix())).is_file()

    def existing_path(self, name):
        """Return an existing loose/override path without extracting a pack."""
        p = cache_name(name)
        if self.packed is not None:
            overlay = self._overlay_path(name)
            if overlay.is_file():
                return overlay
            if self.packed.contains(name):
                return None
        legacy = self.data / Path(p.as_posix())
        return legacy if legacy.is_file() else None

    def read(self, name):
        p = cache_name(name)
        if self.packed is not None:
            try:
                return self._overlay_path(name).read_bytes()
            except FileNotFoundError:
                pass
            data = self.packed.read(name)
            if data is not None:
                return data
        try:
            return (self.data / Path(p.as_posix())).read_bytes()
        except FileNotFoundError:
            return None

    def write_path(self, name):
        p = cache_name(name)
        path = self._overlay_path(name) if self.packed is not None else self.data / Path(p.as_posix())
        if not path.parent.resolve().is_relative_to(self.data):
            raise ValueError('Cache write escaped runtime')
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.parent.resolve().is_relative_to(self.data):
            raise ValueError('Cache write escaped runtime')
        return path

    def write(self, name, data):
        if len(data) > MAX_IMAGE:
            raise ValueError('Generated cache image exceeds size bound')
        target = self.write_path(name)
        temp = target.with_name(target.name + '.' + uuid.uuid4().hex + '.partial')
        try:
            with temp.open('xb') as output:
                output.write(data)
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        return target

    def materialize(self, name):
        """Create only a specifically requested cached frame/image for path APIs."""
        p = cache_name(name)
        if self.packed is not None:
            target = self._overlay_path(name)
            if target.is_file():
                return target
            data = self.packed.read(name)
            if data is not None:
                return self.write(name, data)
        legacy = self.data / Path(p.as_posix())
        if not legacy.is_file():
            raise FileNotFoundError(name)
        return legacy

    def close(self):
        if self.packed is not None:
            self.packed.close()
