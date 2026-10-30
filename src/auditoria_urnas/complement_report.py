"""Trace every printed assertion to source page, calculation and limitations."""
from __future__ import annotations
import json,math,re,shutil
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from .common import root,atomic_json,digest,now
from .analysis import write_csv


def definitions():
    text=(root()/'docs/relatorio_original/transcricao.md').read_text()
    pages={int(k):v for k,v in re.findall(r'## Página (\d+)\n(.*?)(?=\n## Página |\Z)',text,re.S)}
    claims=[]
    def add(identifier,page,quote,metric=None,alleged=None,unit='',*,digits=None,scope=None,interpretation='Inconclusivo',reason='',sources=None):
        if quote not in pages[page]:raise ValueError('claim quote absent from visually checked page: '+identifier)
        claims.append({'id':identifier,'page':page,'original_quote':quote,'metric':metric,'alleged':alleged,'unit':unit,'digits':digits,
                       'scope':scope,'interpretation':interpretation,'reason':reason,'documentary_sources':sources or []})
    for ident,page in [('A01',1),('A02',2),('A03',6)]:
        quote={1:'Total processado: 499.205 seções eleitorais · 128.236.074 votos apurados',2:'499.205 seções eleitorais e 128.236.074 votos apurados',6:'499.205 seções eleitorais do Brasil e do exterior, cobrindo os 128.236.074 votos registrados.'}[page]
        add(ident,page,quote,'coverage',499205,'seções',interpretation='Parcialmente confirmado',reason='Distinguir seções com linhas BWeb de todas as seções instaladas; duas seções sem votos não alteram o total de votos.')
        add(ident+'V',page,quote,'turnout',128236074,'votos')
    add('A04',1,'28 Unidades da Federação','regions',28,'recortes',interpretation='Parcialmente confirmado',reason='27 UFs e exterior ZZ são 28 recortes; ZZ não é unidade federativa.')
    add('A05',1,'Data da análise: 28 de outubro de 2026',reason='Data declarada pelo documento; não prova de execução ou autoria.')
    add('A06',6,'Todos os arquivos foram checados contra os seus respectivos hashes criptográficos originais (.sha512).',reason='A verificação desta auditoria não comprova quais procedimentos o autor executou; não foram fornecidos logs ou código do autor.')
    for ident,page,quote in [('F01',2,'A liberação dos arquivos de Boletim de Urna (BWeb) ocorreu apenas na manhã desta quarta-feira, 28 de outubro.'),('F02',2,'Durante setenta e duas horas, a sociedade civil e os peritos independentes foram privados do acesso aos dados primários'),('F03',5,'Os dados foram sonegados da sociedade por setenta e duas horas.')]:
        add(ident,page,quote,reason='Não há histórico completo de disponibilidade por produto/URL. Datas de geração, catálogo e Last-Modified não bastam; referências de análise de logs em 26/10 são evidência contrária à generalização sobre todos os microdados.',sources=['D12','D13'])
    add('B01',2,'Flávio Bolsonaro venceu com 52,39% dos votos válidos','early_share',52.39,'%',digits=2,interpretation='Interpretação não sustentada',reason='Relógios locais não definem uma janela nacional simultânea; encerramento não informa horário individual do voto.',sources=['D01','D04'])
    add('B02',2,'abrindo uma frente de quase 1,8 milhão de votos.','early_margin',1800000,'votos',reason='Quase não estabelece tolerância matemática; apresentar a margem exata sem teste de igualdade arbitrário.')
    add('B03',2,'mais de 6,1 milhões de votos de vantagem','late_margin',6100000,'votos',interpretation='Interpretação não sustentada',reason='Critério numérico >6.100.000; os votos totais dessas seções não são votos individuais depositados depois de 17h.')
    add('B04',2,'A vitória de Lula foi fabricada exclusivamente no universo de urnas que encerraram as votações após o horário limite legal.',interpretation='Interpretação não sustentada',reason='Uma diferença entre grupos de encerramento não demonstra fabricação, voto irregular ou causalidade.',sources=['D01','D04','D05'])
    for rowid,scope,quote,section_count,turnout,share in [
        ('B05','1701_1715','| 17h01 a 17h15 | 339.593 | 88.071.750 | 53,46% |',339593,88071750,53.46),
        ('B06','1716_1859','| 17h16 a 18h59 | 2.472 | 674.799 | 57,16% |',2472,674799,57.16),
        ('B07','after19','| Após as 19h00 | 6.333 | 1.856.306 | — |',6333,1856306,None)]:
        add(rowid+'S',3,quote,'window_sections',section_count,'seções',scope=scope)
        add(rowid+'T',3,quote,'window_turnout',turnout,'eleitores',scope=scope,interpretation='Interpretação não sustentada',reason='Comparecimento total das seções não é quantidade de eleitores que votaram na janela temporal.')
        if share is not None:add(rowid+'P',3,quote,'window_lula',share,'%',digits=2,scope=scope)
    add('B08',3,'Mais de dois milhões e meio de eleitores votaram em urnas que extrapolaram os limites normais.','late_turnout',2500000,'eleitores',interpretation='Interpretação não sustentada',reason='Separar eleitores de toda a seção e efetivos votos registrados após o limite; legalidade requer norma e decisão.',sources=['D01','D04','D05'])
    for uf,quote,count,share in [('BA','| Bahia | 936 | 72,31% |',936,72.31),('PE','| Pernambuco | 657 | 65,70% |',657,65.70),('MA','| Maranhão | — | 83,31% |',None,83.31),('SP','| São Paulo | 1.571 | 57,46% |',1571,57.46)]:
        if count is not None:add('B09'+uf+'S',3,quote,'state_late_sections',count,'seções',scope=uf)
        add('B09'+uf+'P',3,quote,'state_late_lula',share,'%',digits=2,scope=uf)
    add('B10',3,'contrariando o comportamento eleitoral do restante do estado.',interpretation='Interpretação não sustentada',reason='Comparar seções tardias com o restante de SP, com composição geográfica e comparecimento; diferença descritiva não prova anomalia causal.')
    add('C01',3,'| Total de eleitores liberados sem biometria | 8.632.488 votos (6,73% do comparecimento nacional) |','biographic',8632488,'habilitações',interpretation='Parcialmente confirmado',reason='O número corresponde à habilitação biográfica do campo BWeb, não a pessoas sem biometria cadastrada nem a votos automaticamente irregulares.',sources=['D02','D03'])
    add('C02',3,'| Total de eleitores liberados sem biometria | 8.632.488 votos (6,73% do comparecimento nacional) |','biographic_percent',6.73,'%',digits=2)
    add('C03',3,'| Margem final de vitória de Lula sobre Flávio | 4.430.191 votos |','victory_margin',4430191,'votos')
    add('C04',3,'| Relação entre liberação manual e margem | Quase o dobro da diferença total da eleição |','manual_margin_ratio',2,'razão',interpretation='Interpretação não sustentada',reason='A razão entre grandezas não mostra que essas habilitações sejam indevidas ou destinadas a um candidato. Quase não define tolerância de arredondamento.')
    add('C05',3,'mediante a simples digitação do ano de nascimento:',interpretation='Parcialmente confirmado',reason='Ano de nascimento integra identificação alternativa, mas não substitui toda a conferência documental/caderno/mesário.',sources=['D02','D03'])
    add('C06',3,'A perícia realizou o teste de correlação estatística entre o percentual de votos manuais e o percentual de votos obtidos por Lula.',reason='Não há coeficiente, população, código ou gráfico do autor; refazemos análise própria controlando geografia.')
    for identifier,metric,alleged,quote in [
        ('D01L','lula100',106,'| 100% dos votos válidos | 106 seções | 4 seções | 26,5 : 1 |'),('D01B','bolsonaro100',4,'| 100% dos votos válidos | 106 seções | 4 seções | 26,5 : 1 |'),
        ('D02L','lula_gt90',6899,'| Mais de 90% dos votos | 6.899 seções | 384 seções | 18 : 1 |'),('D02B','bolsonaro_gt90',384,'| Mais de 90% dos votos | 6.899 seções | 384 seções | 18 : 1 |'),
        ('D03','ratio100',26.5,'| 100% dos votos válidos | 106 seções | 4 seções | 26,5 : 1 |'),('D04','ratio90',18,'| Mais de 90% dos votos | 6.899 seções | 384 seções | 18 : 1 |')]:
        add(identifier,4,quote,metric,alleged,'seções' if metric not in ['ratio100','ratio90'] else 'razão',digits=1 if metric=='ratio100' else 0 if metric=='ratio90' else None)
    add('D05',4,'os percentuais de votação seguem distribuições gaussianas suaves em torno da média.',interpretation='Interpretação não sustentada',reason='Normalidade não é exigência eleitoral universal. Percentuais são limitados, discretos e sujeitos a heterogeneidade geográfica; usar referências condicionais binomial/beta-binomial.')
    add('D06',4,'Essas seções coincidem com zonas rurais de baixíssima fiscalização partidária independente, onde a taxa de liberação sem biometria atinge seus picos mais elevados.',reason='Sem classificação geográfica da seção e cadastro de fiscais/comparecimento efetivo, não se verifica o conjunto da alegação. Nomes de escolas e município não substituem essas medições.',sources=['D14'])
    add('E01',4,'Submetemos o conjunto de 499.205 seções eleitorais ao teste forense do primeiro dígito significativo de Benford',reason='Aplicação declarada pelo autor não auditável sem código/saídas; comparar nossa análise exploratória, sem pressupor adequação de Benford.')
    add('E02',4,'[Nota: Os gráficos do teste de Benford e da correlação biométrica não foram incluídos neste documento, pois dependiam de imagens anexas à análise original.]','graphs_absent',1,'constatação',interpretation='Confirmado',reason='Os sete prints não contêm os gráficos; não inventar valores de testes ausentes.')
    add('G01',4,'exatamente sete minutos após a proclamação das urnas, antes mesmo que os recursos da oposição fossem protocolados.',reason='Não foram obtidos a decisão assinada, timestamp de proclamação e protocolos necessários à comparação. A nota da PF identifica PET 16877/DF, mas não confirma o intervalo.',sources=['D06','D11'])
    add('G02',4,'Uma ala da Polícia Federal articulou a prisão cautelar do principal líder da oposição com base em boatos de imprensa',reason='Nota oficial descreve cautelares de viagem; não comprova articulação informal nem permite inferir intenção ou motivação.',sources=['D06'])
    add('G03',4,'forçando a sua extração do país sob proteção diplomática dos Estados Unidos.',reason='Proteção diplomática dos EUA e nexo causal não demonstrados por documentação primária obtida.',sources=['D06','D07','D11'])
    add('G04',4,'os quarenta milhões de dólares',reason='Continua na página 5. Não foi obtida documentação financeira primária para montante, moeda e destinatários; alegação não foi convertida em fato.',sources=[])
    add('G04C',5,'repassados à família de magistrados do tribunal superior.',reason='Complemento da alegação da página 4, sem documentação primária suficiente para confirmar repasses.')
    add('G05',4,'Toda a pirotecnia contra a oposição foi ativada na mesma semana em que deveriam entrar em pauta as apurações financeiras',interpretation='Interpretação não sustentada',reason='Cronologia, mesmo que coincidente, não demonstra operação de abafamento ou motivação causal.')
    add('G06',5,'Donald Trump classificou a eleição como manchada por fraude decorrente da prorrogação',interpretation='Parcialmente confirmado',reason='Há relato jornalístico da declaração; a fala original completa não foi obtida e a declaração não comprova fraude.',sources=['D10'])
    add('G07',5,'a Argentina acolheu a oposição',reason='Acolhimento é ambíguo: entrada, residência, asilo e proteção diplomática são distintos. Coletiva de 27/10 informou ausência de pedido de asilo naquele momento.',sources=['D07'])
    add('G08',5,'a mídia estatal chinesa admitiu que a extensão de duas horas impulsionou a virada governista.',interpretation='Parcialmente confirmado',reason='Existe interpretação desse teor em matéria da Xinhua de 26/10. Matéria posterior de 27/10 também relata que os votos tardios não inverteriam o resultado; declaração jornalística não substitui contrafactual causal.',sources=['D08','D09'])
    for ident,quote in [('H01','A eleição regulamentar até as 17h00 foi vencida por Flávio Bolsonaro.'),('H02','A virada ocorreu exclusivamente em urnas encerradas após o prazo legal.'),('H03','Milhões de votos foram computados na calada da noite sob picos de mais de setenta por cento pró governo.'),('H04','O resultado proclamado pelo sistema não possui integridade matemática, quebrou os protocolos mais elementares de controle biométrico e foi viabilizado por uma intervenção judicial monocrática que alterou as regras no meio do jogo.')]:
        add(ident,5,quote,interpretation='Interpretação não sustentada',reason='O horário de encerramento não separa votos por instante; distribuição agregada ou procedimento legal alternativo não demonstra fraude, irregularidade individual ou perda geral de integridade.',sources=['D01','D02','D03','D04','D05'])
    add('H05',5,'Mais de oito milhões e seiscentos mil votos foram emitidos sem verificação biométrica digital, quase o dobro da diferença que decidiu a presidência.','biographic',8632488,'habilitações',interpretation='Parcialmente confirmado',reason='Número e procedimento precisam ser distinguidos de fraude e de ausência de identificação documental.',sources=['D02','D03'])
    add('H06',5,'a maior auditoria de microdados eleitorais já realizada no Brasil',reason='Superlativo sem inventário comparativo verificável de auditorias e seus escopos.')
    add('I01',6,'o estudo não investigou e não se baseia em teorias sobre invasão de hackers, adulteração de código fonte ou manipulação de sistemas por satélite.',interpretation='Confirmado',reason='Escopo declarado nos prints; não constitui verificação de quais atividades o autor efetivamente executou.')
    add('I02',6,'quando a digital do eleitor falha quatro vezes no leitor, a urna autoriza o mesário a liberar a votação mediante a simples digitação do ano de nascimento do cidadão.',interpretation='Parcialmente confirmado',reason='Há procedimento alternativo regulamentar, condicionado a outras conferências; a formulação simples omite essas condições.',sources=['D02','D03'])
    add('I03',6,'Em seções urbanas com intensa fiscalização de partidos de oposição, essa regra de exceção é aplicada com testemunhas e sob controle social.',reason='Sem cadastro e evidências da atuação de fiscais por seção, não é verificado o contraste urbano/rural.',sources=['D14'])
    add('I04',6,'a substituição do controle biométrico digital pela liberação manual do mesário.',interpretation='Parcialmente confirmado',reason='Há habilitação alternativa regulamentada. Escala inédita e utilização indevida exigem comparação histórica e evidências próprias.',sources=['D02','D03'])
    add('J01',7,'O volume de eleitores liberados manualmente por ano de nascimento somou 8.632.488 votos','biographic',8632488,'habilitações',interpretation='Parcialmente confirmado',reason='Habilitação biográfica e voto nominal são unidades diferentes; não há ligação individual à escolha eleitoral.')
    add('J02',7,'a diferença final entre os dois candidatos foi de 4.430.191 votos.','victory_margin',4430191,'votos')
    add('J03',7,'Nas seções onde mais de noventa e cinco por cento dos eleitores usaram a digital com sucesso, o equilíbrio entre os candidatos foi evidente.',reason='Equilíbrio não define margem quantitativa. O relatório complementar calcula votos e seções com taxa biométrica >95%, sem impor definição retrospectiva.')
    add('J04',7,'nas seções onde as taxas de liberação manual escalaram para vinte, trinta ou mais de cinquenta por cento, a votação de Lula disparou em linha reta, atingindo picos de mais de sessenta e um por cento.',interpretation='Interpretação não sustentada',reason='Refazer faixas, pesos e controles municipais. Correlação bruta, máximo de seção e relação linear/causal não são equivalentes; coeficientes ajustados e intervalos ficam explícitos.')
    add('J05',7,'coincidem de forma assustadora com os municípios e zonas de maior taxa de votos sem biometria e de menor presença de fiscais partidários independentes.',reason='A parte biométrica/geográfica é calculável; não foi obtida medição da presença de fiscais. O conjunto não está confirmado.',sources=['D14'])
    add('J06',7,'a trava biométrica foram desarmados na ponta da linha em um volume de milhões de votos.',interpretation='Interpretação não sustentada',reason='Uso do procedimento alternativo não demonstra desarme irregular; são necessárias evidências de ocorrências e identificação indevida.',sources=['D02','D03'])
    add('J07',7,'Este documento não constitui laudo judicial.','self_description',1,'constatação',interpretation='Confirmado',reason='Consta expressamente nos prints; não é aferição externa de qualificação ou autoria.')
    return claims


