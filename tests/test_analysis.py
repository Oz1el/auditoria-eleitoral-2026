import copy
import numpy as np
import pytest
from auditoria_urnas.analysis import closure_brasilia,municipality_zone,official_values,numeric_claim
from auditoria_urnas.statistics import concentration_counts,digit_counts,benford_probabilities


def test_thresholds_use_integer_comparisons_and_exclude_empty_sections():
    c=concentration_counts([9,10,0,90,91],[1,0,0,10,9],[10,10,0,100,100])
    assert c['lula100']==1 and c['bolsonaro100']==0
    assert c['lula_gt90']==2 and c['lula_ge90']==4 and c['zero_valid']==1


def test_municipal_time_exceptions_and_ambiguous_origins():
    assert municipality_zone('AM','TABATINGA')=='America/Eirunepe'
    assert municipality_zone('AM','MANAUS')=='America/Manaus'
    assert municipality_zone('PE','FERNANDO DE NORONHA')=='America/Noronha'
    for uf,name,time in [('AM','TABATINGA','150000'),('AM','MANAUS','160000'),('PE','FERNANDO DE NORONHA','180000'),('RO','PORTO VELHO','160000')]:
        assert closure_brasilia('20261025T'+time,municipality_zone(uf,name),'dadosSecao')=='2026-10-25T17:00:00-03:00'
    assert closure_brasilia('20261025T170000',municipality_zone('ZZ','TOKYO'),'dadosSecao') is None
    assert closure_brasilia('20261025T170000','America/Sao_Paulo','dadosSA') is None


def test_digit_boundaries_and_probabilities():
    assert digit_counts([0,1,9,10,99,100,999,1000],1).tolist()==[4,0,0,0,0,0,0,0,3]
    assert digit_counts([0,1,9,10,99,100,999,1000],2).tolist()==[3,0,0,0,0,0,0,0,0,2]
    assert sum(benford_probabilities(1))==pytest.approx(1)
    assert sum(benford_probabilities(2))==pytest.approx(1)


def ea20():
    return {'ele':'6258','t':'2','f':'o','cdabr':'br','tf':'s','and':'f',
        'carg':[{'cd':'1','agr':[{'par':[{'cand':[{'n':'13','vap':'6'},{'n':'22','vap':'3'}]}]}]}],
        's':{'st':'3','si':'2','sni':'1','sa':'2','sna':'0'},
        'e':{'esi':'12','c':'10','a':'2','esni':'5','te':'17'},
        'v':{'tv':'10','vvc':'9','vb':'1','tvn':'0','vscv':'0','vv':'9','van':'0','vansj':'0','vn':'0','vnt':'0'}}


def test_official_uses_installed_electorate_and_rejects_unfinished_or_malformed():
    obj=ea20();values,extra=official_values(obj,'BR')
    assert values['aptos']==12 and extra['aptos_total_registros']==17
    obj['and']='p'
    with pytest.raises(ValueError,match='not final'):official_values(obj,'BR')
    obj=ea20();obj['v']['vb']='2'
    with pytest.raises(ValueError,match='accounting'):official_values(obj,'BR')


def test_rounded_percent_claim_and_missing_evidence():
    assert numeric_claim('x','x',6.73,6.731, '%','x',tolerance=.005)['classificacao_numero']=='Confirmado'
    assert numeric_claim('x','x',1,None,'','')['classificacao_numero']=='Inconclusivo'


def test_only_explicit_zero_turnout_allows_empty_vote_list():
    import pandas as pd
    from auditoria_urnas.analysis import complete_empty_votes
    cols=['lula','bolsonaro','validos','brancos','nulos','votos_todos']
    row={k:None for k in cols}
    df=complete_empty_votes(pd.DataFrame([{**row,'comparecimento':0}]))
    assert df.validos.iloc[0]==0 and df.lista_votos_vazia_comparecimento_zero.iloc[0]
    with pytest.raises(ValueError,match='nonzero turnout'):
        complete_empty_votes(pd.DataFrame([{**row,'comparecimento':1}]))
    with pytest.raises(ValueError,match='partial missing'):
        complete_empty_votes(pd.DataFrame([{**row,'lula':0,'comparecimento':0}]))


def test_pandas_missing_timezone_is_unresolved_not_a_timezone_name():
    assert closure_brasilia('20261025T170000',float('nan'),'dadosSecao') is None
    assert closure_brasilia(float('nan'),'America/Sao_Paulo','dadosSecao') is None


def test_local_minute_sensitivity_is_separate_from_brasilia(tmp_path):
    import pandas as pd
    from auditoria_urnas.analysis import local_time_sensitivity
    data=pd.DataFrame({'encerramento_original':['20261025T170059','20261025T170100','20261025T190000','20261025T190001',None],
        'lula':[1,2,3,4,0],'bolsonaro':[4,3,2,1,0],'validos':[5,5,5,5,0]})
    result=local_time_sensitivity(data,tmp_path)
    b={x['faixa']:x for x in result['bins']}
    assert b['ate_170059_local']['secoes']==1
    assert b['170100_171559_local']['secoes']==1
    assert b['apos_190000_local']['secoes']==1
    assert b['exatamente_190000_local']['secoes']==1
    assert result['unresolved']==1
