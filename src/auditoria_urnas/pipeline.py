"""Single-worker, bounded-memory ingestion with atomic batch checkpoints."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import resource
import signal
import shutil
import time
import zipfile
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .common import atomic_json, digest, emit, now, root, signature, stat_key
from .parser import Decoder

BATCH_SIZE = 5000
MIN_FREE = 20 * 1024 ** 3
B_COLUMNS = ['bu_id','uf','municipio','zona','secao','local','pleito','origem','membro','urna','tipo_urna',
             'tipo_arquivo','codigo_carga','versao_software','comparecimento_bu_original','sem_biometria_cadastrada',
             'habilitados_biometria','habilitados_biografia','abertura_original','encerramento_original',
             'emissao_original','geracao_original','fuso','fuso_status','encerramento_brasilia','emissao_brasilia',
             'agregadas_json','historico_cargas_json','dados_sa_json','imagem_sha256','assinatura_digital',
             'arquivo_sha256']
B_INTS = {'municipio','zona','secao','local','pleito','urna','tipo_urna','tipo_arquivo','comparecimento_bu_original',
          'sem_biometria_cadastrada','habilitados_biometria','habilitados_biografia'}
SCHEMAS = {
    'boletins': pa.schema([(n, pa.int64() if n in B_INTS else pa.string()) for n in B_COLUMNS]),
    'eleicoes': pa.schema([(n, pa.string() if n == 'bu_id' else pa.bool_() if n == 'conferido_imagem' else pa.int64())
                           for n in ['bu_id','eleicao','cargo','aptos','aptos_originais','aptos_temporarios',
                                     'comparecimento','abstencoes','conferido_imagem']]),
    'votos': pa.schema([(n, pa.string() if n == 'bu_id' else pa.int64())
                        for n in ['bu_id','eleicao','cargo','tipo_voto','numero','partido','quantidade']])}


def validation(row: dict) -> dict:
    path = Path(row['path'])
    before = stat_key(path)
    start = time.monotonic()
    h, h512 = hashlib.sha256(), hashlib.sha512()
    with path.open('rb') as f:
        while b := f.read(8 * 1024 * 1024):
            h.update(b)
            h512.update(b)
    error = None
    crc = 'not_completed'
    try:
        with zipfile.ZipFile(path) as z:
            names = [i.filename for i in z.infolist()]
            if len(names) != len(set(names)):
                raise ValueError('duplicate archive names; version selection required')
            if bad := z.testzip():
                raise ValueError(f'CRC failure in {bad}')
        crc = 'passed'
    except (zipfile.BadZipFile, ValueError, OSError) as e:
        error = str(e)
        crc = 'failed'
    if stat_key(path) != before:
        error = 'input changed while hashing/CRC checking'
    expected = int(row.get('http', {}).get('content-length') or 0)
    if expected and before[2] != expected:
        error = error or 'local size differs from published size'
    result = {'uf': row['uf'], 'path': str(path), 'stat': list(before), 'bytes': before[2],
              'sha256': h.hexdigest(), 'sha512': h512.hexdigest(), 'zip_crc': crc,
              'official_outer_hash': 'unavailable', 'signature_authenticity': 'not_verified',
              'checked_utc': now(), 'elapsed_seconds': time.monotonic() - start, 'error': error}
    atomic_json(root() / f'data/checkpoints/validation-{row["uf"]}.json', result)
    emit('archive_validated', **result)
    if error:
        raise ValueError(error)
    return result


def write_batch(directory: Path, index: int, rows: dict) -> dict:
    if shutil.disk_usage(root()).free < MIN_FREE:
        raise OSError('less than 20 GiB free; stopping before next batch')
    files = {}
    for table, values in rows.items():
        destination = directory / f'{table}-{index:05}.parquet'
        part = destination.with_suffix('.parquet.part')
        pq.write_table(pa.Table.from_pylist(values, schema=SCHEMAS[table]), part, compression='zstd')
        with part.open('rb') as f:
            os.fsync(f.fileno())
        os.replace(part, destination)
        files[table] = {'path': str(destination), 'sha256': digest(destination), 'rows': len(values)}
    return files


def input_identity(b):
    return b['uf'], b['municipio'], b['zona'], b['secao'], b['pleito']


def ingest(row: dict, checked: dict, *, stop_after_batches=None) -> dict:
    code = signature()
    dataset_id = f'{row["uf"]}-{checked["sha256"][:16]}-{code[:16]}'
    directory = root() / 'data/derived' / dataset_id
    directory.mkdir(parents=True, exist_ok=True)
    checkpoint_path = root() / 'data/checkpoints' / f'{dataset_id}.json'
    state = json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else {
        'dataset_id': dataset_id, 'uf': row['uf'], 'input_sha256': checked['sha256'], 'parser_signature': code,
        'processed_bu': 0, 'batches': [], 'complete': False, 'started_utc': now()}
    if state.get('input_sha256') != checked['sha256'] or state.get('parser_signature') != code:
        raise ValueError('checkpoint provenance mismatch')
    seen = set()
    for batch in state['batches']:
        for item in batch.values():
            if not Path(item['path']).exists() or digest(Path(item['path'])) != item['sha256']:
                raise ValueError('published Parquet missing or changed')
        for b in pq.ParquetFile(batch['boletins']['path']).read().to_pylist():
            key = input_identity(b)
            if key in seen:
                raise ValueError('duplicate section in committed checkpoint')
            seen.add(key)
    if state['complete']:
        return state
    overrides = root() / 'config/timezones.json'
    decoder = Decoder(root() / 'specs', json.loads(overrides.read_text()) if overrides.exists() else {})
    path = Path(row['path'])
    before = stat_key(path)
    if list(before) != checked['stat']:
        raise ValueError('input changed after validation')
    buffers = {k: [] for k in SCHEMAS}
    processed = state['processed_bu']
    def flush():
        nonlocal buffers
        if stat_key(path) != before:
            raise ValueError('input changed during ingestion')
        batch = write_batch(directory, len(state['batches']), buffers)
        state['batches'].append(batch)
        state['processed_bu'] = processed
        state['updated_utc'] = now()
        atomic_json(checkpoint_path, state)
        emit('batch_committed', uf=row['uf'], processed_bu=processed, batches=len(state['batches']))
        buffers = {k: [] for k in SCHEMAS}
    with zipfile.ZipFile(path) as z:
        infos = [i for i in z.infolist() if i.filename.endswith(('-bu.dat', '-busa.dat'))]
        names = set(z.namelist())
        for ordinal, info in enumerate(infos):
            if ordinal < state['processed_bu']:
                continue
            if info.file_size > 16 * 1024 * 1024:
                raise ValueError(f'oversize BU: {info.filename}')
            image_name = info.filename.replace('-busa.dat', '-imgbusa.dat').replace('-bu.dat', '-imgbu.dat')
            if image_name in names and z.getinfo(image_name).file_size > 16 * 1024 * 1024:
                raise ValueError(f'oversize image: {image_name}')
            try:
                b, elections, votes = decoder.decode(info.filename, z.read(info),
                    z.read(image_name) if image_name in names else None, row['uf'])
            except Exception as e:
                raise ValueError(f'{info.filename}: {e}') from e
            if input_identity(b) in seen:
                raise ValueError(f'ambiguous duplicate section: {info.filename}; no arbitrary BU selection')
            seen.add(input_identity(b))
            b['arquivo_sha256'] = checked['sha256']
            buffers['boletins'].append(b)
            buffers['eleicoes'].extend(elections)
            buffers['votos'].extend(votes)
            processed += 1
            if len(buffers['boletins']) >= BATCH_SIZE:
                flush()
                if stop_after_batches is not None and len(state['batches']) >= stop_after_batches:
                    return state
        if buffers['boletins']:
            flush()
    if processed != len(infos) or not processed or stat_key(path) != before:
        raise ValueError('incomplete/unstable ingestion')
    state.update({'complete': True, 'completed_utc': now(), 'max_rss_MiB': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024})
    atomic_json(checkpoint_path, state)
    return state


def connection(states: list[dict]):
    db = duckdb.connect(config={'memory_limit': '6GiB', 'threads': '4', 'temp_directory': str(root() / 'data/tmp/duckdb')})
    for table in SCHEMAS:
        paths = [batch[table]['path'] for state in states for batch in state['batches']]
        if not paths:
            raise ValueError('no committed data')
        db.from_parquet(paths, union_by_name=True).create_view(table)
    return db


def totals(states: list[dict]) -> dict:
    with connection(states) as db:
        duplicates = db.execute('SELECT count(*) FROM (SELECT uf,municipio,zona,secao,pleito FROM boletins GROUP BY ALL HAVING count(*)>1)').fetchone()[0]
        if duplicates:
            raise ValueError('duplicate section identity across selected datasets')
        rows = db.execute('''SELECT b.uf,b.pleito,v.eleicao,v.tipo_voto,v.numero,sum(v.quantidade)::BIGINT quantidade
            FROM votos v JOIN boletins b USING(bu_id) WHERE v.cargo=1 GROUP BY ALL ORDER BY 1,2,3,4,5''').fetchall()
        electorate = db.execute('''SELECT b.uf,b.pleito,e.eleicao,count(*) secoes,sum(aptos)::BIGINT aptos,
            sum(comparecimento)::BIGINT comparecimento,sum(abstencoes)::BIGINT abstencoes
            FROM eleicoes e JOIN boletins b USING(bu_id) WHERE cargo=1 GROUP BY ALL ORDER BY 1,2,3''').fetchall()
        missing_images = db.execute('SELECT count(*) FROM eleicoes WHERE cargo=1 AND NOT conferido_imagem').fetchone()[0]
        unresolved = db.execute("SELECT uf,count(*) FROM boletins WHERE fuso_status='nao_resolvido' GROUP BY uf").fetchall()
    return {'votes_by_uf': [dict(zip(['uf','pleito','eleicao','tipo_voto','numero','quantidade'], r)) for r in rows],
            'electorate_by_uf': [dict(zip(['uf','pleito','eleicao','secoes','aptos','comparecimento','abstencoes'], r)) for r in electorate],
            'missing_image_checks': missing_images, 'unresolved_timezones_by_uf': unresolved,
            'coverage': 'partial' if len({s['uf'] for s in states}) < 28 else 'all_28_archive_regions_ingested',
            'national_official_reconciliation': 'pending_independent_official_snapshot',
            'signature_authenticity': 'not_verified'}


def process(ufs: list[str], *, require_pilot=True):
    def terminate(signum, frame):
        raise KeyboardInterrupt('termination requested; committed checkpoints preserved')
    signal.signal(signal.SIGTERM, terminate)
    with (root() / 'data/checkpoints/pipeline.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if require_pilot:
            gate = json.loads((root() / 'output/reports/pilot.json').read_text())
            if not gate.get('passed') or gate.get('parser_signature') != signature():
                raise ValueError('pilot not passed for this code/schema/config version')
        inv = json.loads((root() / 'data/catalog/inventory.json').read_text())
        run_id = now().replace(':','').replace('.','')
        run = {'run_id': run_id, 'started_utc': now(), 'parser_signature': signature(),
               'requested_ufs': ufs, 'completed': [], 'failures': [], 'status': 'running', 'pid': os.getpid()}
        run_path = root() / 'data/checkpoints' / f'run-{run_id}.json'
        atomic_json(root() / 'data/checkpoints/latest-run.json', {'path': str(run_path), 'pid': os.getpid()})
        atomic_json(run_path, run)
        states = []
        try:
            for uf in ufs:
                if signature() != run['parser_signature']:
                    raise ValueError('source/configuration changed during run')
                row = next(x for x in inv['files'] if x['uf'] == uf)
                if not row['eligible_for_validation']:
                    if row.get('path') and row.get('present'):
                        try:
                            validation(row)
                        except Exception as e:
                            emit('invalid_archive_fingerprinted', uf=uf, error=str(e))
                    run['failures'].append({'uf': uf, 'stage': 'inventory', 'reason': row.get('error','missing/size mismatch')})
                    atomic_json(run_path, run)
                    continue
                emit('processing_uf', uf=uf)
                try:
                    checked = validation(row)
                    state = ingest(row, checked)
                    states.append(state)
                    run['completed'].append({'uf': uf, 'checkpoint': str(root() / 'data/checkpoints' / f'{state["dataset_id"]}.json')})
                    atomic_json(root() / 'output/reports/totals.json', totals(states))
                except Exception as e:
                    run['failures'].append({'uf': uf, 'stage': 'validation_or_ingestion', 'reason': str(e)})
                    emit('uf_failed', uf=uf, reason=str(e))
                atomic_json(run_path, run)
            run['status'] = 'complete_with_gaps' if run['failures'] else 'complete'
        except BaseException:
            run['status'] = 'interrupted'
            raise
        finally:
            run['finished_utc'] = now()
            atomic_json(run_path, run)
        try:
            from .report import reports
            reports()
        except Exception as e:
            emit('final_report_failed', reason=str(e))
            run['report_error'] = str(e)
            atomic_json(run_path, run)
        emit('run_finished', status=run['status'], completed=len(run['completed']), failures=run['failures'])
        return run