def _measure_frame(df,scope,raw):
    if raw:
        stamp=pd.to_datetime(df.encerramento_original,format='%Y%m%dT%H%M%S',errors='coerce')
        sec=stamp.dt.hour*3600+stamp.dt.minute*60+stamp.dt.second
        known=stamp.notna()
    else:
        sec=df.encerramento_segundos_brasilia
        known=(df.uf!='ZZ')&sec.notna()&(df.data_encerramento_brasilia=='2026-10-25')
    if scope=='early':mask=known&(sec<61260)
    elif scope=='late':mask=known&(sec>=61260)
    elif scope=='1701_1715':mask=known&(sec>=61260)&(sec<62160)
    elif scope=='1716_1859':mask=known&(sec>=62160)&(sec<68400)
    elif scope=='after19':mask=known&(sec>68400)
    else:raise ValueError(scope)
    return df[mask]


def matrix(base,output):
    from .statistics import concentration_counts
    cols=['uf','lula','bolsonaro','comparecimento','validos','aptos','habilitados_biografia','encerramento_original','encerramento_segundos_brasilia','data_encerramento_brasilia']
    canonical=pq.read_table(base['sections'],columns=cols).to_pandas()
    raw=canonical
    raw_source='BU; limitações para SA sem horário'
    if (output/'bweb-secoes.parquet').exists():
        candidate=pq.read_table(output/'bweb-secoes.parquet').to_pandas()
        if set(candidate.uf)==set(canonical.uf):
            raw=candidate;raw['validos']=raw.lula+raw.bolsonaro
            raw_source='BWeb; linhas presidenciais deduplicadas por seção'
        else:raw_source+='; BWeb nacional incompleto, não usado nos totais globais'
    counts=concentration_counts(canonical.lula,canonical.bolsonaro,canonical.validos)
    margin=int(canonical.lula.sum()-canonical.bolsonaro.sum());bio=int(canonical.habilitados_biografia.sum())
    observed={'coverage':len(raw) if raw_source.startswith('BWeb') else int((canonical.comparecimento>0).sum()),'turnout':int(canonical.comparecimento.sum()),'regions':int(canonical.uf.nunique()),
              'biographic':bio,'biographic_percent':100*bio/int(canonical.comparecimento.sum()),'victory_margin':margin,'manual_margin_ratio':bio/margin,
              'graphs_absent':1,'self_description':1,**counts,'ratio100':counts['lula100']/counts['bolsonaro100'],
              'ratio90':counts['lula_gt90']/counts['bolsonaro_gt90']}
    out=[]
    for c in definitions():
        val=observed.get(c['metric']);alternative=None;details=''
        metric=c['metric'];scope=c['scope']
        if metric in ['early_share','early_margin','late_margin','late_turnout']:
            window='early' if metric.startswith('early') else ('late' if metric=='late_margin' else '1716_1859')
            def value(frame):
                part=_measure_frame(frame,window,frame is raw)
                if metric=='early_share':return 100*int(part.bolsonaro.sum())/int(part.validos.sum()) if part.validos.sum() else None
                if metric=='early_margin':return int(part.bolsonaro.sum()-part.lula.sum())
                if metric=='late_margin':return int(part.lula.sum()-part.bolsonaro.sum())
                late=_measure_frame(frame,'after19',frame is raw)
                return int(part.comparecimento.sum()+late.comparecimento.sum())
            # Compute each view explicitly: raw and canonical can be the same object.
            def direct(frame,is_raw):
                part=_measure_frame(frame,window,is_raw)
                if metric=='early_share':return 100*int(part.bolsonaro.sum())/int(part.validos.sum()) if part.validos.sum() else None
                if metric=='early_margin':return int(part.bolsonaro.sum()-part.lula.sum())
                if metric=='late_margin':return int(part.lula.sum()-part.bolsonaro.sum())
                late=_measure_frame(frame,'after19',is_raw);return int(part.comparecimento.sum()+late.comparecimento.sum())
            val=direct(raw,True);alternative=direct(canonical,False)
            details='Reprodução: relógios locais, até 17h00 inclui segundos 17:00:00 a 17:00:59; comparação corrigida em Brasília, só território nacional. '+raw_source
        elif metric and metric.startswith(('window_','state_late_')):
            def value(frame,is_raw):
                part=_measure_frame(frame,'after19' if metric.startswith('state_') else scope,is_raw)
                if metric.startswith('state_'):part=part[part.uf==scope]
                if metric.endswith('sections'):return len(part)
                if metric.endswith('turnout'):return int(part.comparecimento.sum())
                return 100*int(part.lula.sum())/int(part.validos.sum()) if part.validos.sum() else None
            val=value(raw,True);alternative=value(canonical,False)
            details='Cortes: 17:01:00–17:15:59; 17:16:00–18:59:59; estritamente >19:00:00. Relógio local vs Brasília. '+raw_source
        alleged=c['alleged'];classification='Inconclusivo'
        if val is not None and alleged is not None:
            tolerance=.5*10**(-c['digits']) if c['digits'] is not None else 0
            if metric in ['early_margin','manual_margin_ratio']:classification='Inconclusivo'
            elif metric in ['late_margin','late_turnout']:classification='Confirmado' if val>alleged else 'Contradito pelos dados'
            else:classification='Confirmado' if abs(val-alleged)<=tolerance+1e-10 else 'Contradito pelos dados'
            if alternative is not None and classification=='Confirmado' and abs(val-alternative)>tolerance:classification='Parcialmente confirmado'
            if metric=='coverage' and not raw_source.startswith('BWeb'):classification='Parcialmente confirmado'
        if metric in ['early_share','early_margin','late_margin','late_turnout','window_sections','window_turnout','window_lula','state_late_sections','state_late_lula'] and not raw_source.startswith('BWeb'):
            classification='Parcialmente confirmado' if classification=='Confirmado' else 'Inconclusivo'
        interpretations=c['interpretation']
        if metric and interpretations=='Inconclusivo':interpretations='Inconclusivo'  # never infer the author's conclusion from a count
        out.append({'id':c['id'],'pagina':c['page'],'transcricao_fiel':c['original_quote'],'originais_conferidos':base.get('context_evidence',{}).get('images_verified_in_this_run',0)==7,
            'transcricao_conferida_historicamente':True,
            'valor_alegado':alleged,'valor_calculado':val,'valor_brasilia_sensibilidade':alternative,
            'diferenca_absoluta':abs(val-alleged) if val is not None and alleged is not None else None,
            'diferenca_percentual':100*(val-alleged)/alleged if val is not None and alleged not in [None,0] else None,
            'unidade':c['unit'],'classificacao_numero':classification,'classificacao_interpretacao':interpretations,
            'fontes_documentais':','.join(c['documentary_sources']),
            'arquivos_utilizados':base['sections']+(';'+str(output/'bweb-secoes.parquet') if raw_source.startswith('BWeb') else ''),
            'reproducao':'auditoria_urnas.complement_report:matrix; metric='+str(metric)+'; scope='+str(scope),
            'filtros_e_populacao':details or 'Presidente, eleição 6258, segundo turno; métricas por seção antes de somas; nulos não imputados.',
            'limitacoes':c['reason'],'evidencia':'matriz.csv; valores-calculados.json; summary.json; tabular-summary.json; fontes-documentais.json'})
    atomic_json(output/'valores-calculados.json',observed)
    atomic_json(output/'matriz.json',out);write_csv(output/'matriz.csv',out)
    return out


