"""Verify available contextual evidence; record originals not distributed with code."""
import json
from .common import digest, evidence_path, root


def verify_context():
    manifest = json.loads((root() / 'docs/relatorio_original/imagens.json').read_text())
    if digest(evidence_path(manifest['transcription'])) != manifest['transcription_sha256']:
        raise ValueError('checked transcription changed')
    checks = []
    for image in manifest['images']:
        path = evidence_path(image['image'])
        status = 'not_available_in_this_checkout'
        if path.exists():
            if digest(path) != image['sha256']:
                raise ValueError('original report image changed')
            status = 'hash_verified'
        checks.append({'kind': 'report_image', 'page': image['page'], 'status': status})
    sources = json.loads((root() / 'docs/evidencias-documentais/fontes.json').read_text())
    for source in sources['sources']:
        if source.get('raw_status') != 'saved':
            continue
        path = evidence_path(source['raw_path'])
        status = 'not_available_in_this_checkout'
        if path.exists():
            if digest(path) != source['raw_sha256']:
                raise ValueError('documentary source changed')
            status = 'hash_verified'
        checks.append({'kind': 'document', 'id': source['id'], 'status': status})
    return {'checks': checks, 'images_verified_in_this_run':
            sum(c['kind'] == 'report_image' and c['status'] == 'hash_verified' for c in checks),
            'historical_visual_review': manifest['visually_checked_pages'],
            'limitation': 'Historical documentary findings are attributed records, not a new web or visual review.'}
