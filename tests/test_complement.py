import copy,hashlib,io,json,zipfile
from pathlib import Path

import pytest

from auditoria_urnas.complement_parsers import summarize_log_lines,parse_log,parse_rdv,verify_signatures,signature_codec,rdv_codec
from auditoria_urnas.complement_statistics import fit_beta_binomial
from auditoria_urnas.complement_sources import bweb_sections,correspondences,select_resources
from auditoria_urnas.common import original_dir


def line(stamp,message,app='VOTA'):
    return f'{stamp}\tINFO\t12345\t{app}\t{message}\tABCDEF\n'


def test_log_separates_rounds_and_counts_terminal_events_once_per_occurrence():
    rows=[line('04/10/2026 17:30:00','Iniciando aplicação - 1º turno'),line('04/10/2026 17:31:00','O voto do eleitor foi computado'),
          line('25/10/2026 15:00:00','Iniciando aplicação - 2º turno'),
          line('25/10/2026 15:00:00','Eleitor foi habilitado'),line('25/10/2026 15:00:00','Voto confirmado para [Presidente]'),
          line('25/10/2026 15:00:00','O voto do eleitor foi computado'),
          line('25/10/2026 15:00:01','O voto do eleitor foi computado'),
          line('25/10/2026 15:00:02','Habilitação cancelada durante confirmação de dado do eleitor'),
          line('25/10/2026 17:00:01','O voto do eleitor foi computado')]
    value=summarize_log_lines(rows,'America/Rio_Branco')
    assert value['log_total_computados']==3
    assert value['log_total_confirmados_presidente']==1
    assert value['log_apos17']==2 and value['log_apos19']==1
    assert value['log_cancelamentos']==1
    assert value['log_contagem_temporal_confiavel']
    # A repeated terminal event at the same timestamp is not silently deduplicated.
    doubled=summarize_log_lines(rows+[rows[-1]],'America/Rio_Branco')
    assert doubled['log_total_computados']==4


def test_log_unknown_round_clock_adjustment_and_missing_zone_are_explicit():
    row=line('25/10/2026 17:01:00','O voto do eleitor foi computado')
    unknown=summarize_log_lines([row],'America/Sao_Paulo')
    assert unknown['log_total_computados']==0 and unknown['log_eventos_sem_turno']==1
    rows=[line('25/10/2026 10:00:00','Iniciando aplicação - 2º turno'),row,line('25/10/2026 18:00:00','Ajuste do relógio da urna')]
    value=summarize_log_lines(rows,'America/Sao_Paulo')
    assert value['log_ajustes_relogio']==1 and not value['log_contagem_temporal_confiavel']
    value=summarize_log_lines(rows,None)
    assert value['log_apos17'] is None
    value=summarize_log_lines(rows,'America/Sao_Paulo','dadosSA')
    assert value['log_apos17'] is None and not value['log_contagem_temporal_confiavel']
    # Individual identifiers from an unrelated log message must not be exported.
    assert '123456789012' not in json.dumps(summarize_log_lines(rows+[line('25/10/2026 17:02:00','Título: 123456789012')],None))


def test_nested_logs_reject_duplicates_corruption_and_oversized_untrusted_members():
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w') as z:z.writestr('unexpected.dat',b'fake')
    with pytest.raises(ValueError,match='unexpected'):parse_log(raw.getvalue(),None,'dadosSecao')
    with pytest.raises(zipfile.BadZipFile):parse_log(b'truncated',None,'dadosSecao')


@pytest.mark.integration
def test_real_rdv_uses_distinct_vote_enums_and_checks_identity():
    with zipfile.ZipFile(original_dir()/'bu_imgbu_logjez_rdv_vscmr_2026_2t_RR.zip') as z:
        name=next(n for n in z.namelist() if n.endswith('-rdv.dat'));raw=z.read(name)
    value=parse_rdv(raw,(3000,4,11))
    assert value['rdv_total']==212 and value['rdv_brancos']==1 and value['rdv_nulos']==3
    assert value['rdv_lula']+value['rdv_bolsonaro']==208
    with pytest.raises(ValueError,match='identity'):parse_rdv(raw,(3000,4,12))
    with pytest.raises(ValueError,match='trailing'):parse_rdv(raw+b'x',(3000,4,11))


