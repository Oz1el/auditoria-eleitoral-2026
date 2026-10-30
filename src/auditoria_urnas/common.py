"""Paths, immutable provenance, and atomic publication."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

UFS = 'AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO ZZ'.split()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def root() -> Path:
    return Path(os.environ.get('URNAS_PROJECT_ROOT', Path(__file__).resolve().parents[2])).resolve()


def original_dir() -> Path:
    return Path(os.environ.get('URNAS_INPUT_DIR', root() / 'data/raw/transmitidos')).resolve()


def prepare_directories() -> None:
    """Create only local runtime directories, including on a clean checkout."""
    for name in ['data/catalog', 'data/checkpoints', 'data/derived', 'data/tmp',
                 'data/cache/uv', 'output/reports', 'output/logs']:
        (root() / name).mkdir(parents=True, exist_ok=True)


def evidence_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root() / path


def emit(event: str, **data) -> None:
    print(json.dumps({'time_utc': now(), 'event': event, **data}, ensure_ascii=False), flush=True)


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.part')
    with tmp.open('w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def digest(path: Path, algorithm='sha256') -> str:
    h = hashlib.new(algorithm)
    with path.open('rb') as f:
        while block := f.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def signature() -> str:
    h = hashlib.sha256()
    paths = sorted((root() / 'src').rglob('*.py')) + sorted((root() / 'specs').glob('*.asn1'))
    paths += sorted((root() / 'scripts').glob('*.py')) + sorted((root() / 'scripts').glob('*.sh'))
    paths += sorted((root() / 'tests').glob('*.py'))
    paths += [root() / 'uv.lock', root() / 'pyproject.toml']
    if (root() / 'config/timezones.json').exists():
        paths.append(root() / 'config/timezones.json')
    for p in paths:
        h.update(str(p.relative_to(root())).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def stat_key(path: Path) -> tuple[int, int, int, int]:
    s = path.stat()
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns


def command(args: list[str]) -> str:
    p = subprocess.run(args, capture_output=True, text=True, timeout=20)
    return (p.stdout + p.stderr).strip()
