"""Public installation assets are built without touching catalogue annotations."""
import hashlib
import io
import json
import zipfile

import pytest


def test_install_builds_offline_references_without_opening_catalogue(tmp_path, monkeypatch):
    from backend import core, setup_references as setup
    monkeypatch.setattr(core, 'DATA', tmp_path/'runtime')
    def forbidden():
        raise AssertionError('Reference installation opened the personal catalogue')
    monkeypatch.setattr(core, 'db', forbidden)
    from backend import place_names
    monkeypatch.setattr(place_names, 'db', forbidden)
    # A small public-reference fixture, not a network request or family database.
    feature = {'type':'FeatureCollection','features':[{'type':'Feature','properties':{},'geometry':{'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,0]]]}}]}
    geojson = json.dumps(feature).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('cities1000.txt','1\tExample\tExample\tExample City\t1.0\t2.0\tP\tPPL\tGB\n')
    files = {'land.geojson':geojson,'countries.geojson':geojson,'cities1000.zip':buffer.getvalue()}
    monkeypatch.setattr(setup, 'LAND_SHA256', hashlib.sha256(geojson).hexdigest())
    downloaded = []
    def download(url, timeout):
        name = next(name for name,value in setup.REFERENCES.items() if value == url)
        downloaded.append(name)
        return io.BytesIO(files[name])
    monkeypatch.setattr(setup, 'urlopen', download)
    setup.install()
    assert set(downloaded) == set(files)
    import sqlite3
    with sqlite3.connect(core.DATA/'maps'/'gazetteer.sqlite') as c:
        assert c.execute('SELECT name FROM cities').fetchall() == [('Example',)]
    assert not (core.DATA/'catalogue.sqlite').exists()
    assert not (core.DATA/'sync.sqlite').exists()
    downloaded.clear()
    setup.install()
    assert downloaded == []


def test_failed_download_does_not_publish_partial_reference(tmp_path, monkeypatch):
    from backend import core, setup_references as setup
    monkeypatch.setattr(core, 'DATA', tmp_path/'runtime')
    monkeypatch.setattr(setup, 'urlopen', lambda *args,**kwargs:io.BytesIO(b'Incomplete download'))
    with pytest.raises(ValueError):
        setup.install()
    assert not (core.DATA/'maps'/'land.geojson').exists()
    assert list((core.DATA/'maps').iterdir()) == []
