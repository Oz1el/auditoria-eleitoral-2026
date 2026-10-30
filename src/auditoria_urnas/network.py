"""Bounded HTTP reads and resumable downloads; never changes existing originals."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .common import atomic_json, now


def request(url, *, method='GET', headers=None, attempts=4, timeout=45):
    for attempt in range(attempts):
        try:
            return urllib.request.urlopen(urllib.request.Request(
                url, method=method, headers={'User-Agent': 'auditoria-urnas/0.1 public research', **(headers or {})}), timeout=timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt == attempts - 1:
                raise
            retry = e.headers.get('Retry-After') if isinstance(e, urllib.error.HTTPError) else None
            time.sleep(min(30, int(retry) if retry and retry.isdigit() else 2 ** attempt))


def small(url: str, cap=5_000_000) -> bytes:
    with request(url) as r:
        b = r.read(cap + 1)
        if len(b) > cap:
            raise ValueError(f'metadata/sample limit exceeded: {url}')
        return b


def head(url: str) -> dict:
    with request(url, method='HEAD') as r:
        return {'url': url, 'queried_utc': now(), 'status': r.status,
                **{k.lower(): r.headers.get(k) for k in ['Content-Length', 'Last-Modified', 'ETag', 'Accept-Ranges', 'Content-Type']}}


def download(url: str, destination: Path, expected_size: int, sha512: str | None = None) -> dict:
    """Resume only our own partial with a matching strong ETag; publish after checks."""
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + '.part')
    checkpoint = partial.with_name(partial.name + '.json')
    remote = head(url)
    if int(remote['content-length'] or 0) != expected_size:
        raise ValueError('remote size changed since approved download plan')
    old = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    offset = partial.stat().st_size if partial.exists() else 0
    etag = remote.get('etag')
    can_resume = bool(offset and offset < expected_size and etag and not etag.startswith('W/')
                      and old.get('etag') == etag and old.get('url') == url)
    headers = {'Range': f'bytes={offset}-', 'If-Range': etag} if can_resume else {}
    with request(url, headers=headers) as response:
        append = can_resume and response.status == 206
        if append and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
            raise ValueError('invalid Content-Range')
        if response.status not in (200, 206) or (response.status == 206 and not append):
            raise ValueError('unexpected response status')
        atomic_json(checkpoint, {'url': url, 'etag': etag, 'started_utc': now()})
        with partial.open('ab' if append else 'wb') as f:
            while b := response.read(8 * 1024 * 1024):
                f.write(b)
                if f.tell() > expected_size:
                    raise ValueError('download exceeds approved size')
            f.flush()
            os.fsync(f.fileno())
    if partial.stat().st_size != expected_size:
        raise ValueError('incomplete download; partial preserved for resume')
    h = hashlib.sha256()
    h512 = hashlib.sha512()
    with partial.open('rb') as f:
        while b := f.read(8 * 1024 * 1024):
            h.update(b)
            h512.update(b)
    if sha512 and h512.hexdigest() != sha512.lower():
        raise ValueError('official SHA-512 mismatch; partial preserved')
    import zipfile
    with zipfile.ZipFile(partial) as z:
        if bad := z.testzip():
            raise ValueError(f'ZIP CRC mismatch: {bad}')
    # No overwriting, even if another process published the destination meanwhile.
    os.link(partial, destination)
    partial.unlink()
    result = {'url': url, 'path': str(destination), 'bytes': expected_size, 'sha256': h.hexdigest(),
              'sha512': h512.hexdigest(), 'official_hash': 'matched' if sha512 else 'unavailable',
              'digital_signature': 'not_verified', 'completed_utc': now(), 'http': remote}
    atomic_json(destination.with_name(destination.name + '.provenance.json'), result)
    return result