@pytest.mark.integration
def test_rdv_synthetic_blank_after_suspension_is_not_nominal():
    with zipfile.ZipFile(original_dir()/'bu_imgbu_logjez_rdv_vscmr_2026_2t_RR.zip') as z:
        raw=z.read(next(n for n in z.namelist() if n.endswith('-rdv.dat')))
    codec=rdv_codec();obj=codec.decode('EntidadeResultadoRDV',raw)
    obj['rdv']['eleicoes'][1][0]['votosCargos'][0]['votos']=[{'tipoVoto':5},{'tipoVoto':6},{'tipoVoto':2,'digitacao':'13'}]
    result=parse_rdv(codec.encode('EntidadeResultadoRDV',obj),(3000,4,11))
    assert (result['rdv_total'],result['rdv_brancos'],result['rdv_nulos'],result['rdv_lula'])==(3,1,1,1)


@pytest.mark.integration
@pytest.mark.parametrize('uf,suffix',[('RR','vota.vsc'),('ZZ','vota.vsc'),('ZZ','sa.vsc')])
def test_real_hardware_signatures_and_modified_payloads(uf,suffix):
    with zipfile.ZipFile(original_dir()/f'bu_imgbu_logjez_rdv_vscmr_2026_2t_{uf}.zip') as z:
        names=set(z.namelist());name=next(n for n in z.namelist() if n.endswith(suffix));raw=z.read(name)
        result=verify_signatures(raw,z.read,names.__contains__)
        assert result['assinatura_hashes_incompativeis']==0
        assert result['assinatura_hw_verificadas']>0 and result['assinatura_hw_invalidas']==0
        assert result['assinatura_hw_autoassinatura']=='compativel'
        assert result['assinatura_cadeia']=='emissor_oficial_assinatura_compativel'
        assert result['assinatura_validade_eleicao'] is True
        changed=verify_signatures(raw,lambda n:z.read(n)+b'changed',names.__contains__,verify_crypto=False)
        assert changed['assinatura_hashes_incompativeis']>0
        codec=signature_codec();obj=codec.decode('EntidadeAssinaturaEcourna',raw)
        payload=codec.decode('Assinatura',obj['assinaturaHW']['conteudoAutoAssinado'])
        payload['arquivosAssinados'][0]['assinatura']['assinatura']=b'\x00'*len(payload['arquivosAssinados'][0]['assinatura']['assinatura'])
        obj['assinaturaHW']['conteudoAutoAssinado']=codec.encode('Assinatura',payload)
        altered=verify_signatures(codec.encode('EntidadeAssinaturaEcourna',obj),z.read,names.__contains__)
        assert altered['assinatura_hashes_incompativeis']>0
        assert altered['assinatura_hw_invalidas']>0
        assert 'CEPESC' not in result['assinatura_hw_autoassinatura']


@pytest.mark.integration
def test_missing_signed_member_is_not_marked_cryptographically_invalid():
    with zipfile.ZipFile(original_dir()/'bu_imgbu_logjez_rdv_vscmr_2026_2t_RR.zip') as z:
        raw=z.read(next(n for n in z.namelist() if n.endswith('vota.vsc')))
        result=verify_signatures(raw,z.read,lambda n:False,verify_crypto=False)
    assert result['assinatura_membros_nao_publicados']>0
    assert result['assinatura_hashes_incompativeis']==0 and result['assinatura_hw_verificadas']==0


@pytest.mark.integration
def test_untrusted_issuer_is_separate_from_valid_file_signature(monkeypatch):
    from auditoria_urnas.official import mr_util
    monkeypatch.setattr(mr_util,'valida_certificado',lambda *args:False)
    with zipfile.ZipFile(original_dir()/'bu_imgbu_logjez_rdv_vscmr_2026_2t_RR.zip') as z:
        names=set(z.namelist());raw=z.read(next(n for n in names if n.endswith('vota.vsc')))
        result=verify_signatures(raw,z.read,names.__contains__)
    assert result['assinatura_cadeia']=='assinatura_emissor_invalida'
    assert result['assinatura_hw_invalidas']==0 and result['assinatura_hw_verificadas']>0
    assert result['assinatura_status']=='verificacao_parcial'


def test_beta_binomial_known_overdispersion():
    import numpy as np
    rng=np.random.default_rng(20261025);n=np.full(1500,200);p=np.full(1500,.5)
    k=rng.binomial(n,rng.beta(5,5,size=len(n)))
    value=fit_beta_binomial(n,k,p)
    assert value['converged'] and .06<value['rho']<.13


