"""Publish natural-language answers from existing artifacts; no audit is rerun."""
from __future__ import annotations
from collections import Counter
from datetime import datetime
import csv,hashlib,importlib.util,json,re,shutil
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle,getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate,PageTemplate,Frame,Paragraph,Spacer,PageBreak,Table,TableStyle,KeepTogether,NextPageTemplate
from reportlab.platypus.tableofcontents import TableOfContents

from auditoria_urnas.common import root,now,digest,atomic_json
from relatorio_natural_content import ENTRIES

BASE=root()
# Render the frozen editorial edition from its published aggregate evidence.
# This path never reads latest-run pointers or produces findings for a new dataset.
edition=json.loads((BASE/'reports/manifesto-da-edicao.json').read_text())
for item in json.loads((BASE/'reports/evidence/index.json').read_text()):
    path=BASE/item['publication_path']
    if not path.exists() or digest(path)!=item['publication_sha256']:
        raise SystemExit('Published editorial evidence unavailable or changed: '+item['publication_path'])
SOURCE=ANALYSIS=BASE/'reports/evidence'
run={'signature':edition['source_processing_signature']}
CLAIMS=json.loads((SOURCE/'matriz.json').read_text());BYID={c['id']:c for c in CLAIMS}
STAMP=datetime.now(ZoneInfo('America/Porto_Velho')).strftime('%Y-%m-%d_%H%M%S')
OUT=BASE/'output/pdf'/('conferencia-alegacoes-sete-prints-'+STAMP);OUT.mkdir(parents=True)
PDF=OUT/'respostas-as-alegacoes.pdf'
DATE=datetime.now(ZoneInfo('America/Porto_Velho')).strftime('%d/%m/%Y')
NAVY=colors.HexColor('#1d354a');INK=colors.HexColor('#202c35');MUTED=colors.HexColor('#526475');LINE=colors.HexColor('#d5dfe6');PALE=colors.HexColor('#f2f5f7')
for name,file in [('Body','DejaVuSans.ttf'),('BodyBold','DejaVuSans-Bold.ttf'),('BodyItalic','DejaVuSans-Oblique.ttf')]:
    pdfmetrics.registerFont(TTFont(name,'/usr/share/fonts/truetype/dejavu/'+file))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='BodyBold',italic='BodyItalic',boldItalic='BodyBold')
ST={
 'body':ParagraphStyle('body',fontName='Body',fontSize=10.2,leading=14.6,textColor=INK,spaceAfter=7,allowWidows=0,allowOrphans=0),
 'small':ParagraphStyle('small',fontName='Body',fontSize=8.5,leading=12,textColor=MUTED,spaceAfter=6,splitLongWords=1),
 'quote':ParagraphStyle('quote',fontName='BodyItalic',fontSize=9.2,leading=13,textColor=MUTED,leftIndent=8,rightIndent=5,borderColor=LINE,borderWidth=0,borderPadding=5,spaceBefore=1,spaceAfter=6),
 'status':ParagraphStyle('status',fontName='BodyBold',fontSize=9.2,leading=13,textColor=NAVY,spaceAfter=5),
 'h1':ParagraphStyle('h1',fontName='BodyBold',fontSize=19,leading=24,textColor=NAVY,spaceAfter=16,keepWithNext=True),
 'h2':ParagraphStyle('h2',fontName='BodyBold',fontSize=11.7,leading=16,textColor=NAVY,spaceBefore=12,spaceAfter=6,keepWithNext=True),
 'table':ParagraphStyle('table',fontName='Body',fontSize=8.8,leading=12,textColor=INK,spaceAfter=0),
 'tablehead':ParagraphStyle('tablehead',fontName='BodyBold',fontSize=8.8,leading=12,textColor=colors.white),
}

ST['refhead']=ParagraphStyle('refhead',parent=ST['h2'],fontSize=10.2,leading=13,spaceBefore=7,spaceAfter=4)
ST['reftext']=ParagraphStyle('reftext',parent=ST['small'],fontSize=8.4,leading=11.2,spaceAfter=4)

def normal(text):return str(text).replace('\u2014','-').replace('\u2013','-').replace('\u2011','-')
def para(text,style='body'):return Paragraph(escape(normal(text)),ST[style])
def tagged(text,style='body'):return Paragraph(text,ST[style])
def num(value,places=0):
    return f'{value:,.{places}f}'.replace(',','@').replace('.',',').replace('@','.')

