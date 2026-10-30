import json
import zipfile
from pathlib import Path

import pytest

from auditoria_urnas.parser import Decoder, printed_president, time_brasilia, validate_counts
from auditoria_urnas.common import root, original_dir


@pytest.fixture(scope='module')
def decoder():
    return Decoder(root()/'specs')


def test_time_rr_is_not_brasilia():
    assert time_brasilia('20261025T160207','America/Boa_Vista')=='2026-10-25T17:02:07-03:00'


def test_unresolved_timezone_stays_missing():
    assert time_brasilia('20261025T170000',None) is None
    assert time_brasilia(None,'America/Sao_Paulo') is None


def test_ac_and_previous_election_date():
    assert time_brasilia('20221030T150000','America/Rio_Branco')=='2022-10-30T17:00:00-03:00'


def test_text_reader_candidate_independent():
    text='---PRESIDENTE---\nNome Num Votos\n FULANO 55 20\n CICLANO 99 10\nEleitores aptos 40\nBrancos 2\nNulos 3\nTotal Apurado 35\nCódigo Verificador'
    assert printed_president(text)=={'candidatos':{55:20,99:10},'aptos':40,'brancos':2,'nulos':3,'apurados':35}


def test_synthetic_accounting_and_duplicates():
    votes=[{'tipo_voto':1,'numero':55,'partido':55,'quantidade':20},{'tipo_voto':2,'numero':None,'partido':None,'quantidade':2}]
    validate_counts(30,28,2,22,votes,{'bio':20,'other':2})
    with pytest.raises(ValueError,match='votes !='):validate_counts(30,28,2,23,votes)
    with pytest.raises(ValueError,match='eligible !='):validate_counts(31,28,2,22,votes)
    with pytest.raises(ValueError,match='duplicate'):validate_counts(30,30,0,24,votes+[votes[1]])
    with pytest.raises(ValueError,match='biometric'):validate_counts(30,28,2,22,votes,{'bio':21})


@pytest.mark.integration
def test_real_rr_schema_and_text(decoder):
    with zipfile.ZipFile(original_dir()/'bu_imgbu_logjez_rdv_vscmr_2026_2t_RR.zip') as z:
        n=next(n for n in z.namelist() if n.endswith('-bu.dat'))
        b,e,v=decoder.decode(n,z.read(n),z.read(n.replace('-bu.dat','-imgbu.dat')),'RR')
        assert e[0]['conferido_imagem']
        assert b['habilitados_biometria']+b['habilitados_biografia']+b['sem_biometria_cadastrada']==b['comparecimento_bu_original']
        assert sum(x['quantidade'] for x in v if x['cargo']==1)==e[0]['comparecimento']


@pytest.mark.integration
def test_real_sa_has_distinct_turnout_and_no_fake_time(decoder):
    with zipfile.ZipFile(original_dir()/'bu_imgbu_logjez_rdv_vscmr_2026_2t_ZZ.zip') as z:
        n=next(n for n in z.namelist() if n.endswith('-busa.dat'))
        b,e,v=decoder.decode(n,z.read(n),z.read(n.replace('-busa.dat','-imgbusa.dat')),'ZZ')
        assert b['origem']=='dadosSA'
        assert b['encerramento_original'] is None and b['encerramento_brasilia'] is None
        assert b['habilitados_biometria'] is None
        assert sum(x['quantidade'] for x in v if x['cargo']==1)==e[0]['comparecimento']


@pytest.mark.integration
def test_filename_identity_mismatch_is_rejected(decoder):
    with zipfile.ZipFile(original_dir()/'bu_imgbu_logjez_rdv_vscmr_2026_2t_RR.zip') as z:
        n=next(n for n in z.namelist() if n.endswith('-bu.dat'))
        with pytest.raises(ValueError,match='identity'):
            decoder.decode(n.replace('0011-bu.dat','9999-bu.dat'),z.read(n),None,'RR')


@pytest.mark.integration
def test_tampered_print_and_trailing_bytes_are_rejected(decoder):
    with zipfile.ZipFile(original_dir()/'bu_imgbu_logjez_rdv_vscmr_2026_2t_RR.zip') as z:
        n=next(n for n in z.namelist() if n.endswith('-bu.dat'))
        raw=z.read(n)
        with pytest.raises(ValueError,match='trailing'):decoder.decode(n,raw+b'x',None,'RR')
        image=bytearray(z.read(n.replace('-bu.dat','-imgbu.dat')))
        index=image.find(b'0042')
        assert index>=0
        image[index:index+4]=b'0043'
        with pytest.raises(ValueError,match='mismatch'):decoder.decode(n,raw,bytes(image),'RR')
