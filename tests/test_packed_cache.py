import hashlib
import json
import zipfile

import pytest
from backend.packed_cache_reader import CacheImages, PackedImages, cache_name


@pytest.fixture
def images(tmp_path):
    root = tmp_path / 'pack'
    root.mkdir()
    data = tmp_path / 'data'
    data.mkdir()
    content = b'fixture-image-bytes'
    archive = root / 'cache-00001.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as stream:
        stream.writestr('thumbs/photo-large.jpg', content)
    owner = {'job_id': 'fixture', 'pack_id': 'fixture-pack'}
    index = {**owner, 'schema': 1, 'image_files': 1, 'image_bytes': len(content),
             'archives': [{'file': archive.name, 'bytes': archive.stat().st_size,
                           'members': [{'relative': 'thumbs/photo-large.jpg',
                                        'size': len(content), 'sha': hashlib.sha256(content).hexdigest()}]}]}
    raw = json.dumps(index).encode()
    (root / 'cache-index.json').write_bytes(raw)
    (root / 'pack-owner.json').write_text(json.dumps(owner))
    (root / 'verification.json').write_text(json.dumps({**owner, 'passed': True,
        'index_sha256': hashlib.sha256(raw).hexdigest(), 'images': 1, 'bytes': len(content)}))
    cache = CacheImages(data, root)
    yield cache, root, content
    cache.close()


def test_pack_loose_override_and_materialization(images):
    cache, root, content = images
    assert cache.read('thumbs/photo-large.jpg') == content
    assert cache.existing_path('thumbs/photo-large.jpg') is None
    loose = cache.data / 'faces/loose.jpg'
    loose.parent.mkdir()
    loose.write_bytes(b'loose')
    assert cache.read('faces/loose.jpg') == b'loose'
    assert cache.materialize('thumbs/photo-large.jpg').read_bytes() == content
    cache.write('thumbs/photo-large.jpg', b'regenerated')
    assert cache.read('thumbs/photo-large.jpg') == b'regenerated'
    assert len(list(root.glob('*.zip'))) == 1
    assert cache.read('frames/missing.jpg') is None


def test_member_checksum_is_checked_on_every_read(images):
    cache, _, _ = images
    filename, member = cache.packed.entries['thumbs/photo-large.jpg']
    cache.packed.entries['thumbs/photo-large.jpg'] = (filename, {**member, 'sha': '0' * 64})
    with pytest.raises(RuntimeError, match='checksum'):
        cache.read('thumbs/photo-large.jpg')


def test_changed_index_receipt_is_rejected(images):
    _, root, _ = images
    (root / 'cache-index.json').write_text('{}')
    with pytest.raises(RuntimeError, match='verification'):
        PackedImages(root)


@pytest.mark.parametrize('name', ['../photo.jpg', 'thumbs/../../photo.jpg',
    'thumbs\\photo.jpg', 'D:/photo.jpg', '/thumbs/photo.jpg', 'originals/photo.jpg'])
def test_cache_names_cannot_escape_generated_image_categories(name):
    with pytest.raises(ValueError):
        cache_name(name)
