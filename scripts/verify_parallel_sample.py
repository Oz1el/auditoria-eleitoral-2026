"""Validate the production four-process executor against all 2,048 frozen results."""
from __future__ import annotations
import hashlib,json,time
from pathlib import Path
from auditoria_urnas.common import root,digest,atomic_json,now
from auditoria_urnas.complement import complement_signature
from auditoria_urnas.complement_workers import parallel_sections,worker_cpus


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,required=True)
    folder=parser.parse_args().folder
    manifest=json.loads((folder/'manifest.json').read_text())
    if digest(folder/'amostra.zip')!=manifest['archive_sha256'] or digest(folder/'rows.json')!=manifest['rows_sha256']:
        raise ValueError('frozen benchmark changed')
    rows=json.loads((folder/'rows.json').read_text())
    reference=json.loads((folder/'cpu1-r1.hashes.json').read_text())
    reference_digest=hashlib.sha256(json.dumps(reference,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    benchmark=json.loads((folder/'status.json').read_text())
    preserved=next(t for t in benchmark['trials'] if t['mode']=='cpu1' and t['repeat']==1)
    if benchmark['status']!='complete' or reference_digest!=preserved['result_digest']:raise ValueError('preserved CPU reference changed')
    version=complement_signature();start=time.monotonic();observed={}
    for result in parallel_sections(rows,folder/'amostra.zip',['rdv','logs','assinaturas'],workers=4):
        key=result['bu_id']
        if key in observed:raise ValueError('duplicate section result')
        observed[key]=hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if complement_signature()!=version:raise ValueError('code changed during verification')
    differences=[key for key in observed.keys()|reference.keys() if observed.get(key)!=reference.get(key)]
    value={'passed':not differences,'signature':version,'workers':4,'physical_cpu_ids':worker_cpus(4),'sections':len(observed),
           'input_sha256':manifest['archive_sha256'],'reference':str(folder/'cpu1-r1.hashes.json'),
           'reference_sha256':digest(folder/'cpu1-r1.hashes.json'),'different_sections':differences,
           'elapsed_seconds':time.monotonic()-start,'finished_utc':now()}
    atomic_json(root()/'output/complementar/parallel-validation.json',value)
    print(json.dumps(value,ensure_ascii=False,indent=2))
    if differences:raise ValueError('production executor differs from CPU reference')


if __name__=='__main__':main()
