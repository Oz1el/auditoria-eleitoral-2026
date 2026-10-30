# Origem dos componentes externos

As especificações em `specs/*.asn1` e `src/auditoria_urnas/official/mr_util.py` vieram do pacote técnico oficial do TSE. As URLs, datas e hashes estão em `specs/origem.json` e `docs/official-helper.json`. O helper foi preservado sem modificações; não se atribui sua autoria ao projeto. A cópia local não traz uma licença explícita no cabeçalho. Sua disponibilização aqui não acrescenta uma licença ou uma autorização de redistribuição concedida pelo projeto. Consulte os termos da fonte para reutilização.

O ECPy é obtido da revisão `8143d9ac017de0cb7f980bedaf56cefe6b4d9180` do repositório público `https://github.com/cslashm/ECPy.git`, fixada no `pyproject.toml` e no `uv.lock`. Essa revisão contém o suporte Ed521 usado pelo helper oficial; substituir somente pela versão estável homônima do PyPI altera a compatibilidade. As demais bibliotecas são identificadas com suas versões e fontes no lock e mantêm suas próprias licenças.

Não foi escolhida uma licença geral nova para o código deste projeto durante a preparação do repositório. Publicação e permissões de reutilização são decisões distintas. Os resultados e os sete prints não transferem autoria do documento analisado. A atribuição da conta do Instagram foi fornecida pelo responsável pelo projeto, sem URL preservada da publicação.