def reports(base,output,status,totals):
    import markdown
    from .report import render_pdf
    claims=matrix(base,output)
    sources=json.loads((root()/'docs/evidencias-documentais/fontes.json').read_text())
    atomic_json(output/'fontes-documentais.json',sources)
    atomic_json(output/'contexto-evidencias.json',base.get('context_evidence',{}))
    shutil.copy2(root()/'docs/relatorio_original/transcricao.md',output/'transcricao-original.md')
    shutil.copy2(root()/'docs/relatorio_original/imagens.json',output/'manifesto-prints.json')
    def value(v):
        if v is None:return 'não disponível'
        return f'{v:.6f}'.rstrip('0').rstrip('.') if isinstance(v,float) else str(v)
    b=json.loads(Path(base['analysis']['output'],'reconciliacao.json').read_text())
    lines=['# Auditoria complementar dos sete prints',
           f"Gerado em {now()}. Processamento: {status['status']}; etapas concluídas: {', '.join(status.get('completed_stages',[])) or 'preparação documental'}. A conclusão do processamento não significa confirmação de todas as alegações.",
           f"A base anterior contém {b['national']['secoes']} seções instaladas. As {b['comparisons']} reconciliações nacionais/estaduais do segundo turno não tiveram divergências. Esse resultado verifica consistência entre representações públicas e não autentica por si cada voto.",
           '## Cobertura complementar',json.dumps(totals,ensure_ascii=False,indent=2) if totals else 'RDVs, logs e assinaturas nacionais ainda não processados nesta publicação inicial. Os resultados do piloto não representam o país inteiro.',
           'Os arquivos .logsa.jez e .sa.vsc são variantes do Sistema de Apuração. Seções sem logs publicados, votos não conciliados, fases incertas e ajustes de relógio não foram convertidos em zero votos após 17h. Intervalos para partes não verificáveis usam comparecimento como limite superior, sem atribuir candidato ou identidade.',
           'Hash compatível, assinatura válida e confiança no emissor são estados distintos. O verificador usa os parâmetros e chaves do pacote oficial preservado. Não foi realizada validação completa RFC5280, revogação ou autenticação CEPESC da assinatura de software.',
           '## Método e interpretação',
           'A matriz separa reprodução dos números dos prints, sensibilidade para Brasília e conclusões do autor. Os relógios locais de regiões diferentes não representam o mesmo instante. O minuto 17h00 e o segundo 17:00:00 são critérios diferentes.',
           'O campo BWeb QT_ELEI_BIOM_SEM_HABILITACAO é confrontado com o contador de habilitação biográfica do BU. Não equivale ao contador separado de ausência de biometria cadastrada. Habilitação alternativa regulamentada não é evidência automática de identificação irregular.',
           'Modelos ecológicos não ligam pessoas ou horários a candidatos. As simulações condicionais binomial e beta-binomial são hipóteses descritivas; não são testes de fraude. Concentração, significância ou desvio de Benford isolados não sustentam uma conclusão geral de integridade ou fraude.',
           '## Matriz integral das alegações']
    for c in claims:
        lines += [f"### {c['id']} — página {c['pagina']}",c['transcricao_fiel'],
            f"Alegado: {value(c['valor_alegado'])}; calculado: {value(c['valor_calculado'])}; sensibilidade em Brasília: {value(c['valor_brasilia_sensibilidade'])}.",
            f"Número: {c['classificacao_numero']}. Interpretação: {c['classificacao_interpretacao']}.",
            c['filtros_e_populacao'],c['limitacoes'] or 'O número não estabelece, por si, a interpretação ou os procedimentos efetivamente executados pelo autor.',
            'Reprodução: '+c['reproducao']+'; fontes: '+(c['fontes_documentais'] or 'microdados e/ou prints fornecidos')+'.']
    lines += ['## Documentos e cronologia']
    for source in sources['sources']:
        lines += [f"### {source['id']} — {source['type']}",source['url'],source['finding'],
            'Revisão: '+source['review']+'. Corpo HTTP: '+source.get('raw_status','não registrado')+'.']
    if (output/'advanced-statistics.json').exists():
        stats=json.loads((output/'advanced-statistics.json').read_text())
        lines += ['## Robustez estatística',f"Simulações por modelo: {stats['replicates']}; semente: {stats['seed']}; seções incluídas: {stats['population_sections']}; excluídas: {stats['excluded_sections']}.",
                  'Ajuste beta-binomial: '+json.dumps(stats['fit'],ensure_ascii=False),
                  'Quantis e referência observada estão em advanced-statistics.json e simulacoes-*.csv. Modelos e intervalos ajustados estão em modelos-controlados.csv; distribuições por UF e faixas biométricas têm tabelas próprias.']
    if (output/'modelos-controlados.csv').exists():
        lines += ['## Associações biométricas com controles']
        model_rows=pd.read_csv(output/'modelos-controlados.csv').to_dict('records')
        for row in model_rows:
            lines += [f"Exposição: {row['exposicao']}; efeitos fixos: {row['efeitos_fixos']}; coeficiente: {row['coeficiente']:.6f}; IC 95%: [{row['ic95_inferior']:.6f}, {row['ic95_superior']:.6f}]. Seções: {row['secoes']}; municípios: {row['municipios']}."]
        lines += ['Coeficientes referem-se a proporções, com ponderação por votos válidos e erros agrupados por município. Intervalo contendo zero não demonstra ausência de fraude; limita a afirmação de associação positiva persistente nesse modelo.']
    if (output/'biometria-95-porcento.json').exists():
        lines += ['## Seções com identificação biométrica acima de 95%',json.dumps(json.loads((output/'biometria-95-porcento.json').read_text()),ensure_ascii=False),
                  'O termo equilíbrio não especifica um intervalo numérico. Os valores calculados são apresentados sem impor uma definição retrospectiva.']
    if (output/'comparisons-summary.json').exists():lines+=['## Comparações entre turnos e anos',json.dumps(json.loads((output/'comparisons-summary.json').read_text()),ensure_ascii=False)]
    lines += ['## Limitações e informações necessárias',
        'O original não inclui os gráficos de Benford/correlação e não fornece código ou logs de execução do autor. A autoria e autenticidade dos prints não foram estabelecidas.',
        'A hipótese de menor presença de fiscais exige cadastro e evidência de atuação por seção. Ruralidade não foi presumida a partir de nome de escola ou perfil de município. Informações sem base específica permanecem inconclusivas.',
        'A alegação de sete minutos exige decisão assinada, marca de tempo da proclamação e protocolos. A investigação das 72 horas exige histórico de acesso por produto e URL. Não foram obtidos documentos primários suficientes para proteção diplomática dos EUA ou os alegados repasses financeiros.',
        'Primeiro turno e 2022 são comparações tabulares; não se presumem equivalência das pessoas, candidaturas, seções ou eleitores. O número 22 corresponde a pessoas diferentes entre os anos.',
        'Cada divergência de RDV, BWeb, correspondência ou assinatura deve ser esclarecida pelo arquivo e chave indicados nas tabelas, com versões, eventos ou documentos que expliquem a origem. Ausência de arquivo publicado não demonstra adulteração.',
        'Falhas de execução registradas: '+json.dumps(status.get('failures',[]),ensure_ascii=False),
        'Não há conclusão geral de fraude ou integridade apoiada apenas na aprovação/reprovação de um conjunto limitado de verificações.']
    md='\n\n'.join(x for x in lines if x)+'\n';(output/'relatorio.md').write_text(md)
    (output/'relatorio.html').write_text('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Auditoria complementar</title><style>body{max-width:1000px;margin:40px auto;padding:20px;font:17px/1.6 sans-serif}a{overflow-wrap:anywhere}</style>'+markdown.markdown(md,extensions=['tables'])+'</html>')
    render_pdf(md,output/'relatorio.pdf',title='Auditoria complementar dos sete prints',footer='Auditoria independente — evidências, cobertura e limitações')
    from .pdf_checks import check_pdf
    check_pdf(output/'relatorio.pdf')
    summary=['# Resumo executivo da auditoria complementar',
        f"Foram catalogadas {len(claims)} alegações/ocorrências nos sete prints. Todos os trechos têm página e vínculo com a transcrição conferida.",
        f"A reconciliação anterior contou {b['national']['secoes']} seções e nenhuma divergência em {b['comparisons']} comparações com a totalização oficial.",
        'Vários números de horários podem ser reproduzidos com relógios locais e limites de minuto. Eles não informam quantos votos individuais ocorreram após 17h. A comparação com Brasília fica separada.',
        'A habilitação biográfica citada nos prints é um procedimento distinto de ausência de biometria cadastrada; a autorização alternativa é regulamentada. Comparar seu volume com a margem não demonstra votos indevidos.',
        'As conclusões institucionais e causais exigem documentos próprios. As classificações inconclusivas não foram preenchidas com suposições.',
        'Processamento complementar: '+status['status']+'. Consulte summary.json e status.json para cobertura e falhas.']
    (output/'resumo.md').write_text('\n\n'.join(summary)+'\n')
    limitations=[c for c in claims if c['classificacao_numero']=='Inconclusivo' or c['classificacao_interpretacao']=='Inconclusivo']
    write_csv(output/'informacoes-nao-verificaveis.csv',limitations)
    existing=json.loads((output/'tabular-summary.json').read_text()) if (output/'tabular-summary.json').exists() else []
    atomic_json(output/'inconsistencias-e-cobertura.json',{'claims_with_numeric_disagreement':[c['id'] for c in claims if c['classificacao_numero']=='Contradito pelos dados'],
        'file_summary':totals,'tabular_summary':existing,'unverifiable_claims':[c['id'] for c in limitations],
        'clarification':'Confrontar as chaves/arquivos nas tabelas de divergências; obter fontes históricas e documentos primários enumerados em limitacoes.'})
    atomic_json(output/'output-manifest.json',{'generated_utc':now(),'files':[{'path':str(p),'sha256':digest(p),'bytes':p.stat().st_size} for p in sorted(output.rglob('*')) if p.is_file() and p.name not in ['output-manifest.json','status.json']]})
    return claims
