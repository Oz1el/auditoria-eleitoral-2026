import json
import shutil
import zipfile
from pathlib import Path

import pytest

from auditoria_urnas import pipeline
from auditoria_urnas.common import original_dir, root
from auditoria_urnas.catalog import inspect_archive


@pytest.fixture
def small_project(tmp_path,monkeypatch):
    real=root()
    originals=original_dir()
    for d in ['src','specs']:
        shutil.copytree(real/d,tmp_path/d)
    for n in ['uv.lock','pyproject.toml']:shutil.copy(real/n,tmp_path/n)
    for d in ['data/checkpoints','data/derived','data/tmp']:(tmp_path/d).mkdir(parents=True)
    monkeypatch.setenv('URNAS_PROJECT_ROOT',str(tmp_path))
    monkeypatch.setenv('URNAS_INPUT_DIR',str(originals))
    monkeypatch.setattr(pipeline,'BATCH_SIZE',2)
    return tmp_path


def sample_zip(tmp_path):
    path=tmp_path/'sample.zip'
    with zipfile.ZipFile(original_dir()/'bu_imgbu_logjez_rdv_vscmr_2026_2t_RR.zip') as src,zipfile.ZipFile(path,'w') as dst:
        for n in [n for n in src.namelist() if n.endswith('-bu.dat')][:5]:
            dst.writestr(n,src.read(n))
            image=n.replace('-bu.dat','-imgbu.dat');dst.writestr(image,src.read(image))
    return path


@pytest.mark.integration
def test_interrupt_resume_is_idempotent(small_project):
    p=sample_zip(small_project)
    row={'uf':'RR','path':str(p)}
    checked=pipeline.validation(row)
    partial=pipeline.ingest(row,checked,stop_after_batches=1)
    assert partial['processed_bu']==2 and not partial['complete']
    resumed=pipeline.ingest(row,checked)
    assert resumed['complete'] and resumed['processed_bu']==5
    totals=pipeline.totals([resumed])
    assert sum(x['secoes'] for x in totals['electorate_by_uf'])==5
    again=pipeline.ingest(row,checked)
    assert again==resumed
    assert pipeline.totals([again])==totals


@pytest.mark.integration
def test_corrupted_output_prevents_resume(small_project):
    p=sample_zip(small_project);row={'uf':'RR','path':str(p)}
    checked=pipeline.validation(row);state=pipeline.ingest(row,checked,stop_after_batches=1)
    Path(state['batches'][0]['votos']['path']).write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='changed'):pipeline.ingest(row,checked)


@pytest.mark.integration
def test_input_change_after_validation_rejected(small_project):
    p=sample_zip(small_project);row={'uf':'RR','path':str(p)}
    checked=pipeline.validation(row)
    with p.open('ab') as f:f.write(b'changed')
    with pytest.raises(ValueError,match='input changed'):pipeline.ingest(row,checked)


def test_truncated_zip_and_duplicate_members(small_project):
    p=small_project/'truncated.zip';p.write_bytes(b'PK\x03\x04not complete')
    assert inspect_archive(p)['zip_directory']=='unreadable'
    with zipfile.ZipFile(p,'w') as z:
        z.writestr('x',b'1');z.writestr('x',b'2')
    with pytest.raises(ValueError,match='duplicate'):pipeline.validation({'uf':'RR','path':str(p)})
