"""Reproducible second-round reconciliation and preliminary claim calculations.

Reads only Parquets committed by the selected ingestion checkpoints. Never changes
raw archives or ingestion checkpoints. Report claims are from the user brief until
original screenshots can be transcribed, so author conclusions remain provisional.
"""
from __future__ import annotations

import csv
import fcntl
import json
import os
import platform
import sys
import traceback
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .common import UFS, atomic_json, digest, emit, now, root, signature
from .network import request
from .parser import ZONES
from .pipeline import connection

BASE = 'https://resultados.tse.jus.br/oficial/ele2026/6258'
TIME_SOURCES = [
 'https://www.tre-am.jus.br/comunicacao/noticias/2026/Setembro/eleitorado-do-amazonas-deve-ficar-atento-aos-horarios-de-votacao-nas-eleicoes-2026',
 'https://www.tse.jus.br/comunicacao/noticias/2026/Setembro/faltam-26-dias-votacao-comeca-e-termina-no-mesmo-horario-em-todo-o-pais']
LATE_SOURCE = 'https://www.tse.jus.br/comunicacao/noticias/2026/Outubro/eleicoes-2026-mais-de-34-mil-votos-foram-registrados-apos-as-17h-no-2o-turno'
DOCS = 'https://www.tse.jus.br/eleicoes/informacoes-tecnicas-sobre-a-divulgacao-de-resultados'
AM_WEST = {'AMATURA','ATALAIA DO NORTE','BENJAMIN CONSTANT','EIRUNEPE','ENVIRA','GUAJARA','IPIXUNA','ITAMARATI','JUTAI','SAO PAULO DE OLIVENCA','TABATINGA'}
SECTION_SQL = '''
WITH v AS (
 SELECT bu_id,
 coalesce(sum(quantidade) FILTER(WHERE tipo_voto=1 AND numero=13),0)::BIGINT lula,
 coalesce(sum(quantidade) FILTER(WHERE tipo_voto=1 AND numero=22),0)::BIGINT bolsonaro,
 coalesce(sum(quantidade) FILTER(WHERE tipo_voto=1),0)::BIGINT validos,
 coalesce(sum(quantidade) FILTER(WHERE tipo_voto=2),0)::BIGINT brancos,
 coalesce(sum(quantidade) FILTER(WHERE tipo_voto=3),0)::BIGINT nulos,
 sum(quantidade)::BIGINT votos_todos
 FROM votos WHERE cargo=1 AND eleicao=6258 GROUP BY bu_id
)
SELECT b.*, e.aptos,e.aptos_originais,e.aptos_temporarios,e.comparecimento,e.abstencoes,
 e.conferido_imagem,v.lula,v.bolsonaro,v.validos,v.brancos,v.nulos,v.votos_todos
FROM boletins b JOIN eleicoes e USING(bu_id) LEFT JOIN v USING(bu_id)
WHERE e.cargo=1 AND e.eleicao=6258
'''


def normalize_name(name):
    return ''.join(c for c in unicodedata.normalize('NFD', name.upper()) if not unicodedata.combining(c))


def municipality_zone(uf, name):
    if uf == 'ZZ':
        return None  # Location-level legal offsets are still to be documented.
    if uf == 'AM':
        return 'America/Eirunepe' if normalize_name(name) in AM_WEST else 'America/Manaus'
    if uf == 'PE':
        return 'America/Noronha' if normalize_name(name) == 'FERNANDO DE NORONHA' else 'America/Recife'
    return ZONES.get(uf, 'America/Sao_Paulo')


def closure_brasilia(raw, zone, origin):
    if pd.isna(raw) or pd.isna(zone) or not raw or origin != 'dadosSecao':
        return None
    dt = datetime.strptime(raw, '%Y%m%dT%H%M%S')
    return dt.replace(tzinfo=ZoneInfo(zone)).astimezone(ZoneInfo('America/Sao_Paulo')).isoformat()


def snapshot(url, destination):
    """Keep original HTTP bytes and a separate provenance sidecar; bounded at 5 MB."""
    sidecar = destination.with_suffix(destination.suffix + '.provenance.json')
    if destination.exists():
        meta = json.loads(sidecar.read_text())
        if meta['url'] != url or digest(destination) != meta['sha256']:
            raise ValueError(f'snapshot changed: {destination}')
        return json.loads(destination.read_bytes()), meta
    destination.parent.mkdir(parents=True, exist_ok=True)
    with request(url) as r:
        raw = r.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError('snapshot exceeds 5 MB cap')
        obj = json.loads(raw)
        meta = {'url': url, 'retrieved_utc': now(), 'bytes': len(raw),
                'etag': r.headers.get('ETag'), 'last_modified': r.headers.get('Last-Modified'),
                'version': {k: obj.get(k) for k in ['idg','dg','hg','dt','ht']},
                'official_hash': 'unavailable', 'digital_signature': 'not_verified'}
    with destination.open('xb') as f:
        f.write(raw)
    meta.update(path=str(destination), sha256=digest(destination))
    atomic_json(sidecar, meta)
    return obj, meta


