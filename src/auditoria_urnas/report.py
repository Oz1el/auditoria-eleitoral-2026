"""Operational reports; no claim verdict is inferred from ingestion checks."""
from __future__ import annotations

import csv
import html
import importlib.metadata
import json
import platform
from pathlib import Path
from xml.sax.saxutils import escape

import markdown
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

from .common import atomic_json, command, now, root, signature


def environment():
    commands = [['uname','-a'], ['lscpu'], ['free','-h'], ['df','-hT',str(root())],
                ['lsblk','-o','NAME,MODEL,SIZE,ROTA,FSTYPE,MOUNTPOINTS'],
                ['nvidia-smi','--query-gpu=name,driver_version,memory.total,memory.used','--format=csv,noheader'],['nvcc','--version']]
    evidence = {}
    for args in commands:
        try:
            evidence[' '.join(args)] = command(args)
        except Exception as e:
            evidence[' '.join(args)] = str(e)
    result = {'captured_utc':now(),'python':platform.python_version(),'platform':platform.platform(),
              'parser_signature':signature(),'packages':{name:importlib.metadata.version(name) for name in
              ['asn1tools','duckdb','pyarrow','reportlab','pytest']},'commands':evidence,
              'limits':{'duckdb_memory':'6GiB','duckdb_threads':4,'workers':1,'batch_bu':5000,'free_floor_GiB':20},
              'gpu':'not_used; hardware and driver availability are recorded in commands; performance is not inferred from detection'}
    atomic_json(root() / 'output/reports/environment.json',result)
    return result


def render_pdf(md: str, destination: Path, *, title="Diagnóstico e piloto dos arquivos eleitorais de 2026", footer="Auditoria independente - diagnóstico e piloto de ingestão"):
    styles = getSampleStyleSheet()
    for heading in ['Heading1','Heading2','Heading3']:
        styles[heading].keepWithNext = True
    styles['BodyText'].fontSize = 10
    styles['BodyText'].leading = 13
    story=[]
    for line in md.splitlines():
        if not line.strip():
            if story and isinstance(story[-1], Paragraph) and story[-1].style.name.startswith('Heading'):
                continue
            story.append(Spacer(1,0.13*cm))
            continue
        style = 'Heading1' if line.startswith('# ') else 'Heading2' if line.startswith('## ') else 'Heading3' if line.startswith('### ') else 'BodyText'
        text = line.lstrip('# ').replace('**','').replace('`','')
        story.append(Paragraph(escape(text),styles[style]))
    def page(canvas, document):
        canvas.setStrokeColor(colors.HexColor('#d6dce3'))
        canvas.line(1.8*cm,1.5*cm,19.2*cm,1.5*cm)
        canvas.setFont('Helvetica',8)
        canvas.drawString(1.8*cm,1.05*cm,footer)
        canvas.drawRightString(19.2*cm,1.05*cm,str(document.page))
    SimpleDocTemplate(str(destination),title=title,author='Auditoria independente',pagesize=(21*cm,29.7*cm),rightMargin=1.8*cm,leftMargin=1.8*cm,
                      topMargin=1.8*cm,bottomMargin=2*cm).build(story,onFirstPage=page,onLaterPages=page)


