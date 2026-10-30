"""Cross-source section joins with explicit handling of repeated BWeb metrics."""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .analysis import write_csv
from .common import atomic_json,emit
from .complement_sources import bweb_sections,correspondences


def key(row):return row['municipio'],row['zona'],row['secao']

def normalized_load(value):
    if value is None:return None
    text=str(value)
    return (text.lstrip('0') or '0') if text.isdigit() else None


def _timestamp(value):
    if not value or value in ['#NULO','#NULO#']:return None
    for fmt in ['%d/%m/%Y %H:%M:%S','%Y-%m-%d %H:%M:%S','%Y%m%dT%H%M%S']:
        try:return datetime.strptime(value,fmt).strftime('%Y%m%dT%H%M%S')
        except ValueError:pass
    raise ValueError('unrecognized BWeb time format')


def reconcile_tables(base,acquired,output):
    from .complement import section_rows
    entries=[];discrepancies=[];correspondence_results=[];schemas=[];bweb_observed=[]
    for source in acquired:
        if source['status']!='complete':entries.append({'uf':source['uf'],'kind':source['kind'],'status':source['status'],'url':source.get('url')});continue
        uf=source['uf'];rows=section_rows(base,uf);lookup={key(row):row for row in rows}
        try:
            if source['kind']=='bweb':
                parsed,headers=bweb_sections(Path(source['path']),uf)
                missing=[k for k in lookup if k not in parsed]
                zero_missing=[k for k in missing if lookup[k]['comparecimento']==0]
                unexpected_missing=[k for k in missing if lookup[k]['comparecimento']!=0]
                unmatched=[k for k in parsed if k not in lookup]
                count=0
                for identity,row in parsed.items():
                    if identity not in lookup:continue
                    bu=lookup[identity];metrics=row['metrics'];differences={}
                    mapping={'QT_APTOS':'aptos','QT_COMPARECIMENTO':'comparecimento','QT_ABSTENCOES':'abstencoes','QT_ELEI_BIOM_SEM_HABILITACAO':'habilitados_biografia'}
                    for col,target in mapping.items():
                        if bu[target] is not None and metrics[col] is not None and metrics[col]!=bu[target]:differences[col]={'bweb':metrics[col],'bu':bu[target]}
                    for number,target in [(13,'lula'),(22,'bolsonaro'),(95,'brancos'),(96,'nulos')]:
                        value=row['votes'].get(number,0)
                        if value!=bu[target]:differences[target]={'bweb':value,'bu':bu[target]}
                    timestamp=_timestamp(metrics['DT_ENCERRAMENTO'])
                    if timestamp!=bu.get('encerramento_original') and bu['origem']=='dadosSecao':differences['encerramento']={'bweb':timestamp,'bu':bu.get('encerramento_original')}
                    if differences:
                        count+=1;discrepancies.append({'uf':uf,'municipio':identity[0],'zona':identity[1],'secao':identity[2],'source':source['path'],'differences':json.dumps(differences,ensure_ascii=False)})
                    bweb_observed.append({'uf':uf,'municipio':identity[0],'zona':identity[1],'secao':identity[2],
                        'lula':row['votes'].get(13,0),'bolsonaro':row['votes'].get(22,0),'comparecimento':metrics['QT_COMPARECIMENTO'],'aptos':metrics['QT_APTOS'],'brancos':row['votes'].get(95,0),'nulos':row['votes'].get(96,0),
                        'bio':metrics['QT_ELEI_BIOM_SEM_HABILITACAO'],'encerramento_original':timestamp})
                entries.append({'uf':uf,'kind':'bweb','status':'complete','sections':len(parsed),'bu_sections':len(rows),
                    'missing_zero_turnout_sections':len(zero_missing),'missing_positive_turnout_sections':len(unexpected_missing),
                    'unmatched_sections':len(unmatched),'discrepant_sections':count,'official_sha512':source['official_hash'],
                    'reproduced_metrics':{'lula':sum(v['votes'].get(13,0) for v in parsed.values()),'bolsonaro':sum(v['votes'].get(22,0) for v in parsed.values())},
                    'zero_turnout_identities':[list(k) for k in zero_missing]})
            else:
                parsed,headers=correspondences(Path(source['path']),uf)
                aggregate_to_main={}
                for row in rows:
                    for section in json.loads(row['agregadas_json'] or '[]'):
                        agg=(row['municipio'],row['zona'],section)
                        if agg in aggregate_to_main and aggregate_to_main[agg]!=key(row):raise ValueError('ambiguous aggregated section parent')
                        aggregate_to_main[agg]=key(row)
                present_keys=set()
                for row in parsed:
                    identity=key(row);parent=identity if identity in lookup else aggregate_to_main.get(identity)
                    if row.get('record_type')=='contingencia':
                        matches=[k for k,b in lookup.items() if b['urna']==row['expected_urna'] and b['zona']==row['zona']]
                        parent=matches[0] if len(matches)==1 else None
                    bu=lookup.get(parent);present_keys.add(parent)
                    effective=row['effective_urna'];expected=row['expected_urna']
                    match=(effective==bu['urna']) if bu and effective is not None else None
                    raw_load_match=(row['effective_load']==bu['codigo_carga']) if bu and row['effective_load'] else None
                    left=normalized_load(row['effective_load']);right=normalized_load(bu['codigo_carga']) if bu else None
                    load_match=(left==right) if left is not None and right is not None else None
                    correspondence_results.append({'uf':uf,'kind':source['kind'],'snapshot':source['path'],**row,
                        'matched_bu':bu['bu_id'] if bu else None,'aggregate_parent':str(parent) if parent and parent!=identity else None,
                        'effective_urna_matches_bu':match,'effective_load_matches_bu':load_match,'effective_load_raw_matches_bu':raw_load_match,'bu_load_raw':bu['codigo_carga'] if bu else None,'load_normalization':'identificador decimal, sem zeros à esquerda; valores originais preservados',
                        'expected_vs_effective_differs':expected!=effective if effective is not None else None})
                entries.append({'uf':uf,'kind':source['kind'],'status':'complete','rows':len(parsed),
                                'bu_sections_without_correspondence':sum(k not in present_keys for k in lookup),
                                'official_sha512':source['official_hash'],'snapshot':source['path']})
            schemas.append({'uf':uf,'kind':source['kind'],'path':source['path'],'headers':headers})
        except Exception as e:
            entries.append({'uf':uf,'kind':source['kind'],'status':'failed','parse_error':type(e).__name__+': '+str(e),'source':source['path']})
        atomic_json(output/'tabular-summary.json',entries)
        emit('complement_tabular_parsed',uf=uf,kind=source['kind'])
    atomic_json(output/'tabular-schemas.json',schemas)
    write_csv(output/'bweb-divergencias.csv',discrepancies)
    write_csv(output/'correspondencias.csv',correspondence_results)
    if bweb_observed:
        import pyarrow as pa,pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist(bweb_observed),output/'bweb-secoes.parquet',compression='zstd')
    return entries
