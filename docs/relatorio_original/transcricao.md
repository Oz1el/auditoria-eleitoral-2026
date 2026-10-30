# Transcrição conferida dos sete prints fornecidos

Transcrição do conteúdo textual, tabelas e notas, conferida visualmente nesta sessão. Quebras de linha foram normalizadas; setas da interface, estilos, cores e linhas decorativas não constituem conteúdo do relatório. Autoria, data de produção e autenticidade do documento não foram estabelecidas. O texto abaixo é evidência a investigar, não conclusão desta auditoria.

## Página 1

Relatório Pericial Independente — Eleições 2026 | Microdados Oficiais TSE

RELATÓRIO PERICIAL INDEPENDENTE

Com Base em Microdados Oficiais do TSE

Abrangência: 100% dos Boletins de Urna (BWeb) das 28 Unidades da Federação

Total processado: 499.205 seções eleitorais · 128.236.074 votos apurados

Data da análise: 28 de outubro de 2026

Fonte: Repositório oficial de Dados Abertos do TSE

AUTÓPSIA DE NARRATIVAS E ESTRUTURAS DE PODER

Fatos primeiro. Efeitos de 2ª ordem. Ruído excluído.

Documento baseado em dados públicos do TSE — Outubro/2026 | Página 1

## Página 2

INTRODUÇÃO: O APAGÃO DE SETENTA E DUAS HORAS

Nenhum processo de auditoria sobre as eleições presidenciais de 2026 pode começar sem registrar a primeira e mais evidente anomalia do pleito: a quebra da cadeia de transparência imediata.

Em um sistema eletrônico propagandeado como instantâneo e ultramoderno, os resultados gerais foram totalizados e proclamados pelo Tribunal Superior Eleitoral na noite de domingo, 25 de outubro. No entanto, os microdados públicos de cada urna, fundamentais para a checagem independente de horários e biometria, foram trancados em sigilo técnico por quase três dias.

A liberação dos arquivos de Boletim de Urna (BWeb) ocorreu apenas na manhã desta quarta-feira, 28 de outubro. Durante setenta e duas horas, a sociedade civil e os peritos independentes foram privados do acesso aos dados primários, enquanto a máquina estatal acelerava o reconhecimento diplomático internacional, impunha medidas de exceção contra a oposição e consolidava o fato político consumado.

Com a abertura final dos arquivos, a equipe de inteligência processou a totalidade do banco de dados oficial: 499.205 seções eleitorais e 128.236.074 votos apurados. Os dados estão gravados e auditados, e a verdade que deles emerge desmonta a narrativa oficial.

CAPÍTULO 1: O PONTO DE INFLEXÃO DAS 17H00

(Duas Eleições em um Só Dia)

A análise do carimbo temporal gravado na memória física de cada urna eletrônica (DT_ENCERRAMENTO) revela que o Brasil viveu duas eleições completamente distintas no domingo:

| Janela Temporal | Resultado |
|---|---|
| Urnas encerradas até as 17h00 (prazo legal) | Flávio Bolsonaro venceu com 52,39% dos votos válidos, abrindo uma frente de quase 1,8 milhão de votos. |
| Urnas encerradas após as 17h00 (prorrogação) | Lula obteve uma explosão atípica de mais de 6,1 milhões de votos de vantagem, suficiente para anular a liderança da oposição e virar o resultado nacional. |

A vitória de Lula foi fabricada exclusivamente no universo de urnas que encerraram as votações após o horário limite legal.

CAPÍTULO 2: A DEMOLIÇÃO DO MITO DOS TRINTA E QUATRO MIL VOTOS

Após a contestação da oposição sobre a prorrogação de duas horas concedida pelo ministro Cristiano Zanin, a grande mídia e os porta-vozes do governo divulgaram amplamente que apenas trinta e quatro mil votos teriam sido depositados no período estendido, qualificando a

Documento baseado em dados públicos do TSE — Outubro/2026 | Página 2

## Página 3

Relatório Pericial Independente — Eleições 2026 | Microdados Oficiais TSE

