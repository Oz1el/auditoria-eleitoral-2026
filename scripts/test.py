"""Run tests and record the exact parser version eligible for launching."""
import os
import subprocess
import sys
from auditoria_urnas.common import atomic_json, now, root, signature

(root()/'output/reports').mkdir(parents=True,exist_ok=True)
with (root()/'output/reports/pytest.txt').open('w') as log:
    result=subprocess.run([sys.executable,'-m','pytest','-q','--disable-warnings','--junitxml=output/reports/pytest.xml'],
                          cwd=root(),stdout=log,stderr=subprocess.STDOUT)
atomic_json(root()/'output/reports/tests.json',{'exit_code':result.returncode,'parser_signature':signature(),'finished_utc':now()})
print((root()/'output/reports/pytest.txt').read_text())
raise SystemExit(result.returncode)