REFERENCES={
'R0':('Sete prints e transcrição conferida','docs/relatorio_original/transcricao.md',BASE/'docs/relatorio_original/transcricao.md'),
'R1':('Matriz dos números e recortes do relatório anterior','matriz.json',SOURCE/'matriz.json'),
'R2':('Conferência BWeb e correspondências por UF','tabular-summary.json',SOURCE/'tabular-summary.json'),
'R3':('Reconstrução nacional e comparação com a totalização','reconciliacao.json',ANALYSIS/'reconciliacao.json'),
'R4':('Sensibilidades de encerramento local e em Brasília','horarios-sensibilidade-local.json; horarios.json; horarios-uf.csv',ANALYSIS/'horarios-sensibilidade-local.json'),
'R5':('Cobertura de RDVs, logs e assinaturas','summary.json; logs-limitacoes.csv',SOURCE/'summary.json'),
'R6':('Biometria e concentração na base completa','estatisticas.json',ANALYSIS/'estatisticas.json'),
'R7':('Modelos geográficos e faixas de habilitação biográfica','modelos-controlados.csv; biometria-faixas.csv',SOURCE/'modelos-controlados.csv'),
'R8':('Simulações binomial e beta-binomial já concluídas','advanced-statistics.json',SOURCE/'advanced-statistics.json'),
'R9':('Sensibilidades de primeiro e segundo dígitos de Benford','benford-sensibilidades.json',SOURCE/'benford-sensibilidades.json'),
'R10':('Seções com mais de 95% de habilitação biométrica','biometria-95-porcento.json',SOURCE/'biometria-95-porcento.json'),
'R11':('Comparações tabulares de votação entre turnos e anos','comparisons-summary.json',SOURCE/'comparisons-summary.json'),
'R12':('Cabeçalhos dos arquivos examinados','tabular-schemas.json',SOURCE/'tabular-schemas.json'),
}
DOCS=json.loads((SOURCE/'fontes-documentais.json').read_text())['sources']
PAGE_TITLES={1:'Cobertura, totais e origem',2:'Publicação dos dados e recortes de horário',3:'Tabelas de horários, estados e biometria',4:'Concentração de votos, Benford e alegações institucionais',5:'Alegações internacionais e conclusões do original',6:'Método declarado e habilitação biográfica',7:'Comparações biométricas e conclusão do anexo'}

# These are document-coverage checks, not statistical tests or data processing.
covered=[];counters=Counter()
for e in ENTRIES:
    old=[BYID[i] for i in e['ids'] if i in BYID]
    e['page']=e['page'] or old[0]['pagina'];covered.extend(c['id'] for c in old)
    if not e['quote']:
        quotes=list(dict.fromkeys(c['transcricao_fiel'] for c in old));e['quote']=' / '.join(quotes)
    counters[e['page']]+=1;e['number']=f"{e['page']}.{counters[e['page']]}";e['bookmark']='point-'+e['number']
if set(covered)!=set(BYID) or len(covered)!=len(set(covered)):raise ValueError('document must cover each original matrix ID exactly once')

class Report(BaseDocTemplate):
    def __init__(self,path):
        super().__init__(str(path),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,topMargin=21*mm,bottomMargin=20*mm,title='Conferência das alegações dos sete prints - eleições 2026',author='Relatório de conferência de dados')
        frame=Frame(self.leftMargin,self.bottomMargin,self.width,self.height,id='body',leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
        self.addPageTemplates([PageTemplate(id='normal',frames=[frame],onPage=self.footer)])
        self.entry_pages={}
    def footer(self,canvas,doc):
        canvas.saveState();w,h=A4
        if doc.page>1:
            canvas.setFont('Body',7.8);canvas.setFillColor(MUTED);canvas.drawString(20*mm,h-12*mm,'Conferência das alegações dos sete prints | Eleições 2026')
        canvas.setStrokeColor(LINE);canvas.line(20*mm,15*mm,w-20*mm,15*mm)
        canvas.setFont('Body',7.6);canvas.setFillColor(MUTED);canvas.drawString(20*mm,10.3*mm,'Base: resultados já produzidos | Sem novo processamento eleitoral')
        canvas.drawRightString(w-20*mm,10.3*mm,f'Pág. {doc.page}');canvas.restoreState()
    def afterFlowable(self,flowable):
        key=getattr(flowable,'bookmark',None)
        if key:
            self.canv.bookmarkPage(key)
            title=flowable.getPlainText();level=getattr(flowable,'outline_level',0)
            self.canv.addOutlineEntry(title,key,level=level,closed=False)
            if getattr(flowable,'in_toc',False):self.notify('TOCEntry',(0,title,self.page,key))
            if key.startswith('point-'):self.entry_pages[key]=self.page

def heading(title,key,in_toc=True,level=0):
    p=para(title,'h1' if level==0 else 'h2');p.bookmark=key;p.in_toc=in_toc;p.outline_level=level;return p

def table(headers,rows,widths):
    data=[[para(x,'tablehead') for x in headers]]+[[para(x,'table') for x in row] for row in rows]
    t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),NAVY),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),('LINEBELOW',(0,0),(-1,0),.5,NAVY),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,PALE]),('LINEBELOW',(0,1),(-1,-1),.35,LINE)]));return t