medida como juridicamente inofensiva. Os números oficiais desmentem essa versão de forma acachapante:

| Janela de Encerramento | Seções | Eleitores | % Lula |
|---|---:|---:|---:|
| 17h01 a 17h15 | 339.593 | 88.071.750 | 53,46% |
| 17h16 a 18h59 | 2.472 | 674.799 | 57,16% |
| Após as 19h00 | 6.333 | 1.856.306 | — |

Mais de dois milhões e meio de eleitores votaram em urnas que extrapolaram os limites normais. E nessas seções que invadiram a noite de domingo, o desempenho do governismo atingiu índices avassaladores:

| Estado | Seções após 19h | % para Lula |
|---|---:|---:|
| Bahia | 936 | 72,31% |
| Pernambuco | 657 | 65,70% |
| Maranhão | — | 83,31% |
| São Paulo | 1.571 | 57,46% |

Em São Paulo, as 1.571 seções que cruzaram as 19h deram 57,46% para Lula, contrariando o comportamento eleitoral do restante do estado.

CAPÍTULO 3: O COLAPSO DA BIOMETRIA

(O Dobro da Margem de Vitória)

A maior vulnerabilidade material de todo o processo de 2026 reside no campo oficial QT_ELEI_BIOM_SEM_HABILITACAO. Esse dado registra o número de pessoas que não conseguiram validar a impressão digital e foram autorizadas a votar por liberação manual do mesário, mediante a simples digitação do ano de nascimento:

| Indicador | Valor |
|---|---|
| Total de eleitores liberados sem biometria | 8.632.488 votos (6,73% do comparecimento nacional) |
| Margem final de vitória de Lula sobre Flávio | 4.430.191 votos |
| Relação entre liberação manual e margem | Quase o dobro da diferença total da eleição |

O contingente de pessoas que depositaram votos na urna sem a salvaguarda da identificação biométrica digital é quase o dobro da diferença total da eleição. A perícia realizou o teste de correlação estatística entre o percentual de votos manuais e o percentual de votos obtidos por Lula.

Documento baseado em dados públicos do TSE — Outubro/2026 | Página 3

## Página 4

Relatório Pericial Independente — Eleições 2026 | Microdados Oficiais TSE

CAPÍTULO 4: ABERRAÇÕES DE UNANIMIDADE

(A Cauda Não Gaussiana)

Em sistemas eleitorais massivos e altamente polarizados, os percentuais de votação seguem distribuições gaussianas suaves em torno da média. A base de 2026 exibe anomalias extremas de seções quase unânimes concentradas em áreas rurais:

| Tipo de Seção | Lula | Flávio Bolsonaro | Razão |
|---|---:|---:|---:|
| 100% dos votos válidos | 106 seções | 4 seções | 26,5 : 1 |
| Mais de 90% dos votos | 6.899 seções | 384 seções | 18 : 1 |

Existe uma desproporção aberrante de dezoito para um na existência de seções com mais de noventa por cento de votos pró Lula. Essas seções coincidem com zonas rurais de baixíssima fiscalização partidária independente, onde a taxa de liberação sem biometria atinge seus picos mais elevados.

CAPÍTULO 5: O TESTE DA LEI DE BENFORD

Submetemos o conjunto de 499.205 seções eleitorais ao teste forense do primeiro dígito significativo de Benford, uma ferramenta matemática consagrada internacionalmente para detectar manipulação ou artificialidade em dados estatísticos massivos. O comportamento dos dígitos dos votos de ambos os candidatos foi comparado com a curva logarítmica natural.

[Nota: Os gráficos do teste de Benford e da correlação biométrica não foram incluídos neste documento, pois dependiam de imagens anexas à análise original.]

CAPÍTULO 6: O CONTEXTO INSTITUCIONAL E A OPERAÇÃO DE ABAFAMENTO

A matemática não opera no vácuo. O comportamento anômalo dos dados ganha contornos definitivos quando analisado em conjunto com as ações do aparato estatal:

A Ordem dos Sete Minutos

