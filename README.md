# Conferência reproduzível de alegações sobre os microdados eleitorais de 2026

Este projeto verifica os números e as interpretações de um relatório de sete páginas encontrado no Instagram. Segundo a identificação fornecida pelo responsável pelo projeto, os prints foram publicados pela conta de **Joey Mannarino**. O endereço da postagem não foi preservado no repositório; essa atribuição não é uma verificação independente de autoria ou autenticidade.

O objetivo é científico: comparar afirmações com registros públicos, explicitar os critérios de cálculo e permitir revisão e reprodução. O projeto não representa candidato, partido ou órgão eleitoral. A conferência separa números reproduzidos, diferenças de recorte e alegações que permanecem sem evidência suficiente. Consistência entre arquivos públicos, isoladamente, não demonstra integridade de todo o processo eleitoral; uma diferença estatística também não demonstra fraude.

## Resultado publicado

Leia [respostas às alegações — PDF, 32 páginas](reports/respostas-as-alegacoes.pdf). A edição de 29/10/2026 responde individualmente às alegações dos sete prints. Estão disponíveis o [texto das respostas](reports/respostas-as-alegacoes.md), o [índice de cobertura](reports/indice-de-cobertura.csv), as [respostas estruturadas](reports/respostas-estruturadas.json) e o [manifesto da edição](reports/manifesto-da-edicao.json).

Na execução documentada, foram reconstruídos 499.207 boletins e 128.236.074 votos. Os totais presidenciais concordaram com a totalização oficial; os RDVs concordaram com os BUs nas categorias verificadas. O BWeb contém 499.205 seções: duas seções do exterior sem comparecimento explicam a diferença de cobertura, sem diferença de votos. Os [arquivos agregados que sustentam o PDF](reports/evidence/index.json) e os [hashes e URLs dos 28 pacotes utilizados](reports/fontes-da-execucao.csv) permitem examinar essas afirmações.

Alguns números do original conferem apenas com determinado relógio, denominador ou limite inclusivo. Encerramento de uma seção não informa o horário de cada voto. Há limitações na contagem temporal dos logs, na validação das assinaturas e nas alegações documentais. As questões de 72 horas de indisponibilidade, fiscalização e motivações institucionais não foram resolvidas integralmente. Consulte o PDF para as respostas e razões específicas.

O PDF é uma publicação preservada. Novas execuções geram relatórios próprios em `output/`; não sobrescrevem esse documento. Texto editorial e classificação automática podem diferir quando o PDF esclarece sensibilidades adicionais: veja [como a edição foi produzida](reports/README.md).

## Escopo implementado

A base principal é a eleição presidencial de 2026, segundo turno, eleição `6258`, pleito `3221`, cargo `1`, números `13` e `22`, nas 27 UFs e no exterior (`ZZ`). Esses parâmetros estão explícitos no código. O programa não é um auditor universal de eleições ou candidatos: as comparações do primeiro turno de 2026 e de 2022 são tabulares. Adaptar outro ano exige examinar os esquemas e parâmetros correspondentes.

O fluxo preserva ZIPs, calcula hashes, verifica CRC, decodifica BU/RDV, confronta a representação textual do BU e publica Parquet com checkpoints. Depois reconcilia totais oficiais, BWeb, correspondências, logs e assinaturas, produz estatísticas e relatórios Markdown, HTML e PDF. Nenhuma ligação entre eleitor, horário e candidato é realizada.

## Requisitos

