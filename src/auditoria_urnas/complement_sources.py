"""Incremental official acquisitions. Reuse original bytes and provenance."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from .analysis import snapshot
from .catalog import discover
from .common import atomic_json,digest,emit,now,root
from .network import head,small,download


def acquired_zip(url,*,official_hash_url=None):
    directory=root()/'data/raw/complementar'/hashlib.sha256(url.encode()).hexdigest()[:20]
    directory.mkdir(parents=True,exist_ok=True)
    destination=directory/url.rsplit('/',1)[1]
    expected_hash=None
    if official_hash_url:
        hashfile=directory/(destination.name+'.sha512')
        hashmeta=hashfile.with_name(hashfile.name+'.provenance.json')
        if not hashfile.exists() or not hashmeta.exists():
            raw=small(official_hash_url,cap=100_000)
            if hashfile.exists():
                if hashfile.read_bytes()!=raw:raise ValueError('published sidecar changed; old bytes preserved')
            else:
                with hashfile.open('xb') as f:f.write(raw)
            atomic_json(hashmeta,{'url':official_hash_url,'retrieved_utc':now(),'sha256':digest(hashfile)})
        meta=json.loads(hashmeta.read_text())
        if meta['url']!=official_hash_url or digest(hashfile)!=meta['sha256']:raise ValueError('hash sidecar provenance differs')
        matches=re.findall(r'(?i)\b[0-9a-f]{128}\b',hashfile.read_text())
        if len(set(matches))!=1:raise ValueError('ambiguous official SHA512 sidecar')
        expected_hash=matches[0].lower()
    sidecar=destination.with_name(destination.name+'.provenance.json')
    if destination.exists():
        meta=json.loads(sidecar.read_text())
        if meta['url']!=url or digest(destination)!=meta['sha256']:raise ValueError('acquisition changed')
        if expected_hash and digest(destination,'sha512')!=expected_hash:raise ValueError('reused archive fails official SHA512')
        return {**meta,'official_hash':'matched' if expected_hash else meta.get('official_hash','unavailable')}
    # Existing acquisitions are reused by URL and verified bytes, never by basename alone.
    for prior in (root()/'data/raw').rglob('*.provenance.json'):
        try:
            meta=json.loads(prior.read_text());path=Path(meta.get('path',''))
            if meta.get('url')!=url or not path.is_file() or path.suffix!='.zip':continue
            if digest(path)!=meta['sha256']:raise ValueError('previous acquisition changed')
            if expected_hash and digest(path,'sha512')!=expected_hash:raise ValueError('previous acquisition fails official SHA512')
            return {**meta,'official_hash':'matched' if expected_hash else meta.get('official_hash','unavailable'),'reused_from':str(path)}
        except (json.JSONDecodeError,KeyError):continue
    remote=head(url);size=int(remote.get('content-length') or 0)
    if size<=0:raise ValueError('unknown download size')
    if shutil.disk_usage(root()).free<size+20*1024**3:raise OSError('insufficient disk margin')
    return download(url,destination,size,expected_hash)


def _date_resource(url):
    match=re.search(r'_(\d{12})\.zip$',url)
    return datetime.strptime(match[1],'%d%m%Y%H%M') if match else datetime.min


def select_resources(catalog,ufs):
    """Keep current and earlier expected snapshots; latest BWeb/effective per UF."""
    all_urls={r['url'] for r in catalog['resources']}
    # A published archive.sha512 resource explicitly identifies its associated archive.
    all_urls|={u[:-7] for u in list(all_urls) if u.endswith('.zip.sha512')}
    plan=[]
    for uf in ufs:
        groups={
            'bweb':[u for u in all_urls if re.search(r'/bweb_2t_'+uf+r'_\d+\.zip$',u)],
            'esperadas':[u for u in all_urls if re.search(r'/CESP_2t_'+uf+r'_\d+\.zip$',u)],
            'efetivadas':[u for u in all_urls if re.search(r'/CEFT_2t_'+uf+r'_\d+\.zip$',u)]}
        for kind,urls in groups.items():
            if not urls:
                plan.append({'uf':uf,'kind':kind,'url':None,'reason':'not_in_official_catalog'});continue
            chosen=sorted(urls,key=_date_resource)
            if kind!='esperadas':chosen=chosen[-1:]
            for url in chosen:
                plan.append({'uf':uf,'kind':kind,'url':url,'hash_url':url+'.sha512' if url+'.sha512' in all_urls else None})
    return plan


def prepare(ufs,output,*,refresh=True,kinds=None):
    catalog=discover() if refresh else json.loads((root()/'data/catalog/latest.json').read_text())
    plan=select_resources(catalog,ufs)
    if kinds is not None:plan=[p for p in plan if p['kind'] in kinds]
    for item in plan:
        if item['url']:
            try:item['head']=head(item['url'])
            except Exception as e:item['head_error']=str(e)
    estimated=sum(int(item.get('head',{}).get('content-length') or 0) for item in plan)
    atomic_json(output/'download-plan.json',{'estimated_traffic_bytes_upper_bound':estimated,'free_bytes':shutil.disk_usage(root()).free,'temporary_policy':'stream ZIP entries; no national extraction; 20 GiB minimum margin','created_utc':now(),'authorized_by':'explicit CLI invocation of complementary acquisition stage','items':plan,
                                           'policy':'originais preservados; apenas fontes complementares; inventário HEAD antes de cada transferência'})
    acquired=[]
    for item in plan:
        if not item['url']:
            acquired.append({**item,'status':'unavailable'});continue
        try:
            result=acquired_zip(item['url'],official_hash_url=item['hash_url'])
            acquired.append({**item,'status':'complete',**result})
            emit('complement_source_ready',kind=item['kind'],uf=item['uf'],bytes=result['bytes'])
        except Exception as e:
            acquired.append({**item,'status':'failed','error':type(e).__name__+': '+str(e)})
            if isinstance(e,OSError) and (getattr(e,'errno',None)==28 or 'disk margin' in str(e)):
                atomic_json(output/'acquisitions.json',acquired);raise
        atomic_json(output/'acquisitions.json',acquired)
    return acquired


def recover_missing_sp(output):
    base='https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/3221/dados/sp/64777/0395/0298'
    filename='p003221-sp-m64777-z0395-s0298-aux.json'
    directory=root()/'data/raw/complementar/recuperacao-sp'
    obj,meta=snapshot(base+'/'+filename,directory/filename)
    logs=[]
    for version in obj.get('hashes',[]):
        if version.get('st')!='Totalizado':continue
        for entry in version.get('arq',[]):
            if entry['nm'].endswith(('-log.jez','-logsa.jez')):
                url=base+'/'+version['hash']+'/'+entry['nm']
                raw=small(url,cap=128*1024**2)
                path=directory/version['hash']/entry['nm'];path.parent.mkdir(parents=True,exist_ok=True)
                if not path.exists():path.write_bytes(raw)
                elif path.read_bytes()!=raw:raise ValueError('recovered log changed')
                logs.append({'path':str(path),'sha256':digest(path),'url':url})
    result={'section':'SP:64777:395:298','index':meta,'logs':logs,
            'status':'recovered' if logs else 'log_not_listed_in_official_auxiliary',
            'limitation':'ausência de log publicado não é zero votos após 17h'}
    atomic_json(output/'recuperacao-log-sp.json',result)
    return result


def csv_members(path):
    """Stream real CSVs and expose their observed header before any conversion."""
    with zipfile.ZipFile(path) as archive:
        names=[n for n in archive.namelist() if n.lower().endswith('.csv')]
        if len(names)!=len(set(names)):raise ValueError('duplicate CSV member names')
        if not names:raise ValueError('no CSV in official archive')
        for name in names:
            with archive.open(name) as stream:
                reader=csv.DictReader(io.TextIOWrapper(stream,encoding='latin1'),delimiter=';')
                yield name,reader.fieldnames,reader


def nullable_int(value):
    if value in [None,'','#NULO','#NULO#','#NE','-1','-3']:return None
    return int(value)


def bweb_sections(path,uf):
    required={'NR_TURNO','CD_ELEICAO','SG_UF','CD_MUNICIPIO','NR_ZONA','NR_SECAO','CD_CARGO_PERGUNTA','QT_VOTOS','NR_VOTAVEL',
              'QT_APTOS','QT_COMPARECIMENTO','QT_ABSTENCOES','QT_ELEI_BIOM_SEM_HABILITACAO','DT_ENCERRAMENTO'}
    sections={};seen=set();headers=[]
    for name,header,reader in csv_members(path):
        headers.append({'member':name,'columns':header})
        if not required.issubset(header):raise ValueError('BWeb schema missing '+str(sorted(required-set(header))))
        for row in reader:
            if int(row['NR_TURNO'])!=2 or int(row['CD_ELEICAO'])!=6258 or int(row['CD_CARGO_PERGUNTA'])!=1:continue
            if row['SG_UF']!=uf:raise ValueError('BWeb UF mismatch')
            key=tuple(int(row[k]) for k in ['CD_MUNICIPIO','NR_ZONA','NR_SECAO'])
            number=int(row['NR_VOTAVEL']);quantity=int(row['QT_VOTOS'])
            vk=(*key,number,row['CD_TIPO_VOTAVEL'])
            if vk in seen:raise ValueError('duplicate BWeb section/votable; explicit version reconciliation needed')
            seen.add(vk)
            metrics={k:nullable_int(row[k]) for k in ['QT_APTOS','QT_COMPARECIMENTO','QT_ABSTENCOES','QT_ELEI_BIOM_SEM_HABILITACAO']}
            metrics['DT_ENCERRAMENTO']=row['DT_ENCERRAMENTO']
            if key not in sections:sections[key]={'metrics':metrics,'votes':{},'candidate_votes':{}}
            elif sections[key]['metrics']!=metrics:raise ValueError('BWeb repeated section metrics disagree')
            sections[key]['votes'][number]=quantity
            if int(row['CD_TIPO_VOTAVEL'])==1:sections[key]['candidate_votes'][number]=quantity
    return sections,headers


def correspondences(path,uf):
    rows=[];headers=[];seen=set()
    for name,header,reader in csv_members(path):
        headers.append({'member':name,'columns':header})
        if not {'SG_UF','CD_PLEITO','CD_MUNICIPIO','NR_ZONA','NR_URNA_ESPERADA'}.issubset(header):
            raise ValueError('unknown correspondence schema')
        for row in reader:
            if row['SG_UF']!=uf or int(row['CD_PLEITO'])!=3221:raise ValueError('correspondence UF/pleito mismatch')
            contingency='NR_SECAO' not in header
            if contingency and not name.lower().startswith('ccont_'):raise ValueError('unknown sectionless correspondence schema')
            key=(int(row['CD_MUNICIPIO']),int(row['NR_ZONA']),None if contingency else int(row['NR_SECAO']))
            version=tuple(row.get(k,'') for k in ['SQ_CORRESPONDENCIA_ESPERADA','SQ_CORRESPONDENCIA_EFETIVADA','NR_URNA_ESPERADA','NR_URNA_EFETIVADA','CD_CARGA_URNA_ESPERADA','CD_CARGA_URNA_EFETIVADA'])
            if (*key,*version) in seen:raise ValueError('duplicate correspondence key/version')
            seen.add((*key,*version))
            rows.append({'municipio':key[0],'zona':key[1],'secao':key[2],'record_type':'contingencia' if contingency else 'secao',
                         'expected_urna':nullable_int(row.get('NR_URNA_ESPERADA')),'effective_urna':nullable_int(row.get('NR_URNA_EFETIVADA')),
                         'expected_load':row.get('CD_CARGA_URNA_ESPERADA'),'effective_load':row.get('CD_CARGA_URNA_EFETIVADA'),
                         'divergence_type':row.get('TP_DIVERGENCIA'),'vote_origin':row.get('DS_ORIGEM_VOTO'),
                         'generated_date':row.get('DT_GERACAO'),'generated_time':row.get('HH_GERACAO')})
    return rows,headers
