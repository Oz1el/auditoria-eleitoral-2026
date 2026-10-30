# Edição preservada de 29/10/2026

O PDF é a edição final já revisada, com 32 páginas, 68 respostas e cobertura dos 75 IDs da matriz, além de pontos de contexto. Seu SHA-256 é `98c72b9e450769824c5ed25ed07a06fa807a3747e611c894bf69af16126f19c2`.

O Markdown contém as respostas; os apêndices e a diagramação completa estão no PDF. O JSON e o CSV permitem localizar cada alegação. O manifesto registra hashes das entradas históricas, inclusive arquivos não distribuídos no Git. Caminhos foram projetados para relativos na cópia pública do manifesto; os hashes continuam identificando os bytes originais.

O texto natural teve revisão editorial. `scripts/create_natural_report.py` e `scripts/relatorio_natural_content.py` preservam essa autoria, incluindo números explicitamente escritos. O gerador editorial verifica os hashes das evidências agregadas publicadas, não consulta ponteiros de novas execuções e não deve ser usado como cálculo para uma base diferente. A reprodução computacional usa a CLI, que gera novos relatórios técnicos e nunca substitui este PDF.

O PDF registra a sensibilidade inclusiva de 19:00:00 para BA e SP. A matriz técnica histórica usava corte estrito: preserve essa distinção ao comparar classificações. O texto natural esclarece limites e recortes; não se deve confundir diferença de filtro com diferença na soma de votos.

`evidence/index.json` distingue o hash histórico do hash público. Somente prefixos de caminhos locais foram removidos nas cópias agregadas; números, filtros e classificações foram preservados. Os arquivos originais permanecem na execução local. `fontes-da-execucao.csv` lista os hashes previamente registrados, não uma nova leitura dos grandes ZIPs.

Para conferir os hashes e o índice sem executar análise: `uv run --frozen python scripts/verify_publication.py`. Isso verifica os arquivos publicados, não refaz a conferência eleitoral.
