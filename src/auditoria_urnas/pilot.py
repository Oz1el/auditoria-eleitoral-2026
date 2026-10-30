"""Pilot acceptance: two local archives, text/binary and BWeb/BU reconciliation."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import time
import zipfile
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

from .common import atomic_json, digest, emit, now, root, signature
from .network import small
from .pipeline import connection, ingest, totals, validation


def bweb_zz() -> dict:
    catalog = json.loads((root() / 'data/catalog/latest.json').read_text())
    candidates = [r for r in catalog['resources'] if '/buweb/bweb_2t_ZZ_' in r['url'] and r['url'].endswith('.zip')]
    if len(candidates) != 1:
        raise ValueError('ambiguous/missing second-turn ZZ BWeb resource')
    url = candidates[0]['url']
    directory = root() / 'data/raw/pilot'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / url.rsplit('/',1)[1]
    sha_path = path.with_name(path.name + '.sha512')
    if not path.exists():
        path.write_bytes(small(url))
    if not sha_path.exists():
        sha_path.write_bytes(small(url + '.sha512', 4096))
    expected = sha_path.read_text().split()[0].lower()
    if len(expected) != 128 or digest(path, 'sha512') != expected:
        raise ValueError('BWeb official SHA-512 mismatch')
    result = {'url':url, 'path':str(path),'sha512':expected,'official_sha512':'matched',
              'sha256':digest(path),'retrieved_utc':now(),'signature_authenticity':'not_verified'}
    atomic_json(path.with_name(path.name + '.provenance.json'), result)
    return result


def reconcile_bweb(state: dict, bweb: dict) -> dict:
    from_bweb = Counter()
    metrics = {}
    with zipfile.ZipFile(bweb['path']) as z:
        if bad := z.testzip():
            raise ValueError(f'BWeb CRC: {bad}')
        name = next(n for n in z.namelist() if n.endswith('.csv'))
        with z.open(name) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding='latin1'), delimiter=';')
            header = reader.fieldnames
            for row in reader:
                if int(row['NR_TURNO']) != 2 or int(row['CD_CARGO_PERGUNTA']) != 1:
                    continue
                identity = (int(row['CD_MUNICIPIO']), int(row['NR_ZONA']), int(row['NR_SECAO']))
                vote_type = int(row['CD_TIPO_VOTAVEL'])
                number = int(row['NR_VOTAVEL']) if vote_type == 1 else None
                from_bweb[(*identity, vote_type, number)] += int(row['QT_VOTOS'])
                value = (int(row['QT_APTOS']), int(row['QT_COMPARECIMENTO']), int(row['QT_ABSTENCOES']))
                if identity in metrics and metrics[identity] != value:
                    raise ValueError('inconsistent repeated BWeb section metrics')
                metrics[identity] = value
    with connection([state]) as db:
        rows = db.execute('''SELECT b.municipio,b.zona,b.secao,v.tipo_voto,v.numero,sum(v.quantidade)::BIGINT
            FROM votos v JOIN boletins b USING(bu_id) WHERE cargo=1 GROUP BY ALL''').fetchall()
        metric_rows = db.execute('''SELECT b.municipio,b.zona,b.secao,e.aptos,e.comparecimento,e.abstencoes
            FROM eleicoes e JOIN boletins b USING(bu_id) WHERE cargo=1''').fetchall()
    from_bu = Counter({r[:5]:r[5] for r in rows})
    # Zero-vote entries need not exist in both representations.
    differences = [{'key':list(k), 'bu':from_bu[k], 'bweb':from_bweb[k]}
                   for k in from_bu.keys() | from_bweb.keys() if from_bu[k] != from_bweb[k]]
    bu_metrics = {r[:3]:r[3:] for r in metric_rows}
    metric_diffs = [{'key':list(k),'bu':bu_metrics.get(k),'bweb':metrics.get(k)}
                    for k in bu_metrics.keys() | metrics.keys() if bu_metrics.get(k) != metrics.get(k)]
    zero_sections = [d for d in metric_diffs if d['bweb'] is None and d['bu'] is not None and d['bu'][1] == 0]
    unexplained = [d for d in metric_diffs if d not in zero_sections]
    atomic_json(root() / 'docs/bweb-schema.json', {'fields':header,'encoding':'ISO-8859-1','delimiter':';',
                'sample_file':bweb, 'row_grain':'section/election/office/votable; metrics repeat across votables'})
    return {'vote_differences':differences, 'metric_differences':metric_diffs,
            'unexpected_metric_differences':unexplained, 'zero_turnout_sections_absent_bweb':zero_sections,
            'metric_comparison_scope':'common sections; eligible counts in absent zero-turnout sections not validated by BWeb',
            'bu_sections':len(bu_metrics), 'bweb_sections':len(metrics), 'official_sample':bweb}


def run_pilot() -> dict:
    import fcntl
    start = time.monotonic()
    gate_path = root() / 'output/reports/pilot.json'
    result = {'started_utc':now(), 'parser_signature':signature(), 'passed':False, 'ufs':['RR','ZZ']}
    atomic_json(gate_path, result)
    with (root() / 'data/checkpoints/pipeline.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            inv = json.loads((root() / 'data/catalog/inventory.json').read_text())
            states = []
            python_totals = Counter()
            for uf in ['RR','ZZ']:
                row = next(x for x in inv['files'] if x['uf']==uf)
                if not row['eligible_for_validation']:
                    raise ValueError(f'{uf} not eligible for pilot')
                checked = validation(row)
                state = ingest(row, checked)
                states.append(state)
                for batch in state['batches']:
                    for vote in pq.ParquetFile(batch['votos']['path']).read().to_pylist():
                        if vote['cargo']==1:
                            python_totals[(uf,vote['eleicao'],vote['tipo_voto'],vote['numero'])] += vote['quantidade']
            calculated = totals(states)
            duck_totals = Counter({(v['uf'],v['eleicao'],v['tipo_voto'],v['numero']):v['quantidade'] for v in calculated['votes_by_uf']})
            if python_totals != duck_totals:
                raise ValueError('Python/DuckDB totals disagree')
            reconciliation = reconcile_bweb(states[1], bweb_zz())
            if reconciliation['vote_differences'] or reconciliation['unexpected_metric_differences']:
                result['bweb_reconciliation'] = reconciliation
                raise ValueError('ZZ BU/BWeb reconciliation differs; inspect pilot.json')
            if calculated['missing_image_checks']:
                raise ValueError('pilot requires a printed-image comparison for every presidential BU')
            result.update({'passed':True,'totals':calculated,'bweb_reconciliation':reconciliation,
                           'python_duckdb_agreement':True,'checkpoints':[str(root()/ 'data/checkpoints'/f'{s["dataset_id"]}.json') for s in states]})
        except Exception as e:
            result['error'] = str(e)
            raise
        finally:
            result.update({'finished_utc':now(),'elapsed_seconds':time.monotonic()-start})
            atomic_json(gate_path,result)
            emit('pilot_finished',passed=result['passed'],seconds=result['elapsed_seconds'],error=result.get('error'))
    return result