O ministro Alexandre de Moraes assinou o cancelamento dos passaportes de Flávio Bolsonaro exatamente sete minutos após a proclamação das urnas, antes mesmo que os recursos da oposição fossem protocolados.

A Ameaça de Prisão Preventiva

Uma ala da Polícia Federal articulou a prisão cautelar do principal líder da oposição com base em boatos de imprensa, forçando a sua extração do país sob proteção diplomática dos Estados Unidos.

A Cortina de Fumaça sobre o Banco Master

Toda a pirotecnia contra a oposição foi ativada na mesma semana em que deveriam entrar em pauta as apurações financeiras sobre Daniel Vorcaro e os quarenta milhões de dólares

Documento baseado em dados públicos do TSE — Outubro/2026 | Página 4

## Página 5

Relatório Pericial Independente — Eleições 2026 | Microdados Oficiais TSE

repassados à família de magistrados do tribunal superior.

O Reconhecimento Internacional Dividido

Enquanto Donald Trump classificou a eleição como manchada por fraude decorrente da prorrogação e a Argentina acolheu a oposição, a mídia estatal chinesa admitiu que a extensão de duas horas impulsionou a virada governista.

CONCLUSÃO PERICIAL: O VEREDITO DOS DADOS

O que a maior auditoria de microdados eleitorais já realizada no Brasil comprova não é uma tese partidária. É um fato aritmético:

• A eleição regulamentar até as 17h00 foi vencida por Flávio Bolsonaro.

• A virada ocorreu exclusivamente em urnas encerradas após o prazo legal.

• Mais de oito milhões e seiscentos mil votos foram emitidos sem verificação biométrica digital, quase o dobro da diferença que decidiu a presidência.

• Milhões de votos foram computados na calada da noite sob picos de mais de setenta por cento pró governo.

• Os dados foram sonegados da sociedade por setenta e duas horas.

O resultado proclamado pelo sistema não possui integridade matemática, quebrou os protocolos mais elementares de controle biométrico e foi viabilizado por uma intervenção judicial monocrática que alterou as regras no meio do jogo.

Os arquivos estão salvos, os gráficos estão traçados e os números agora pertencem ao julgamento da história e do povo brasileiro.

Documento baseado em dados públicos do TSE — Outubro/2026 | Página 5

## Página 6

Relatório Pericial Independente — Eleições 2026 | Microdados Oficiais TSE

ANEXO: NOTA DE ESCLARECIMENTO TÉCNICO

A Metodologia do Estudo e a Vulnerabilidade da Fiscalização Biométrica

Diante da repercussão do dossiê estatístico das eleições de 2026, faz-se necessário registrar uma nota pública de método e escopo para delimitar, com rigor científico e transparência absoluta, como o estudo trabalhou os dados oficiais do Tribunal Superior Eleitoral.

1. O que este estudo NÃO é: O Mito das Invasões Externas

É fundamental esclarecer ao público e aos especialistas o que nunca esteve no radar pericial: o estudo não investigou e não se baseia em teorias sobre invasão de hackers, adulteração de código fonte ou manipulação de sistemas por satélite. Teses mirabolantes de interferência cibernética invisível servem apenas para desviar a atenção daquilo que realmente pode ser auditado e comprovado no mundo real. A perícia não buscou fantasmas em servidores. A perícia debruçou-se sobre o chão de fábrica do processo eleitoral: o procedimento físico da votação, a presença de fiscais e o cumprimento das normas legais na ponta da linha.

2. A Lacuna Investigada: A Fragilidade da Fiscalização e a Liberação Manual

O coração da investigação concentrou-se em uma vulnerabilidade humana e processual conhecida, mas que foi explorada em escala inédita no segundo turno: a substituição do controle biométrico digital pela liberação manual do mesário. A propaganda institucional vendeu ao país que a biometria era o escudo inviolável que impedia um eleitor de votar no lugar de outro ou que cadastros fantasmas fossem ativados. No entanto, o próprio sistema possui uma válvula de escape regulamentar: quando a digital do eleitor falha quatro vezes no leitor, a urna autoriza o mesário a liberar a votação mediante a simples digitação do ano de nascimento do cidadão.

