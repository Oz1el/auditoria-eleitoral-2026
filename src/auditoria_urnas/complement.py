"""Incremental national RDV/log/signature audit, with isolated file failures."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import signal
import tarfile
import time
import traceback
import zipfile
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .common import UFS,atomic_json,digest,emit,now,root,signature,stat_key
from .complement_parsers import parse_rdv,parse_log,verify_signatures

STAGES=['rdv','logs','assinaturas','bweb','correspondencias','estatisticas','comparacoes','relatorios']
BATCH=100
MIN_FREE=20*1024**3
COLUMNS=['bu_id','uf','municipio','municipio_nome','zona','secao','pleito','origem','membro','urna','codigo_carga',
         'comparecimento','aptos','abstencoes','lula','bolsonaro','brancos','nulos','validos','fuso_analise',
         'encerramento_brasilia_analise','encerramento_original','habilitados_biografia','sem_biometria_cadastrada','habilitados_biometria','agregadas_json']


def complement_signature():
    h=hashlib.sha256(signature().encode())
    for folder in ['docs/relatorio_original','docs/evidencias-documentais']:
        for p in sorted((root()/folder).glob('*')):
            if p.is_file():h.update(p.name.encode());h.update(p.read_bytes())
    return h.hexdigest()


def base_data():
    from .evidence import verify_context
    context=verify_context()
    latest=json.loads((root()/'data/checkpoints/latest-analysis.json').read_text())
    if latest['status']!='complete':raise ValueError('completed national BU analysis required')
    folder=Path(latest['output']);manifest=json.loads((folder/'input-manifest.json').read_text())
    for item in manifest['files']:
        if digest(Path(item['path']))!=item['sha256']:raise ValueError('committed input Parquet changed')
    source=folder/'secoes.parquet'
    return {'context_evidence':context,'analysis':latest,'sections':str(source),'sha256':digest(source),'manifest_sha256':digest(folder/'input-manifest.json')}


def state_sources(ufs):
    pointer=json.loads((root()/'data/checkpoints/latest-run.json').read_text())
    combined=json.loads(Path(pointer['path']).read_text())
    sources={}
    for uf in ufs:
        selected=next(s for s in combined['completed'] if s['uf']==uf)
        state=json.loads(Path(selected['checkpoint']).read_text())
        validated=json.loads((root()/f'data/checkpoints/validation-{uf}.json').read_text())
        if not state['complete'] or validated['sha256']!=state['input_sha256'] or validated.get('error'):
            raise ValueError('selected state and validation mismatch: '+uf)
        path=Path(validated['path'])
        current=list(stat_key(path))
        if current!=validated['stat']:
            if digest(path)!=state['input_sha256']:raise ValueError('selected raw archive changed: '+uf)
        sources[uf]={'path':str(path),'sha256':state['input_sha256'],'stat':current,'checkpoint':selected['checkpoint']}
    return sources


def section_rows(base,uf):
    return sorted(pq.read_table(base['sections'],columns=COLUMNS,filters=[('uf','=',uf)]).to_pylist(),key=lambda x:x['membro'])


def section_result(section,archive,names,stages,*,crypto=True,recovered=None):
    result={k:section[k] for k in ['bu_id','uf','municipio','zona','secao','origem','urna','comparecimento']}
    if 'rdv' in stages:result.update(rdv_concorda_bu=None)
    if 'logs' in stages:result.update(log_total_computados=None,log_concorda_comparecimento=None,log_contagem_temporal_confiavel=None,log_apos17=None,log_17_18=None,log_18_19=None,log_apos19=None)
    if 'assinaturas' in stages:result.update(assinatura_hashes_incompativeis=None,assinatura_hw_verificadas=None,assinatura_hw_invalidas=None,assinatura_cadeia=None)
    prefix=section['membro'].rsplit('-',1)[0];cache={}
    def read(name):
        if name not in cache:cache[name]=archive.read(name)
        return cache[name]
    def invoke(stage,member,fn):
        result[stage+'_membro']=member
        if member not in names:
            if stage=='log' and recovered:
                data=Path(recovered['path']).read_bytes()
                if hashlib.sha256(data).hexdigest()!=recovered['sha256']:raise ValueError('recovered log changed')
                result[stage+'_sha256']=recovered['sha256'];result.update(fn(data));return
            result[stage+'_status']='ausente';return
        try:
            data=read(member);result[stage+'_sha256']=hashlib.sha256(data).hexdigest();result.update(fn(data))
        except Exception as e:
            result[stage+'_status']='erro';result[stage+'_erro']=type(e).__name__+': '+str(e)[:300]
    if 'rdv' in stages:
        invoke('rdv',prefix+'-rdv.dat',lambda raw:parse_rdv(raw,(section['municipio'],section['zona'],section['secao'])))
        if result.get('rdv_status')=='ok':
            diffs={k:result['rdv_'+k]-section[k] for k in ['lula','bolsonaro','brancos','nulos']}
            diffs['total']=result['rdv_total']-section['comparecimento']
            result['rdv_concorda_bu']=not any(diffs.values()) and result['rdv_outros']==0
            result['rdv_diferencas_json']=json.dumps(diffs)
    if 'logs' in stages:
        invoke('log',prefix+('-logsa.jez' if section['origem']=='dadosSA' else '-log.jez'),
               lambda raw:parse_log(raw,section['fuso_analise'],section['origem'],(section['municipio'],section['zona'],section['secao'])))
        if result.get('log_total_computados') is not None:
            result['log_concorda_comparecimento']=result['log_total_computados']==section['comparecimento']
            result['log_concorda_confirmacoes']=result['log_total_confirmados_presidente']==section['comparecimento']
            result['log_contagem_temporal_confiavel']=result['log_contagem_temporal_confiavel'] and result['log_concorda_comparecimento'] and result['log_concorda_confirmacoes']
    if 'assinaturas' in stages:
        invoke('assinatura',prefix+('-sa.vsc' if section['origem']=='dadosSA' else '-vota.vsc'),
               lambda raw:verify_signatures(raw,read,names.__contains__,verify_crypto=crypto))
    return result


def commit_batch(directory,index,rows):
    if shutil.disk_usage(root()).free<MIN_FREE:raise OSError('less than 20 GiB free')
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/f'batch-{index:06}.parquet';temp=path.with_suffix('.parquet.part')
    keys=sorted({k for row in rows for k in row})
    normalized=[{k:row.get(k) for k in keys} for row in rows]
    pq.write_table(pa.Table.from_pylist(normalized),temp,compression='zstd')
    with temp.open('rb') as f:os.fsync(f.fileno())
    os.replace(temp,path)
    return {'path':str(path),'sha256':digest(path),'rows':len(rows)}


def process_state(uf,base,source,stages,version,update,*,limit=None,crypto=True,recovery=None,pilot=False,workers=4):
    from .complement_workers import parallel_sections,worker_cpus
    from .complement_resume import import_legacy,validate_batches
    cpus=worker_cpus(workers)
    key=hashlib.sha256(json.dumps({'source':source['sha256'],'base':base['sha256'],'code':version,'stages':sorted(stages),'crypto':crypto,'limit':limit,'workers':workers},sort_keys=True).encode()).hexdigest()[:24]
    directory=root()/'data/derived/complementar'/('pilot' if pilot else 'national')/uf/key
    checkpoint=root()/'data/checkpoints/complementar'/('pilot' if pilot else 'national')/f'{uf}-{key}.json'
    rows=section_rows(base,uf)
    if limit is not None:
        normal=[r for r in rows if r['origem']=='dadosSecao']
        sa=[r for r in rows if r['origem']=='dadosSA']
        rows=normal[:limit]+sa
        rows.sort(key=lambda x:x['membro'])
    if checkpoint.exists():state=json.loads(checkpoint.read_text())
    else:
        state={'uf':uf,'source':source,'base':base,'version':version,'stages':stages,'crypto':crypto,
               'batches':[],'processed':0,'total':len(rows),'status':'running','created_utc':now(),'elapsed_seconds':0.0}
        imported=import_legacy(uf,base,source,stages,version,rows,crypto=crypto,limit=limit) if not pilot else None
        if imported:
            state.update(batches=imported['batches'],processed=imported['processed'],status=imported['status'],
                         reused_from=imported['provenance'],previous_elapsed_seconds=imported['previous_elapsed_seconds'])
    validate_batches(state,rows)
    initial=state['processed'];state.update(workers=workers,physical_cpu_ids=cpus,reused_sections=initial,
        session_processed=0,session_elapsed_seconds=0.0,session_started_utc=now())
    atomic_json(checkpoint,state);update(state)
    if state['status']=='complete':return state,str(checkpoint)
    start=time.monotonic();batch_rows=[]
    results=parallel_sections(rows[initial:],source['path'],stages,workers=workers,crypto=crypto,recovery=recovery)
    try:
        for result in results:
            if not batch_rows and complement_signature()!=version:raise ValueError('source/configuration changed during processing')
            expected=rows[state['processed']+len(batch_rows)]['bu_id']
            if result['bu_id']!=expected:raise ValueError('worker result identity/order mismatch')
            batch_rows.append(result)
            if len(batch_rows)>=BATCH:
                state['batches'].append(commit_batch(directory,len(state['batches']),batch_rows))
                state['processed']+=len(batch_rows);batch_rows=[]
                elapsed=time.monotonic()-start;state['elapsed_seconds']+=elapsed
                state['session_elapsed_seconds']+=elapsed;state['session_processed']=state['processed']-initial
                start=time.monotonic();state['updated_utc']=now();atomic_json(checkpoint,state);update(state)
        if batch_rows:
            state['batches'].append(commit_batch(directory,len(state['batches']),batch_rows));state['processed']+=len(batch_rows)
    finally:results.close()
    if list(stat_key(Path(source['path'])))!=source['stat']:raise ValueError('raw archive changed during read')
    elapsed=time.monotonic()-start
    state.update(status='complete',completed_utc=now(),elapsed_seconds=state['elapsed_seconds']+elapsed,
                 session_elapsed_seconds=state['session_elapsed_seconds']+elapsed,session_processed=state['processed']-initial)
    atomic_json(checkpoint,state);update(state)
    return state,str(checkpoint)


def summary(states,output):
    paths=[b['path'] for s in states for b in s['batches']]
    if not paths:return {}
    db=duckdb.connect(config={'memory_limit':'6GiB','threads':'4','temp_directory':str(root()/'data/tmp/complement-duckdb')})
    db.read_parquet(paths,union_by_name=True).create_view('c')
    columns={r[0] for r in db.execute('describe c').fetchall()}
    totals={'sections':db.execute('select count(*) from c').fetchone()[0]}
    if 'rdv_status' in columns:
        totals['rdv']=db.execute('''select count(*) filter(where rdv_status='ok'),count(*) filter(where rdv_concorda_bu),
         count(*) filter(where rdv_status='erro'),count(*) filter(where rdv_status='ausente') from c''').fetchone()
        selection='* exclude(assinatura_itens_json)' if 'assinatura_itens_json' in columns else '*'
        db.execute("copy (select "+selection+" from c where rdv_concorda_bu is false) to ? (header,delimiter ',')",[str(output/'rdv-divergencias.csv')])
    if 'log_status' in columns:
        totals['logs']={'status_counts':db.execute('select log_status,count(*) from c group by 1').fetchall(),
            'trusted_domestic':db.execute("select count(*) from c where uf!='ZZ' and log_contagem_temporal_confiavel").fetchone()[0],
            'observed_late':dict(zip(['apos17','17_18','18_19','apos19'],db.execute("select sum(log_apos17),sum(log_17_18),sum(log_18_19),sum(log_apos19) from c where uf!='ZZ' and log_contagem_temporal_confiavel").fetchone())),
            'unresolved_turnout_upper_bound':db.execute("select coalesce(sum(comparecimento),0) from c where uf!='ZZ' and (log_contagem_temporal_confiavel is not true)").fetchone()[0]}
        db.execute("copy (select uf,municipio,zona,secao,comparecimento,log_status,log_total_computados,log_concorda_comparecimento,log_contagem_temporal_confiavel from c where log_contagem_temporal_confiavel is not true) to ? (header,delimiter ',')",[str(output/'logs-limitacoes.csv')])
    if 'assinatura_status' in columns:
        totals['signatures']={'status_counts':db.execute('select assinatura_status,count(*) from c group by 1').fetchall(),
            'hash_mismatches':db.execute('select sum(assinatura_hashes_incompativeis) from c').fetchone()[0],
            'hw_verified':db.execute('select sum(assinatura_hw_verificadas) from c').fetchone()[0],
            'hw_invalid':db.execute('select sum(assinatura_hw_invalidas) from c').fetchone()[0],
            'issuer_status_counts':db.execute('select assinatura_cadeia,count(*) from c group by 1').fetchall(),
            'trust_limit':'emissor embutido no pacote oficial; sem validação completa RFC5280/revogação; CEPESC SW não verificado'}
    atomic_json(output/'summary.json',totals)
    db.close();return totals


def pilot(workers=4):
    from .complement_sources import prepare
    version=complement_signature()
    output=root()/'output/complementar/pilots'/version/f'workers-{workers}';output.mkdir(parents=True,exist_ok=True)
    base=base_data();sources=state_sources(['RR','ZZ']);states=[]
    for uf in ['RR','ZZ']:
        state,_=process_state(uf,base,sources[uf],['rdv','logs','assinaturas'],version,lambda x:emit('complement_pilot_progress',uf=uf,processed=x['processed']),limit=128,pilot=True,workers=workers)
        states.append(state)
    value=summary(states,output)
    if value['rdv'][0]!=value['sections'] or value['rdv'][1]!=value['sections']:raise ValueError('pilot RDV comparison failed; investigate before launch')
    if value['logs']['trusted_domestic']==0:raise ValueError('pilot did not verify any domestic vote timing')
    if any(kind=='erro' for kind,count in value['logs']['status_counts']):raise ValueError('pilot contains unhandled log format')
    if value['signatures']['hash_mismatches'] or value['signatures']['hw_invalid'] or value['signatures']['hw_verified']==0:
        raise ValueError('pilot cryptographic verification failed')
    # Exercise observed BWeb/correspondence schemas in both pilot regions.
    acquired=prepare(['RR','ZZ'],output,refresh=False)
    from .complement_tables import reconcile_tables
    tabular=reconcile_tables(base,acquired,output)
    if any(x.get('parse_error') for x in tabular):raise ValueError('pilot tabular parser failed')
    for uf in ['RR','ZZ']:
        for kind in ['bweb','esperadas','efetivadas']:
            if not any(x['uf']==uf and x['kind']==kind and x['status']=='complete' for x in tabular):
                raise ValueError('pilot missing verified tabular source '+uf+':'+kind)
    from .complement_statistics import advanced
    from .complement_report import reports
    pilot_table=pq.read_table(base['sections'],filters=[('uf','in',['RR','ZZ'])])
    pilot_path=output/'secoes-piloto.parquet';pq.write_table(pilot_table,pilot_path,compression='zstd')
    advanced({**base,'sections':str(pilot_path),'sha256':digest(pilot_path)},output,simulations=20)
    reports(base,output,{'status':'piloto_RR_ZZ_concluido_nacional_pendente','completed_stages':['piloto_RR_ZZ'],'failures':[]},value)
    gate={'passed':True,'signature':version,'workers':workers,'finished_utc':now(),'summary':value,'tabular':tabular,
          'elapsed_seconds':sum(s['elapsed_seconds'] for s in states),'sections':value['sections'],'output':str(output)}
    atomic_json(output/'gate.json',gate)
    pointer=root()/'output/complementar/pilot/gate.json'
    if pointer.exists():
        previous=json.loads(pointer.read_text())
        atomic_json(root()/'output/complementar/pilot/gate-history'/f"{previous['signature']}-workers-{previous.get('workers',1)}.json",previous)
    atomic_json(pointer,gate)
    emit('complement_pilot_passed',sections=value['sections'])


def run(ufs,stages,simulations=1000,workers=4):
    if not set(ufs).issubset(UFS) or not set(stages).issubset(STAGES):raise ValueError('unknown region/stage')
    from .complement_workers import worker_cpus
    cpus=worker_cpus(workers)
    version=complement_signature()
    gate=json.loads((root()/'output/complementar/pilot/gate.json').read_text())
    if not gate['passed'] or gate['signature']!=version or gate.get('workers')!=workers:raise ValueError('current complement pilot with matching workers required')
    def stop(signum,frame):raise KeyboardInterrupt('termination; committed checkpoints retained')
    signal.signal(signal.SIGTERM,stop)
    lockpath=root()/'data/checkpoints/complementar.lock'
    with lockpath.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        folder=root()/'output/complementar'/now().replace(':','').replace('.','');folder.mkdir(parents=True)
        status={'status':'running','pid':os.getpid(),'started_utc':now(),'output':str(folder),'signature':version,
                'ufs':ufs,'stages':stages,'completed_states':[],'completed_stages':[],'failures':[],'simulations':simulations,
                'workers':workers,'physical_cpu_ids':cpus,'gpu_used':False,'audit_closed':False,'pid_start_ticks':Path(f'/proc/{os.getpid()}/stat').read_text().rsplit(')',1)[1].split()[19],'progress':{}}
        pointer=root()/'data/checkpoints/latest-complement.json'
        def save():atomic_json(folder/'status.json',status);atomic_json(pointer,status)
        save();states=[]
        try:
            base=base_data();sources=state_sources(ufs)
            counts=pq.read_table(base['sections'],columns=['uf']).to_pandas()['uf'].value_counts().to_dict()
            atomic_json(folder/'inputs.json',{'base':base,'sources':sources,'signature':version})
            import sys,platform,importlib.metadata
            atomic_json(folder/'environment.json',{'python':sys.version,'platform':platform.platform(),'signature':version,'parameters':{'ufs':ufs,'stages':stages,'simulations':simulations,'workers':workers,'physical_cpu_ids':cpus},'packages':{name:importlib.metadata.version(name) for name in ['duckdb','pyarrow','numpy','scipy','statsmodels','plotly','ECPy','pyOpenSSL']},'uv_lock_sha256':digest(root()/'uv.lock'),'backend':f'CPU, {workers} file processes on distinct physical cores; BLAS/OMP 1; DuckDB up to 4 threads'})
            with tarfile.open(folder/'source-code.tar.gz','x:gz') as archive:
                for p in ['src','tests','scripts','specs','docs','postman','uv.lock','pyproject.toml']:
                    archive.add(root()/p,arcname=p,filter=lambda info:None if '__pycache__' in info.name else info)
            acquired=[]
            if any(x in stages for x in ['bweb','correspondencias']):
                from .complement_sources import prepare
                kinds=(['bweb'] if 'bweb' in stages else [])+(['esperadas','efetivadas'] if 'correspondencias' in stages else [])
                acquired=prepare(ufs,folder,refresh=True,kinds=kinds)
                status['completed_stages'].append('fontes_complementares');save()
            recovery=None
            if 'SP' in ufs and 'logs' in stages:
                try:
                    from .complement_sources import recover_missing_sp
                    rec=recover_missing_sp(folder);recovery=rec['logs'][-1] if rec['logs'] else None
                except Exception as e:status['failures'].append({'stage':'sp_recovery','error':str(e)});save()
            file_stages=[s for s in stages if s in ['rdv','logs','assinaturas']]
            finished_new=0;finished_elapsed=0.0
            for uf in ufs if file_stages else []:
                def update(s):
                    measured=finished_new+s['session_processed'];elapsed=finished_elapsed+s['session_elapsed_seconds']
                    speed=measured/elapsed if elapsed and measured else None
                    completed=sum(x['processed'] for x in states)+s['processed']
                    reused=sum(x['reused_sections'] for x in states)+s['reused_sections']
                    status['progress']={'uf':uf,'processed':s['processed'],'total':s['total'],
                        'workers':workers,'physical_cpu_ids':cpus,'national_processed':completed,
                        'national_total':sum(counts[x] for x in ufs),'reused_sections':reused,
                        'new_sections_this_run':measured,'measured_seconds_this_run':elapsed,
                        'sections_per_second':speed,'estimated_remaining_seconds':(sum(counts[x] for x in ufs)-completed)/speed if speed else None,
                        'eta_scope':'RDV/log/signature file stage only'}
                    save();emit('complement_progress',**status['progress'])
                try:
                    state,path=process_state(uf,base,sources[uf],file_stages,version,update,recovery=recovery,workers=workers)
                    states.append(state);finished_new+=state['session_processed'];finished_elapsed+=state['session_elapsed_seconds']
                    status['completed_states'].append({'uf':uf,'checkpoint':path,'reused_sections':state['reused_sections']});save()
                except (ValueError,OSError,zipfile.BadZipFile) as e:
                    status['failures'].append({'stage':'files','uf':uf,'error':str(e)});save()
                    if isinstance(e,OSError) or 'changed' in str(e):raise
            totals=summary(states,folder);status['completed_stages']+=file_stages;save()
            if any(s in stages for s in ['bweb','correspondencias']):
                from .complement_tables import reconcile_tables
                table_results=reconcile_tables(base,acquired,folder)
                for entry in table_results:
                    if entry['status']!='complete':status['failures'].append({'stage':entry['kind'],'uf':entry['uf'],'error':entry.get('parse_error',entry['status'])})
                status['completed_stages']+=[s for s in ['bweb','correspondencias'] if s in stages];save()
            if 'estatisticas' in stages:
                from .complement_statistics import advanced
                advanced(base,folder,simulations=simulations,ufs=ufs);status['completed_stages'].append('estatisticas');save()
            if 'comparacoes' in stages:
                from .complement_comparisons import compare
                profiles=compare(folder,ufs=ufs)
                for profile in profiles:
                    if profile['status']!='complete':status['failures'].append({'stage':'comparacoes','year':profile['year'],'error':profile.get('error')})
                status['completed_stages'].append('comparacoes');save()
            if 'relatorios' in stages:
                from .complement_report import reports
                reports(base,folder,{**status,'status':'processamento_concluido_com_limitacoes','completed_stages':[*status['completed_stages'],'relatorios']},totals);status['completed_stages'].append('relatorios');save()
            if complement_signature()!=version:raise ValueError('source/documentation changed during execution')
            status.update(status='complete_with_limitations' if status['failures'] else 'complete',finished_utc=now())
            save();emit('complement_complete',output=str(folder),status=status['status'])
        except BaseException as e:
            status.update(status='interrupted' if isinstance(e,KeyboardInterrupt) else 'failed',error=str(e),traceback=traceback.format_exc(),finished_utc=now())
            save();raise
        return status
