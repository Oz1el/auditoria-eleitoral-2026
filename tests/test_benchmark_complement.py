import json,zipfile
from collections import Counter

import numpy as np
import pytest

from auditoria_urnas.common import original_dir
from auditoria_urnas.benchmark_complement import (
    canonical_hash,finish_histogram,gpu_histograms,rdv_features,select_rows,report,physical_cpus,
)
from auditoria_urnas.complement_parsers import parse_rdv


class ArrayBackend:
    """Exercise batch offset/reconstruction deterministically without CUDA."""
    asarray=staticmethod(np.asarray)
    asnumpy=staticmethod(np.asarray)
    bincount=staticmethod(np.bincount)
    class cuda:
        @staticmethod
        def get_current_stream():
            class Stream:
                def synchronize(self):pass
            return Stream()


def test_sample_is_deterministic_unique_and_includes_manual_empty_cases():
    rows=[{'bu_id':str(i),'origem':'dadosSA' if i<3 else 'dadosSecao','comparecimento':0 if i==4 else 100} for i in range(20)]
    selected=select_rows(rows,10)
    assert selected==select_rows(list(reversed(rows)),10)
    assert len({r['bu_id'] for r in selected})==10
    assert {'0','1','2','4'}<={r['bu_id'] for r in selected}
    with pytest.raises(ValueError,match='too small'):select_rows(rows,2)


@pytest.mark.integration
def test_real_rdv_batched_reduction_matches_reference_including_empty_section():
    with zipfile.ZipFile(original_dir()/'bu_imgbu_logjez_rdv_vscmr_2026_2t_RR.zip') as archive:
        raw=archive.read(next(n for n in archive.namelist() if n.endswith('-rdv.dat')))
    feature=rdv_features(raw,(3000,4,11))
    assert feature['labels']==sorted(feature['labels'])
    empty={'source':feature['source'],'labels':[]}
    result=gpu_histograms([feature,empty,feature],ArrayBackend)
    assert result[0]==parse_rdv(raw,(3000,4,11))==result[2]
    assert result[1]['rdv_total']==0 and result[1]['rdv_tipos_json']=='{}'
    with pytest.raises(ValueError,match='identity'):rdv_features(raw,(3000,4,12))
    with pytest.raises(ValueError,match='trailing'):rdv_features(raw+b'x',(3000,4,11))


def test_histogram_preserves_suspended_blank_null_unknown_nominal_and_enum_one():
    feature={'source':'test','labels':[1,2,10,2,11,2,3,4,5,6,7,8,9]}
    result=gpu_histograms([feature],ArrayBackend)[0]
    assert result['rdv_total']==11 and result['rdv_lula']==1 and result['rdv_bolsonaro']==1
    assert result['rdv_brancos']==2 and result['rdv_nulos']==5 and result['rdv_outros']==2


def test_result_hash_detects_changes_and_is_independent_of_dictionary_order():
    assert canonical_hash({'a':1,'b':2})==canonical_hash({'b':2,'a':1})
    assert canonical_hash({'a':1})!=canonical_hash({'a':2})


def test_report_does_not_recommend_a_fast_but_non_equivalent_backend(tmp_path,monkeypatch):
    import auditoria_urnas.benchmark_complement as module
    monkeypatch.setattr(module,'root',lambda:tmp_path)
    status={'status':'running','sections':10,'repeats':2,'trials':[
        {'mode':mode,'elapsed_seconds':duration,'equivalent_to_cpu1':ok,'peak_process_tree_rss_bytes_sampled':100}
        for mode,duration,ok in [('cpu1',10,True),('cpu1',12,True),('cpu2',6,True),('cpu2',5,True),('gpu4',1,False),('gpu4',1,False)]
    ]}
    report(tmp_path,status)
    assert status['fastest_equivalent_mode']=='cpu2'
    assert 'gpu4' not in [r['mode'] for r in status['comparison']]
    assert (tmp_path/'comparacao.csv').exists()
    assert 'nacional permanece parado' in (tmp_path/'comparacao.md').read_text()


def test_physical_core_selection_does_not_repeat_hyperthreads():
    from pathlib import Path
    cores=[(Path(f'/sys/devices/system/cpu/cpu{i}/topology/core_id').read_text(),Path(f'/sys/devices/system/cpu/cpu{i}/topology/physical_package_id').read_text()) for i in physical_cpus()]
    assert len(cores)==len(set(cores))
