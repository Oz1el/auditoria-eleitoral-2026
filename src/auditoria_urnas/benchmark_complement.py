"""Reproducible CPU/process and hybrid GPU trials over one frozen evidence ZIP.

GPU accelerates RDV histograms only. ASN.1 decoding, logs and official signature
verification remain on CPU. No national execution is started by this module.
"""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import io
import json
import multiprocessing as mp
import os
from pathlib import Path
import resource
import signal
import statistics
import subprocess
import sys
import threading
import time
import traceback
import zipfile

import numpy as np

from .common import atomic_json, digest, emit, now, root
from .complement import base_data, section_rows, section_result, state_sources, complement_signature
from .complement_parsers import decode_complete, rdv_codec

STAGES=['rdv','logs','assinaturas']
MODES={'cpu1':(1,False),'cpu2':(2,False),'cpu4':(4,False),'gpu1':(1,True),'gpu4':(4,True)}
_ARCHIVE=None
_NAMES=None
_HYBRID=False


def physical_cpus():
    selected=[];seen=set()
    for cpu in sorted(os.sched_getaffinity(0)):
        topology=Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
        key=((topology/'physical_package_id').read_text(),(topology/'core_id').read_text())
        if key not in seen:selected.append(cpu);seen.add(key)
    return selected


def select_rows(rows,limit):
    """Deterministic sample: preserve all manual/empty cases, hash-sample others."""
    special=[r for r in rows if r['origem']=='dadosSA' or r['comparecimento']==0]
    if len(special)>limit:raise ValueError('sample too small to include all manual/empty cases')
    ids={r['bu_id'] for r in special}
    remaining=sorted((r for r in rows if r['bu_id'] not in ids),key=lambda r:hashlib.sha256(('benchmark-20261025:'+r['bu_id']).encode()).digest())
    return sorted(special+remaining[:limit-len(special)],key=lambda r:r['bu_id'])