story=[]
cover=ParagraphStyle('cover',parent=ST['h1'],fontSize=29,leading=36,spaceAfter=20)
story.extend([Spacer(1,24*mm),para('RELATÓRIO DE CONFERÊNCIA','status'),Paragraph('Respostas às alegações<br/>dos sete prints',cover),para('Eleições presidenciais de 2026 | Segundo turno','h2'),Spacer(1,8*mm),para('Uma resposta para cada ponto verificável, com prioridade aos números, aos recortes usados e às informações que ainda faltam.'),Spacer(1,6*mm),para(f'{len(ENTRIES)} respostas organizadas pelas sete páginas originais. Cobertura dos 75 registros da matriz anterior, com nove complementos de contexto da leitura integral.'),Spacer(1,13*mm),para('Preparado em '+DATE+'. Esta edição usa exclusivamente arquivos e resultados já produzidos. Não houve nova coleta, recontagem nacional ou execução de testes estatísticos.'),para('Os prints são o documento a conferir. Sua autoria, autenticidade e qualificação pericial não foram estabelecidas. Este texto não constitui laudo judicial.','small'),PageBreak()])
story.append(heading('Como ler esta conferência','guide'))
for text in [
'Cada resposta identifica a página do original e os códigos da matriz de alegações. Quando vários números pertencem à mesma linha de tabela, são respondidos juntos, sem omitir os componentes. Afirmações repetidas nas páginas seguintes recebem resposta própria.',
'“Confere” significa que o valor foi reproduzido na população e no critério indicados. “Confere no recorte” exige observar, por exemplo, se o relógio é local ou de Brasília e se o limite é estrito ou inclusivo. Uma diferença de reprodução não é automaticamente prova de adulteração.',
'Quando o original usa aproximações, este documento apresenta o valor exato e a aproximação correspondente. Quando não há informação suficiente, a resposta informa o motivo e o documento ou dado necessário. Uma afirmação não verificada não é automaticamente falsa.',
'Citações mantêm o conteúdo da transcrição, com normalização de espaços e sinais tipográficos. As respostas separam o número da conclusão atribuída a ele. Não foi criada uma pontuação geral de fraude nem de integridade a partir de contagens isoladas.',
'Os resultados em relógio local podem incluir o exterior quando há horário original disponível. A alternativa em Brasília aqui citada considera somente o território nacional. Portanto, a comparação entre essas duas colunas envolve relógio e população. No recorte “até 17h00”, a reprodução inclui até 17:00:59; isso não equivale ao instante exato de 17:00:00.',
'Somas, subtrações e divisões simples dos totais já tabulados foram usadas para explicitar limites inclusivos e comparar grupos. Isso não constitui nova recontagem dos arquivos brutos ou novo teste estatístico. No total de comparecimento estão votos válidos, brancos e nulos. Percentuais de candidatos usam votos válidos. Habilitação biográfica, ausência de biometria cadastrada e voto individual são grandezas diferentes. Nenhuma pessoa foi ligada a um candidato ou a um horário por essas agregações.'
]:story.append(para(text))
story.append(para('As fontes são indicadas como R0-R12 para resultados locais e D01-D14 para documentos consultados. A relação está ao final. Os nomes de arquivos servem para localizar evidências, não para exigir leitura de código.','small'))
story.append(PageBreak());story.append(heading('Guia das páginas','contents'))
toc=TableOfContents();toc.levelStyles=[ParagraphStyle('toc',fontName='Body',fontSize=10.2,leading=16,spaceBefore=5,textColor=INK)];story.append(toc)
story.append(Spacer(1,12*mm));story.append(para('As páginas 1 a 7 nos títulos abaixo são as páginas dos prints originais. A numeração do rodapé pertence a este novo PDF.'))
md=['# Respostas às alegações dos sete prints','',f'Edição de {DATE}. Resultados existentes; sem novos testes ou processamento eleitoral.','']
for page in range(1,8):
    story.append(PageBreak());label=f'Página {page} do original';story.append(heading(label+' - '+PAGE_TITLES[page],'original-'+str(page)))
    story.append(para('As respostas seguem os assuntos dessa página. Códigos entre parênteses identificam os registros da matriz ou os complementos desta edição.','small'))
    md.extend(['## '+label+' - '+PAGE_TITLES[page],''])
    for e in [x for x in ENTRIES if x['page']==page]:
        title=e['number']+' '+e['title'];p=heading(title,e['bookmark'],in_toc=False,level=1)
        quote=para('No original: “'+e['quote']+'”','quote')
        status=tagged('<b>Conferência:</b> '+escape(e['status']),'status')
        body=para(e['answer']);refs=para('Referências: '+', '.join(e['refs'])+'. Códigos: '+', '.join(e['ids'])+'.','small')
        story.append(KeepTogether([p,quote,status,body,refs]))
        md.extend(['### '+title,'','> '+normal(e['quote']),'','**Conferência: '+e['status']+'.**','',normal(e['answer']),'','Referências: '+', '.join(e['refs'])+'. Códigos: '+', '.join(e['ids'])+'.',''])

