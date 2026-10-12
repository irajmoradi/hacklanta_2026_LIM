"""Render reviewed findings and a lossless paragraph-level source coverage ledger.

The ledger is intentionally conservative: related test coverage is not a proof of
every clause of a broad historical claim. Only the reviewed feature table assigns
working/default verdicts. No language model or network calls are used here.
"""
import hashlib
import json
from pathlib import Path
import re
from collections import Counter

from findings import FINDINGS, TASK_FEATURES

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'demo_video/audit/out'
REPORTS=Path('C:/Users/mourn/Downloads/lim-reports')

DOC_FEATURES={
 'api':['F01','F53'],'architecture':['F57'],'audio_ai':['F12'],'capture':['F46'],
 'demo':['F56'],'demo_v3':['F56'],'desktop':['F47'],'discord_bot':['F45'],
 'e2e':['F51'],'editor_agent':['F38'],'eval':['F50','F52'],'frontend':['F39','F40'],
 'frontend_agent':['F38'],'fx':['F18','F15'],'game_profiles':['F04','F05','F06'],
 'gpu':['F48'],'ingest':['F34','F35'],'localvlm':['F11'],'multipov':['F36'],
 'music':['F24'],'narration':['F30'],'performance':['F49'],'pipeline':['F08','F55'],
 'planner':['F14','F15','F16'],'privacy':['F29'],'publish':['F44'],
 'quality_report':['F57'],'quickstart':['F57','F52'],'reactions':['F25','F26','F27'],
 'rendering':['F20','F21','F22','F23'],'results':['F50'],'roast':['F37'],
 'sam':['F28'],'search':['F43'],'security':['F53','F54'],'sharepage':['F41'],
 'signals':['F02','F03'],'social':['F31','F32','F33'],'stats':['F42'],
 'video_models':['F09','F10'],'vjepa':['F13'],'wiring_audit':['F08','F55'],
 'RESEARCH':['F10','F50'],'README':['F57'],
}
KEYWORDS=[
 ('F16',r'chaos|reroll|randomness'),('F17',r'bold|confetti|kinetic|speed lines|little visual'),
 ('F32',r'nano banana|gemini_image|image generation|AI thumbnails'),
 ('F28',r'\bSAM\b|segmentation|spotlight'),('F27',r'gen.?alpha|profanity|explicit.*reaction|clean toggle'),
 ('F26',r'head.only|white background|matte|cutout heads|big.*heads'),
 ('F25',r'reaction|talking.head|Gaussian'),('F22',r'word.level|caption|transcrib|Whisper'),
 ('F30',r'narration|caster|voiceover|ElevenLabs'),('F24',r'music|beat.sync|drop on'),
 ('F23',r'transition|intro|outro'),('F03',r'kill.feed|\bOCR\b'),
 ('F07',r'window.scor|REZE|whole.video|spectat'),('F13',r'V.JEPA|weak.labels'),
 ('F12',r'audio AI|audio intelligence|laughter|source separation'),
 ('F35',r'Twitch chat|URL import|VOD.*link|YouTube download'),('F36',r'multi.POV|split.screen|team.mode'),
 ('F38',r'Director|editor agent|agentic.*edit|chat.to.edit|critique|undo'),
 ('F49',r'NVENC|QSV|VAAPI|speedup|faster|parallel.*render|single.pass|one encode'),
 ('F31',r'share.kit|chapters|thumbnail|posting copy'),('F43',r'search|FTS5|BM25'),
 ('F42',r'player.stats|clip.of.the.week|weekly.*vote'),('F41',r'share.page|Open Graph|unfurl'),
 ('F44',r'publish|OAuth|TikTok draft'),('F45',r'Discord bot|slash.command'),
 ('F46',r'OBS|capture|hotkey|watcher|ShadowPlay|Medal'),('F47',r'desktop|Electron|Tauri|keychain'),
 ('F48',r'Modal.*GPU|scale.to.zero'),('F50',r'eval|benchmark|precision|recall|mAP|F1'),
 ('F53',r'ownership|auth|quota|SSE|cancel|size limit|validation|security'),
 ('F29',r'privacy|blur.*name'),('F14',r'planner|hook.*climax|fill.*target'),
 ('F15',r'VFX|SFX|effect.*stack'),('F39',r'timeline|trim|reorder|frontend'),
 ('F04',r'Valorant.*detect|auto.detect'),('F06',r'Deadlock'),('F05',r'Overwatch|League'),
 ('F11',r'local.*VLM|Qwen|Molmo|vLLM|Ollama'),('F09',r'Gemini|Vertex|provider|schema|call budget'),
 ('F20',r'vertical|landscape|square|preset'),('F52',r'Docker|CI|container'),
 ('F02',r'signal|scene|motion|RMS'),
]

