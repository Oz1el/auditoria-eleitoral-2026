"""Exploratory ecological statistics with explicit populations and null models."""
from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .common import atomic_json, emit


def concentration_counts(lula, bolsonaro, valid):
    l,b,n=np.asarray(lula,dtype=np.int64),np.asarray(bolsonaro,dtype=np.int64),np.asarray(valid,dtype=np.int64)
    usable=n>0
    return {'zero_valid':int((~usable).sum()),
            'lula100':int((usable & (l==n)).sum()),'bolsonaro100':int((usable & (b==n)).sum()),
            'lula_gt90':int((usable & (10*l>9*n)).sum()),'bolsonaro_gt90':int((usable & (10*b>9*n)).sum()),
            'lula_ge90':int((usable & (10*l>=9*n)).sum()),'bolsonaro_ge90':int((usable & (10*b>=9*n)).sum())}


def digit_counts(values, digit=1):
    a=np.asarray(values,dtype=np.int64)
    a=a[a>=(1 if digit==1 else 10)]
    if not len(a):return np.zeros(9 if digit==1 else 10,dtype=np.int64)
    # Strings avoid floating log10 errors at exact powers of ten.
    text=a.astype(str)
    d=np.fromiter((int(x[digit-1]) for x in text),dtype=np.int64,count=len(text))
    return np.bincount(d,minlength=10)[1:] if digit==1 else np.bincount(d,minlength=10)


def benford_probabilities(digit):
    if digit==1:return np.log10(1+1/np.arange(1,10))
    return np.array([sum(np.log10(1+1/(10*k+d)) for k in range(1,10)) for d in range(10)])


def benford(values,digit):
    observed=digit_counts(values,digit)
    p=benford_probabilities(digit);n=int(observed.sum())
    if not n:return {'n':0,'chi2':None,'p':None,'mad':None,'observed':observed.tolist()}
    chi,pvalue=stats.chisquare(observed,n*p)
    return {'n':n,'chi2':float(chi),'p':float(pvalue),'mad':float(np.mean(np.abs(observed/n-p))),
            'observed':observed.tolist(),'expected_probabilities':p.tolist(),
            'min_expected_count':float((n*p).min())}


def association_models(df):
    import statsmodels.api as sm
    q=df[(df.validos>0)&(df.comparecimento>0)&(df.aptos>0)&df.habilitados_biografia.notna()&
         df.sem_biometria_cadastrada.notna()].copy()
    q['share_lula']=q.lula/q.validos
    q['log_aptos']=np.log(q.aptos)
    q['turnout_rate']=q.comparecimento/q.aptos
    q['invalid_rate']=(q.brancos+q.nulos)/q.comparecimento
    q['bio_rate']=q.habilitados_biografia/q.comparecimento
    q['unregistered_rate']=q.sem_biometria_cadastrada/q.comparecimento
    q['municipal_key']=q.uf+':'+q.municipio.astype(str)
    result=[]
    for exposure in ['bio_rate','unregistered_rate']:
        corr=stats.pearsonr(q[exposure],q.share_lula)
        rank=stats.spearmanr(q[exposure],q.share_lula)
        cols=['share_lula',exposure,'log_aptos','turnout_rate','invalid_rate']
        for fixed in [None,'uf','municipal_key']:
            work=q[cols].copy()
            if fixed:
                weighted=work.mul(q.validos,axis=0)
                means=weighted.groupby(q[fixed]).transform('sum').div(q.validos.groupby(q[fixed]).transform('sum'),axis=0)
                work=work-means
                X=work[cols[1:]]
            else:X=sm.add_constant(work[cols[1:]])
            # Demeaning exactly removes all weighted fixed effects. Municipal
            # clustering is descriptive; fixed-effect degrees of freedom differ
            # slightly from an explicit dummy matrix and are documented below.
            model=sm.WLS(work.share_lula,X,weights=q.validos).fit(cov_type='cluster',
                cov_kwds={'groups':pd.factorize(q.municipal_key)[0],'use_correction':False},use_t=False)
            ci=model.conf_int().loc[exposure]
            result.append({'exposicao':exposure,'efeitos_fixos':fixed or 'nenhum','secoes':len(q),
                'municipios':int(q.municipal_key.nunique()),'coeficiente':float(model.params[exposure]),
                'erro_padrao_cluster_municipio':float(model.bse[exposure]),
                'ic95_inferior':float(ci.iloc[0]),'ic95_superior':float(ci.iloc[1]),
                'pearson_bruto':float(corr.statistic),'spearman_bruto':float(rank.statistic),
                'peso':'votos válidos','controles':'log(aptos), comparecimento/aptos, (brancos+nulos)/comparecimento',
                'covariancia':'cluster municipal assintótica, sem correção de amostra finita',
                'interpretacao':'associação ecológica descritiva; não causal; coeficiente por unidade de proporção'})
    return result


