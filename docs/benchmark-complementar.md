# Comparação de CPU e GPU do processamento complementar

O processamento nacional foi interrompido por solicitação do operador em 29/10/2026, preservando os checkpoints confirmados. O benchmark é independente e não reinicia a auditoria nacional.

A amostra congelada contém 2.048 seções (1.024 de RR e 1.024 de ZZ): todos os 29 casos de Sistema de Apuração e as duas seções sem comparecimento dessas UFs, com as restantes selecionadas por uma ordenação SHA-256 reproduzível. Um único ZIP preserva os bytes dos membros originais; manifesto registra origem, hashes e seleção. Todas as configurações leem esse mesmo arquivo e as mesmas linhas de referência do BU.

As configurações `cpu1`, `cpu2`, `cpu4` usam respectivamente um, dois e quatro processos, fixados em núcleos físicos distintos. Cada processo executa os parsers e a verificação criptográfica oficial atuais. As threads BLAS/OMP são limitadas a uma por processo. Não se promete ganho linear com o número de processos.

As configurações `gpu1` e `gpu4` são híbridas: decodificam o RDV na CPU e transferem lotes de categorias anônimas para a GPU contar os votos presidenciais com histogramas inteiros. Logs e assinaturas permanecem na CPU. Não há associação entre escolha, ordem, identidade ou horário individual. As categorias são ordenadas antes da transferência e não são persistidas. O resultado deve ser idêntico à implementação CPU em todos os campos, inclusive brancos, nulos, tipos de voto, hashes e exceções. Isto mede uma alternativa GPU concreta para uma parte do fluxo, não estabelece um limite de desempenho de possíveis implementações CUDA futuras.

Cada configuração é repetida duas vezes, invertendo a ordem na segunda repetição. O tempo inclui inicialização dos processos/CUDA, leitura, descompressão, decodificação, logs, assinaturas, IPC, transferência e sincronização GPU. Exclui montagem da amostra, hash prévio de seus arquivos e publicação dos JSONs. O hash anterior a cada execução aquece o cache do sistema operacional igualmente; não se trata de um benchmark de disco com cache frio. A afinidade limita o número de núcleos elegíveis, mas não reserva esses núcleos exclusivamente contra outros programas do computador.

O pico de memória é amostrado como soma de RSS da árvore e pode contar páginas compartilhadas mais de uma vez. As leituras de utilização/memória GPU abrangem a placa inteira e podem incluir outros aplicativos. Os tempos não devem ser extrapolados para todo o país sem considerar composição das urnas, tamanhos de logs e contenção de disco.

Não são repetidos os downloads, o BWeb, as análises estatísticas ou a geração dos relatórios nacionais: o alvo deste comparativo é a etapa de arquivos que domina a estimativa de duração. A documentação, o serviço e os resultados registram essa limitação.

A instalação GPU é opcional (`uv sync --extra benchmark-gpu`), usa CuPy e o CUDA existente em `/usr`. Caches e temporários da execução ficam no disco de dados. Não há mudança de drivers ou serviços da máquina.

Comandos de reprodução, na raiz do projeto:

```bash
export UV_CACHE_DIR="$PWD/data/cache/uv"
export TMPDIR="$PWD/data/tmp"
export CUPY_CACHE_DIR="$PWD/data/cache/cupy"
export CUDA_PATH=/usr
export PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
uv sync --extra benchmark-gpu
.venv/bin/python -m auditoria_urnas.benchmark_complement prepare --folder "$PWD/output/benchmarks/nova-comparacao" --per-uf 1024
.venv/bin/python -m auditoria_urnas.benchmark_complement run --folder "$PWD/output/benchmarks/nova-comparacao" --repeats 2 --budget-seconds 3300
```

O script não permite execução duplicada, publica resultados incrementalmente e encerra a comparação ao atingir o orçamento de tempo, preservando os testes terminados. O serviço systemd tem limite de 20 GiB e prazo máximo independente como proteção operacional. `comparacao.md`, `comparacao.csv` e `status.json` registram medianas, faixas observadas, aceleração relativa e equivalência. Resultados diferentes da referência não podem ser recomendados como vencedores. A decisão nacional exige avaliar o conjunto de resultados.

Uma mudança de código altera a assinatura de execução da auditoria. Os checkpoints antigos continuam preservados; qualquer adoção posterior do novo paralelismo exigirá uma estratégia explícita para validar/reaproveitar seus resultados, além de novo piloto. O benchmark não altera esses checkpoints.