- Linux com Python 3.12 e [uv](https://docs.astral.sh/uv/). O alvo original foi Pop!_OS 24.04.
- Quatro núcleos físicos e 32 GiB de RAM para a configuração de referência. `--workers 1` ou `2` permite outros limites. A etapa complementar usa quatro processos por padrão, sem GPU; DuckDB usa até quatro threads e 6 GiB por conexão sequencial.
- Espaço livre para os ZIPs, Parquet, relatórios e temporários. Consulte o inventário antes de baixar. A execução interrompe a publicação de lotes quando há menos de 20 GiB livres. Isso é uma margem de parada, não uma estimativa do tamanho total necessário.
- Para gerar e inspecionar PDFs: `pdfinfo`, `pdftotext` e `pdftoppm` do pacote `poppler-utils`; os scripts editoriais também usam fontes DejaVu.

Instale o repositório no disco que armazenará o processamento. Os comandos abaixo mantêm ambiente, cache, temporários, dados e saídas nesse diretório:

```bash
mkdir -p data/cache/uv data/tmp
export UV_CACHE_DIR="$PWD/data/cache/uv"
export TMPDIR="$PWD/data/tmp"
uv sync --frozen
./scripts/run.sh --help
```

O `uv.lock` fixa as versões, inclusive uma revisão Git do ECPy necessária para Ed521. Leia [origem dos componentes externos](docs/componentes-externos.md). CUDA e Postman não são necessários para executar a auditoria.

## Reprodução a partir do TSE

Os comandos são explícitos e sequenciais. Nenhum download nacional ou processamento pesado é iniciado durante a instalação. Um comando com `--confirmar-download` autoriza a transferência do plano exibido. As etapas analíticas consultam fontes complementares oficiais; executá-las autoriza essas aquisições, cujos planos, URLs e hashes são registrados. Mantenha o código e o arquivo de dependências inalterados durante cada execução.

### 1. Inventariar e testar com RR e ZZ

```bash
./scripts/run.sh ambiente
./scripts/run.sh inventariar --online
./scripts/run.sh baixar-reposicoes --ufs RR ZZ
# Confira tamanhos, URLs e espaço antes do próximo comando.
./scripts/run.sh baixar-reposicoes --ufs RR ZZ --confirmar-download
./scripts/run.sh inventariar
uv run --frozen python scripts/test.py
./scripts/run.sh piloto
./scripts/run.sh processar --ufs RR ZZ
./scripts/run.sh piloto-analise
```

`baixar-reposicoes` também atende ao primeiro download, quando os arquivos ainda não existem. A seleção vem do catálogo oficial, com uma cópia versionada em `data/raw/replacements/`; arquivos existentes não são sobrescritos. O inventário offline atualiza a seleção após o download. Se já tiver os ZIPs, informe seu diretório antes do inventário:

```bash
export URNAS_INPUT_DIR=/caminho/absoluto/dos/arquivos
```

Sem essa variável, arquivos colocados manualmente são procurados em `data/raw/transmitidos/`. O arquivo `.env.example` é explicativo e não é executado automaticamente. Os pilotos verificam RR/ZZ, incluindo as variantes do Sistema de Apuração. As verificações em arquivos reais exigem dados baixados; os testes unitários padrão não usam a base nacional.

### 2. Ingerir e analisar o país

```bash
./scripts/run.sh inventariar --online
./scripts/run.sh baixar-reposicoes
# Confira o plano nacional antes de confirmar.
./scripts/run.sh baixar-reposicoes --confirmar-download
./scripts/run.sh inventariar
./scripts/run.sh processar
./scripts/run.sh analisar --simulations 100 --seed 20261025
./scripts/run.sh piloto-complementar --workers 4
./scripts/run.sh processar-complementar --workers 4 --simulacoes 1000
```

A análise nacional exige todos os 28 recortes completos. O piloto complementar ocorre depois dessa base e testa RDVs, logs, assinaturas e tabelas antes da etapa complementar nacional. O processamento inicial de BU usa um trabalhador; os quatro processos são usados na etapa complementar de arquivos. A [comparação de CPU e GPU](docs/benchmark-complementar.md) explica a escolha observada e suas limitações; os tempos dependem do equipamento e dos dados.

Para executar a última etapa como serviço de usuário independente do terminal, após os testes e o piloto da mesma versão:

```bash
uv run --frozen python scripts/start_complement.py
```

O serviço usa `MemoryMax=20G`, quatro processos e temporários no repositório. O comando direto da CLI não impõe esse limite global de systemd. Acompanhe, se desejar, com `./scripts/run.sh status` e `./scripts/run.sh status-complementar`. Interromper preserva lotes confirmados; repetir a mesma etapa e parâmetros reaproveita checkpoints compatíveis. Dados de versões diferentes não devem ser reunidos por um glob de todos os Parquet. Consulte [métodos, rastreabilidade e limites](docs/metodo-e-reproducao.md).

### 3. Ler as saídas

- `data/catalog/`: inventários e snapshots dos catálogos.
- `data/raw/`: downloads preservados, parciais e metadados de aquisição.
- `data/derived/`: lotes Parquet publicados atomicamente.
- `data/checkpoints/`: seleção das entradas, andamento e ponteiros da execução.
- `output/analises/<execucao>/`: reconciliação nacional, horários e estatísticas iniciais.
- `output/complementar/<execucao>/`: matriz das alegações, RDVs/logs/assinaturas, tabelas, modelos e relatórios finais.

Arquivos locais, originais das imagens, ambientes virtuais, grandes bases, logs e resultados intermediários ficam fora do Git. As exceções publicadas são explícitas: o PDF revisado, seu texto/índice/manifesto e evidências agregadas pequenas. Nenhum resultado é gerado na instalação a partir de números de exemplo.

## Testes e revisão

```bash
uv run --frozen python scripts/test.py
# Opcional: requer arquivos oficiais e, para alguns testes, checkpoints históricos.
uv run --frozen pytest -m integration
```

Os testes padrão usam casos sintéticos para contabilidade, tipos, chaves, fusos, limites temporais, formatos, propagação de falhas e ordenação. Eles não substituem os pilotos com arquivos reais. Os testes marcados `integration` preservam verificações da execução original e não fazem download automático. O contrato HTTP e a simulação opcional estão em [docs/http-contract.yaml](docs/http-contract.yaml) e `postman/`; testam transporte com bytes sintéticos, sem atestar a confiabilidade do servidor real.

Correções devem informar o arquivo/versão, recorte, denominador, consulta e evidência da diferença. Resultados podem mudar se o TSE atualizar ou retirar recursos. Igualdade com esta edição exige os mesmos bytes de entrada e parâmetros, não apenas nomes de arquivos iguais. Não se presume disponibilidade futura das fontes.
