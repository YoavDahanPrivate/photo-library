"""Read-only catalogue/API measurements; expensive filesystem checks are opt-in."""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory', default=os.environ.get('DAHAN_DATA'))
    parser.add_argument('--database-directory', default=os.environ.get('DAHAN_DATABASE_DIR'))
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    parser.add_argument('--iterations', type=int, default=5)
    parser.add_argument('--check-originals', action='store_true', help='Stat original files; may be slow on a NAS.')
    parser.add_argument('--include-disk-usage', action='store_true', help='Walk derivative folders; may be slow.')
    parser.add_argument('--output', type=Path, help='Optional JSON report destination; default is stdout only.')
    args = parser.parse_args()
    if not args.data_directory:
        parser.error('Set DAHAN_DATA or supply --data-directory explicitly.')
    if args.iterations < 1:
        parser.error('--iterations must be positive')
    os.environ['DAHAN_DATA'] = args.data_directory
    os.environ['DAHAN_DATABASE_DIR'] = args.database_directory or args.data_directory
    os.environ['DAHAN_REQUIRE_EXISTING_DATABASE'] = '1'
    import httpx
    from backend.core import DATA, database_path, db, original

    with db() as connection:
        count = connection.execute('SELECT count(*) FROM media').fetchone()[0]
        counts = [dict(row) for row in connection.execute('SELECT kind,extension,count(*) count FROM media GROUP BY kind,extension')]
        unknown_dates = connection.execute('SELECT count(*) FROM media WHERE taken IS NULL').fetchone()[0]
        gps_count = connection.execute('SELECT count(*) FROM media WHERE latitude IS NOT NULL AND longitude IS NOT NULL').fetchone()[0]
        active_actions = connection.execute('SELECT count(*) FROM actions WHERE undone=0').fetchone()[0]
        records = connection.execute('SELECT * FROM media').fetchall() if args.check_originals else []

    changed, unavailable = [], []
    for row in records:
        try:
            info = original(row).stat()
            if info.st_size != row['bytes'] or abs(info.st_mtime-row['mtime']) > .001:
                changed.append(row['id'])
        except (OSError, ValueError):
            unavailable.append(row['id'])

    times = []
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        for _ in range(args.iterations):
            started = time.perf_counter()
            response = client.get('/api/media', params={'limit': 80})
            response.raise_for_status()
            times.append((time.perf_counter()-started)*1000)
        api_total = response.json()['total']
    report = dict(catalogue_records=count, visible_api_records=api_total, formats=counts,
                  unknown_capture_dates=unknown_dates, with_gps=gps_count, active_actions=active_actions,
                  database_bytes={name: database_path(name).stat().st_size for name in ('catalogue.sqlite','sync.sqlite')},
                  api_query_ms=dict(median=round(statistics.median(times), 2),
                                    maximum=round(max(times), 2), iterations=len(times)))
    if args.check_originals:
        report['original_checks'] = dict(checked=len(records), changed_ids=changed, unavailable_ids=unavailable)
    if args.include_disk_usage:
        report['generated_bytes'] = {name: sum(path.stat().st_size for path in (DATA/name).rglob('*') if path.is_file() and not path.is_symlink())
                                     for name in ('thumbs','frames','faces','previews')}
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
