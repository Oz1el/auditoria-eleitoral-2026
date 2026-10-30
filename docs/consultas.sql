-- As views são criadas por auditoria_urnas.pipeline.connection(states).
-- states contém somente checkpoints completos selecionados para esta execução.

-- Votos presidenciais por UF/candidato/tipo, sem repetir métricas de seção.
SELECT b.uf, b.pleito, v.eleicao, v.tipo_voto, v.numero,
       sum(v.quantidade)::BIGINT AS votos
FROM votos v JOIN boletins b USING (bu_id)
WHERE v.cargo = 1
GROUP BY ALL ORDER BY 1,2,3,4,5;

-- Comparecimento e aptos: nenhuma ligação com a tabela de votos.
SELECT b.uf, b.pleito, e.eleicao, count(*) AS secoes,
       sum(e.aptos)::BIGINT AS aptos,
       sum(e.comparecimento)::BIGINT AS comparecimento,
       sum(e.abstencoes)::BIGINT AS abstencoes
FROM eleicoes e JOIN boletins b USING (bu_id)
WHERE e.cargo = 1 GROUP BY ALL;

-- Unicidade da identidade de seção selecionada.
SELECT uf,municipio,zona,secao,pleito,count(*) AS n
FROM boletins GROUP BY ALL HAVING count(*) > 1;

-- Conservação presidencial por BU/eleição.
SELECT e.bu_id,e.eleicao,e.comparecimento,sum(v.quantidade) AS votos
FROM eleicoes e JOIN votos v USING(bu_id,eleicao,cargo)
WHERE e.cargo=1 GROUP BY ALL HAVING votos != e.comparecimento;
