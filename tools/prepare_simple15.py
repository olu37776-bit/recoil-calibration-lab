"""Prepare exact verified source objects only; never update repository refs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import urllib.request
import zlib

REPO = 'olu37776-bit/recoil-calibration-lab'
BASE = '0930d7ab893599a4df0f8f542531986a075a5e0f'
TREE = '9d1f3c27e73eeefad5a0ab8f46af37378c509d2f'
EXPECTED = '8e02713d2504e5f2f4aed284ccea31c501980dc1'
ALLOWED = {'src/recoil_lab/simple_panel.py', 'src/recoil_lab/simple_panel_model.py', 'src/recoil_lab/simple_panel_selftest.py', 'tests/test_simple_panel.py', 'src/recoil_lab/simple_app.py', 'src/recoil_lab/simple_core.py', 'tools/build_simple.py', '.github/workflows/simple.yml', 'docs/CURRENT.md', 'docs/SIMPLE_MODE.md', 'docs/SIMPLE_15_PLAN.md', 'docs/SIMPLE_15_VERIFICATION.json'}
assert os.environ['GITHUB_REPOSITORY'] == REPO
parts = sorted(Path('tools/simple15-payload').glob('*.txt'))
assert len(parts) == 18
encoded = ''.join(p.read_text(encoding='utf-8').strip() for p in parts)
payload = json.loads(zlib.decompress(base64.b64decode(encoded, validate=True)))
assert payload['base_commit'] == BASE and payload['base_tree'] == TREE
assert payload['expected_tree'] == EXPECTED
assert len(payload['files']) == len(ALLOWED)
assert {f['path'] for f in payload['files']} == ALLOWED

def api(endpoint, data):
    assert endpoint in {'git/blobs', 'git/trees'}
    request = urllib.request.Request('https://api.github.com/repos/' + REPO + '/' + endpoint,
        data=json.dumps(data).encode('utf-8'), method='POST', headers={
        'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
        'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
        'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)

entries = []
for item in payload['files']:
    path = Path(item['path'])
    if item['old_sha256'] is None:
        assert not path.exists(), 'Unexpected existing new file: ' + str(path)
        text = ''
    else:
        text = path.read_text(encoding='utf-8')
        assert hashlib.sha256(text.encode()).hexdigest() == item['old_sha256'], str(path)
    lines = text.splitlines(keepends=True)
    previous = len(lines) + 1
    for hunk in reversed(item['hunks']):
        start, end = hunk['start'], hunk['end']
        assert 0 <= start <= end <= len(lines) and end < previous
        previous = start
        lines[start:end] = [hunk['text']]
    result = ''.join(lines).encode('utf-8')
    assert hashlib.sha256(result).hexdigest() == item['sha256'], str(path)
    blob_sha = hashlib.sha1(b'blob ' + str(len(result)).encode() + b'\0' + result).hexdigest()
    assert blob_sha == item['blob_sha'], str(path)
    uploaded = api('git/blobs', {'content': result.decode('utf-8'), 'encoding': 'utf-8'})
    assert uploaded['sha'] == blob_sha, str(path)
    entries.append({'path': str(path), 'mode': '100644', 'type': 'blob', 'sha': blob_sha})
    print('SOURCE_OK', path, blob_sha, flush=True)
result = api('git/trees', {'base_tree': TREE, 'tree': entries})
assert result['sha'] == EXPECTED, result['sha']
Path('runs').mkdir(exist_ok=True)
Path('runs/source-objects.json').write_text(json.dumps({'base': BASE, 'tree': result['sha'], 'files': entries, 'refs_updated': False}, indent=2), encoding='utf-8')
print('TREE_READY', result['sha'], flush=True)
