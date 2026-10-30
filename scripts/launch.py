"""Detach the approved local batch only after checks for the exact source version."""
import json
import os
from pathlib import Path
import subprocess
import tarfile
from datetime import datetime, timezone

from auditoria_urnas.common import atomic_json, root, signature

project=root()
code=signature()
pilot=json.loads((project/'output/reports/pilot.json').read_text())
tests=json.loads((project/'output/reports/tests.json').read_text())
if not pilot.get('passed') or pilot.get('parser_signature')!=code:
    raise SystemExit('Pilot must pass for the current source version.')
if tests.get('exit_code')!=0 or tests.get('parser_signature')!=code:
    raise SystemExit('Automated tests must pass for the current source version.')
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
unit=f'auditoria-urnas-{stamp}'
log=project/'output/logs'/f'{unit}.jsonl'
archive=project/'output/reports'/f'source-{code[:16]}.tar.gz'
if not archive.exists():
    with tarfile.open(archive,'w:gz') as tar:
        for directory in ['src','scripts','tests','docs','specs','config','postman']:
            if (project/directory).exists():
                tar.add(project/directory,arcname=directory,filter=lambda info:None if '__pycache__' in info.name else info)
        for name in ['pyproject.toml','uv.lock','README.md','.env.example','.gitignore']:
            if (project/name).exists():tar.add(project/name,arcname=name)
args=[str(project/'.venv/bin/python'),'-m','auditoria_urnas.cli','processar']
env={**os.environ,'URNAS_PROJECT_ROOT':str(project),'UV_CACHE_DIR':str(project/'data/cache/uv'),
     'TMPDIR':str(project/'data/tmp'),'PYTHONDONTWRITEBYTECODE':'1'}
systemd=['systemd-run','--user',f'--unit={unit}',f'--working-directory={project}',
         '--property=Nice=10','--property=MemoryMax=12G','--property=IOSchedulingPriority=7',
         f'--property=StandardOutput=append:{log}',f'--property=StandardError=append:{log}',
         *[f'--setenv={k}={env[k]}' for k in ['URNAS_PROJECT_ROOT','UV_CACHE_DIR','TMPDIR','PYTHONDONTWRITEBYTECODE']],*args]
r=subprocess.run(systemd,capture_output=True,text=True)
if r.returncode==0:
    status=subprocess.run(['systemctl','--user','show',unit,'--property=ActiveState,SubState,MainPID,Result'],capture_output=True,text=True)
    info={'method':'systemd-user','unit':unit,'log':str(log),'source_archive':str(archive),
          'parser_signature':code,'launch_response':r.stdout+r.stderr,'initial_state':status.stdout}
    if 'ActiveState=failed' in status.stdout:
        atomic_json(project/'output/reports/launch.json',info)
        raise SystemExit('Service failed at startup; inspect launch.json and log.')
else:
    # Only fall back when no unit has been created (e.g. unavailable user bus).
    with log.open('ab') as stream:
        p=subprocess.Popen(args,cwd=project,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,start_new_session=True)
    os.kill(p.pid,0)
    info={'method':'detached-process','pid':p.pid,'log':str(log),'source_archive':str(archive),
          'parser_signature':code,'systemd_unavailable':r.stdout+r.stderr}
atomic_json(project/'output/reports/launch.json',info)
print(json.dumps(info,ensure_ascii=False,indent=2))