story.append(PageBreak());story.append(heading('Tabelas de apoio à leitura','support'))
story.append(para('Os quadros abaixo reorganizam valores já presentes nas saídas da auditoria. Percentuais de faixas são a razão entre os votos agregados de Lula e os votos válidos já tabulados, não uma nova estimação ou teste.'))
story.append(para('Faixas de habilitação biográfica e votação de Lula','h2'))
bins=list(csv.DictReader((SOURCE/'biometria-faixas.csv').open()))
labels=['Até 5%','Acima de 5% até 10%','Acima de 10% até 20%','Acima de 20% até 30%','Acima de 30% até 50%','Acima de 50% até 100%']
rows=[]
for label,row in zip(labels,bins):
    share=100*int(row['lula'])/int(row['validos']);rows.append([label,num(int(row['secoes'])),num(int(row['validos'])),num(share,2)+'%'])
story.append(table(['Faixa por seção','Seções','Votos válidos','Lula nos válidos'],rows,[145,75,105,157]))
story.append(Spacer(1,4*mm));story.append(para('Fonte: R7. População doméstica com detalhamento biométrico. Os limites das faixas são os já definidos no arquivo. O crescimento dos percentuais agregados é visível, mas os tamanhos dos grupos diferem; esse quadro não identifica irregularidade nem substitui os controles geográficos.','small'))
story.append(para('Controles geográficos já calculados','h2'))
story.append(para('A correlação bruta de Pearson entre taxa biográfica e participação de Lula foi aproximadamente 0,068. No modelo com controle por município, o coeficiente estimado foi -0,00749 e o intervalo de 95% foi de -0,07789 a 0,06290. O intervalo contém zero. A leitura possível é que a associação positiva não ficou clara nesse modelo, não que se tenha provado ausência de qualquer irregularidade. Fonte: R7.'))
story.append(para('Contagens de horário que permanecem sem fechamento exato','h2'))
story.append(table(['Grandeza','Levantamento oficial','Saída independente','Observação'],[
 ['Votos individuais após 17h','34.393','33.995','Contagem independente parcial de logs reconciliados.'],
 ['Seções encerradas após 17:00:00','497.333','497.897','Saída doméstica em Brasília; diferença de 564.'],
 ['Seções encerradas após 19:00:00','6.766','6.336','Saída doméstica em Brasília, corte estrito; diferença de 430.']
],[140,95,95,152]))
story.append(Spacer(1,3*mm));story.append(para('Fontes: R4, R5 e D04. As diferenças não foram totalmente esclarecidas por versão, população, critério temporal ou eventos. A parte temporal não verificada contém comparecimento somado de 164.717, registrado como limite conservador de cobertura, e não como quantidade de votos tardios. Há um log ausente e 29 casos de Sistema de Apuração tratados separadamente; não se inferiu horário individual para esses casos.','small'))
story.append(para('Confronto dos registros de votação e assinaturas','h2'))
story.append(para('Os RDVs das 499.207 seções coincidiram com os BUs, sem divergências de candidatos, brancos, nulos ou total nas comparações realizadas. Houve 261 reconciliações nacionais/estaduais sem divergências com a totalização. Nos itens de assinatura examinados foram registradas 1.996.827 verificações de hardware sem assinatura inválida e nenhum hash incompatível. Esse total conta verificações, não necessariamente arquivos físicos únicos. A verificação não incluiu toda a validação de cadeia/revogação RFC5280 nem a autenticação CEPESC da assinatura de software. Fontes: R3 e R5.'))

