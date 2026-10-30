"""Repair only municipal SQL comparisons and reports; retain original national run."""
from __future__ import annotations
import json,shutil,tarfile,time
from pathlib import Path
import duckdb
import pandas as pd

from auditoria_urnas.common import root,atomic_json,digest,now,emit
from auditoria_urnas.complement import base_data,complement_signature
from auditoria_urnas.complement_comparisons import municipal_round_comparison
from auditoria_urnas.complement_report import reports


def main():
    base=root();pointer=base/'data/checkpoints/latest-complement.json'
    previous=json.loads(pointer.read_text());source=Path(previous['output'])
    if previous['status'] not in ['complete_with_limitations','complete']:raise ValueError('completed national run required')
    if previous['progress']['national_processed']!=previous['progress']['national_total']:raise ValueError('national files incomplete')
    manifest=json.loads((source/'output-manifest.json').read_text())
    expected={entry['path']:entry['sha256'] for entry in manifest['files']}
    version=complement_signature();folder=base/'output/complementar'/(now().replace(':','').replace('.','')+'-comparacoes-corrigidas')
    folder.mkdir(parents=True)
    status={**previous,'status':'running','output':str(folder),'signature':version,'started_utc':now(),'finished_utc':None,
            'source_processing_run':str(source),'source_processing_signature':previous['signature'],
            'repair_stages':['comparacoes','relatorios'],'previous_execution_failures':previous['failures'],'failures':[],'audit_closed':False}
    atomic_json(folder/'status.json',status)
    for path in source.iterdir():
        if path.is_file() and path.name not in ['status.json','output-manifest.json','source-code.tar.gz','environment.json']:
            if str(path) in expected and digest(path)!=expected[str(path)]:raise ValueError('previous artifact changed: '+str(path))
            shutil.copy2(path,folder/path.name)
    target=folder/'comparacoes';target.mkdir()
    input_files=[]
    for path in sorted((source/'comparacoes').iterdir()):
        if not path.is_file():continue
        if str(path) not in expected or digest(path)!=expected[str(path)]:raise ValueError('comparison input not in verified manifest')
        shutil.copy2(path,target/path.name)
        input_files.append({'original_path':str(path),'path':str(target/path.name),'sha256':expected[str(path)]})
    atomic_json(folder/'repair-input-manifest.json',{'source_run':str(source),'previous_output_manifest_sha256':digest(source/'output-manifest.json'),'files':input_files})
    environment=json.loads((source/'environment.json').read_text())
    environment.update(signature=version,source_processing_signature=previous['signature'],repair_stages=status['repair_stages'])
    atomic_json(folder/'environment.json',environment)
    with tarfile.open(folder/'source-code.tar.gz','x:gz') as archive:
        for name in ['src','tests','scripts','specs','docs','uv.lock','pyproject.toml']:
            archive.add(base/name,arcname=name,filter=lambda item:None if '__pycache__' in item.name else item)
    profiles=[]
    for year in [2026,2022]:
        paths=[entry['path'] for entry in input_files if Path(entry['path']).name.startswith(str(year)+'-') and Path(entry['path']).suffix=='.parquet']
        if not paths:raise ValueError('missing verified historical Parquet '+str(year))
        with duckdb.connect(config={'memory_limit':'6GiB','threads':'4','temp_directory':str(base/'data/tmp/comparison-duckdb')}) as db:
            db.read_parquet(paths,union_by_name=True).create_view('votes')
            duplicate=db.execute('select count(*) from (select year,turn,uf,municipio,zona,secao,number from votes group by all having count(*)>1)').fetchone()[0]
            if duplicate:raise ValueError('duplicate historical section/votable')
            coverage=db.execute('select year,turn,count(*) from (select distinct year,turn,uf,municipio,zona,secao from votes) group by 1,2 order by 1,2').fetchall()
            frame=municipal_round_comparison(db)
            if frame.duplicated(['uf','municipio']).any():raise ValueError('duplicate municipality comparison')
            frame.to_csv(target/f'dois-turnos-{year}.csv',index=False)
        profiles.append({'year':year,'status':'complete','coverage':coverage,'municipalities':len(frame),
                         'source_processing_run':str(source),'validated_parquet_files':len(paths),
                         'provenance_manifest':str(folder/'repair-input-manifest.json'),
                         'limitations':'Municipal changes and different populations across turns; candidate number 22 identifies different people in 2022 and 2026; no individual voter inference.'})
        emit('complement_comparison_repaired',year=year,municipalities=len(frame))
    a=pd.read_csv(target/'dois-turnos-2022.csv');b=pd.read_csv(target/'dois-turnos-2026.csv')
    joined=a.merge(b,on=['uf','municipio'],how='outer',suffixes=('_2022','_2026'),indicator=True,validate='one_to_one')
    joined.to_csv(target/'comparacao-2022-2026.csv',index=False)
    atomic_json(folder/'comparisons-summary.json',profiles)
    atomic_json(folder/'cross-year-coverage.json',joined['_merge'].value_counts().to_dict())
    if complement_signature()!=version:raise ValueError('source changed during correction')
    status.update(status='complete_with_limitations',finished_utc=now(),limitations=['One section log absent from the published package/index; incomplete temporal coverage and documentary/cryptographic trust limitations remain explicit.'])
    reports(base_data(),folder,status,json.loads((folder/'summary.json').read_text()))
    status['finished_utc']=now();atomic_json(folder/'status.json',status);atomic_json(pointer,status)
    emit('complement_repair_complete',output=str(folder),failures=status['failures'])


if __name__=='__main__':main()