def test_resource_selection_preserves_expected_versions_and_uses_latest_effective():
    base='https://cdn.tse.jus.br/'
    resources=[{'url':base+n} for n in ['CESP_2t_RR_241020261231.zip','CESP_2t_RR_251020261345.zip','CEFT_2t_RR_261020261201.zip','bweb_2t_RR_261020260742.zip','bweb_2t_RR_261020260742.zip.sha512']]
    selected=select_resources({'resources':resources},['RR'])
    assert len(selected)==4
    assert next(x for x in selected if x['kind']=='bweb')['hash_url'].endswith('.sha512')


@pytest.mark.integration
def test_committed_complement_batches_resume_without_duplicates_and_reject_corruption(tmp_path,monkeypatch):
    import shutil
    import pyarrow as pa,pyarrow.parquet as pq
    from auditoria_urnas import complement as comp
    from auditoria_urnas.common import root,stat_key
    real=root();base=comp.base_data();original=comp.state_sources(['RR'])['RR']
    selected=comp.section_rows(base,'RR')[:3]
    for name in ['src','specs','scripts','tests','docs']:shutil.copytree(real/name,tmp_path/name)
    for name in ['uv.lock','pyproject.toml']:shutil.copy(real/name,tmp_path/name)
    monkeypatch.setenv('URNAS_PROJECT_ROOT',str(tmp_path));monkeypatch.setattr(comp,'BATCH',2)
    path=tmp_path/'sections.parquet';pq.write_table(pa.Table.from_pylist(selected),path)
    base={**base,'sections':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    version=comp.complement_signature()
    def interrupt(state):
        if state['processed']==2:raise KeyboardInterrupt('synthetic crash after committed checkpoint')
    with pytest.raises(KeyboardInterrupt):comp.process_state('RR',base,original,['rdv'],version,interrupt)
    state,path=comp.process_state('RR',base,original,['rdv'],version,lambda s:None)
    assert state['processed']==3 and len(state['batches'])==2
    with __import__('duckdb').connect() as db:
        result=db.read_parquet([b['path'] for b in state['batches']]).df()
        assert len(result)==result.bu_id.nunique()==3 and result.rdv_concorda_bu.all()
    Path(state['batches'][0]['path']).write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='Parquet changed'):
        comp.process_state('RR',base,original,['rdv'],version,lambda s:None)


def test_all_claims_have_exact_page_transcription_and_unique_identifiers():
    from auditoria_urnas.complement_report import definitions
    rows=definitions()
    assert len(rows)>=70 and len({r['id'] for r in rows})==len(rows)
    assert {r['page'] for r in rows}==set(range(1,8))


def test_anticipated_reserve_schema_and_bweb_duplicate_metrics(tmp_path):
    from auditoria_urnas.complement_sources import correspondences,bweb_sections
    p=tmp_path/'expected.zip'
    header='SG_UF;CD_PLEITO;CD_MUNICIPIO;NR_ZONA;NR_URNA_ESPERADA;CD_CARGA_URNA_ESPERADA\n'
    with zipfile.ZipFile(p,'w') as z:z.writestr('ccont_2t_RR_241020261231.csv',header+'RR;3221;3000;4;123;456\n')
    rows,headers=correspondences(p,'RR')
    assert rows[0]['record_type']=='contingencia' and rows[0]['secao'] is None
    with zipfile.ZipFile(p,'w') as z:z.writestr('unknown.csv',header+'RR;3221;3000;4;123;456\n')
    with pytest.raises(ValueError,match='unknown sectionless'):correspondences(p,'RR')


@pytest.mark.integration
def test_tabular_zero_turnout_coverage_and_manual_field_reconcile():
    from auditoria_urnas.common import root
    from auditoria_urnas.complement import base_data,section_rows
    path=root()/'data/raw/pilot/bweb_2t_ZZ_261020260742.zip'
    data,headers=bweb_sections(path,'ZZ');base=section_rows(base_data(),'ZZ')
    absent=[r for r in base if (r['municipio'],r['zona'],r['secao']) not in data]
    assert len(absent)==2 and sum(r['comparecimento'] for r in absent)==0
    assert sum(v['votes'].get(13,0) for v in data.values())==sum(r['lula'] for r in base)