story.append(PageBreak());story.append(heading('Fontes e localização das evidências','sources'))
story.append(para('A reprodução dos resultados, os arquivos originais e os manifestos permanecem no projeto local. As fontes documentais abaixo são as já consultadas na execução anterior; não foram atualizadas nesta edição. Quando a fonte integral não foi preservada ou a revisão se apoiou em notícia/indexação, a limitação permanece indicada.','small'))
for key,(label,filename,path) in REFERENCES.items():
    block=[para(key+' - '+label,'refhead'),para(filename,'reftext')]
    if key=='R0':block.append(para('Inclui os sete prints em input/relatorio_original/, com hashes em docs/relatorio_original/imagens.json.','reftext'))
    story.append(KeepTogether(block))
for d in DOCS:
    block=[para(d['id']+' - '+d['type'].replace('_',' '),'refhead')]
    block.append(Paragraph('<link href="'+escape(d['url'],{'"':'&quot;'})+'" color="#245a7c">'+escape(d['url'])+'</link>',ST['reftext']))
    block.append(para(d['finding'],'reftext'))
    review=d.get('raw_status','não indicado')
    status='Corpo preservado localmente' if review=='saved' else 'Corpo integral não preservado localmente nesta coleta; consultar a limitação documental registrada'
    block.append(para(status+'.','reftext'))
    story.append(KeepTogether(block))

story.append(PageBreak());story.append(heading('Índice de cobertura das alegações','coverage'))
story.append(para('Os 75 códigos da matriz anterior aparecem uma vez nas respostas, agrupados quando são componentes da mesma frase ou tabela. Os nove códigos X são complementos da leitura integral. O índice permite localizar cada referência sem interpretar a quantidade de códigos como um placar de acertos ou erros.'))
coverage=[]
for e in ENTRIES:
    coverage.append([', '.join(e['ids']),str(e['page']),e['number'],e['title']])
story.append(table(['Códigos','Pág. original','Resposta','Assunto'],coverage,[98,70,55,259]))

doc=Report(PDF);doc.multiBuild(story)
for e in ENTRIES:e['pdf_page']=doc.entry_pages.get(e['bookmark'])
(OUT/'respostas-as-alegacoes.md').write_text('\n'.join(md))
atomic_json(OUT/'respostas-estruturadas.json',ENTRIES)
with (OUT/'indice-de-cobertura.csv').open('w') as f:
    writer=csv.DictWriter(f,fieldnames=['id','pagina_original','resposta','pagina_pdf','titulo']);writer.writeheader()
    for e in ENTRIES:
        for identifier in e['ids']:writer.writerow(dict(id=identifier,pagina_original=e['page'],resposta=e['number'],pagina_pdf=e['pdf_page'],titulo=e['title']))
source_paths={path for _,_,path in REFERENCES.values()}|{BASE/'docs/relatorio_original/imagens.json',SOURCE/'biometria-faixas.csv',SOURCE/'fontes-documentais.json',ANALYSIS/'horarios.json',ANALYSIS/'horarios-uf.csv',SOURCE/'logs-limitacoes.csv'}
metadata={'created_utc':now(),'source_completed_run':str(SOURCE),'source_processing_signature':run.get('source_processing_signature',run['signature']),
          'new_audit_processing':False,'new_statistical_tests':False,'original_matrix_records':len(CLAIMS),'supplemental_context_points':sum(i.startswith('X') for e in ENTRIES for i in e['ids']),
          'answers':len(ENTRIES),'covered_matrix_ids':sorted(covered),'source_files':[{'path':str(p),'sha256':digest(p)} for p in sorted(source_paths)],
          'authoring_scripts':[{'path':str(Path(__file__).resolve()),'sha256':digest(Path(__file__).resolve())},{'path':str(Path(__file__).with_name('relatorio_natural_content.py').resolve()),'sha256':digest(Path(__file__).with_name('relatorio_natural_content.py'))}],
          'pdf':str(PDF),'pdf_sha256':digest(PDF),'editorial_adjustments':['BA/SP figures reproduced including closures exactly at 19:00:00, from existing UF time tables','SP remainder share obtained by subtraction of existing statewide and inclusive late-group totals'],
          'editorial_policy':'Numbers and scopes first; approximate expressions reported as approximate; unverified claims are not classified as false.'}
atomic_json(OUT/'manifesto-da-edicao.json',metadata)
# Artifact layout verification only: renders all pages; does not rerun electoral tests.
from auditoria_urnas.pdf_checks import check_pdf
check_pdf(PDF)
print(json.dumps({'output':str(OUT),'pdf':str(PDF),'answers':len(ENTRIES),'matrix_records':len(CLAIMS),'additional_points':metadata['supplemental_context_points'],'pages_mapped':len(doc.entry_pages)},ensure_ascii=False,indent=2))
