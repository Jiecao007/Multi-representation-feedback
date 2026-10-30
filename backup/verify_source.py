"""Verify copied source bytes before changing a restored working copy."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'backup/source_manifest.json').read_text())
failures = []
for name, expected in manifest['files'].items():
    path = root / name
    if not path.is_file():
        failures.append(name + ': missing')
        continue
    data = path.read_bytes()
    if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
        failures.append(name + ': changed')
if failures:
    raise SystemExit('\n'.join(failures))
print('Verified ' + str(len(manifest['files'])) + ' byte-identical source files.')