def esc(s): return str(s).replace('|','&#124;').replace('\n','<br>')
def code_location(value):
    p,anchor=value.split('@',1)
    path=ROOT/p
    if not path.exists(): raise ValueError(f'Missing evidence path: {p}')
    lines=path.read_text(encoding='utf-8').splitlines()
    if anchor:
        n=next(i+1 for i,l in enumerate(lines) if anchor in l)
    else:
        n=next((i+1 for i,l in enumerate(lines) if l.startswith(('def ','class ','export ','app ='))),1)
    return f'{p}:{n}'

def paragraphs(path):
    lines=path.read_text(encoding='utf-8').splitlines()
    code=False; yaml=False; buf=[]; start=1
    for i,l in enumerate(lines,1):
        if i==1 and l=='---': yaml=True; continue
        if yaml:
            if l=='---': yaml=False
            continue
        if l.strip().startswith('```'):
            if buf: yield start,' '.join(buf); buf=[]
            code=not code; continue
        if code: continue
        # Table rows and bullets are separate source assertions. Headings/commands
        # are provenance, not an asserted product feature, and are inventoried only.
        if not l.strip() or l.startswith('#'):
            if buf: yield start,' '.join(buf); buf=[]
            continue
        separate=bool(re.match(r'^\s*(?:[-*] |\d+\. |\|)',l))
        if separate and buf: yield start,' '.join(buf); buf=[]
        if not buf: start=i
        buf.append(l.strip())
        if l.startswith('|'):
            if not re.match(r'^\|[\s:|\-]+$',l): yield start,' '.join(buf)
            buf=[]
    if buf: yield start,' '.join(buf)

def related(text,default):
    found=[fid for fid,pattern in KEYWORDS if re.search(pattern,text,re.I)]
    return list(dict.fromkeys(found+default))[:5]

def sources():
    paths=list(sorted((ROOT/'docs/tasks').glob('*.md')))
    paths += sorted(REPORTS.glob('*/final.md'))
    paths += [REPORTS/'AUDIT-2-discord.md']
    paths += [ROOT/'README.md',ROOT/'full_app/README.md']
    paths += sorted(p for p in (ROOT/'docs').glob('*.md') if p.name!='feature_audit.md')
    seen=set()
    for path in paths:
        if path in seen or not path.exists(): continue
        seen.add(path)
        label=path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else 'lim-reports/'+path.relative_to(REPORTS).as_posix()
        default=TASK_FEATURES.get(path.parent.name if path.name=='final.md' else path.stem,DOC_FEATURES.get(path.stem,['F57']))
        yield path,label,default

