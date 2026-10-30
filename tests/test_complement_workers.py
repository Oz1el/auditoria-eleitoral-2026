import copy
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from auditoria_urnas import complement as comp
from auditoria_urnas import complement_resume as resume
from auditoria_urnas.common import root,digest,atomic_json
from auditoria_urnas.complement_workers import ordered_bounded,worker_cpus


def _crash_worker(value):os._exit(23)


def test_bounded_submission_preserves_order_and_cancels_pending_on_close():
    class Future:
        def __init__(self,pool,value):self.pool=pool;self.value=value;self.done=False
        def result(self):self.done=True;self.pool.active-=1;return self.value
        def cancel(self):
            if not self.done:self.pool.active-=1;self.pool.cancelled+=1;self.done=True
    class Pool:
        def __init__(self):self.active=0;self.peak=0;self.cancelled=0
        def submit(self,function,value):
            self.active+=1;self.peak=max(self.peak,self.active);return Future(self,value)
    pool=Pool()
    assert list(ordered_bounded(pool,None,range(21)))==list(range(21))
    assert pool.peak==8 and pool.active==0
    pool=Pool();iterator=ordered_bounded(pool,None,range(50))
    assert next(iterator)==0
    iterator.close()
    assert pool.cancelled==7 and pool.active==0


def test_abrupt_worker_failure_is_propagated_and_not_a_successful_empty_batch():
    with ProcessPoolExecutor(max_workers=2,mp_context=mp.get_context('spawn')) as pool:
        with pytest.raises(BrokenProcessPool):list(ordered_bounded(pool,_crash_worker,[1,2,3]))


def copy_project(destination):
    real=root()
    for directory in ['src','specs','scripts','tests','docs','config']:
        if (real/directory).exists():shutil.copytree(real/directory,destination/directory)
    for filename in ['uv.lock','pyproject.toml']:shutil.copy(real/filename,destination/filename)
    return real


@pytest.mark.integration
@pytest.mark.parametrize('workers',[1,2,4])
def test_parallel_checkpoint_interrupt_resume_has_exact_order_and_no_duplicate(tmp_path,monkeypatch,workers):
    base=comp.base_data();source=comp.state_sources(['RR'])['RR']
    rows=comp.section_rows(base,'RR')[:5]
    copy_project(tmp_path);monkeypatch.setenv('URNAS_PROJECT_ROOT',str(tmp_path));monkeypatch.setattr(comp,'BATCH',2)
    table=tmp_path/'sections.parquet';pq.write_table(pa.Table.from_pylist(rows),table)
    base={**base,'sections':str(table),'sha256':digest(table)};version=comp.complement_signature()
    def stop(state):
        if state['session_processed']==2:raise KeyboardInterrupt('safe checkpoint stop')
    with pytest.raises(KeyboardInterrupt):comp.process_state('RR',base,source,['rdv'],version,stop,workers=workers)
    state,_=comp.process_state('RR',base,source,['rdv'],version,lambda s:None,workers=workers)
    result=pq.read_table([b['path'] for b in state['batches']]).to_pylist()
    assert [r['bu_id'] for r in result]==[r['bu_id'] for r in rows]
    assert all(r['rdv_concorda_bu'] for r in result)
    assert state['reused_sections']==2 and state['session_processed']==3
    assert state['session_elapsed_seconds']>0 and state['workers']==workers


def synthetic_legacy(tmp_path,monkeypatch):
    monkeypatch.setattr(resume,'root',lambda:tmp_path)
    monkeypatch.setattr(resume,'compatibility',lambda:{'verified_test_contract':True})
    rows=[{key:value for key,value in zip(resume.IDENTITY,[str(i),'RR',3000,4,i,'dadosSecao',123,100])} for i in range(1,4)]
    path=tmp_path/'old.parquet';pq.write_table(pa.Table.from_pylist(rows[:2]),path)
    base={'sha256':'base','manifest_sha256':'manifest'};source={'sha256':'archive'};stages=['rdv','logs']
    key=hashlib.sha256(json.dumps({'source':'archive','base':'base','code':resume.LEGACY_SIGNATURE,'stages':sorted(stages),'crypto':True,'limit':None},sort_keys=True).encode()).hexdigest()[:24]
    checkpoint=tmp_path/'data/checkpoints/complementar/national'/f'RR-{key}.json'
    state={'uf':'RR','version':resume.LEGACY_SIGNATURE,'source':source,'base':base,'stages':stages,'processed':2,'total':3,
           'status':'running','elapsed_seconds':10,'batches':[{'path':str(path),'sha256':digest(path),'rows':2}]}
    atomic_json(checkpoint,state)
    return rows,base,source,stages,state,checkpoint,path


def test_legacy_import_preserves_original_and_records_provenance(tmp_path,monkeypatch):
    rows,base,source,stages,state,checkpoint,path=synthetic_legacy(tmp_path,monkeypatch)
    before=digest(checkpoint),digest(path)
    value=resume.import_legacy('RR',base,source,stages,'new-version',rows)
    assert value['processed']==2 and value['batches']==state['batches']
    assert value['provenance']['source_checkpoint']==str(checkpoint)
    assert before==(digest(checkpoint),digest(path))


@pytest.mark.parametrize('problem',['hash','order','version','base','stages'])
def test_legacy_import_rejects_invalid_inputs_without_deleting_them(tmp_path,monkeypatch,problem):
    rows,base,source,stages,state,checkpoint,path=synthetic_legacy(tmp_path,monkeypatch)
    if problem=='hash':path.write_bytes(b'altered')
    if problem=='order':
        pq.write_table(pa.Table.from_pylist(list(reversed(rows[:2]))),path);state['batches'][0]['sha256']=digest(path)
    if problem=='version':state['version']='incompatible'
    if problem=='base':state['base']={**base,'manifest_sha256':'different'}
    if problem=='stages':state['stages']=['rdv']
    atomic_json(checkpoint,state);before=digest(checkpoint),digest(path)
    assert resume.import_legacy('RR',base,source,stages,'new-version',rows) is None
    record=json.loads((tmp_path/'data/checkpoints/complementar/migrations/new-version/RR.json').read_text())
    assert record['status']=='rejected' and record['reason']
    assert before==(digest(checkpoint),digest(path))


@pytest.mark.integration
@pytest.mark.parametrize('problem',['parser','dependency'])
def test_compatibility_rejects_changed_parser_and_locked_dependency(tmp_path,monkeypatch,problem):
    real=copy_project(tmp_path)
    legacy=tmp_path/resume.LEGACY_RUN;legacy.mkdir(parents=True)
    shutil.copy(real/resume.LEGACY_RUN/'source-code.tar.gz',legacy/'source-code.tar.gz')
    shutil.copy(real/resume.LEGACY_RUN/'environment.json',legacy/'environment.json')
    if problem=='parser':
        parser=tmp_path/'src/auditoria_urnas/complement_parsers.py';parser.write_text(parser.read_text()+'\n# changed\n')
    else:
        lock=tmp_path/'uv.lock';text=lock.read_text();text=text.replace('name = "numpy"\nversion = "2.5.4"','name = "numpy"\nversion = "0.0.0"');lock.write_text(text)
    monkeypatch.setattr(resume,'root',lambda:tmp_path)
    with pytest.raises(ValueError,match='incompatible'):resume.compatibility()


def test_worker_count_is_validated_before_creating_processes():
    with pytest.raises(ValueError,match='workers'):worker_cpus(3)