def calculate(df,out,*,seed,simulations):
    detail=df[df.habilitados_biografia.notna() & df.sem_biometria_cadastrada.notna() & df.habilitados_biometria.notna()]
    detail_sum=detail.habilitados_biografia+detail.sem_biometria_cadastrada+detail.habilitados_biometria
    if not (detail_sum==detail.comparecimento_bu_original).all():
        raise ValueError('biometric details fail reconciliation with general BU turnout')
    bio={'biographic_enabled':int(detail.habilitados_biografia.sum()),
         'without_registered_biometrics':int(detail.sem_biometria_cadastrada.sum()),
         'biometric_enabled':int(detail.habilitados_biometria.sum()),
         'sections_with_detail':len(detail),'sections_missing_detail':len(df)-len(detail),
         'detail_turnout_general_bu':int(detail.comparecimento_bu_original.sum()),
         'detail_turnout_presidential':int(detail.comparecimento.sum()),
         'biographic_pct_national_turnout':100*int(detail.habilitados_biografia.sum())/int(df.comparecimento.sum()),
         'biographic_pct_detail_turnout':100*int(detail.habilitados_biografia.sum())/int(detail.comparecimento.sum()),
         'without_registered_pct_national_turnout':100*int(detail.sem_biometria_cadastrada.sum())/int(df.comparecimento.sum())}
    for level in [['uf'],['uf','municipio'],['uf','municipio','zona']]:
        agg=detail.groupby(level).agg(secoes=('bu_id','size'),biografia=('habilitados_biografia','sum'),
            sem_biometria_cadastrada=('sem_biometria_cadastrada','sum'),biometria=('habilitados_biometria','sum'),
            comparecimento=('comparecimento','sum'),lula=('lula','sum'),bolsonaro=('bolsonaro','sum'),validos=('validos','sum')).reset_index()
        agg.to_csv(out/('biometria-'+'-'.join(level)+'.csv'),index=False)
    extreme=detail.assign(taxa_biografia=detail.habilitados_biografia/detail.comparecimento.replace(0,np.nan),
                          taxa_sem_cadastro=detail.sem_biometria_cadastrada/detail.comparecimento.replace(0,np.nan))
    extreme.nlargest(100,'taxa_biografia')[['uf','municipio','zona','secao','comparecimento','habilitados_biografia','taxa_biografia']].to_csv(out/'biometria-extremos.csv',index=False)
    bio['biographic_rate_quantiles']={str(k):float(v) for k,v in extreme.taxa_biografia.quantile([0,.01,.25,.5,.75,.99,1]).items()}
    uni=concentration_counts(df.lula,df.bolsonaro,df.validos)
    q=df.copy()
    q['tamanho_aptos']=pd.cut(q.aptos,[-1,50,100,200,300,400,500,1000,np.inf]).astype(str)
    q['lula100']=(q.validos>0)&(q.lula==q.validos)
    q['bolsonaro100']=(q.validos>0)&(q.bolsonaro==q.validos)
    q['lula_gt90']=(q.validos>0)&(10*q.lula>9*q.validos)
    q['bolsonaro_gt90']=(q.validos>0)&(10*q.bolsonaro>9*q.validos)
    for level in [['uf'],['uf','municipio'],['tamanho_aptos'],['uf','tamanho_aptos']]:
        agg=q.groupby(level,observed=True).agg(secoes=('bu_id','size'),lula100=('lula100','sum'),
            bolsonaro100=('bolsonaro100','sum'),lula_gt90=('lula_gt90','sum'),bolsonaro_gt90=('bolsonaro_gt90','sum')).reset_index()
        agg.to_csv(out/('concentracao-'+'-'.join(level)+'.csv'),index=False)
    q[q.lula100|q.bolsonaro100][['uf','municipio','zona','secao','aptos','comparecimento','validos','lula','bolsonaro']].to_csv(out/'secoes-unanimes.csv',index=False)
    models=association_models(df)
    pd.DataFrame(models).to_csv(out/'modelos.csv',index=False)
    emit('analysis_descriptive_statistics_done',unanimity=uni,biometry=bio)
    municipal=df.groupby(['uf','municipio'])[['lula','bolsonaro','validos']].sum().reset_index()
    ben=[]
    for level,table in [('secao',df),('municipio',municipal)]:
        for candidate in ['lula','bolsonaro']:
            for digit in [1,2]:
                ben.append({'aggregation':level,'candidate':candidate,'digit':digit,**benford(table[candidate],digit),
                            'interpretation':'exploratório; condições de Benford não demonstradas'})
    adjusted=multipletests([r['p'] for r in ben],method='holm')[1]
    for row,p in zip(ben,adjusted):row['p_holm']=float(p)
    atomic_json(out/'benford.json',ben)
    # Conditional model fitted with each tested section left out of its municipality.
    totals=df.groupby(['uf','municipio'])[['lula','validos']].transform('sum')
    n=df.validos.to_numpy(np.int64)
    denom=totals.validos.to_numpy(np.int64)-n
    use=(n>0)&(denom>0)
    prob=(totals.lula.to_numpy(np.int64)[use]-df.lula.to_numpy(np.int64)[use])/denom[use]
    trials=n[use];observed=df.lula.to_numpy(np.int64)[use]
    probability=np.clip(prob,0,1)
    threshold=(9*trials)//10
    expected={'lula100':float(np.power(probability,trials).sum()),
              'bolsonaro100':float(np.power(1-probability,trials).sum()),
              'lula_gt90':float(stats.binom.sf(threshold,trials,probability).sum()),
              'bolsonaro_gt90':float(stats.binom.sf(threshold,trials,1-probability).sum())}
    rng=np.random.default_rng(seed)
    counts=[];mad_l=[];mad_b=[]
    for i in range(simulations):
        draw=rng.binomial(trials,probability)
        counts.append(concentration_counts(draw,trials-draw,trials))
        mad_l.append(benford(draw,1)['mad']);mad_b.append(benford(trials-draw,1)['mad'])
        if (i+1)%20==0:emit('analysis_simulation_progress',completed=i+1,total=simulations)
    simulated=pd.DataFrame(counts)
    simulated.to_csv(out/'simulacoes-contagens.csv',index=False)
    model={'hypothesis':'independent binomial votes, section valid count fixed, municipality leave-one-section-out candidate probability',
           'seed':seed,'simulations':simulations,'sections':int(use.sum()),'excluded_sections':int((~use).sum()),
           'observed_same_population':concentration_counts(observed,trials-observed,trials),
           'expected_analytic':expected,
           'simulation_quantiles':{k:{str(p):float(v) for p,v in simulated[k].quantile([.025,.5,.975]).items()}
                                   for k in simulated.columns if k!='zero_valid'},
           'first_digit_mad_observed':{'lula':benford(observed,1)['mad'],'bolsonaro':benford(trials-observed,1)['mad']},
           'first_digit_mad_simulated_quantiles':{'lula':np.quantile(mad_l,[.025,.5,.975]).tolist(),
                                                  'bolsonaro':np.quantile(mad_b,[.025,.5,.975]).tolist()},
           'limitations':'Homogeneity within municipality is a strong descriptive hypothesis; not a fraud null model; no individual vote timing/identity; Monte Carlo quantiles are approximate.'}
    atomic_json(out/'simulacoes.json',model)
    results={'biometry':bio,'unanimity':uni,'models':models,'benford':ben,'simulation':model,
             'additional':{'turnout_rate_quantiles':{str(k):float(v) for k,v in (df.comparecimento/df.aptos.replace(0,np.nan)).quantile([0,.01,.25,.5,.75,.99,1]).items()}}}
    atomic_json(out/'estatisticas.json',results)
    # A standalone interactive view; Plotly is embedded so it works offline.
    import plotly.graph_objects as go
    groups=df.groupby('uf')[['lula','bolsonaro','validos','comparecimento','aptos']].sum()
    fig=go.Figure()
    fig.add_bar(x=groups.index,y=100*groups.lula/groups.validos,name='Lula (% válidos)')
    fig.add_bar(x=groups.index,y=100*groups.bolsonaro/groups.validos,name='Flávio (% válidos)')
    fig.update_layout(title='Votação presidencial por UF e exterior — segundo turno de 2026',
                      yaxis_title='% dos votos válidos',barmode='group',template='plotly_white',
                      updatemenus=[{'buttons':[
                          {'label':'Ambos','method':'restyle','args':['visible',[True,True]]},
                          {'label':'Lula','method':'restyle','args':['visible',[True,False]]},
                          {'label':'Flávio','method':'restyle','args':['visible',[False,True]]}]}],
                      annotations=[{'text':'Fonte: BUs selecionados por checkpoint; confira reconciliação e limites no relatório.','xref':'paper','yref':'paper','x':0,'y':-0.2,'showarrow':False}])
    fig.write_html(out/'graficos.html',include_plotlyjs=True)
    return results