Em seções urbanas com intensa fiscalização de partidos de oposição, essa regra de exceção é aplicada com testemunhas e sob controle social. A pergunta metodológica que fizemos foi: o que acontece com essa regra de exceção nas regiões mais isoladas do país, nos grotões rurais e nas seções onde a oposição não possuía nenhum fiscal físico acompanhando a mesa receptora? Ao retirar a trava biométrica do computador e devolver o poder absoluto de liberação à caneta de quem opera o terminal, a tecnologia de ponta é anulada e o processo retrocede ao velho modelo de confiança cega em quem está na sala.

3. A Metodologia de Coleta e Auditoria

Para responder a essa pergunta com números irrefutáveis, adotamos um protocolo técnico transparente e auditável por qualquer perito:

• Fonte Primária Aberta: Trabalhamos exclusivamente com os arquivos oficiais de Boletins de Urna (BWeb) do segundo turno disponibilizados pelo repositório oficial de Dados Abertos do TSE. Todos os arquivos foram checados contra os seus respectivos hashes criptográficos originais (.sha512).

• Universalidade do Banco: Não fizemos amostragem. Processamos cem por cento das 499.205 seções eleitorais do Brasil e do exterior, cobrindo os 128.236.074 votos registrados.

• Cruzamento de Três Variáveis Internas: A quantidade de eleitores habilitados sem validação biométrica (QT_ELEI_BIOM_SEM_HABILITACAO); o horário físico de encerramento gravado pela urna eletrônica (DT_ENCERRAMENTO); e a votação nominal conferida a cada candidato na respectiva seção (QT_VOTOS).

Documento baseado em dados públicos do TSE — Outubro/2026 | Página 6

## Página 7

Relatório Pericial Independente — Eleições 2026 | Microdados Oficiais TSE

4. O Diagnóstico Factual Extraído da Base

A perícia não criou números. A perícia apenas organizou as variáveis oficiais, e os resultados revelam a extensão da fragilidade:

• A Quebra do Controle Superou a Margem de Vitória: O volume de eleitores liberados manualmente por ano de nascimento somou 8.632.488 votos, enquanto a diferença final entre os dois candidatos foi de 4.430.191 votos. Ou seja: a margem de segurança do sistema foi superada em quase duas vezes pelo volume de liberações manuais.

• A Curva de Correlação Positiva: Nas seções onde mais de noventa e cinco por cento dos eleitores usaram a digital com sucesso, o equilíbrio entre os candidatos foi evidente. Mas nas seções onde as taxas de liberação manual escalaram para vinte, trinta ou mais de cinquenta por cento, a votação de Lula disparou em linha reta, atingindo picos de mais de sessenta e um por cento.

• O Casamento com a Janela Noturna: As seções que fecharam após o horário regulamentar das dezessete horas, beneficiadas pela prorrogação monocrática, coincidem de forma assustadora com os municípios e zonas de maior taxa de votos sem biometria e de menor presença de fiscais partidários independentes.

O objetivo deste trabalho foi demonstrar, com a frieza dos microdados, que a fragilidade do sistema não está em um ataque cibernético de ficção científica, mas na facilidade com que o rito de fiscalização e a trava biométrica foram desarmados na ponta da linha em um volume de milhões de votos. Quando um pleito presidencial de quase cento e trinta milhões de eleitores é decidido por quatro milhões de votos, e quase nove milhões foram chancelados sem a conferência eletrônica da identidade do votante sob a proteção da escuridão de uma prorrogação, a integridade do processo deixa de ser uma certeza matemática e torna-se uma questão em aberto que nenhum tribunal tem o direito de ignorar.

Os dados estão disponíveis, o método é replicável e os números falam por si mesmos.

Fonte primária: Microdados oficiais do TSE (BWeb). Este documento não constitui laudo judicial.

Documento baseado em dados públicos do TSE — Outubro/2026 | Página 7
