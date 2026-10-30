"""Checkpointed binomial/beta-binomial sensitivity, without fraud inference."""
from __future__ import annotations
import hashlib,json,math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize,special,stats

from .common import atomic_json,digest,emit,root,now,signature
from .statistics import concentration_counts,benford,association_models


def fit_beta_binomial(n,k,p):
    """Estimate one overdispersion parameter, with fixed leave-one-out p."""
    n=np.asarray(n,dtype=np.int64);k=np.asarray(k,dtype=np.int64);p=np.asarray(p,dtype=float)
    use=(n>0)&(p>0)&(p<1)
    n,k,p=n[use],k[use],p[use]
    if len(n)<10:return {'converged':False,'reason':'fewer than 10 usable sections','n':len(n)}
    comb=special.gammaln(n+1)-special.gammaln(k+1)-special.gammaln(n-k+1)
    def loss(logphi):
        phi=np.exp(logphi);a=p*phi;b=(1-p)*phi
        return -float(np.sum(comb+special.betaln(k+a,n-k+b)-special.betaln(a,b)))
    result=optimize.minimize_scalar(loss,bounds=(-8,16),method='bounded',options={'xatol':1e-6,'maxiter':150})
    phi=float(np.exp(result.x));rho=1/(1+phi)
    return {'converged':bool(result.success and np.isfinite(result.fun)),'n':len(n),'phi':phi,'rho':rho,
            'negative_log_likelihood':float(result.fun),'optimizer_evaluations':int(result.nfev),
            'binomial_negative_log_likelihood':-float(stats.binom.logpmf(k,n,p).sum()),
            'boundary':bool(abs(result.x+8)<1e-3 or abs(result.x-16)<1e-3),
            'hypothesis':'fixed municipal leave-one-section-out probabilities; one pooled overdispersion parameter',
            'limitations':'Not a causal or fraud model; local heterogeneity and estimated baseline influence fit.'}


