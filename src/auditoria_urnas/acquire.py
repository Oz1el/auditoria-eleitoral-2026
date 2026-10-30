"""Acquire selected missing archives from the previously inspected catalog plan."""
from __future__ import annotations
import json
import shutil
from urllib.parse import urlsplit
from .common import UFS, atomic_json, digest, emit, root
from .network import download


def acquire_missing(ufs, *, confirm=False):
    if not ufs or not set(ufs).issubset(UFS):
        raise ValueError('unknown or empty region selection')
    plan = json.loads((root() / 'data/catalog/replacement-plan.json').read_text())
    files = [item for item in plan['files'] if item['uf'] in ufs]
    inventory = json.loads((root() / 'data/catalog/inventory.json').read_text())
    planned = {item['uf'] for item in files}
    unresolved = [row['uf'] for row in inventory['files']
                  if row['uf'] in ufs and not row['eligible_for_validation'] and row['uf'] not in planned]
    if unresolved:
        raise ValueError('no official resource/size available for: ' + ', '.join(unresolved))
    selected = {**plan, 'files': files, 'requested_ufs': ufs,
                'traffic_bytes': sum(item['expected_bytes'] for item in files)}
    print(json.dumps(selected, ensure_ascii=False, indent=2))
    if not confirm:
        return selected
    if shutil.disk_usage(root()).free < selected['traffic_bytes'] + 20 * 1024**3:
        raise OSError('insufficient disk margin for new copies')
    folder = root() / 'data/raw/replacements' / plan['created_utc'].replace(':', '')
    folder.mkdir(parents=True, exist_ok=True)
    for item in files:
        url = urlsplit(item['url'])
        if url.scheme != 'https' or url.hostname not in {'cdn.tse.jus.br', 'dadosabertos.tse.jus.br'}:
            raise ValueError('archive URL outside official HTTPS sources')
        target = folder / url.path.rsplit('/', 1)[1]
        if target.exists():
            meta = json.loads(target.with_name(target.name + '.provenance.json').read_text())
            if (meta['url'] != item['url'] or target.stat().st_size != item['expected_bytes']
                    or digest(target) != meta['sha256']):
                raise ValueError('existing acquisition differs; original preserved')
        else:
            meta = download(item['url'], target, item['expected_bytes'])
        emit('archive_acquired', **meta)
    atomic_json(folder / 'selected-plan.json', selected)
    return selected
