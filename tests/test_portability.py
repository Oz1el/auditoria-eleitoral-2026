"""Clean-checkout paths, source selection and explicit contextual coverage."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from auditoria_urnas import acquire, evidence
from auditoria_urnas.common import atomic_json, original_dir, prepare_directories


def test_default_input_and_runtime_directories_are_inside_project(tmp_path, monkeypatch):
    monkeypatch.setenv('URNAS_PROJECT_ROOT', str(tmp_path))
    monkeypatch.delenv('URNAS_INPUT_DIR', raising=False)
    assert original_dir() == tmp_path / 'data/raw/transmitidos'
    prepare_directories()
    assert (tmp_path / 'data/checkpoints').is_dir()
    assert (tmp_path / 'output/reports').is_dir()
    monkeypatch.setenv('URNAS_INPUT_DIR', str(tmp_path / 'existing'))
    assert original_dir() == tmp_path / 'existing'


def download_plan(tmp_path, monkeypatch):
    monkeypatch.setenv('URNAS_PROJECT_ROOT', str(tmp_path))
    atomic_json(tmp_path / 'data/catalog/replacement-plan.json', {
        'created_utc':'2026-10-29T12:00:00+00:00', 'files':[
            {'uf':uf, 'expected_bytes':100, 'url':f'https://cdn.tse.jus.br/{uf}.zip'}
            for uf in ['RR','ZZ']]})
    atomic_json(tmp_path / 'data/catalog/inventory.json', {
        'files':[{'uf':uf, 'eligible_for_validation':False} for uf in ['RR','ZZ']]})


def test_download_plan_only_selects_requested_regions_without_transfer(tmp_path, monkeypatch):
    download_plan(tmp_path, monkeypatch)
    monkeypatch.setattr(acquire, 'download', lambda *a:pytest.fail('download without confirmation'))
    plan=acquire.acquire_missing(['RR'])
    assert plan['traffic_bytes']==100 and [x['uf'] for x in plan['files']]==['RR']
    assert not (tmp_path / 'data/raw').exists()


def test_unresolved_region_or_unofficial_url_cannot_be_acquired(tmp_path, monkeypatch):
    download_plan(tmp_path, monkeypatch)
    atomic_json(tmp_path / 'data/catalog/replacement-plan.json', {'created_utc':'x','files':[]})
    with pytest.raises(ValueError,match='no official resource'):acquire.acquire_missing(['RR'])
    download_plan(tmp_path, monkeypatch)
    path=tmp_path/'data/catalog/replacement-plan.json';plan=json.loads(path.read_text())
    plan['files'][0]['url']='https://example.org/RR.zip';atomic_json(path,plan)
    monkeypatch.setattr(acquire.shutil,'disk_usage',lambda _:SimpleNamespace(free=10**15))
    monkeypatch.setattr(acquire,'download',lambda *a:pytest.fail('unofficial transfer'))
    with pytest.raises(ValueError,match='official HTTPS'):acquire.acquire_missing(['RR'],confirm=True)


def test_missing_optional_originals_are_explicit_and_present_changes_fail(tmp_path, monkeypatch):
    monkeypatch.setenv('URNAS_PROJECT_ROOT', str(tmp_path))
    transcription=tmp_path/'docs/relatorio_original/transcricao.md'
    transcription.parent.mkdir(parents=True);transcription.write_text('checked text')
    image=b'preserved example'
    atomic_json(transcription.parent/'imagens.json',{
        'transcription':'docs/relatorio_original/transcricao.md',
        'transcription_sha256':hashlib.sha256(transcription.read_bytes()).hexdigest(),
        'visually_checked_pages':[1], 'images':[{'page':1,'image':'input/report.png','sha256':hashlib.sha256(image).hexdigest()}]})
    atomic_json(tmp_path/'docs/evidencias-documentais/fontes.json',{'sources':[]})
    result=evidence.verify_context()
    assert result['images_verified_in_this_run']==0
    assert result['checks'][0]['status']=='not_available_in_this_checkout'
    (tmp_path/'input').mkdir();(tmp_path/'input/report.png').write_bytes(image)
    assert evidence.verify_context()['images_verified_in_this_run']==1
    (tmp_path/'input/report.png').write_bytes(b'changed')
    with pytest.raises(ValueError,match='image changed'):evidence.verify_context()
    transcription.write_text('changed')
    with pytest.raises(ValueError,match='transcription changed'):evidence.verify_context()


def test_missing_inventory_data_is_not_a_successful_cli_exit(tmp_path, monkeypatch):
    from auditoria_urnas import cli, pipeline
    monkeypatch.setenv('URNAS_PROJECT_ROOT',str(tmp_path))
    monkeypatch.setattr('sys.argv',['auditoria-urnas','processar','--ufs','RR'])
    monkeypatch.setattr(pipeline,'process',lambda _: {'failures':[{'stage':'inventory','uf':'RR'}]})
    assert cli.main()==2


def test_inventory_rejects_ambiguous_official_versions(tmp_path, monkeypatch):
    from auditoria_urnas import catalog
    monkeypatch.setenv('URNAS_PROJECT_ROOT',str(tmp_path))
    name='bu_imgbu_logjez_rdv_vscmr_2026_2t_AC.zip'
    atomic_json(tmp_path/'data/catalog/latest.json',{'resources':[
        {'url':'https://cdn.tse.jus.br/a/'+name}, {'url':'https://cdn.tse.jus.br/b/'+name}]})
    with pytest.raises(ValueError,match='ambiguous'):catalog.inventory()
