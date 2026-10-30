"""Evidence inventory from local ZIPs plus independently preserved CKAN and HTML."""
from __future__ import annotations

import collections
import json
import shutil
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from .common import UFS, atomic_json, emit, now, original_dir, root, stat_key
from .network import head, small

CATALOG = 'https://dadosabertos.tse.jus.br'
SLUGS = ['resultados-2026-arquivos-transmitidos-para-totalizacao', 'resultados-2026-boletim-de-urna',
         'resultados-2026', 'resultados-2026-correspondencias-esperadas-e-efetivadas-2-turno']


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = set()

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get('href', '')
        if tag == 'a' and urlsplit(href).hostname == 'cdn.tse.jus.br':
            self.urls.add(href)


def discover() -> dict:
    stamp = now().replace(':', '').replace('.', '')
    folder = root() / 'data/catalog' / stamp
    folder.mkdir(parents=True, exist_ok=True)
    resources = {}
    differences = []
    errors = []
    for slug in SLUGS:
        api_urls = set()
        html_urls = set()
        for kind, url in [('api', f'{CATALOG}/api/3/action/package_show?id={slug}'),
                          ('html', f'{CATALOG}/dataset/{slug}')]:
            try:
                b = small(url)
                (folder / f'{slug}.{kind}').write_bytes(b)
                if kind == 'api':
                    payload = json.loads(b)
                    if not payload.get('success'):
                        raise ValueError('CKAN success=false')
                    for entry in payload['result']['resources']:
                        resource_url = entry.get('url', '')
                        api_urls.add(resource_url)
                        resources.setdefault(resource_url, {}).update({'id': entry.get('id'), 'name': entry.get('name'),
                            'created': entry.get('created'), 'modified': entry.get('last_modified'),
                            'catalog_hash': entry.get('hash'), 'format': entry.get('format')})
                else:
                    links = Links()
                    links.feed(b.decode('utf-8'))
                    html_urls = links.urls
                for resource_url in api_urls | html_urls:
                    item = resources.setdefault(resource_url, {})
                    item.update({'url': resource_url})
                    item.setdefault('catalogs', [])
                    if slug not in item['catalogs']:
                        item['catalogs'].append(slug)
            except Exception as e:
                errors.append({'catalog': slug, 'surface': kind, 'error': str(e)})
        differences.append({'catalog': slug, 'only_html': sorted(html_urls - api_urls), 'only_api': sorted(api_urls - html_urls)})
        emit('catalog_discovered', catalog=slug, api=len(api_urls), html=len(html_urls))
    result = {'captured_utc': now(), 'snapshot_dir': str(folder), 'resources': list(resources.values()),
              'surface_differences': differences, 'errors': errors}
    atomic_json(folder / 'index.json', result)
    atomic_json(root() / 'data/catalog/latest.json', result)
    return result


def inspect_archive(path: Path) -> dict:
    before = stat_key(path)
    data = {'path': str(path), 'bytes': before[2], 'mtime_ns': before[3], 'observed_utc': now()}
    try:
        with zipfile.ZipFile(path) as z:
            members = z.infolist()
            names = [x.filename for x in members]
            data.update({'zip_directory': 'readable', 'members': len(members),
                         'uncompressed_bytes': sum(x.file_size for x in members),
                         'extensions': dict(collections.Counter(Path(x.filename).suffix for x in members)),
                         'bu_members': sum(n.endswith(('-bu.dat', '-busa.dat')) for n in names),
                         'duplicate_names': len(names) - len(set(names))})
    except (zipfile.BadZipFile, OSError) as e:
        data.update({'zip_directory': 'unreadable', 'error': str(e)})
    data['stable_during_inventory'] = stat_key(path) == before
    return data


def inventory(online=False) -> dict:
    catalog_path = root() / 'data/catalog/latest.json'
    catalog = discover() if online else json.loads(catalog_path.read_text()) if catalog_path.exists() else {'resources': []}
    resources = catalog['resources']
    entries = []
    replacement = []
    for uf in UFS:
        filename = f'bu_imgbu_logjez_rdv_vscmr_2026_2t_{uf}.zip'
        candidates = [original_dir() / filename] + sorted((root() / 'data/raw/replacements').glob(f'*/{filename}'))
        existing = [p for p in candidates if p.exists()]
        # Prefer a separately acquired replacement, but always retain the original in the inventory.
        path = existing[-1] if existing else original_dir() / filename
        matches = {x['url']: x for x in resources if x['url'].endswith('/' + filename)}
        if len(matches) > 1:
            raise ValueError('ambiguous official archive versions: ' + uf)
        resource = next(iter(matches.values()), None)
        row = {'uf': uf, 'present': path.exists(), 'resource': resource, 'original_path': str(original_dir() / filename)}
        if path.exists():
            row.update(inspect_archive(path))
        if resource and online:
            try:
                row['http'] = head(resource['url'])
            except Exception as e:
                row['http_error'] = str(e)
        elif (old := root() / 'data/catalog/inventory.json').exists():
            prior = json.loads(old.read_text())
            oldrow = next((x for x in prior['files'] if x['uf'] == uf), {})
            if oldrow.get('http'):
                row['http'] = oldrow['http']
        expected = int(row.get('http', {}).get('content-length') or 0)
        row['size_matches_published'] = (row.get('bytes') == expected) if expected else None
        row['eligible_for_validation'] = (row.get('zip_directory') == 'readable' and row.get('stable_during_inventory')
                                          and row.get('size_matches_published') is not False)
        row['official_outer_hash'] = 'not_published_in_transmitted_catalog'
        if not row['eligible_for_validation'] and resource and expected:
            replacement.append({'uf': uf, 'url': resource['url'], 'expected_bytes': expected,
                                'reason': row.get('error', 'missing or published size mismatch'),
                                'preserve_existing': True})
        entries.append(row)
        emit('inventory_file', uf=uf, eligible=row['eligible_for_validation'], bytes=row.get('bytes'))
    free = shutil.disk_usage(root()).free
    result = {'captured_utc': now(), 'files': entries, 'expected_regions': 28,
              'present_regions': sum(x['present'] for x in entries),
              'readable_regions': sum(x['eligible_for_validation'] for x in entries),
              'free_bytes': free, 'full_crc_and_sha_pending_except_pilot': True,
              'compressed_bytes': sum(x.get('bytes', 0) for x in entries),
              'uncompressed_bytes_readable': sum(x.get('uncompressed_bytes', 0) for x in entries),
              'catalog_errors': catalog.get('errors', [])}
    atomic_json(root() / 'data/catalog/inventory.json', result)
    plan = {'created_utc': now(), 'requires_user_authorization': True, 'files': replacement,
            'traffic_bytes': sum(x['expected_bytes'] for x in replacement), 'free_bytes': free,
            'temporary_policy': 'new version; never overwrite original; preserve .part on failure'}
    atomic_json(root() / 'data/catalog/replacement-plan.json', plan)
    return result