def advanced(base,output,*,simulations=1000,seed=20261025,ufs=None):
    import pyarrow.parquet as pq
    columns=['uf','municipio','zona','secao','lula','bolsonaro','validos','comparecimento','aptos','brancos','nulos','habilitados_biografia','sem_biometria_cadastrada','habilitados_biometria','encerramento_segundos_brasilia']
    df=pq.read_table(base['sections'],columns=columns,filters=[('uf','in',ufs)] if ufs else None).to_pandas()
    totals=df.groupby(['uf','municipio'])[['lula','validos']].transform('sum')
    denom=totals.validos.to_numpy(np.int64)-df.validos.to_numpy(np.int64)
    use=(df.validos.to_numpy()>0)&(denom>0)
    n=df.validos.to_numpy(np.int64)[use];k=df.lula.to_numpy(np.int64)[use]
    p=(totals.lula.to_numpy(np.int64)[use]-k)/denom[use]
    fit=fit_beta_binomial(n,k,p);atomic_json(output/'beta-binomial-fit.json',fit)
    # Parametric simulation is resumable by deterministic replicate seed.
    identity=hashlib.sha256(json.dumps({'base':base['sha256'],'code':signature(),'ufs':ufs,'seed':seed,'fit':fit,'replicates':simulations},sort_keys=True).encode()).hexdigest()[:24]
    directory=root()/'data/checkpoints/complementar/simulations'/identity;directory.mkdir(parents=True,exist_ok=True)
    manifest_path=directory/'completed.json'
    hashes=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    rows=[]
    for replicate in range(simulations):
        path=directory/f'{replicate:06}.json'
        if str(replicate) in hashes:
            if not path.exists() or digest(path)!=hashes[str(replicate)]:raise ValueError('simulation checkpoint changed')
            row=json.loads(path.read_text())
        else:
            rng=np.random.default_rng(np.random.SeedSequence([seed,replicate]))
            draws={'binomial':rng.binomial(n,p)}
            if fit['converged']:
                probability=p.copy();interior=(p>0)&(p<1)
                probability[interior]=rng.beta(p[interior]*fit['phi'],(1-p[interior])*fit['phi'])
                draws['beta_binomial']=rng.binomial(n,probability)
            row={'replicate':replicate,'models':{}}
            for label,draw in draws.items():
                row['models'][label]={'counts':concentration_counts(draw,n-draw,n),
                    'mad_first_digit_lula':benford(draw,1)['mad'],'mad_first_digit_bolsonaro':benford(n-draw,1)['mad']}
            atomic_json(path,row)
            hashes[str(replicate)]=digest(path);atomic_json(manifest_path,hashes)
        rows.append(row)
        if (replicate+1)%20==0:
            atomic_json(output/'simulation-progress.json',{'completed':replicate+1,'total':simulations,'seed':seed,'checkpoint_directory':str(directory)})
            emit('complement_simulations_progress',completed=replicate+1,total=simulations)
    quantiles={}
    for model in rows[0]['models']:
        counts=pd.DataFrame([r['models'][model]['counts'] for r in rows])
        counts.to_csv(output/f'simulacoes-{model}.csv',index=False)
        quantiles[model]={col:{str(q):float(v) for q,v in counts[col].quantile([.025,.5,.975]).items()} for col in counts}
    observed=concentration_counts(k,n-k,n)
    result={'seed':seed,'replicates':simulations,'population_sections':len(n),'excluded_sections':int((~use).sum()),
            'observed':observed,'fit':fit,'quantiles':quantiles,'checkpoint_directory':str(directory),
            'limitations':'Model-dependent reference distributions. No inference about fraud or individual voter behavior.'}
    result['simulated_first_digit_mad_quantiles']={model:{candidate:np.quantile([r['models'][model]['mad_first_digit_'+candidate] for r in rows],[.025,.5,.975]).tolist() for candidate in ['lula','bolsonaro']} for model in rows[0]['models']}
    atomic_json(output/'advanced-statistics.json',result)
    from statsmodels.stats.multitest import multipletests
    tests=[]
    municipal=df.groupby(['uf','municipio'])[['lula','bolsonaro']].sum().reset_index()
    for aggregation,table in [('secao',df),('municipio',municipal)]:
        for candidate in ['lula','bolsonaro']:
            for digit in [1,2]:tests.append({'aggregation':aggregation,'candidate':candidate,'digit':digit,**benford(table[candidate],digit)})
    valid=[i for i,t in enumerate(tests) if t['p'] is not None]
    if valid:
        for i,pvalue in zip(valid,multipletests([tests[i]['p'] for i in valid],method='holm')[1]):tests[i]['p_holm']=float(pvalue)
    atomic_json(output/'benford-sensibilidades.json',tests)
    # Geographic controls, descriptive ecological associations, no individual linkage.
    models=association_models(df);pd.DataFrame(models).to_csv(output/'modelos-controlados.csv',index=False)
    q=df[(df.comparecimento>0)&df.habilitados_biografia.notna()].copy()
    q['taxa_manual']=q.habilitados_biografia/q.comparecimento
    q['taxa_biometrica']=q.habilitados_biometria/q.comparecimento
    q['faixa_manual']=pd.cut(q.taxa_manual,[-.001,.05,.1,.2,.3,.5,1],right=True).astype(str)
    q.groupby('faixa_manual',observed=True).agg(secoes=('secao','size'),lula=('lula','sum'),bolsonaro=('bolsonaro','sum'),validos=('validos','sum'),comparecimento=('comparecimento','sum')).reset_index().to_csv(output/'biometria-faixas.csv',index=False)
    good=q[q.taxa_biometrica>.95]
    atomic_json(output/'biometria-95-porcento.json',{'sections':len(good),'lula':int(good.lula.sum()),'bolsonaro':int(good.bolsonaro.sum()),'validos':int(good.validos.sum()),
        'lula_percent_valid':100*int(good.lula.sum())/int(good.validos.sum()) if good.validos.sum() else None,
        'definition':'habilitados_biometria / comparecimento presidencial > 0.95; sem detalhe não imputado'})
    sensitivities=[]
    for minimum in [1,20,50,100]:
        part=df[df.validos>=minimum]
        sensitivities.append({'minimum_valid':minimum,'sections':len(part),**concentration_counts(part.lula,part.bolsonaro,part.validos)})
    pd.DataFrame(sensitivities).to_csv(output/'concentracao-sensibilidades.csv',index=False)
    # Quantiles and outliers by municipality and section; z-scores not fraud labels.
    df['comparecimento_taxa']=df.comparecimento/df.aptos.replace(0,np.nan)
    df['brancos_nulos_taxa']=(df.brancos+df.nulos)/df.comparecimento.replace(0,np.nan)
    distributions=[]
    for metric in ['comparecimento_taxa','brancos_nulos_taxa']:
        for uf,part in df.groupby('uf'):
            distributions.append({'uf':uf,'metric':metric,**{str(q):float(v) for q,v in part[metric].quantile([0,.01,.25,.5,.75,.99,1]).items()}})
    pd.DataFrame(distributions).to_csv(output/'distribuicoes-uf.csv',index=False)
    import plotly.express as px
    bins=q.groupby(['uf','faixa_manual'],observed=True).agg(lula=('lula','sum'),validos=('validos','sum'),secoes=('secao','size')).reset_index()
    bins['Lula (% válidos)']=100*bins.lula/bins.validos
    fig=px.scatter(bins,x='faixa_manual',y='Lula (% válidos)',color='uf',size='secoes',hover_data=['validos'],
        title='Associação descritiva por UF e faixa de habilitação biográfica — sem interpretação causal')
    fig.write_html(output/'biometria-interativa.html',include_plotlyjs=True)
    return result