@pytest.mark.integration
def test_preliminary_matrix_does_not_treat_unfinished_national_bweb_as_complete(tmp_path):
    from auditoria_urnas.complement_report import matrix
    from auditoria_urnas.complement import base_data
    result=matrix(base_data(),tmp_path)
    assert all(r['originais_conferidos'] for r in result)
    assert next(r for r in result if r['id']=='C01')['valor_calculado']==8632488
    assert next(r for r in result if r['id']=='B07S')['classificacao_numero']=='Inconclusivo'
    assert next(r for r in result if r['id']=='G04')['classificacao_interpretacao']=='Inconclusivo'


def test_load_code_normalization_preserves_meaning_without_coercing_other_formats():
    from auditoria_urnas.complement_tables import normalized_load
    assert normalized_load('079084187576558852268066')==normalized_load('79084187576558852268066')
    assert normalized_load('001')=='1'
    assert normalized_load('#NULO') is None
    assert normalized_load('1.0') is None


def test_batch_schema_keeps_error_fields_added_after_first_row(tmp_path):
    import pyarrow.parquet as pq
    from auditoria_urnas.complement import commit_batch
    result=commit_batch(tmp_path,0,[{'id':1,'rdv_status':'ok'},{'id':2,'rdv_status':'erro','rdv_erro':'known synthetic error'}])
    rows=pq.read_table(result['path']).to_pylist()
    assert rows[0]['rdv_erro'] is None and rows[1]['rdv_erro']=='known synthetic error'


def test_low_disk_margin_stops_before_publishing_a_batch(tmp_path,monkeypatch):
    from auditoria_urnas import complement as comp
    monkeypatch.setattr(comp,'MIN_FREE',10**30)
    with pytest.raises(OSError,match='20 GiB'):comp.commit_batch(tmp_path,0,[{'id':1}])
    assert not list(tmp_path.glob('*.parquet'))


@pytest.mark.integration
def test_nested_historical_log_reconciles_replaced_foreign_urn():
    with zipfile.ZipFile(original_dir()/'bu_imgbu_logjez_rdv_vscmr_2026_2t_ZZ.zip') as z:
        value=parse_log(z.read('o03221zz2935100010956-log.jez'),None,'dadosSecao',(29351,1,956))
    assert value['log_total_computados']==481
    assert value['log_total_confirmados_presidente']==481
    assert len(json.loads(value['log_componentes_json']))==2


def test_cross_file_event_copies_do_not_erase_within_file_multiplicity():
    intro=line('25/10/2026 10:00:00','Iniciando aplicação - 2º turno')
    event=line('25/10/2026 17:00:01','O voto do eleitor foi computado')
    def packed(text,history=None):
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:
            z.writestr('logd.dat',text.encode('latin1'))
            if history:z.writestr('history.jez',history)
        return raw.getvalue()
    raw=packed(intro+event+event,packed(intro+event))
    value=parse_log(raw,'America/Sao_Paulo','dadosSecao')
    assert value['log_total_computados']==2
    assert value['log_eventos_duplicados_entre_arquivos']==1


def test_log_identity_and_explicit_prior_round_are_not_counted_as_current_votes():
    rows=[line('25/10/2026 10:00:00','Iniciando aplicação - ELEIÇÃO OFICIAL SEGUNDO TURNO - 2º turno'),
          line('25/10/2026 10:00:01','Município: 1'),line('25/10/2026 10:00:01','Zona Eleitoral: 2'),
          line('25/10/2026 10:00:01','Seção Eleitoral: 4'),line('25/10/2026 17:00:01','O voto do eleitor foi computado')]
    value=summarize_log_lines(rows,'America/Sao_Paulo',identity=(1,2,3))
    assert value['log_total_computados']==0 and value['log_eventos_outra_secao']==1
    rows[3]=line('25/10/2026 10:00:01','Seção Eleitoral: 3')
    assert summarize_log_lines(rows,'America/Sao_Paulo',identity=(1,2,3))['log_total_computados']==1


def test_beta_binomial_result_is_json_serializable():
    import numpy as np
    result=fit_beta_binomial(np.full(20,20),np.arange(20),np.full(20,.5))
    assert json.loads(json.dumps(result))['converged']


@pytest.mark.integration
def test_real_domestic_log_uses_prior_gap_configuration_and_round_marker():
    with zipfile.ZipFile(original_dir()/'bu_imgbu_logjez_rdv_vscmr_2026_2t_RR.zip') as z:
        name='o03221rr0300000040011-log.jez'
        result=parse_log(z.read(name),'America/Boa_Vista','dadosSecao',(3000,4,11))
    assert result['log_total_computados']==212 and result['log_total_confirmados_presidente']==212
    assert result['log_contagem_temporal_confiavel']
