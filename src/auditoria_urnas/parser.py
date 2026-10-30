"""Decode the official ASN.1 schema and independently read the printed BU."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import asn1tools

NAME = re.compile(r'^o(?P<pleito>\d{5})(?P<uf>[a-z]{2})(?P<municipio>\d{5})(?P<zona>\d{4})(?P<secao>\d{4})-(?:bu|busa)\.dat$')
# AM and PE need municipal exceptions. ZZ needs a documented per-location mapping.
# Keeping a timestamp unresolved is safer than inventing an offset.
ZONES = {'AC': 'America/Rio_Branco', 'RR': 'America/Boa_Vista', 'RO': 'America/Porto_Velho',
         'MT': 'America/Cuiaba', 'MS': 'America/Campo_Grande'}
UNRESOLVED = {'AM', 'PE', 'ZZ'}


def time_brasilia(raw: str | None, zone: str | None) -> str | None:
    if raw is None or zone is None:
        return None
    dt = datetime.strptime(raw, '%Y%m%dT%H%M%S')
    return dt.replace(tzinfo=ZoneInfo(zone)).astimezone(ZoneInfo('America/Sao_Paulo')).isoformat()


def validate_counts(eligible: int, original: int, temporary: int, turnout: int, votes: list[dict], biometric=None):
    if min(eligible, original, temporary, turnout, *(v['quantidade'] for v in votes)) < 0:
        raise ValueError('negative count')
    if original + temporary != eligible:
        raise ValueError('eligible != original + temporary')
    if turnout > eligible:
        raise ValueError('turnout exceeds eligible')
    if sum(v['quantidade'] for v in votes) != turnout:
        raise ValueError('votes != cargo turnout')
    keys = [(v['tipo_voto'], v['numero'], v['partido']) for v in votes]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate votable key')
    if biometric is not None and sum(biometric.values()) != turnout:
        raise ValueError('biometric categories != turnout')


def printed_president(text: str) -> dict:
    """Independent text extraction; candidate names are never fixed in code."""
    block = re.search(r'-+PRESIDENTE-+\s*(.*?)(?:Código Verificador|=============)', text, re.S)
    if not block:
        raise ValueError('printed presidential block missing')
    block = block[1]
    candidates = {int(number): int(count) for number, count in
                  re.findall(r'^\s*[^\d\n].*?\s+(\d{1,2})\s+(\d+)\s*$', block, re.M)}
    def value(label, default=None):
        m = re.search(r'^\s*' + label + r'\s+(\d+)\s*$', block, re.M)
        if m:
            return int(m[1])
        if default is not None:
            return default
        raise ValueError(f'printed field missing: {label}')
    return {'candidatos': candidates, 'brancos': value('Brancos', 0), 'nulos': value('Nulos', 0),
            'aptos': value('Eleitores aptos'), 'apurados': value('Total Apurado')}


class Decoder:
    def __init__(self, specs: Path, timezone_overrides=None):
        self.codec = asn1tools.compile_files(str(specs / 'bu.asn1'), codec='ber', numeric_enums=True)
        self.timezone_overrides = timezone_overrides or {}

    def entity(self, kind: str, raw: bytes):
        entity, consumed = self.codec.decode_with_length(kind, raw, check_constraints=True)
        if consumed != len(raw):
            raise ValueError(f'trailing bytes in {kind}')
        return entity

    def envelope(self, raw: bytes):
        result = self.entity('EntidadeEnvelopeGenerico', raw)
        if result['fase'] != 2 or 'seguranca' in result:
            raise ValueError('non-official or encrypted envelope')
        return result

    def decode(self, name: str, raw: bytes, image: bytes | None, uf: str):
        match = NAME.fullmatch(name)
        if not match or match['uf'].upper() != uf:
            raise ValueError(f'filename/UF mismatch: {name}')
        envelope = self.envelope(raw)
        if envelope['tipoEnvelope'] != 1:
            raise ValueError('not a BU envelope')
        bu = self.entity('EntidadeBoletimUrna', envelope['conteudo'])
        ident = bu['identificacaoSecao']
        municipality, zone, section = ident['municipioZona']['municipio'], ident['municipioZona']['zona'], ident['secao']
        pleito = bu['cabecalho']['idEleitoral']
        expected = (int(match['municipio']), int(match['zona']), int(match['secao']))
        if expected != (municipality, zone, section) or pleito != ('idPleito', int(match['pleito'])):
            raise ValueError('BU identity differs from archive member name')
        envelope_kind, envelope_id = envelope['identificacao']
        if (envelope['cabecalho']['idEleitoral'] != pleito
                or envelope_id['municipioZona'] != ident['municipioZona']
                or (envelope_kind == 'identificacaoSecaoEleitoral' and envelope_id['secao'] != section)):
            raise ValueError('envelope identity differs from BU')
        if bu['fase'] != 2:
            raise ValueError('non-official BU')
        data_kind, data = bu['dadosSecaoSA']
        timezone_key = f'{uf}:{municipality:05}'
        timezone = self.timezone_overrides.get(timezone_key)
        if not timezone and uf not in UNRESOLVED and data_kind == 'dadosSecao':
            timezone = ZONES.get(uf, 'America/Sao_Paulo')
        if data_kind != 'dadosSecao':
            timezone = None
        turnout_detail = bu.get('detalhamentoComparecimento')
        if turnout_detail and sum(turnout_detail.values()) != bu['qtdEleitoresCompareceram']:
            raise ValueError('biometric categories do not sum to BU turnout')
        load = bu['urna']['correspondenciaResultado']['carga']
        bu_id = hashlib.sha256(raw).hexdigest()
        text = None
        if image is not None:
            ie = self.envelope(image)
            if ie['tipoEnvelope'] != 4 or ie['identificacao'] != envelope['identificacao']:
                raise ValueError('printed image identity/envelope mismatch')
            text = ie['conteudo'].decode('latin1')
        aggregate = []
        if text and (m := re.search(r'Seções agregadas:\s*([\d\s/]+)', text)):
            aggregate = [int(x) for x in re.findall(r'\d+', m[1])]
        record = {'bu_id': bu_id, 'uf': uf, 'municipio': municipality, 'zona': zone, 'secao': section,
                  'local': ident['local'], 'pleito': pleito[1], 'origem': data_kind, 'membro': name,
                  'urna': load['numeroInternoUrna'], 'tipo_urna': bu['urna']['tipoUrna'],
                  'tipo_arquivo': bu['urna']['tipoArquivo'], 'codigo_carga': load['codigoCarga'],
                  'versao_software': bu['urna']['versaoVotacao'], 'comparecimento_bu_original': bu['qtdEleitoresCompareceram'],
                  'sem_biometria_cadastrada': turnout_detail.get('qtdEleitoresCompareceramSemBiometria') if turnout_detail else None,
                  'habilitados_biometria': turnout_detail.get('qtdEleitoresHabilitadosPorBiometria') if turnout_detail else None,
                  'habilitados_biografia': turnout_detail.get('qtdEleitoresHabilitadosPorBiografia') if turnout_detail else None,
                  'abertura_original': data.get('dataHoraAbertura'), 'encerramento_original': data.get('dataHoraEncerramento'),
                  'emissao_original': bu['dataHoraEmissao'], 'geracao_original': bu['cabecalho']['dataGeracao'],
                  'fuso': timezone, 'fuso_status': 'mapeado' if timezone else 'nao_resolvido',
                  'encerramento_brasilia': time_brasilia(data.get('dataHoraEncerramento'), timezone),
                  'emissao_brasilia': time_brasilia(bu['dataHoraEmissao'], timezone),
                  'agregadas_json': json.dumps(aggregate), 'historico_cargas_json': json.dumps(bu['historicoCodigosCarga']),
                  'dados_sa_json': json.dumps(data) if data_kind == 'dadosSA' else None,
                  'imagem_sha256': hashlib.sha256(image).hexdigest() if image is not None else None,
                  'assinatura_digital': 'nao_verificada'}
        elections, votes = [], []
        seen = set()
        for election in bu['resultadosVotacaoPorEleicao']:
            for voting in election['resultadosVotacao']:
                for office in voting['totaisVotosCargo']:
                    cargo = office['codigoCargo'][1]
                    key = (election['idEleicao'], cargo)
                    if key in seen:
                        raise ValueError('duplicate election/office in BU')
                    seen.add(key)
                    ev = []
                    for value in office['votosVotaveis']:
                        votable = value.get('identificacaoVotavel', {})
                        ev.append({'bu_id': bu_id, 'eleicao': key[0], 'cargo': cargo,
                                   'tipo_voto': value['tipoVoto'], 'numero': votable.get('codigo'),
                                   'partido': votable.get('partido'), 'quantidade': value['quantidadeVotos']})
                    eligible = election['qtdEleitoresAptos']
                    turnout = voting['qtdComparecimento']
                    # Multi-seat offices can yield multiple choices; strict vote conservation is presidential.
                    if cargo == 1:
                        validate_counts(eligible, election['qtdEleitoresAptosSecao'], election['qtdEleitoresAptosTTE'], turnout, ev)
                        if data_kind == 'dadosSecao' and turnout != bu['qtdEleitoresCompareceram']:
                            raise ValueError('presidential turnout differs from section turnout')
                        if text is not None:
                            printed = printed_president(text)
                            calculated = {v['numero']: v['quantidade'] for v in ev if v['tipo_voto'] == 1 and v['quantidade']}
                            if {n: q for n, q in printed['candidatos'].items() if q} != calculated:
                                raise ValueError('printed/binary candidate mismatch')
                            if (printed['aptos'], printed['apurados'], printed['brancos'], printed['nulos']) != (
                                    eligible, turnout, sum(v['quantidade'] for v in ev if v['tipo_voto'] == 2),
                                    sum(v['quantidade'] for v in ev if v['tipo_voto'] == 3)):
                                raise ValueError('printed/binary accounting mismatch')
                    elections.append({'bu_id': bu_id, 'eleicao': key[0], 'cargo': cargo, 'aptos': eligible,
                                      'aptos_originais': election['qtdEleitoresAptosSecao'],
                                      'aptos_temporarios': election['qtdEleitoresAptosTTE'],
                                      'comparecimento': turnout, 'abstencoes': eligible - turnout,
                                      'conferido_imagem': bool(text is not None and cargo == 1)})
                    votes.extend(ev)
        return record, elections, votes
