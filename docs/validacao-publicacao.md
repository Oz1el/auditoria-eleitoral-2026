# Verificação da preparação para publicação

Verificação realizada em 30/10/2026 UTC (29/10 no fuso local). Esta preparação não refez o processamento eleitoral nacional nem novos testes estatísticos.

- 48 testes unitários passaram em uma cópia extraída somente do índice Git, sem ZIPs, Parquet ou checkpoints locais; 25 casos de integração foram excluídos explicitamente.
- O inventário offline dessa cópia identificou os 28 recortes ausentes e não iniciou downloads.
- O lock passou em `uv lock --check --offline`; o teste usou o interpretador e as dependências já instalados. Não houve instalação independente a partir da internet ou reprodução nacional de ponta a ponta nesta preparação.
- Onze cenários do cliente HTTP real passaram contra a simulação Postman local, com requisições observadas no servidor: erros transitórios, falha persistente, limite de leitura, downloads novos e retomados, Range ignorado, ETag alterado, hash divergente e proibição de sobrescrita. Isso não é validação nova da disponibilidade do TSE.
- O PDF e os hashes das evidências agregadas publicadas passaram na verificação offline. O PDF preserva o SHA-256 `98c72b9e450769824c5ed25ed07a06fa807a3747e611c894bf69af16126f19c2`.
- Não foram incluídos dados brutos, Parquet, bancos, ambientes, caches, logs ou autorizações operacionais. A varredura textual de padrões comuns de credenciais não encontrou ocorrências; isso não equivale a uma auditoria de segurança completa.

Os módulos abaixo foram comparados byte a byte com o snapshot da execução complementar concluída, após a correção das comparações municipais. Permaneceram idênticos durante a organização do repositório. O SHA-256 do arquivo histórico `source-code.tar.gz` usado nessa comparação é `30a1a4e55dd5bf07f935c6b707061dc2fc2628bb0b076ce4a70719cfeae9be1d`.

| Módulo | SHA-256 preservado |
| --- | --- |
| `parser.py` | `9c46376b74a5e3402a40c9cd192d59f96f26af67f876261c91686e32365c419d` |
| `analysis.py` | `33298ed2ab4448128e34c5286db49bc677bf92fa4213918b6116bc43d5ef2ce3` |
| `statistics.py` | `d54a20cf65c4f9585101ab7527fd9325d23b945a3419b05390a182e4ad8f434c` |
| `complement_parsers.py` | `5c54061c5c6066b83df87536f889ff8e408e4feed06cb5c005e68f7029ff84ac` |
| `complement_statistics.py` | `ec006057d01dd23ce032dcb04762ee1023ecacc06870222ba0fbf45bccb43f69` |
| `complement_tables.py` | `a22ac21215fd2fcc1a8bbc234d1baa817f2751d6d5078da8ef503ac45c99681c` |
| `complement_comparisons.py` | `8deff0d3826c88688407a4673968d800596e2cecdf7864bb9846006e26ff46b6` |

As mudanças de preparação afetam caminhos, inicialização de diretórios, seleção explícita de downloads, tratamento de versões ambíguas, códigos de saída, disponibilidade de evidências contextuais e documentação. Os testes dependentes de bases reais passaram a exigir seleção explícita. O gerador editorial foi fixado às evidências da edição publicada. A etapa complementar deixou de exigir o arquivo privado do benchmark antigo para lançamento; continuam exigidos os testes e o piloto da versão atual.

Prefixos de caminhos da máquina foram removidos apenas nas cópias públicas das evidências agregadas. `reports/evidence/index.json` registra hashes antes e depois dessa projeção. Os originais, os checkpoints e as publicações anteriores continuam no disco local.
