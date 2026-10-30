"""Verified, non-destructive import of the original interrupted checkpoints."""
from __future__ import annotations
import ast
import hashlib
from importlib import metadata
import json
from pathlib import Path
import tarfile
import tomllib

import pyarrow.parquet as pq
from .common import atomic_json,digest,emit,now,root

# This is the explicitly preserved run, not a glob over arbitrary derived files.
LEGACY_RUN='output/complementar/2026-10-29T132342515328+0000'
LEGACY_SIGNATURE='3601c7c3b6b9cd8ccc6382fb943c14ac82b5dc10db2ea1e17aa9f98d8701b11d'
IDENTITY=['bu_id','uf','municipio','zona','secao','origem','urna','comparecimento']


def _function(content,name):
    tree=ast.parse(content)
    node=next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    return ast.dump(node,include_attributes=False)


def _snapshot_signature(read,names):
    paths=sorted(n for n in names if n.startswith('src/') and n.endswith('.py'))
    paths+=sorted(n for n in names if n.startswith('specs/') and n.endswith('.asn1') and len(Path(n).parts)==2)
    paths+=sorted(n for n in names if n.startswith('scripts/') and n.endswith('.py') and len(Path(n).parts)==2)
    paths+=sorted(n for n in names if n.startswith('scripts/') and n.endswith('.sh') and len(Path(n).parts)==2)
    paths+=sorted(n for n in names if n.startswith('tests/') and n.endswith('.py') and len(Path(n).parts)==2)
    paths+=['uv.lock','pyproject.toml']
    h=hashlib.sha256()
    for name in paths:h.update(name.encode());h.update(read(name))
    tz=root()/'config/timezones.json'
    if tz.exists():h.update(b'config/timezones.json');h.update(tz.read_bytes())
    outer=hashlib.sha256(h.hexdigest().encode())
    for folder in ['docs/relatorio_original','docs/evidencias-documentais']:
        for name in sorted(n for n in names if str(Path(n).parent)==folder):
            outer.update(Path(name).name.encode());outer.update(read(name))
    return outer.hexdigest()


def compatibility():
    directory=root()/LEGACY_RUN;archive=directory/'source-code.tar.gz'
    with tarfile.open(archive,'r:gz') as snapshot:
        names={item.name for item in snapshot.getmembers() if item.isfile()}
        def read(name):
            stream=snapshot.extractfile(name)
            if stream is None:raise ValueError('missing archived source '+name)
            return stream.read()
        if _snapshot_signature(read,names)!=LEGACY_SIGNATURE:raise ValueError('legacy source snapshot signature mismatch')
        critical=['src/auditoria_urnas/complement_parsers.py','src/auditoria_urnas/common.py',
                  'src/auditoria_urnas/analysis.py','src/auditoria_urnas/official/mr_util.py']
        critical+=sorted(n for n in names if n.startswith('specs/') and n.endswith('.asn1'))
        for name in critical:
            if read(name)!=(root()/name).read_bytes():raise ValueError('incompatible parser/specification '+name)
        old_source=read('src/auditoria_urnas/complement.py');current=(root()/'src/auditoria_urnas/complement.py').read_bytes()
        for function in ['section_result','section_rows']:
            if _function(old_source,function)!=_function(current,function):raise ValueError('incompatible section function '+function)
        old_lock=tomllib.loads(read('uv.lock').decode());new_lock=tomllib.loads((root()/'uv.lock').read_text())
        current_packages={p['name']:p for p in new_lock['package']}
        # Optional GPU additions are immaterial; every original dependency must match exactly.
        for package in old_lock['package']:
            if package['name']=='auditoria-urnas':continue
            if current_packages.get(package['name'])!=package:raise ValueError('incompatible locked dependency '+package['name'])
            if package['name'] in {'asn1tools','bitstruct','pyparsing','ecpy','pyopenssl','cryptography','cffi','pycparser','pyasn1','pyasn1-modules'}:
                if metadata.version(package['name'])!=package['version']:raise ValueError('incompatible installed parser dependency '+package['name'])
        environment=json.loads((directory/'environment.json').read_text())
        for name,version in environment['packages'].items():
            if metadata.version(name)!=version:raise ValueError('incompatible installed dependency '+name)
        ecpy=json.loads(metadata.distribution('ECPy').read_text('direct_url.json'))
        expected=current_packages['ecpy']['source']['git'].split('#')[-1]
        if ecpy.get('vcs_info',{}).get('commit_id')!=expected:raise ValueError('incompatible installed ECPy revision')
    return {'legacy_signature':LEGACY_SIGNATURE,'archive':str(archive),'archive_sha256':digest(archive),'checked_utc':now()}


def validate_batches(state,rows):
    """Every committed row must be the exact ordered prefix of the selected BU base."""
    offset=0
    for batch in state['batches']:
        path=Path(batch['path'])
        if digest(path)!=batch['sha256']:raise ValueError('complementary Parquet changed')
        actual=pq.read_table(path,columns=IDENTITY).to_pylist()
        expected=[{key:r[key] for key in IDENTITY} for r in rows[offset:offset+len(actual)]]
        if len(actual)!=batch['rows'] or actual!=expected:raise ValueError('committed section identity/order mismatch')
        offset+=len(actual)
    if offset!=state['processed'] or state['total']!=len(rows):raise ValueError('committed section coverage mismatch')
    if state['status']=='complete' and offset!=len(rows):raise ValueError('incomplete checkpoint marked complete')


def import_legacy(uf,base,source,stages,version,rows,*,crypto=True,limit=None):
    log=root()/'data/checkpoints/complementar/migrations'/version/f'{uf}.json'
    result={'uf':uf,'new_signature':version,'checked_utc':now(),'status':'not_available'}
    old_key=hashlib.sha256(json.dumps({'source':source['sha256'],'base':base['sha256'],'code':LEGACY_SIGNATURE,
                  'stages':sorted(stages),'crypto':crypto,'limit':limit},sort_keys=True).encode()).hexdigest()[:24]
    path=root()/'data/checkpoints/complementar/national'/f'{uf}-{old_key}.json'
    if not path.exists():return None
    try:
        contract=compatibility();state=json.loads(path.read_text())
        if state['version']!=LEGACY_SIGNATURE or state['uf']!=uf:raise ValueError('legacy version/UF mismatch')
        if state['source']['sha256']!=source['sha256'] or state['base']['sha256']!=base['sha256']:
            raise ValueError('legacy source/base mismatch')
        if state['base']['manifest_sha256']!=base['manifest_sha256'] or sorted(state['stages'])!=sorted(stages):
            raise ValueError('legacy manifest/stages mismatch')
        validate_batches(state,rows)
        result.update(status='imported',sections=state['processed'],source_checkpoint=str(path),
                      source_checkpoint_sha256=digest(path),contract=contract)
        atomic_json(log,result)
        return {'batches':state['batches'],'processed':state['processed'],'status':state['status'],
                'provenance':result,'previous_elapsed_seconds':state['elapsed_seconds']}
    except (ValueError,KeyError,OSError,tarfile.TarError,StopIteration) as e:
        result.update(status='rejected',reason=type(e).__name__+': '+str(e));atomic_json(log,result)
        emit('complement_checkpoint_reuse_rejected',uf=uf,reason=result['reason'])
        return None
