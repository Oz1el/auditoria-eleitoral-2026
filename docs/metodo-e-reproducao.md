# Métodos, rastreabilidade e limites

## População e chaves

Os BUs são identificados por UF, município, zona, seção e pleito, com `bu_id` ligando representações e tabelas. Eleições e votos acrescentam eleição, cargo e categoria/candidato. Métricas da seção não são somadas depois de um join que as repita por candidato. A consulta em `analysis.SECTION_SQL` agrega os votos antes do join; o BWeb valida a repetição das métricas antes de deduplicar. Seções agregadas, origens do Sistema de Apuração, cargas e equipamentos são preservados.

## Integridade e inferência

CRC detecta corrupção do ZIP; SHA-256 identifica os bytes locais. SHA-512 é comparado ao oficial quando o recurso o oferece. Os hashes dos pacotes transmitidos, sem hash externo publicado, são identificadores locais. Assinatura de hardware, compatibilidade com emissor, confiança completa da cadeia e assinatura de software são verificações distintas. A implementação não faz validação completa RFC5280/revogação ou autenticação CEPESC de software. Comparecer em duas representações públicas concordantes não é observação independente do ato de votar.

Os parsers rejeitam identidade incompatível, dados truncados, categorias inesperadas e inconsistências contábeis. Arquivo ausente ou evento ambíguo não se torna zero. A ausência de um log de SP permanece explícita; o código tenta a recuperação oficial e preserva a limitação quando ela não é possível.

## Horários e biometria

São mantidos horário original e conversão de fuso. Os recortes de relógio local e de Brasília são distintos; o exterior sem fuso fundamentado não recebe conversão presumida. Limites em minutos incluem segundos: até 17h00 corresponde a até 17:00:59. São registrados separadamente encerramento, geração do BU e eventos dos logs. Não é possível distribuir votos de candidatos por horário individual usando apenas o encerramento do BU.

O corte técnico principal de seções após 19h é estrito (`>19:00:00`). O PDF apresenta também a sensibilidade inclusiva (`>=19:00:00`), importante para reproduzir os números de BA e SP. Ambos devem permanecer visíveis. Os números de 90% também dependem de `>` ou `>=` sobre votos válidos. Seções sem votos válidos não entram no denominador de proporção de candidato.

Habilitação biográfica não é o mesmo contador de ausência de biometria cadastrada. Os modelos são ecológicos, com controles e agrupamentos geográficos; não identificam a escolha do eleitor nem uma causa de irregularidade. Binomial e beta-binomial simulam hipóteses explícitas. A beta-binomial ajustada não explicou completamente os extremos observados. Desvio de Benford isolado, significância e concentração não são testes conclusivos de fraude. A semente e os números de simulações constam das saídas; a otimização numérica pode variar ligeiramente entre plataformas.

## Evidência documental e edição humana

`docs/relatorio_original/transcricao.md` preserva o conteúdo conferido dos sete prints; `imagens.json` registra seus hashes e a revisão histórica. Os PNGs não são redistribuídos aqui. Se presentes nos caminhos indicados, seus hashes são verificados; se ausentes, `contexto-evidencias.json` informa que não foram reverificados na nova execução. A transcrição distribuída continua protegida por hash. Conclusões documentais em `fontes.json` são registros atribuídos da pesquisa anterior, com URL, data, limitações e hashes quando houve captura. A execução numérica não refaz automaticamente a pesquisa institucional ou uma linha do tempo histórica da internet.

A classificação de interpretação nas definições da matriz envolve julgamento documentado; não é saída de um classificador de fraude. O PDF natural também tem texto editorial explícito e evidência referenciada. O gerador editorial lê somente as evidências agregadas desta edição, verificando seus hashes; não consulta os ponteiros da execução mais recente. Seus números escritos não são resultados de outra execução. Os scripts de reparo e migração preservam histórico e não integram a sequência normal de reprodução.

## Versões e execução

Fontes, esquemas ASN.1, dependências e scripts entram na assinatura de execução. Os checkpoints registram hashes de entradas e saídas; as análises leem somente lotes selecionados. O coordenador publica lotes complementares de 100 seções; os trabalhadores leem seus próprios ZIPs, recebem tarefas de 32 seções e no máximo oito tarefas ficam pendentes. Só o coordenador escreve resultados e checkpoints. Uma falha de trabalhador é propagada. Locks evitam a mesma etapa concorrente.

O módulo `complement_resume` contém uma migração específica da execução interrompida original. Ela só tenta reaproveitamento se encontrar o checkpoint exato e comprovar compatibilidade. Em um clone novo não existe essa entrada: o processamento começa do zero. Nenhum resultado desse histórico é necessário para a sequência pública, exceto nos testes de integração explicitamente identificados.

O piloto inicial baixa uma amostra BWeb de ZZ. A análise consulta snapshots EA20 e configuração municipal. O complemento adquire BWeb, correspondências e tabelas históricas de 2026/2022. Os comandos que realizam essas consultas constam do README. Downloads interrompidos preservam parciais; a retomada depende de ETag forte compatível. Alterações de recursos não são aceitas como os mesmos bytes. Uma versão nova requer novo inventário e revisão.

## O que não foi demonstrado

Não há comprovação geral de fraude ou integridade eleitoral. Permanecem limitações documentais e temporais explicitadas no PDF. Não foram obtidos todos os históricos de publicação, cadastros de fiscais, ocorrências de identificação ou documentos necessários para várias alegações institucionais. Nada disso é classificado como inexistente apenas por falta de evidência. A reprodução requer recursos ainda acessíveis no TSE; uma indisponibilidade futura não deve ser ocultada ou substituída por dados fictícios.