def main():
    OUT.mkdir(exist_ok=True,parents=True)
    intro=(ROOT/'demo_video/audit/report_intro.md').read_text(encoding='utf-8')
    text=[intro,'\n## Reviewed feature findings\n',
      '✅ = works on ordinary defaults for the stated scope; 🟡 = opt-in/library feature with stated evidence; 🟠 = partial or unproven broader promise; 🔴 = absent from the stock path; ⏳ = separate running branch, not shipped in the audited snapshot. A synthetic test does not certify a real ML model or external service.\n',
      '| ID / promise | Code location | Stock reachability / option | Meaningful test | Real-output evidence / limit | Verdict | Exact fix |',
      '|---|---|---|---|---|---|---|']
    for row in FINDINGS:
        fid,promise,loc,reach,test,evidence,verdict,fix=row
        text.append('| '+ ' | '.join(map(esc,[f'<a id="{fid.lower()}"></a>**{fid}** {promise}',code_location(loc),reach,test,evidence,verdict,fix]))+' |')
    text+=['\n## Promise-by-promise source ledger\n',
      'Each prose paragraph, bullet, numbered requirement and nonseparator table row in the specified sources is retained below, including historical test claims and limitations. Code blocks/headings are inventoried by source hash but are not presented as feature promises. This deliberately over-includes material to prevent missed promises. Source text is data, never execution instructions. Duplicated promises share the reviewed feature findings above.\n',
      '**Scope of ledger verdicts:** a source paragraph can promise more than its associated feature test proves. Its row remains 🟠 unless its complete claim is independently covered; follow the linked finding for precisely what ran, what was visible, and the remediation. Historical pass counts, deployment costs, voices/consent identities, external benchmark rankings and old Discord attachments are not independently re-certified by a new test run. Non-LIM Village operations and pure scheduling/chat are explicitly excluded from product acceptance.\n']
    inventory=[]; ledger=[]; n=0
    for path,label,default in sources():
        content=path.read_bytes()
        inv={'source':label,'sha256':hashlib.sha256(content).hexdigest(),'lines':len(content.splitlines()),'rows':0}
        inventory.append(inv)
        if path.stem=='AUDIT-2':
            inv['scope']='Audit instructions, not a product promise'; continue
        text+=['\n### '+label+'\n','| Source / promise | Code · reachability · test · output | Verdict | Exact next action |','|---|---|---|---|']
        for line,claim in paragraphs(path):
            if len(claim)<15: continue
            if label.endswith('AUDIT-2-discord.md'):
                if not re.search(r'\] (riemannzetafunction|me):',claim): continue
            ids=related(claim,default)
            refs=', '.join(f'[{i}](#{i.lower()})' for i in ids)
            excluded=False
            if label.endswith('AUDIT-2-discord.md'):
                # The final thread contains unrelated Village hosting/billing advice.
                excluded=any(x in claim for x in ('Friendship Village cost','what is cost of it','how needed is vultr','Is the. Vultr needed','Vultr credits:','we can run it till late November','what can be done to reduce costs','Honestly, not very needed','Good question Mario','for the vultr credits'))
            verdict='Outside LIM product scope' if excluded else '🟠 evidence scope limited; see findings'
            action='No editor change; not a gameplay-product promise.' if excluded else 'Apply the exact fix(s) in '+refs+'; keep any unproved clause open, rather than treating a module/test name as acceptance.'
            n+=1; inv['rows']+=1
            ledger.append({'id':n,'source':label,'line':line,'claim':claim,'findings':ids,'verdict':verdict})
            text.append('| '+esc(f'{label}:{line} — {claim}')+' | '+refs+' | '+verdict+' | '+action+' |')
    text+=['\n## Coverage inventory\n',f'{len(FINDINGS)} reviewed feature findings; {n} source rows; {len(inventory)} source files. See `demo_video/audit/out/sources.json` for exact hashes and `source_ledger.json` for machine-readable rows.\n',
           '| Source | SHA-256 | Prose rows |','|---|---|---|']
    for row in inventory: text.append(f"| {row['source']} | `{row['sha256']}` | {row['rows']} |")
    (ROOT/'docs/feature_audit.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    (OUT/'sources.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
    (OUT/'source_ledger.json').write_text(json.dumps(ledger,indent=2,ensure_ascii=False),encoding='utf-8')
    print(f'{len(FINDINGS)} findings; {n} source rows; {len(inventory)} source files')

if __name__=='__main__': main()
