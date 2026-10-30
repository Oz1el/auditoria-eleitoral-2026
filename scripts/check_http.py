"""Exercise the real Python HTTP client against the local Postman simulation."""
import hashlib
import json
import urllib.error
import uuid
import zipfile
from auditoria_urnas.common import atomic_json, root, signature, now
from auditoria_urnas.network import small, head, request, download

base='http://127.0.0.1:4517/tse'
checks=[]
for mode in ['normal','500','429']:
    payload=json.loads(small(base+'/api/3/action/package_show?mode='+mode))
    assert payload['success'] is True and isinstance(payload['result']['resources'],list)
    checks.append('metadata_'+mode)
try:
    with request(base+'/api/3/action/package_show?mode=always500',attempts=2):pass
    raise AssertionError('persistent failure was swallowed')
except urllib.error.HTTPError as error:
    assert error.code==500
    checks.append('bounded_retry_failure')
try:
    small(base+'/api/3/action/package_show?mode=normal',cap=1)
    raise AssertionError('metadata cap ignored')
except ValueError:
    checks.append('bounded_metadata')
folder=root()/'data/tmp'/('http-test-'+uuid.uuid4().hex)
folder.mkdir()
url=base+'/archive.zip'
reference=small(url)
sha=hashlib.sha512(reference).hexdigest()
for mode in ['fresh','resume','ignore_range','changed_etag']:
    u=url+('?ignore_range=1' if mode=='ignore_range' else '')
    target=folder/(mode+'.zip')
    if mode!='fresh':
        target.with_name(target.name+'.part').write_bytes(reference[:20])
        atomic_json(target.with_name(target.name+'.part.json'),{'url':u,'etag':'"old"' if mode=='changed_etag' else '"fixture-v1"'})
    result=download(u,target,len(reference),sha)
    assert target.read_bytes()==reference and result['official_hash']=='matched'
    with zipfile.ZipFile(target) as z:assert z.read('fixture.txt')==b'synthetic transport fixture'
    checks.append('download_'+mode)
bad=folder/'bad-hash.zip'
try:
    download(url,bad,len(reference),'0'*128)
    raise AssertionError('hash mismatch accepted')
except ValueError:
    assert not bad.exists()
    checks.append('hash_mismatch_not_published')
try:
    download(url,folder/'fresh.zip',len(reference),sha)
    raise AssertionError('original overwritten')
except FileExistsError:
    assert (folder/'fresh.zip').read_bytes()==reference
    checks.append('no_overwrite')
result={'passed':True,'checks':checks,'environment':'local Postman simulation; synthetic bytes only',
        'real_provider_guarantees':'not inferred from simulation', 'parser_signature':signature(),'finished_utc':now()}
atomic_json(root()/'output/reports/http-tests.json',result)
print(json.dumps(result,indent=2))
