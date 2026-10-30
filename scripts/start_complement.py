"""Launch the tested complement pipeline as an independent systemd user service."""
from __future__ import annotations
import json,os,subprocess,sys
from pathlib import Path
from auditoria_urnas.common import root,now,atomic_json,signature
from auditoria_urnas.complement import complement_signature

base=root();version=complement_signature()
gate=json.loads((base/'output/complementar/pilot/gate.json').read_text())
tests=json.loads((base/'output/reports/tests.json').read_text())
if not gate.get('passed') or gate['signature']!=version or gate.get('workers')!=4:raise SystemExit('current pilot required')
if tests.get('exit_code')!=0 or tests['parser_signature']!=signature():raise SystemExit('current tests required')
stamp=now().split('.')[0].replace(':','').replace('-','').replace('T','-')
unit='auditoria-complementar-'+stamp
log=base/'output/logs'/f'{unit}.jsonl';log.parent.mkdir(exist_ok=True)
args=['systemd-run','--user','--unit='+unit,'--working-directory='+str(base),'--property=Nice=10',
      '--property=MemoryMax=20G','--property=TimeoutStopSec=90','--property=StandardOutput=append:'+str(log),'--property=StandardError=inherit',
      '/usr/bin/env','URNAS_PROJECT_ROOT='+str(base),'TMPDIR='+str(base/'data/tmp'),
      'UV_CACHE_DIR='+str(base/'data/cache/uv'),'PYTHONDONTWRITEBYTECODE=1','OPENBLAS_NUM_THREADS=1','OMP_NUM_THREADS=1','MKL_NUM_THREADS=1','NUMEXPR_NUM_THREADS=1',
      str(base/'.venv/bin/python'),'-m','auditoria_urnas.cli','processar-complementar','--simulacoes','1000','--workers','4']
result=subprocess.run(args,capture_output=True,text=True)
record={'unit':unit+'.service','log':str(log),'signature':version,'started_utc':now(),'launch_exit_code':result.returncode,
        'output':result.stdout+result.stderr,'command':args,'automatic_notifications':False,'workers':4,'gpu_used':False}
atomic_json(base/'output/complementar/launch.json',record)
print(json.dumps(record,ensure_ascii=False,indent=2))
raise SystemExit(result.returncode)
