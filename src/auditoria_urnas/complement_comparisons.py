"""Presidential municipal comparisons using official tabular packages only."""
from __future__ import annotations
import json,re
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .common import atomic_json,digest,root,emit,now
from .network import small
from .catalog import Links
from .complement_sources import acquired_zip,csv_members


def municipal_round_comparison(db):
    return db.execute('''with shares as (select year,turn,uf,municipio,
                sum(votes) filter(where number=13)*1.0/nullif(sum(votes) filter(where number not in (95,96)),0) lula_share,
                sum(votes) filter(where number not in (95,96))::BIGINT validos
                from votes group by all)
                select coalesce(a.year,b.year) AS "year",coalesce(a.uf,b.uf) uf,coalesce(a.municipio,b.municipio) municipio,a.lula_share share_first,b.lula_share share_second,
                       b.lula_share-a.lula_share share_change,a.validos valid_first,b.validos valid_second
                from (select * from shares where turn=1) a full join (select * from shares where turn=2) b on a.year=b.year and a.uf=b.uf and a.municipio=b.municipio''').fetchdf()


def _resource(year,output,region='BR'):
    slug=f'resultados-{year}';urls=set();evidence={}
    for kind,url in [('api',f'https://dadosabertos.tse.jus.br/api/3/action/package_show?id={slug}'),('html',f'https://dadosabertos.tse.jus.br/dataset/{slug}')]:
        try:
            raw=small(url);path=output/f'catalog-{year}.{kind}';path.write_bytes(raw)
            evidence[kind]={'url':url,'sha256':digest(path),'queried_utc':now()}
            if kind=='api':
                obj=json.loads(raw)
                if obj.get('success'):urls.update(r['url'] for r in obj['result']['resources'])
            else:
                links=Links();links.feed(raw.decode());urls|=links.urls
        except Exception as e:evidence[kind]={'url':url,'error':str(e)}
    atomic_json(output/f'catalog-{year}-provenance.json',evidence)
    matches=[u for u in urls if u.endswith(f'/votacao_secao_{year}_{region}.zip')]
    if len(matches)!=1:raise ValueError('could not discover unique official presidential BR table for '+str(year))
    url=matches[0]
    return acquired_zip(url,official_hash_url=url+'.sha512' if url+'.sha512' in urls else None)


def compare(output,*,ufs=None):
    folder=output/'comparacoes';folder.mkdir(exist_ok=True)
    manifests=[];profiles=[]
    for year in [2026,2022]:
        try:
            acquisition=_resource(year,folder,region=ufs[0] if ufs and len(ufs)==1 else 'BR');manifests.append(acquisition)
            batches=[];rows=[];headers=[]
            for name,header,reader in csv_members(Path(acquisition['path'])):
                headers.append({'member':name,'columns':header})
                required={'NR_TURNO','SG_UF','CD_MUNICIPIO','NR_ZONA','NR_SECAO','CD_CARGO','NR_VOTAVEL','NM_VOTAVEL','QT_VOTOS'}
                if not required.issubset(header):raise ValueError('historical schema missing '+str(sorted(required-set(header))))
                for row in reader:
                    if int(row['CD_CARGO'])!=1:continue
                    if ufs and row['SG_UF'] not in ufs:continue
                    if int(row['QT_VOTOS'])<0:raise ValueError('negative historical vote count')
                    if int(row.get('ANO_ELEICAO',year))!=year or int(row['NR_TURNO']) not in [1,2]:raise ValueError('historical year/turn mismatch')
                    rows.append({'year':year,'turn':int(row['NR_TURNO']),'uf':row['SG_UF'],
                        'municipio':int(row['CD_MUNICIPIO']),'zona':int(row['NR_ZONA']),'secao':int(row['NR_SECAO']),
                        'number':int(row['NR_VOTAVEL']),'candidate':row['NM_VOTAVEL'],'votes':int(row['QT_VOTOS'])})
                    if len(rows)>=50000:
                        p=folder/f'{year}-{len(batches):05}.parquet';pq.write_table(pa.Table.from_pylist(rows),p,compression='zstd');batches.append(str(p));rows=[]
                if rows:
                    p=folder/f'{year}-{len(batches):05}.parquet';pq.write_table(pa.Table.from_pylist(rows),p,compression='zstd');batches.append(str(p));rows=[]
            atomic_json(folder/f'schemas-{year}.json',headers)
            if not batches:raise ValueError('no presidential rows')
            db=duckdb.connect(config={'memory_limit':'6GiB','threads':'4','temp_directory':str(root()/'data/tmp/comparison-duckdb')})
            db.read_parquet(batches,union_by_name=True).create_view('votes')
            duplicates=db.execute('select count(*) from (select year,turn,uf,municipio,zona,secao,number from votes group by all having count(*)>1)').fetchone()[0]
            if duplicates:raise ValueError('duplicate historical section/votable rows')
            db.execute("copy (select year,turn,uf,municipio,number,candidate,sum(votes)::BIGINT votes from votes group by all order by 1,2,3,4,5) to ? (header,delimiter ',')",[str(folder/f'municipios-{year}.csv')])
            db.execute("copy (select year,turn,uf,number,candidate,sum(votes)::BIGINT votes from votes group by all order by 1,2,3,4) to ? (header,delimiter ',')",[str(folder/f'ufs-{year}.csv')])
            sections=db.execute('select year,turn,count(*) from (select distinct year,turn,uf,municipio,zona,secao from votes) group by 1,2').fetchall()
            round_comparison=municipal_round_comparison(db)
            round_comparison.to_csv(folder/f'dois-turnos-{year}.csv',index=False)
            profiles.append({'year':year,'status':'complete','coverage':sections,'source':acquisition,
                'limitations':'Municipal changes and different populations across turns; number 22 refers to different candidates in 2022 and 2026; no individual voter inference.'})
            db.close();emit('complement_comparison_complete',year=year)
        except Exception as e:
            profiles.append({'year':year,'status':'failed','error':type(e).__name__+': '+str(e)})
        atomic_json(output/'comparisons-summary.json',profiles)
    # Cross-year comparison on explicit common municipality codes, with unmatched coverage.
    import pandas as pd
    if all((folder/f'dois-turnos-{year}.csv').exists() for year in [2022,2026]):
        a=pd.read_csv(folder/'dois-turnos-2022.csv');b=pd.read_csv(folder/'dois-turnos-2026.csv')
        a.merge(b,on=['uf','municipio'],how='outer',suffixes=('_2022','_2026'),indicator=True).to_csv(folder/'comparacao-2022-2026.csv',index=False)
    return profiles