def official_values(obj, uf):
    required = {'ele':'6258','t':'2','f':'o','cdabr':uf.lower(),'tf':'s','and':'f'}
    if any(str(obj.get(k)) != v for k,v in required.items()):
        raise ValueError(f'EA20 not final official result for {uf}: {required}')
    candidates = {}
    for office in obj['carg']:
        if str(office['cd']) != '1':
            continue
        for group in office['agr']:
            for party in group['par']:
                for candidate in party['cand']:
                    number = int(candidate['n'])
                    if number in candidates:
                        raise ValueError('duplicate EA20 candidate')
                    candidates[number] = int(candidate['vap'])
    if set(candidates) != {13,22}:
        raise ValueError('unexpected presidential candidate set')
    s,e,v = obj['s'],obj['e'],obj['v']
    identities = [
        int(s['st']) == int(s['si']) + int(s['sni']),
        int(s['si']) == int(s['sa']) + int(s['sna']),
        int(e['esi']) == int(e['c']) + int(e['a']),
        int(v['tv']) == int(v['vvc']) + int(v['vb']) + int(v['tvn']) + int(v['vscv']),
        int(v['vvc']) == int(v['vv']) + int(v['van']) + int(v['vansj']),
        int(v['tvn']) == int(v['vn']) + int(v['vnt']),
        sum(candidates.values()) == int(v['vv'])]
    if not all(identities):
        raise ValueError('EA20 accounting identity failed')
    if any(int(v[k]) != 0 for k in ['van','vansj','vscv','vnt']):
        raise ValueError('special vote categories require explicit treatment before reconciliation')
    return {'secoes':int(s['si']),'aptos':int(e['esi']),'comparecimento':int(e['c']),
            'abstencoes':int(e['a']),'lula':candidates[13],'bolsonaro':candidates[22],
            'validos':int(v['vv']),'brancos':int(v['vb']),'nulos':int(v['vn'])}, {
                'secoes_nao_instaladas':int(s['sni']), 'aptos_nao_instaladas':int(e['esni']),
                'aptos_total_registros':int(e['te'])}


def committed_inputs(out):
    pointer = json.loads((root()/'data/checkpoints/latest-run.json').read_text())
    run_path = Path(pointer['path'])
    run = json.loads(run_path.read_text())
    states = [json.loads(Path(x['checkpoint']).read_text()) for x in run['completed']]
    if len(states) != 28 or {s['uf'] for s in states} != set(UFS) or not all(s['complete'] for s in states):
        raise ValueError('requires exactly the completed 27 UFs and ZZ')
    if len({s['parser_signature'] for s in states}) != 1:
        raise ValueError('mixed ingestion signatures')
    files = []
    for state in states:
        for batch in state['batches']:
            for table, item in batch.items():
                path = Path(item['path'])
                if digest(path) != item['sha256']:
                    raise ValueError(f'committed Parquet hash differs: {path}')
                files.append({'uf':state['uf'],'table':table,**item})
    manifest = {'selected_run':str(run_path),'selected_run_sha256':digest(run_path),
                'ingestion_signature':states[0]['parser_signature'], 'files':files,
                'checkpoint_sha256':{s['uf']:digest(Path(x['checkpoint'])) for s,x in zip(states,run['completed'])}}
    atomic_json(out/'input-manifest.json',manifest)
    emit('analysis_inputs_verified',files=len(files),regions=len(states))
    return states