def reports():
    folder=root()/'output/reports'
    inv=json.loads((root()/'data/catalog/inventory.json').read_text())
    plan=json.loads((root()/'data/catalog/replacement-plan.json').read_text())
    pilot_path=folder/'pilot.json'
    pilot=json.loads(pilot_path.read_text()) if pilot_path.exists() else {}
    pending=[x['uf'] for x in inv['files'] if not x['eligible_for_validation']]
    status='aprovado' if pilot.get('passed') else 'pendente ou reprovado'
    md=f'''# Diagnóstico e piloto dos arquivos eleitorais de 2026

Gerado em UTC: {now()}

## Resumo executivo

Esta entrega inventaria os arquivos locais, verifica integridade e prepara a base de votação presidencial. O piloto está {status}. Estes resultados não classificam a integridade da eleição nem as alegações do relatório original.

Encontrados {inv['present_regions']} de 28 recortes esperados (27 UFs e ZZ). Diretórios ZIP e tamanhos elegíveis: {inv['readable_regions']}. Pendências: {', '.join(pending) or 'nenhuma nesta etapa'}.

Arquivos locais: {inv['compressed_bytes']/2**30:.2f} GiB. Conteúdo descompactado dos ZIPs legíveis: {inv['uncompressed_bytes_readable']/2**30:.2f} GiB. Espaço livre na captura: {inv['free_bytes']/2**40:.2f} TiB. A ingestão lê membros dos ZIPs; não exige extrair todo esse conteúdo.

## Ambiente e execução

Execução por CPU, com um trabalhador, DuckDB limitado a 6 GiB e quatro threads; lotes de até 5.000 BUs. Memória e espaço são medidos no piloto. Temporários, cache e ambiente virtual ficam no disco de 4 TB. No host, nvidia-smi identificou RTX 3060 de 12 GiB e driver 580.173.02; nvcc informou toolkit 12.0. A falha inicial era uma restrição de acesso no sandbox. Não foi executado benchmark CUDA/RAPIDS: esta etapa de leitura, descompactação e interpretação de ASN.1 usa CPU, sem ganho de GPU demonstrado.

Não foi realizado benchmark destrutivo ou de escrita no disco. Tempos de validação e ingestão incluem os efeitos do cache do sistema operacional e não representam a velocidade sustentada de todo o disco.

## Integridade e origem

CRC verifica a consistência dos membros do ZIP. SHA-256 e SHA-512 locais identificam os bytes lidos. Um hash oficial só é marcado como confirmado quando o mesmo algoritmo coincide para o mesmo arquivo e versão. Autenticação criptográfica por assinatura e cadeia de certificados permanece não verificada nesta entrega.

Nos pacotes de arquivos transmitidos não foi localizado hash oficial externo no catálogo consultado. Não se aplicam a esses pacotes os hashes dos BWeb, que são outros arquivos. O manifesto registra essa limitação.

As consultas CKAN e HTML são preservadas separadamente em data/catalog. Divergências entre as duas superfícies não são resolvidas pela escolha silenciosa de uma delas. A data de geração ou o Last-Modified atual não prova a primeira data de publicação, nem estabelece um período histórico de indisponibilidade.

## Esquema e regras analíticas

O parser usa specs/bu.asn1, obtido no endereço oficial pelo navegador, com arquivo original e SHA-256 preservados. As imagens dos boletins são decodificadas e seus textos são confrontados com os votos binários presidenciais por um leitor independente.

boletins contém uma linha por BU, com identidade, urna, horários e contadores originais. eleicoes contém uma linha por BU, eleição e cargo, com aptos e comparecimento do cargo. votos contém uma linha por BU, eleição, cargo, tipo de voto e votável. A chave de seção inclui UF, município TSE, zona, seção e pleito; cargo e eleição complementam o grão dos resultados.

Métricas de eleitores não são somadas após joins com os votáveis. O Sistema de Apuração usa o comparecimento do cargo para a conservação de votos; seu contador geral original é preservado. Ambiguidades de múltiplos BUs para a mesma seção bloqueiam a publicação daquele recorte.

Biometria: sem_biometria_cadastrada significa eleitor sem biometria cadastrada; habilitados_biografia significa eleitor com biometria cadastrada habilitado por ano de nascimento. Ausência do detalhamento permanece nula, não zero. Nenhuma dessas situações é classificada automaticamente como irregularidade.

Horários originais são preservados. Encerramento, emissão e geração permanecem campos distintos. O encerramento do BU não é utilizado como horário de cada voto. Nesta versão AM, PE e ZZ exigem mapeamento municipal documentado; seus horários de Brasília ficam nulos na ausência desse mapeamento. BUs do Sistema de Apuração não recebem o fuso da seção por presunção.

## Piloto e cobertura

Piloto: {status}. Os números abaixo são verificações de ingestão em RR e ZZ; não são respostas às alegações do relatório.
'''
    if pilot.get('passed'):
        count=sum(x['secoes'] for x in pilot['totals']['electorate_by_uf'])
        md+=f'\nForam ingeridos {count} BUs presidenciais. CRC dos dois pacotes aprovado, concordância dos agregados Python/DuckDB confirmada e imagem impressa conferida em todos os BUs presidenciais do piloto.\n'
        rec=pilot['bweb_reconciliation']
        md+=f"\nZZ: {rec['bu_sections']} seções em BU e {rec['bweb_sections']} no BWeb; {len(rec['vote_differences'])} divergências de votos e {len(rec['unexpected_metric_differences'])} divergências de métricas nas seções comuns. Há {len(rec['zero_turnout_sections_absent_bweb'])} seções com comparecimento zero ausentes do BWeb; seus aptos não foram confirmados por esse CSV. A diferença permanece registrada no piloto. SHA-512 da amostra BWeb coincide com o publicado.\n"
        md+=f"\nTempo total do piloto: {pilot['elapsed_seconds']:.2f} segundos. Os checkpoints incluem a versão do parser e os hashes de entrada e saída.\n"
    elif pilot.get('error'):
        md+=f"\nBloqueio do piloto: {pilot['error']}\n"
    md+=f'''
## Reposições e autorização

Tráfego estimado para novas cópias: {plan['traffic_bytes']/2**30:.2f} GiB. Arquivos atuais serão preservados. O plano concreto está em data/catalog/replacement-plan.json. Nenhuma reposição volumosa é iniciada automaticamente.

## Limitações e próximas fases

O lote local pode processar recortes válidos e permanecer parcial. Mesmo a presença dos 28 pacotes não comprova a cobertura de todas as seções esperadas: isso exige integrar o cadastro oficial de seções e correspondências. A reconciliação nacional contra uma fonte oficial independente ainda está pendente.

Recontagem dos RDVs, interpretação dos logs, validação de assinaturas, análise de publicação histórica, testes estatísticos e verificações institucionais pertencem às fases seguintes. Os sete prints ainda precisam estar em input/relatorio_original para transcrição fiel e montagem da matriz de alegações. Nenhuma alegação recebeu classificação final nesta entrega.

## Reprodução

Executar scripts/run.sh inventariar --online; scripts/run.sh piloto; scripts/run.sh relatorio. Para processar os recortes disponíveis após o piloto e os testes: scripts/start.sh. O estado pode ser consultado com scripts/run.sh status. Interrupções retomam os lotes confirmados; alterações de entrada, parser ou configuração geram outra identidade de dataset.

Fontes: https://dadosabertos.tse.jus.br/dataset/resultados-2026-arquivos-transmitidos-para-totalizacao ; https://dadosabertos.tse.jus.br/dataset/resultados-2026-boletim-de-urna ; https://dadosabertos.tse.jus.br/dataset/resultados-2026 ; https://dadosabertos.tse.jus.br/dataset/resultados-2026-correspondencias-esperadas-e-efetivadas-2-turno ; https://www.tse.jus.br/eleicoes/eleicoes-2026/eleicoes-2026
'''
    (folder/'diagnostico.md').write_text(md)
    body=markdown.markdown(md)
    (folder/'diagnostico.html').write_text('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Diagnóstico e piloto</title><style>body{font:17px/1.6 system-ui;max-width:960px;margin:3rem auto;padding:0 2rem;color:#182536}h1,h2{line-height:1.2}h2{margin-top:2rem}p{overflow-wrap:anywhere}</style>'+body+'</html>')
    render_pdf(md,folder/'diagnostico.pdf')
    with (folder/'manifesto.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=['uf','path','bytes','zip_directory','size_matches_published','sha256','sha512','zip_crc','official_outer_hash','signature_authenticity'])
        writer.writeheader()
        for row in inv['files']:
            p=root()/f'data/checkpoints/validation-{row["uf"]}.json'
            validated=json.loads(p.read_text()) if p.exists() else {}
            writer.writerow({k:validated.get(k,row.get(k)) for k in writer.fieldnames})
    fields=['id','pagina','transcricao_fiel','tipo_numero_ou_conclusao','fontes','filtros','populacao',
            'valor_alegado','valor_calculado','diferenca_absoluta','diferenca_percentual','consulta','evidencia',
            'interpretacao','limitacoes','classificacao']
    matrix=folder/'alegacoes.csv'
    if not matrix.exists():
        with matrix.open('w') as f:
            csv.writer(f).writerow(fields)
    return {'markdown':str(folder/'diagnostico.md'),'html':str(folder/'diagnostico.html'),'pdf':str(folder/'diagnostico.pdf')}