def prepare(folder,per_uf=1024):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    base=base_data();sources=state_sources(['RR','ZZ']);rows=[];members=[]
    target=folder/'amostra.zip';partial=target.with_suffix('.zip.part')
    with zipfile.ZipFile(partial,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as output:
        for uf in ['RR','ZZ']:
            chosen=select_rows(section_rows(base,uf),per_uf);rows.extend(chosen)
            prefixes={r['membro'].rsplit('-',1)[0] for r in chosen}
            with zipfile.ZipFile(sources[uf]['path']) as archive:
                for member in sorted(archive.namelist()):
                    if member.rsplit('-',1)[0] not in prefixes:continue
                    data=archive.read(member);output.writestr(member,data)
                    members.append({'name':member,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'source_uf':uf})
    os.replace(partial,target)
    atomic_json(folder/'rows.json',rows)
    manifest={'created_utc':now(),'source_signature':complement_signature(),'sources':sources,'base':base,
              'archive':str(target),'archive_sha256':digest(target),'rows_sha256':digest(folder/'rows.json'),
              'sections':len(rows),'national_sections':499207,'national_fraction':len(rows)/499207,
              'selection':'all SA/zero-turnout cases in RR/ZZ; remaining by fixed SHA256 order',
              'by_uf':dict(Counter(r['uf'] for r in rows)),'by_origin':dict(Counter(r['origem'] for r in rows)),
              'zero_turnout':sum(r['comparecimento']==0 for r in rows),'members':members}
    atomic_json(folder/'manifest.json',manifest)
    emit('benchmark_sample_ready',folder=str(folder),sections=len(rows),bytes=target.stat().st_size)
    return manifest


def rdv_features(raw,identity):
    """Decode on CPU; emit anonymous section/bucket labels, never voter ordering."""
    obj=decode_complete(rdv_codec(),'EntidadeResultadoRDV',raw)
    r=obj['rdv'];ident=r['identificacao'];mz=ident['municipioZona']
    if (r['fase'],r['pleito'],mz['municipio'],mz['zona'],ident['secao'])!=(2,3221,*identity):
        raise ValueError('RDV identity/phase/pleito mismatch')
    labels=[];offices=0
    for election in r['eleicoes'][1]:
        if election['idEleicao']!=6258:continue
        for office in election['votosCargos']:
            if office['idCargo']!=('cargoConstitucional',1):continue
            offices+=1
            if office['quantidadeEscolhas']!=1:raise ValueError('unexpected presidential choices')
            for vote in office['votos']:
                kind=vote['tipoVoto']
                if kind not in range(1,10):raise ValueError('unknown RDV vote enum')
                labels.append(kind)
                if kind==2:
                    if 'digitacao' not in vote:raise ValueError('nominal RDV without digits')
                    candidate=int(vote['digitacao'])
                    if candidate in (13,22):labels.append(10 if candidate==13 else 11)
    if offices!=1:raise ValueError('missing/duplicated presidential RDV office')
    # Buckets have no temporal information and are sorted before IPC/GPU transfer.
    return {'source':r['eleicoes'][0],'labels':sorted(labels)}


def finish_histogram(feature,hist):
    counts={i:int(hist[i]) for i in range(1,10) if hist[i]}
    result={'rdv_status':'ok','rdv_source':feature['source'],'rdv_lula':int(hist[10]),'rdv_bolsonaro':int(hist[11]),
            'rdv_brancos':int(hist[3]+hist[5]),'rdv_nulos':int(sum(hist[i] for i in [4,6,7,8,9])),
            'rdv_total':int(sum(hist[1:10])),'rdv_cargos_encontrados':1,'rdv_tipos_json':json.dumps(counts,sort_keys=True)}
    result['rdv_outros']=result['rdv_total']-sum(result[k] for k in ['rdv_lula','rdv_bolsonaro','rdv_brancos','rdv_nulos'])
    return result


def gpu_histograms(features,cp):
    """One batched integer histogram on GPU, with explicit synchronization."""
    keys=np.asarray([i*12+label for i,f in enumerate(features) for label in f['labels']],dtype=np.int64)
    device=cp.asarray(keys)
    counts=cp.bincount(device,minlength=len(features)*12).reshape(len(features),12)
    host=cp.asnumpy(counts);cp.cuda.get_current_stream().synchronize()
    return [finish_histogram(feature,hist) for feature,hist in zip(features,host)]


def _init_worker(archive,hybrid,queue):
    global _ARCHIVE,_NAMES,_HYBRID
    os.sched_setaffinity(0,{queue.get(timeout=20)})
    _ARCHIVE=zipfile.ZipFile(archive);_NAMES=set(_ARCHIVE.namelist());_HYBRID=hybrid


def _batch(rows):
    results=[];features=[]
    for section in rows:
        result=section_result(section,_ARCHIVE,_NAMES,['logs','assinaturas'] if _HYBRID else STAGES)
        feature=None
        if _HYBRID:
            member=section['membro'].rsplit('-',1)[0]+'-rdv.dat'
            result.update(rdv_membro=member,rdv_concorda_bu=None)
            if member not in _NAMES:result['rdv_status']='ausente'
            else:
                try:
                    raw=_ARCHIVE.read(member);result['rdv_sha256']=hashlib.sha256(raw).hexdigest()
                    feature=rdv_features(raw,(section['municipio'],section['zona'],section['secao']))
                except Exception as e:result.update(rdv_status='erro',rdv_erro=type(e).__name__+': '+str(e)[:300])
        results.append(result);features.append(feature)
    return results,features


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class Monitor:
    def __init__(self):
        self.stop_event=threading.Event();self.peak_rss=0;self.samples=[]
        self.thread=threading.Thread(target=self._loop,daemon=True)
    def _rss(self,pid):
        try:
            status=Path(f'/proc/{pid}/status').read_text()
            own=int(next(s.split()[1] for s in status.splitlines() if s.startswith('VmRSS:')))*1024
            children=Path(f'/proc/{pid}/task/{pid}/children').read_text().split()
            return own+sum(self._rss(int(child)) for child in children)
        except (FileNotFoundError,ProcessLookupError,StopIteration):return 0
    def _loop(self):
        while not self.stop_event.is_set():
            self.peak_rss=max(self.peak_rss,self._rss(os.getpid()))
            try:
                p=subprocess.run(['nvidia-smi','--query-gpu=utilization.gpu,memory.used','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=2)
                if p.returncode==0:self.samples.append(p.stdout.strip())
            except (OSError,subprocess.TimeoutExpired):pass
            self.stop_event.wait(1)
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.stop_event.set();self.thread.join(timeout=3)


def trial(folder,mode,repeat=1,limit=None):
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text())
    if digest(folder/'amostra.zip')!=manifest['archive_sha256'] or digest(folder/'rows.json')!=manifest['rows_sha256']:
        raise ValueError('benchmark frozen input changed')
    rows=json.loads((folder/'rows.json').read_text())
    if limit:rows=rows[:limit]
    workers,hybrid=MODES[mode];cpus=physical_cpus()[:workers]
    if len(cpus)!=workers:raise ValueError('not enough distinct physical CPU cores')
    os.sched_setaffinity(0,set(cpus))
    ctx=mp.get_context('spawn');queue=ctx.Queue()
    for cpu in cpus:queue.put(cpu)
    started=time.perf_counter();cpu_start=time.process_time();cp=None;gpu_startup=0.;gpu_seconds=0.
    if hybrid:
        gpu_begin=time.perf_counter()
        import cupy as cp
        cp.cuda.Device(0).use()
        gpu_histograms([{'source':'warmup','labels':[1,2,10]}],cp)
        gpu_startup=time.perf_counter()-gpu_begin
    results=[]
    chunks=[rows[i:i+32] for i in range(0,len(rows),32)]
    with Monitor() as monitor:
        with ProcessPoolExecutor(max_workers=workers,mp_context=ctx,initializer=_init_worker,
                                 initargs=(str(folder/'amostra.zip'),hybrid,queue)) as pool:
            for batch_index,(batch,features) in enumerate(pool.map(_batch,chunks)):
                if hybrid:
                    active=[i for i,f in enumerate(features) if f is not None]
                    begin=time.perf_counter()
                    aggregated=gpu_histograms([features[i] for i in active],cp) if active else []
                    gpu_seconds+=time.perf_counter()-begin
                    for i,value in zip(active,aggregated):
                        batch[i].update(value);section=chunks[batch_index][i]
                        diffs={k:batch[i]['rdv_'+k]-section[k] for k in ['lula','bolsonaro','brancos','nulos']}
                        diffs['total']=batch[i]['rdv_total']-section['comparecimento']
                        batch[i]['rdv_concorda_bu']=not any(diffs.values()) and batch[i]['rdv_outros']==0
                        batch[i]['rdv_diferencas_json']=json.dumps(diffs)
                results.extend(batch)
                if batch_index%8==0:emit('benchmark_trial_progress',mode=mode,repeat=repeat,processed=len(results),total=len(rows))
    elapsed=time.perf_counter()-started
    expected=[r['bu_id'] for r in rows];observed=[r['bu_id'] for r in results]
    if observed!=expected or len(set(observed))!=len(expected):raise ValueError('missing/duplicated/reordered results')
    hashes={r['bu_id']:canonical_hash(r) for r in results}
    filename=folder/f'{mode}-r{repeat}'
    atomic_json(filename.with_suffix('.records.json'),results)
    atomic_json(filename.with_suffix('.hashes.json'),hashes)
    resource_children=resource.getrusage(resource.RUSAGE_CHILDREN)
    value={'mode':mode,'repeat':repeat,'sections':len(rows),'workers':workers,'physical_cpu_ids':cpus,
           'hybrid_gpu':hybrid,'gpu_scope':'RDV histogram counts only; ASN.1, logs, signatures on CPU' if hybrid else None,
           'elapsed_seconds':elapsed,'sections_per_second':len(rows)/elapsed,
           'cpu_seconds':time.process_time()-cpu_start+resource_children.ru_utime+resource_children.ru_stime,
           'peak_process_tree_rss_bytes_sampled':monitor.peak_rss,'gpu_startup_seconds':gpu_startup,
           'gpu_histogram_transfer_sync_seconds':gpu_seconds,'whole_gpu_samples':monitor.samples,
           'result_digest':canonical_hash(hashes),'finished_utc':now(),
           'rdv_mismatches':sum(r.get('rdv_concorda_bu') is False for r in results),
           'parser_errors':sum(r.get(stage+'_status')=='erro' for r in results for stage in ['rdv','log','assinatura'])}
    atomic_json(filename.with_suffix('.json'),value)
    emit('benchmark_trial_finished',**{k:v for k,v in value.items() if k!='whole_gpu_samples'})
    queue.close();return value


def report(folder,status):
    folder=Path(folder);trials=status['trials'];rows=[]
    for mode in MODES:
        values=[t for t in trials if t['mode']==mode and t.get('equivalent_to_cpu1')]
        if values:
            seconds=[v['elapsed_seconds'] for v in values]
            rows.append({'mode':mode,'repetitions':len(values),'median_seconds':statistics.median(seconds),
                         'min_seconds':min(seconds),'max_seconds':max(seconds),
                         'peak_rss_gib':max(v['peak_process_tree_rss_bytes_sampled'] for v in values)/1024**3})
    baseline=next((r['median_seconds'] for r in rows if r['mode']=='cpu1'),None)
    for r in rows:r['speedup']=baseline/r['median_seconds'] if baseline else None
    candidates=[r for r in rows if r['repetitions']>=status['repeats']]
    winner=min(candidates,key=lambda r:r['median_seconds'])['mode'] if candidates else None
    status.update(comparison=rows,fastest_equivalent_mode=winner)
    atomic_json(folder/'status.json',status)
    atomic_json(root()/'output/benchmarks/latest.json',status)
    if rows:
        with (folder/'comparacao.csv').open('w') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    lines=['# Comparação de processamento da mesma amostra','',f"Estado: {status['status']}. Amostra: {status['sections']} seções.",'',
           '| Configuração | Repetições | Mediana (s) | Aceleração | Pico RSS da árvore (GiB) |','|---|---:|---:|---:|---:|']
    for r in rows:lines.append(f"| {r['mode']} | {r['repetitions']} | {r['median_seconds']:.2f} | {r['speedup']:.2f}x | {r['peak_rss_gib']:.2f} |")
    lines+=['',f'Mais rápida entre configurações equivalentes com repetições completas: {winner or "ainda sem conclusão"}.','',
            'Todos os campos de cada seção são comparados por hash canônico com a referência cpu1. Divergências desqualificam a configuração.',
            'O tempo inclui inicialização dos processos, CUDA, leitura/descompressão, RDV, logs, assinaturas, IPC e agregação; exclui preparação da amostra, hash prévio dos arquivos e publicação do JSON de resultados.',
            'gpu1/gpu4 são variantes híbridas: somente histogramas presidenciais de RDV na GPU. Decodificação ASN.1, logs e verificação criptográfica oficial permanecem na CPU. Não representam uma reimplementação integral em CUDA.',
            'Um processo por núcleo físico distinto, afinidade registrada; BLAS/OMP limitados a uma thread. Repetições em ordem invertida para reduzir viés de ordem. A amostra é aquecida por sua verificação de hash antes de cada execução; não há teste de cache frio.',
            'RSS é soma amostrada dos processos e pode contar páginas compartilhadas mais de uma vez. Uso da GPU é global e pode incluir outros aplicativos.',
            'RR/ZZ cobrem formatos normais, SA e seções vazias; a amostra não estima sem viés o tempo nacional nem testa nesta comparação downloads, BWeb, modelos estatísticos ou relatórios.',
            'O processamento nacional permanece parado. Nenhuma escolha reinicia automaticamente a auditoria.','']
    if status.get('failures'):lines+=['## Falhas registradas','',json.dumps(status['failures'],ensure_ascii=False,indent=2)]
    (folder/'comparacao.md').write_text('\n'.join(lines))


def run(folder,repeats=2,budget_seconds=3300,limit=None,modes=None):
    import fcntl
    folder=Path(folder);modes=modes or list(MODES)
    lock=(root()/'data/checkpoints/benchmark-complementar.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    sample=json.loads((folder/'manifest.json').read_text());count=min(limit,sample['sections']) if limit else sample['sections']
    status={'status':'running','pid':os.getpid(),'started_utc':now(),'folder':str(folder),'sections':count,
            'repeats':repeats,'budget_seconds':budget_seconds,'trials':[],'failures':[],
            'signature':complement_signature(),'national_restarted':False,'modes':modes}
    atomic_json(folder/'environment.json',{'python':sys.version,'cpu_topology':subprocess.run(['lscpu'],capture_output=True,text=True).stdout,
                'nvidia':subprocess.run(['nvidia-smi'],capture_output=True,text=True).stdout,'uv_lock_sha256':digest(root()/'uv.lock'),
                'physical_cpu_ids_available':physical_cpus(),'cache_policy':'pre-read SHA256; warmed filesystem cache'})
    import tarfile
    with tarfile.open(folder/'benchmark-source.tar.gz','x:gz') as archive:
        for path in ['src','tests','scripts','specs','uv.lock','pyproject.toml']:
            archive.add(root()/path,arcname=path,filter=lambda item:None if '__pycache__' in item.name else item)
    report(folder,status);start=time.monotonic();reference=None
    try:
        for repeat in range(1,repeats+1):
            order=modes if repeat%2 else list(reversed(modes))
            for mode in order:
                if complement_signature()!=status['signature']:raise ValueError('benchmark source changed during execution')
                remaining=budget_seconds-(time.monotonic()-start)
                if remaining<10:raise TimeoutError('benchmark time budget exhausted; partial results retained')
                command=[sys.executable,'-m','auditoria_urnas.benchmark_complement','trial','--folder',str(folder),'--mode',mode,'--repeat',str(repeat)]
                if limit:command+=['--limit',str(limit)]
                log=folder/f'{mode}-r{repeat}.log'
                with log.open('w') as stream:
                    child=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
                    try:code=child.wait(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=15)
                        raise TimeoutError('trial exceeded remaining benchmark budget')
                if code!=0:
                    status['failures'].append({'mode':mode,'repeat':repeat,'exit_code':code,'log':str(log)})
                    if mode=='cpu1':raise RuntimeError('CPU reference failed')
                    report(folder,status);continue
                value=json.loads((folder/f'{mode}-r{repeat}.json').read_text())
                hashes=json.loads((folder/f'{mode}-r{repeat}.hashes.json').read_text())
                if reference is None:
                    if mode!='cpu1':raise ValueError('cpu1 reference must run first')
                    reference=hashes
                value['equivalent_to_cpu1']=hashes==reference
                if not value['equivalent_to_cpu1']:
                    differing=[key for key in reference.keys()|hashes.keys() if reference.get(key)!=hashes.get(key)]
                    atomic_json(folder/f'{mode}-r{repeat}.differences.json',differing)
                    status['failures'].append({'mode':mode,'repeat':repeat,'different_sections':len(differing)})
                status['trials'].append(value);report(folder,status)
        status['status']='complete_with_failures' if status['failures'] else 'complete'
    except BaseException as e:
        status.update(status='budget_exhausted' if isinstance(e,TimeoutError) else 'failed',error=str(e),traceback=traceback.format_exc())
    finally:
        status.update(finished_utc=now(),elapsed_seconds=time.monotonic()-start);report(folder,status);lock.close()
    emit('benchmark_finished',status=status['status'],folder=str(folder),fastest=status['fastest_equivalent_mode'])
    return status


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare');p.add_argument('--folder',type=Path,required=True);p.add_argument('--per-uf',type=int,default=1024)
    p=sub.add_parser('trial');p.add_argument('--folder',type=Path,required=True);p.add_argument('--mode',choices=MODES,required=True);p.add_argument('--repeat',type=int,default=1);p.add_argument('--limit',type=int)
    p=sub.add_parser('run');p.add_argument('--folder',type=Path,required=True);p.add_argument('--repeats',type=int,default=2);p.add_argument('--budget-seconds',type=int,default=3300);p.add_argument('--limit',type=int);p.add_argument('--modes',nargs='+',choices=MODES)
    args=parser.parse_args();kwargs=vars(args);action=kwargs.pop('action')
    if action=='prepare':prepare(**kwargs)
    elif action=='trial':trial(**kwargs)
    else:
        result=run(**kwargs)
        if result['status'] not in ['complete','complete_with_failures']:return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