def write_csv(path, rows):
    rows = list(rows)
    if not rows:
        return
    with path.open('w',newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def reconcile(df, sources, out):
    metrics = ['aptos','comparecimento','abstencoes','lula','bolsonaro','validos','brancos','nulos']
    comparisons, absent = [], []
    for uf in ['BR',*UFS]:
        expected, extra = official_values(sources[uf],uf)
        part = df if uf == 'BR' else df[df.uf == uf]
        actual = {m:int(part[m].sum()) for m in metrics}
        actual['secoes'] = len(part)
        for metric,wanted in expected.items():
            comparisons.append({'uf':uf,'metrica':metric,'calculado':actual[metric],
                                'oficial':wanted,'diferenca':actual[metric]-wanted})
        absent.append({'uf':uf,**extra})
    write_csv(out/'reconciliacao.csv',comparisons)
    write_csv(out/'secoes-nao-instaladas.csv',absent)
    result = {'passed':all(r['diferenca']==0 for r in comparisons), 'comparisons':len(comparisons),
              'divergences':[r for r in comparisons if r['diferenca']],
              'national':{r['metrica']:r['calculado'] for r in comparisons if r['uf']=='BR'},
              'uninstalled':absent[0], 'scope':'presidente; eleição 6258; segundo turno; 27 UFs e ZZ'}
    atomic_json(out/'reconciliacao.json',result)
    return result


def complete_empty_votes(df):
    """An empty candidate list is zero votes only with explicit zero turnout."""
    cols=['lula','bolsonaro','validos','brancos','nulos','votos_todos']
    absent=df[cols].isna().all(axis=1)
    any_missing=df[cols].isna().any(axis=1)
    if ((any_missing & ~absent) | (absent & (df.comparecimento!=0))).any():
        raise ValueError('section without presidential vote records and nonzero turnout, or partial missing metrics')
    df['lista_votos_vazia_comparecimento_zero']=absent
    df.loc[absent,cols]=0
    df[cols]=df[cols].astype('int64')
    return df


def sections(states, municipal, out):
    (out/'secoes.sql').write_text(SECTION_SQL)
    with connection(states) as db:
        df = db.execute(SECTION_SQL).fetchdf()
        independent = db.execute('''SELECT tipo_voto,numero,sum(quantidade)::BIGINT n FROM votos
           WHERE cargo=1 AND eleicao=6258 GROUP BY ALL''').fetchall()
    keys = ['uf','municipio','zona','secao','pleito']
    if df.duplicated(keys).any() or df.bu_id.duplicated().any():
        raise ValueError('duplicate section or BU; version reconciliation required')
    df=complete_empty_votes(df)
    if not ((df.validos==df.lula+df.bolsonaro) &
            (df.comparecimento==df.validos+df.brancos+df.nulos) &
            (df.aptos==df.comparecimento+df.abstencoes) &
            (df.votos_todos==df.comparecimento) &
            (df.aptos==df.aptos_originais+df.aptos_temporarios)).all():
        raise ValueError('section accounting identity failed')
    # Python integer loop is independent of the SQL aggregation and section join.
    for typ,num,n in independent:
        col = {1: {13:'lula',22:'bolsonaro'}.get(num),2:'brancos',3:'nulos'}.get(typ)
        if col is None or sum(int(x) for x in df[col]) != n:
            raise ValueError('independent vote aggregate mismatch')
    names = {(a['cd'].upper(),int(m['cd'])):m['nm'] for a in municipal['abr'] for m in a['mu']}
    if any((u,int(m)) not in names for u,m in zip(df.uf,df.municipio)):
        raise ValueError('municipality missing from official configuration')
    df['municipio_nome'] = [names[(u,int(m))] for u,m in zip(df.uf,df.municipio)]
    df['fuso_analise'] = [municipality_zone(u,n) for u,n in zip(df.uf,df.municipio_nome)]
    df['encerramento_brasilia_analise'] = [closure_brasilia(r,z,o) for r,z,o in
        zip(df.encerramento_original,df.fuso_analise,df.origem)]
    # Offset-aware time converted first; then store wall-clock seconds of Brasilia.
    timestamps = pd.to_datetime(df.encerramento_brasilia_analise,utc=True).dt.tz_convert('America/Sao_Paulo')
    df['encerramento_segundos_brasilia'] = timestamps.dt.hour*3600 + timestamps.dt.minute*60 + timestamps.dt.second
    df['data_encerramento_brasilia'] = timestamps.dt.strftime('%Y-%m-%d')
    pq.write_table(pa.Table.from_pandas(df,preserve_index=False),out/'secoes.parquet',compression='zstd')
    return df


def aggregate_times(df, out):
    domestic = df[df.uf!='ZZ']
    seconds = domestic.encerramento_segundos_brasilia
    known = seconds.notna() & (domestic.data_encerramento_brasilia=='2026-10-25')
    predicates = {
        'ate_170000':known & (seconds<=61200),
        'apos_170000':known & (seconds>61200),
        '170001_170059':known & (seconds>61200) & (seconds<61260),
        '170100_171559':known & (seconds>=61260) & (seconds<62160),
        '171600_185959':known & (seconds>=62160) & (seconds<68400),
        'apos_190000':known & (seconds>68400),
        'a_partir_190000':known & (seconds>=68400)}
    rows = []
    for label,mask in predicates.items():
        part=domestic[mask]
        valid=int(part.validos.sum()); b=int(part.bolsonaro.sum()); l=int(part.lula.sum())
        rows.append({'faixa':label,'secoes':len(part),'lula':l,'bolsonaro':b,'validos':valid,
                     'percentual_bolsonaro_validos':100*b/valid if valid else None,'vantagem_bolsonaro':b-l})
    write_csv(out/'horarios.csv',rows)
    # Allow replication by UF/municipality/zone/section without repeating vote rows.
    for level in [['uf'],['uf','municipio'],['uf','municipio','zona']]:
        selected=domestic[known].copy()
        selected['faixa']=pd.cut(selected.encerramento_segundos_brasilia,
            [-1,61200,61259,62159,68399,68400,172800],
            labels=['ate_17','170001_170059','1701_1715','1716_1859','190000','apos_19'])
        selected.groupby([*level,'faixa'],observed=True).agg(secoes=('bu_id','size'),lula=('lula','sum'),
            bolsonaro=('bolsonaro','sum'),validos=('validos','sum')).reset_index().to_csv(out/('horarios-'+'-'.join(level)+'.csv'),index=False)
    result={'population':'seções domésticas; data de encerramento em Brasília = 25/10/2026',
            'known':int(known.sum()),'domestic':len(domestic),'unresolved':int((~known).sum()),
            'exterior_excluded':int((df.uf=='ZZ').sum()),'bins':rows,
            'official_differences':{'closed_after_17':sum(r['secoes'] for r in rows if r['faixa']=='apos_170000')-497333, 'closed_after_19':sum(r['secoes'] for r in rows if r['faixa']=='apos_190000')-6766},
            'official_reference':{'closed_after_17':497333,'closed_after_19':6766,
                                  'individual_votes_after_17':34393,'url':LATE_SOURCE},
            'limitation':'BU registra encerramento, não horário individual do voto; SA/fusos não resolvidos e datas diferentes ficam fora e são quantificados.'}
    atomic_json(out/'horarios.json',result)
    return result


def local_time_sensitivity(df, out):
    """Reproduce raw-clock and minute choices separately from normalized times."""
    raw=pd.to_datetime(df.encerramento_original,format='%Y%m%dT%H%M%S',errors='coerce')
    seconds=raw.dt.hour*3600+raw.dt.minute*60+raw.dt.second
    known=raw.notna() & (raw.dt.strftime('%Y-%m-%d')=='2026-10-25')
    filters={
        'ate_170059_local':known & (seconds<61260),
        'apos_170059_local':known & (seconds>=61260),
        '170100_171559_local':known & (seconds>=61260)&(seconds<62160),
        '171600_185959_local':known & (seconds>=62160)&(seconds<68400),
        'apos_190000_local':known & (seconds>68400),
        'exatamente_190000_local':known & (seconds==68400)}
    rows=[]
    for label,mask in filters.items():
        part=df[mask];l=int(part.lula.sum());b=int(part.bolsonaro.sum());v=int(part.validos.sum())
        rows.append({'faixa':label,'secoes':len(part),'lula':l,'bolsonaro':b,'validos':v,
                     'percentual_bolsonaro_validos':100*b/v if v else None,'vantagem_bolsonaro':b-l})
    write_csv(out/'horarios-sensibilidade-local.csv',rows)
    result={'population':'todas as regiões, inclusive ZZ, com horário original disponível; relógios locais não comparáveis entre fusos',
            'known':int(known.sum()),'unresolved':int((~known).sum()),'bins':rows,
            'warning':'Reprodução de escolhas de recorte. Não representa encerramento simultâneo em Brasília nem horário individual de voto.'}
    atomic_json(out/'horarios-sensibilidade-local.json',result)
    return result


def numeric_claim(identifier, text, alleged, measured, unit, evidence, *, tolerance=0, limitation=''):
    difference = measured-alleged if measured is not None else None
    return {'id':identifier,'transcricao_fornecida_no_pedido':text,'pagina':None,
            'originais_conferidos':False,'valor_alegado':alleged,'valor_calculado':measured,'valor_sensibilidade_local':None,'criterio_sensibilidade_local':None,
            'diferenca_absoluta':difference,'diferenca_percentual':100*difference/alleged if difference is not None and alleged else None,
            'unidade':unit,'criterio_tolerancia_absoluta':tolerance,
            'classificacao_numero':('Inconclusivo' if difference is None else 'Confirmado' if abs(difference)<=tolerance+1e-10 else 'Contradito pelos dados'),
            'classificacao_conclusao_autor':'Inconclusivo','evidencia':evidence,
            'funcao_reproducao':('auditoria_urnas.analysis:aggregate_times' if identifier.startswith('B') else 'auditoria_urnas.statistics:calculate'),'limitacoes':limitation or 'Conferência preliminar do texto do pedido; aguarda prints e definição original.'}


def claims_report(out, rec, times, stats, local):
    bins={r['faixa']:r for r in times['bins']}
    claims=[numeric_claim('B01','52,39% dos votos para Flávio nas urnas encerradas até 17h',52.39,
                         bins['ate_170000']['percentual_bolsonaro_validos'],'percentual','horarios.csv',tolerance=.005,
                         limitation=times['limitation']),
        numeric_claim('B02','Vantagem de quase 1,8 milhão até 17h',1800000,bins['ate_170000']['vantagem_bolsonaro'],'votos','horarios.csv',tolerance=50000,
                      limitation='Aproximação quase 1,8 milhão: tolerância exploratória 50 mil, não definida pelo autor.'),
        numeric_claim('B03','Vantagem de mais de 6,1 milhões para Lula depois das 17h',6100000,
                      -bins['apos_170000']['vantagem_bolsonaro'],'votos','horarios.csv'),
        numeric_claim('B04','339.593 seções entre 17h01 e 17h15',339593,bins['170100_171559']['secoes'],'seções','horarios.csv'),
        numeric_claim('B05','2.472 seções entre 17h16 e 18h59',2472,bins['171600_185959']['secoes'],'seções','horarios.csv'),
        numeric_claim('B06','6.333 seções depois das 19h',6333,bins['apos_190000']['secoes'],'seções','horarios.csv'),
        numeric_claim('C01','8.632.488 eleitores habilitados sem biometria',8632488,stats['biometry']['without_registered_biometrics'],'eleitores','estatisticas.json',
                      limitation='sem_biometria_cadastrada; habilitados_biografia é outra categoria. Exterior sem detalhe não foi imputado.'),
        numeric_claim('C02','8.632.488 habilitados por biografia (sensibilidade de definição)',8632488,stats['biometry']['biographic_enabled'],'eleitores','estatisticas.json'),
        numeric_claim('C03','6,73% dos comparecentes',6.73,stats['biometry']['biographic_pct_national_turnout'],'percentual','estatisticas.json',tolerance=.005),
        numeric_claim('D01','106 seções com 100% dos válidos para Lula',106,stats['unanimity']['lula100'],'seções','estatisticas.json'),
        numeric_claim('D02','Quatro seções com 100% dos válidos para Bolsonaro',4,stats['unanimity']['bolsonaro100'],'seções','estatisticas.json'),
        numeric_claim('D03','6.899 seções com mais de 90% para Lula',6899,stats['unanimity']['lula_gt90'],'seções','estatisticas.json',
                      limitation=f"Comparação estrita >90%; com >=90%: {stats['unanimity']['lula_ge90']}."),
        numeric_claim('D04','384 seções com mais de 90% para Bolsonaro',384,stats['unanimity']['bolsonaro_gt90'],'seções','estatisticas.json',
                      limitation=f"Comparação estrita >90%; com >=90%: {stats['unanimity']['bolsonaro_ge90']}.")]
    local_bins={r['faixa']:r for r in local['bins']}
    alternative={
        'B01':('ate_170059_local','percentual_bolsonaro_validos'),
        'B02':('ate_170059_local','vantagem_bolsonaro'),
        'B03':('apos_170059_local','vantagem_bolsonaro'),
        'B04':('170100_171559_local','secoes'),
        'B05':('171600_185959_local','secoes'),
        'B06':('apos_190000_local','secoes')}
    for c in claims:
        if c['id'] in alternative:
            label,metric=alternative[c['id']]
            val=local_bins[label][metric]
            c['valor_sensibilidade_local']=-val if c['id']=='B03' else val
            c['criterio_sensibilidade_local']=label+'; horários originais locais, inclusive exterior quando disponível; sem normalização de fusos'
            c['limitacoes'] += ' Sensibilidade local calculada em horarios-sensibilidade-local.csv; não equivale ao corte nacional em Brasília.'
    # This is an inequality, not an equality to an approximate threshold.
    claims[2]['classificacao_numero']='Confirmado' if claims[2]['valor_calculado']>6100000 else 'Contradito pelos dados'
    claims[2]['limitacoes']='Critério: valor > 6.100.000; dados de encerramento não representam votos individuais após 17h.'
    if times['unresolved']:
        for c in claims:
            if c['id'].startswith('B'):
                c['classificacao_numero']='Inconclusivo'
                c['limitacoes'] += f" Cobertura incompleta: {times['unresolved']} seções domésticas fora do recorte temporal."
    for c in claims:
        if c['id'] in alternative and c['id'] not in {'B02','B03'}:
            if abs(c['valor_sensibilidade_local']-c['valor_alegado'])<=c['criterio_tolerancia_absoluta']+1e-10:
                c['classificacao_numero']='Parcialmente confirmado'
        if c['id']=='B03' and c['valor_sensibilidade_local']>6100000:
            c['classificacao_numero']='Parcialmente confirmado'
        if c['id']=='B02':
            c['classificacao_numero']='Inconclusivo'
            c['criterio_tolerancia_absoluta']=None
            c['limitacoes']='Quase 1,8 milhão não define tolerância matemática; os dois recortes e suas margens são fornecidos, sem decidir uma igualdade aproximada arbitrária.'
    for ident,text in [('E01','Benford mencionado nos prints'),('F01','72 horas sem acesso aos dados de urnas'),('G01','Afirmações políticas, jurídicas e institucionais das páginas 4 e 5')]:
        claims.append(numeric_claim(ident,text,None,None,'','limitacoes.md',limitation='Sem os prints e/ou evidência histórica primária suficiente para confirmar a alegação.'))
    write_csv(out/'alegacoes.csv',claims)
    atomic_json(out/'alegacoes.json',claims)
    return claims


def render_reports(out, rec, times, stats, claims, metadata, local):
    import html
    import markdown
    from .report import render_pdf
    n=rec['national'];bio=stats['biometry'];uni=stats['unanimity']
    lines=['# Auditoria dos boletins e confronto com a totalização',
           f"Executado em {metadata['started_utc']}. Eleição 6258, presidente, segundo turno de 25/10/2026.",
           '## Resultado da reconciliação',
           f"{rec['comparisons']} comparações entre os boletins e os snapshots EA20 oficiais: " + ('nenhuma divergência.' if rec['passed'] else f"{len(rec['divergences'])} divergências; consultar reconciliacao.csv."),
           f"Seções instaladas: {n['secoes']:,}. Lula: {n['lula']:,}; Flávio Bolsonaro: {n['bolsonaro']:,}; brancos: {n['brancos']:,}; nulos: {n['nulos']:,}.",
           f"Comparecimento: {n['comparecimento']:,}; abstenções: {n['abstencoes']:,}; aptos das seções instaladas: {n['aptos']:,}.",
           f"O EA20 nacional informa {rec['uninstalled']['secoes_nao_instaladas']} seções não instaladas, com {rec['uninstalled']['aptos_nao_instaladas']} registros de aptos. Esses registros não integram a soma de seções instaladas. Não são uma divergência de votos.",
           'O cadastro contém particularidades de transferência temporária; somas de registros por seção não devem ser automaticamente chamadas de pessoas únicas.',
           '## Alegações numéricas fornecidas no pedido',
           'Os sete prints ainda não estavam na pasta de entrada. Os números abaixo conferem o enunciado do pedido; página e transcrição fiel permanecem pendentes. A classificação do número é separada da conclusão do autor.']
    for c in claims:
        lines += [f"### {c['id']}: {c['transcricao_fornecida_no_pedido']}",
                  f"Alegado: {c['valor_alegado']}; calculado no critério principal: {c['valor_calculado']}; sensibilidade de horário local: {c['valor_sensibilidade_local']}; classificação numérica preliminar: {c['classificacao_numero']}.",
                  c['limitacoes']]
    lines += ['## Horários e cobertura',
              f"Seções domésticas com horário e data utilizáveis: {times['known']:,} de {times['domestic']:,}. Fora do recorte: {times['unresolved']:,}. Exterior excluído deste confronto: {times['exterior_excluded']:,}.",
              'O horário original é preservado. O fuso por município utiliza o cadastro EA12 e as regras oficiais de AM e Fernando de Noronha. As linhas originais dos Parquets não são alteradas.',
              'Os valores 52,39%, 339.593 e 2.472 são reproduzidos ao comparar relógios locais sem normalização, com o grupo até 17h incluindo todos os segundos de 17h00. A sensibilidade também calcula o corte estrito depois de 19h. Isso não demonstra o método original sem os prints, mas explica como números podem coincidir com populações temporalmente diferentes. Consulte horarios-sensibilidade-local.csv.',
              'Encerramento não é horário do último eleitor, emissão do BU, transmissão, recebimento nem totalização. A soma dos votos de seções encerradas tarde não informa quantos votos foram registrados tarde nem em quem esses eleitores votaram.',
              f"Diferenças de contagem frente ao comunicado oficial: {times['official_differences']}.",
              'O comunicado oficial de 27/10 menciona 497.333 seções domésticas encerradas após 17h, 6.766 após 19h e 34.393 votos individuais após 17h. O último número exige logs para reconstrução independente; não foi recalculado a partir de BUs.',
              '## Biometria e controles geográficos',
              f"Habilitados por biografia: {bio['biographic_enabled']:,}; sem biometria cadastrada: {bio['without_registered_biometrics']:,}; habilitados por biometria: {bio['biometric_enabled']:,}.",
              f"Biografia dividida pelo comparecimento nacional: {bio['biographic_pct_national_turnout']:.6f}%. Detalhe disponível em {bio['sections_with_detail']:,} seções; ausente em {bio['sections_missing_detail']:,}.",
              'Habilitação biográfica de eleitor com biometria cadastrada não é a mesma categoria que ausência de biometria cadastrada. Ausência de detalhe não foi preenchida com zero.',
              'O modelo descritivo usa fração de votos válidos para Lula, ponderação por válidos, log de aptos, comparecimento/aptos e fração de brancos+nulos. Compara associação sem efeitos geográficos, com efeitos fixos de UF e de município por transformação de médias ponderadas. Erros agrupados por município. Consulte modelos.csv e estatisticas.json.',
              'As correlações e regressões são ecológicas, não causais. Não há características individuais, controle socioeconômico completo nem ligação entre identificação do eleitor e candidato. A sensibilidade geográfica ajuda a examinar confusão e Simpson, mas não elimina toda confusão.',
              '## Votação concentrada e simulações',
              f"Seções sem válidos excluídas dos percentuais: {uni['zero_valid']}. Comparações de 90% usam inteiros (10*votos > 9*válidos), sem erro de arredondamento.",
              'As distribuições por UF, município e tamanho do eleitorado estão em concentracao-*.csv. A simulação binomial usa n igual aos válidos da seção e probabilidade municipal calculada deixando a própria seção fora. Municípios sem outros votos válidos são excluídos da simulação. Ela é uma hipótese ilustrativa de homogeneidade dentro do município, não um detector de fraude; heterogeneidade local pode gerar forte sobredispersão.',
              '## Benford e testes exploratórios',
              'Primeiro e segundo dígitos são calculados para contagens positivas de cada candidato, por seção e município. Segundo dígito requer valor >=10. São informados MAD, qui-quadrado, p-valor e correção de Holm. Contagens de seção são limitadas pelo eleitorado e não foram demonstradas como amostras adequadas à lei de Benford. Os testes são descritivos e não constituem evidência de fraude.',
              'Simulações condicionais de primeiro dígito usam a mesma hipótese municipal binomial, com semente e repetições registradas. O intervalo simulado depende dessa hipótese e não estabelece normalidade eleitoral.',
              '## Fontes e rastreabilidade',
              f"Resultados e configuração municipal: {BASE}/dados/br/br-c0001-e006258-u.json e {BASE}/config/mun-e006258-cm.json. BR inclui ZZ; UF e ZZ são confrontados separadamente.",
              f"Documentação de campos e organização: {DOCS}",
              *TIME_SOURCES,LATE_SOURCE,
              'input-manifest.json seleciona cada Parquet por checkpoint e hash. sources.json registra cada URL e SHA-256 dos bytes HTTP preservados, datas de consulta e versão. ambiente.json registra versões, parâmetros e assinaturas de código. secoes.sql contém a consulta e o pacote Python contém as funções de reprodução.',
              'Hash local, assinatura digital e consistência de conteúdo são verificações diferentes. A autenticidade criptográfica de assinaturas digitais não foi verificada.',
              '## Limitações e próximos passos',
              'A investigação das 72 horas exige histórico de disponibilidade: Last-Modified e a data de um snapshot atual não provam o primeiro momento de publicação. As alegações institucionais exigem os prints e documentos primários específicos.',
              'RDVs, logs, correspondências, substituições e totalização de votos eventualmente rejeitados exigem integração própria. Este relatório não declara essas análises concluídas. Primeiro turno e eleições anteriores não integram esta rodada.',
              'O confronto entre fontes do mesmo órgão verifica consistência pública; não estabelece, sozinho, a autenticidade de cada voto ou uma conclusão geral de fraude ou integridade.']
    md='\n\n'.join(lines)+'\n'
    (out/'relatorio.md').write_text(md)
    (out/'relatorio.html').write_text('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Auditoria dos boletins</title><style>body{max-width:960px;margin:40px auto;font:17px/1.6 sans-serif;padding:16px}a{overflow-wrap:anywhere}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #bbb}</style>'+markdown.markdown(md,extensions=['tables'])+'</html>')
    render_pdf(md,out/'relatorio.pdf',title='Auditoria dos boletins e confronto com a totalização',footer='Auditoria independente - resultados preliminares e limitações')
    (out/'limitacoes.md').write_text('\n\n'.join(lines[lines.index('## Limitações e próximos passos'):]))
    summary=['# Resumo executivo',
        f"Foram comparadas {n['secoes']:,} seções com a totalização oficial nacional, de cada UF e do exterior. Diferenças encontradas: {len(rec['divergences'])}.",
        f"A contagem de habilitação biográfica é {bio['biographic_enabled']:,}, enquanto a categoria sem biometria cadastrada soma {bio['without_registered_biometrics']:,}. A interpretação depende da definição correta.",
        f"Unanimidade nos válidos: {uni['lula100']} seções para Lula e {uni['bolsonaro100']} para Flávio. Mais de 90%: {uni['lula_gt90']} e {uni['bolsonaro_gt90']}; pelo menos 90%: {uni['lula_ge90']} e {uni['bolsonaro_ge90']}.",
        'Horário de encerramento não permite atribuir horário individual aos votos. Os resultados completos, filtros e limites estão no relatório técnico.',
        'A análise ainda depende dos sete prints para reproduzir fielmente todas as alegações, e de logs/RDVs e evidências históricas para questões que os BUs não respondem. Os resultados não são uma conclusão geral sobre fraude ou integridade.']
    (out/'resumo.md').write_text('\n\n'.join(summary)+'\n')


def run(*, seed=20261025, simulations=100):
    from .statistics import calculate
    folder=root()/'output/analises'/now().replace(':','').replace('.','')
    folder.mkdir(parents=True)
    meta={'status':'running','pid':os.getpid(),'started_utc':now(),'output':str(folder),
          'analysis_signature':signature(),'seed':seed,'simulations':simulations,
          'backend':'CPU; DuckDB + NumPy/SciPy/statsmodels','gpu_used':False}
    pointer=root()/'data/checkpoints/latest-analysis.json'
    atomic_json(pointer,meta)
    try:
        import tarfile
        with tarfile.open(folder/'source-code.tar.gz','x:gz') as archive:
            for relative in ['src','tests','scripts','specs','pyproject.toml','uv.lock']:
                archive.add(root()/relative,arcname=relative,filter=lambda info: None if '__pycache__' in info.name else info)
        atomic_json(folder/'source-archive.json',{'sha256':digest(folder/'source-code.tar.gz'),'analysis_signature':meta['analysis_signature']})
        states=committed_inputs(folder)
        source_folder=root()/'data/raw/official-analysis'/folder.name
        sources,provenance={},[]
        for uf in ['BR',*UFS]:
            low=uf.lower()
            obj,entry=snapshot(f'{BASE}/dados/{low}/{low}-c0001-e006258-u.json',source_folder/f'{low}-ea20.json')
            official_values(obj,uf)
            sources[uf]=obj;provenance.append(entry)
        municipal,entry=snapshot(f'{BASE}/config/mun-e006258-cm.json',source_folder/'municipios-ea12.json')
        if municipal.get('f')!='o':raise ValueError('non-official municipality configuration')
        provenance.append(entry)
        atomic_json(folder/'sources.json',provenance)
        emit('analysis_snapshots_saved',count=len(provenance))
        df=sections(states,municipal,folder)
        rec=reconcile(df,sources,folder)
        emit('analysis_reconciled',**rec)
        times=aggregate_times(df,folder)
        local=local_time_sensitivity(df,folder)
        inconsistencies=[{'id':'T01','onde':'horarios.json: official_differences.closed_after_17','diferenca':times['official_differences']['closed_after_17'],'para_esclarecer':'Obter universo, campo temporal e registros por seção usados no levantamento oficial de 27/10; distinguir logs de encerramento do BU.'},
            {'id':'T02','onde':'horarios.json: official_differences.closed_after_19','diferenca':times['official_differences']['closed_after_19'],'para_esclarecer':'Confrontar listagem oficial por seção e definir se corte inclui o segundo 19:00:00 e qual fuso foi utilizado.'},
            {'id':'M01','onde':'input/relatorio_original','diferenca':None,'para_esclarecer':'Disponibilizar os sete prints para conferir transcrição, páginas, definições e conclusões originais.'}]
        write_csv(folder/'inconsistencias.csv',inconsistencies)
        stats=calculate(df,folder,seed=seed,simulations=simulations)
        claims=claims_report(folder,rec,times,stats,local)
        import importlib.metadata
        atomic_json(folder/'ambiente.json',{**meta,'python':sys.version,'platform':platform.platform(),
            'packages':{p:importlib.metadata.version(p) for p in ['duckdb','pyarrow','numpy','scipy','statsmodels','plotly']}})
        render_reports(folder,rec,times,stats,claims,meta,local)
        if signature()!=meta['analysis_signature']:raise ValueError('analysis source changed during execution')
        meta.update(status='complete',finished_utc=now(),reconciliation_passed=rec['passed'])
        atomic_json(folder/'status.json',meta)
        atomic_json(pointer,meta)
        emit('analysis_complete',**meta)
        return folder
    except BaseException as e:
        meta.update(status='failed',error=str(e),traceback=traceback.format_exc(),finished_utc=now())
        atomic_json(folder/'status.json',meta);atomic_json(pointer,meta)
        emit('analysis_failed',**meta)
        raise


def pilot():
    from .statistics import calculate
    out=root()/'output/analysis-pilot'
    out.mkdir(exist_ok=True)
    selected=json.loads(Path(json.loads((root()/'data/checkpoints/latest-run.json').read_text())['path']).read_text())
    states=[json.loads(Path(next(s['checkpoint'] for s in selected['completed'] if s['uf']==uf)).read_text()) for uf in ['RR','ZZ']]
    for state in states:
        for batch in state['batches']:
            for item in batch.values():
                if digest(Path(item['path']))!=item['sha256']:raise ValueError('pilot input hash changed')
    municipal,_=snapshot(BASE+'/config/mun-e006258-cm.json',out/'municipios-ea12.json')
    df=sections(states,municipal,out)
    comparisons={}
    for uf in ['RR','ZZ']:
        official,_=snapshot(BASE+f'/dados/{uf.lower()}/{uf.lower()}-c0001-e006258-u.json',out/f'{uf.lower()}-ea20.json')
        expected,_=official_values(official,uf)
        part=df[df.uf==uf]
        actual={m:(len(part) if m=='secoes' else int(part[m].sum())) for m in expected}
        if actual!=expected:raise ValueError(f'{uf} pilot official reconciliation failed')
        comparisons[uf]=actual
    calculate(df,out,seed=20261025,simulations=20)
    gate={'passed':True,'analysis_signature':signature(),'finished_utc':now(),'ufs':['RR','ZZ'],
          'sections':len(df),'reconciliation':comparisons,'simulations':20}
    atomic_json(out/'gate.json',gate)
    emit('analysis_pilot_passed',**gate)


def execute(*,seed=20261025,simulations=100):
    gate=json.loads((root()/'output/analysis-pilot/gate.json').read_text())
    if not gate.get('passed') or gate['analysis_signature']!=signature():
        raise ValueError('run piloto-analise with the current source and dependencies first')
    with (root()/'data/checkpoints/analysis.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return run(seed=seed,simulations=simulations)


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seed',type=int,default=20261025)
    p.add_argument('--simulations',type=int,default=100)
    a=p.parse_args()
    if not 20<=a.simulations<=1000:p.error('simulations must be between 20 and 1000')
    execute(seed=a.seed,simulations=a.simulations)


if __name__=='__main__':main()
