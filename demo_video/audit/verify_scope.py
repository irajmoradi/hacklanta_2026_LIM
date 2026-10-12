"""Check scope and secret absence; emit neither key nor matching content."""
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
paths=subprocess.check_output(['git','diff','--name-only','8db1f6d'],cwd=ROOT,text=True).splitlines()
paths+=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines()
for name in set(paths):
    assert name=='docs/feature_audit.md' or name.startswith('demo_video/audit/'),name
    assert not name.startswith('demo_video/audit/out/'),name
env=Path('C:/Users/mourn/Downloads/hacklanta/.env').read_text(encoding='utf-8')
match=re.search(r'^GOOGLE_API_KEY\s*=\s*[\"\']?([^\r\n\"\']+)',env,re.M)
assert match,'Runtime key missing for nonprinting secret check'
key=match.group(1).strip().encode()
assert len(key)>20
candidates=[ROOT/name for name in set(paths)]
candidates += [p for p in (ROOT/'demo_video/audit/out').rglob('*') if p.suffix in ('.json','.log','.txt','.md','.srt')]
for path in candidates:
    if path.is_file(): assert key not in path.read_bytes(),f'Secret found in {path.name}'
print(f'Scope and nonprinting secret check passed: {len(set(paths))} changed files; {len(candidates)} text artifacts checked')
