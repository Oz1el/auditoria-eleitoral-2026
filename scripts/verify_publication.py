"""Verify the preserved PDF and the exact published evidence bytes, offline."""
import csv
import hashlib
import json
from pathlib import Path

base=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
edition=json.loads((base/'reports/manifesto-da-edicao.json').read_text())
if sha(base/edition['publication_pdf'])!=edition['pdf_sha256']:
    raise SystemExit('Publication PDF hash differs')
for item in json.loads((base/'reports/evidence/index.json').read_text()):
    if sha(base/item['publication_path'])!=item['publication_sha256']:
        raise SystemExit('Published evidence hash differs: '+item['publication_path'])
rows=list(csv.DictReader((base/'reports/indice-de-cobertura.csv').open()))
if len(rows)!=len({r['id'] for r in rows}):raise SystemExit('Duplicate coverage IDs')
covered={r['id'] for r in rows}
if not set(edition['covered_matrix_ids']).issubset(covered):raise SystemExit('Missing matrix IDs')
print('Publication PDF, published evidence hashes and claim coverage verified; no electoral processing run.')
