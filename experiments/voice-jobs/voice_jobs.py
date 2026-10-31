#!/usr/bin/env python3
"""Offline-first voice job contract. Mock WAVs are tones, never speech."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import wave

VERSION = 'voice-jobs/0.1'
ID = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
SHA = re.compile(r'^[0-9a-f]{64}$')
EMOTIONS = {'natural', 'happy', 'angry', 'sad', 'afraid', 'disgusted', 'melancholic', 'surprised', 'calm'}

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write_json(path, value):
    # Atomic replacement only inside a newly reserved attempt directory.
    p = Path(path); tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_bytes(canonical(value)); os.replace(tmp, p)

def require(condition, message):
    if not condition:
        raise ValueError(message)

def exact(obj, fields, label):
    require(isinstance(obj, dict) and set(obj) == set(fields), f'{label}: unexpected or missing fields')

def valid_id(value):
    return isinstance(value, str) and bool(ID.fullmatch(value))

def validate(job):
    exact(job, ['schema_version','project_id','job_id','revision','engine','locale','voice_id','consent_id','purpose','content_class','lines'], 'job')
    require(job['schema_version'] == 1 and type(job['schema_version']) is int, 'schema_version must be 1')
    for field in ('project_id','job_id','revision','voice_id','consent_id'):
        require(valid_id(job[field]), f'invalid {field}')
    require(job['engine'] in ('breezyvoice','indextts'), 'unsupported engine')
    require(job['locale'] == 'zh-TW', 'prototype contract supports zh-TW requests only')
    require(job['purpose'] in ('technical_evaluation','production','commercial'), 'invalid purpose')
    require(job['content_class'] in ('public_fixture','private'), 'invalid content class')
    require(isinstance(job['lines'],list) and 1 <= len(job['lines']) <= 100, '1..100 lines required')
    ids = set()
    for line in job['lines']:
        exact(line, ['id','text','emotion','strength'], 'line')
        require(valid_id(line['id']) and line['id'] not in ids, 'invalid or duplicate line id'); ids.add(line['id'])
        require(isinstance(line['text'],str) and 0 < len(line['text'].strip()) <= 1000, 'invalid text')
        require(isinstance(line['emotion'],str) and line['emotion'] in EMOTIONS, 'invalid emotion')
        require(type(line['strength']) in (int,float) and math.isfinite(line['strength']) and 0 <= line['strength'] <= 1, 'invalid strength')
        if job['engine'] == 'breezyvoice':
            require(line['emotion'] == 'natural' and line['strength'] == 0,
                    'BreezyVoice has no verified emotion/strength API; choose natural/0 or an explicitly evaluated separate engine')
    return job

def resolve_voice(job, registry):
    require(isinstance(registry,dict) and isinstance(registry.get('voices'),dict), 'invalid private voice registry')
    voice = registry['voices'].get(job['voice_id'])
    require(isinstance(voice,dict), 'voice not registered')
    require(voice.get('consent_id') == job['consent_id'], 'consent id mismatch')
    require(voice.get('synthesis_authorized') is True and voice.get('revoked') is False, 'voice synthesis permission missing/revoked')
    require(valid_id(voice.get('authorization_evidence_id')), 'authorization evidence ID required')
    try:
        expiry=datetime.fromisoformat(voice.get('expires_at','').replace('Z','+00:00'))
        require(expiry.tzinfo is not None and expiry > datetime.now(timezone.utc), 'voice authorization expired')
    except (TypeError,ValueError):
        raise ValueError('valid future voice authorization expiry required')
    require(type(voice.get('output_redistribution_allowed')) is bool, 'output rights must be explicit')
    require(voice.get('engine') == job['engine'], 'voice engine mismatch')
    require(isinstance(voice.get('allowed_purposes'),list) and all(isinstance(x,str) for x in voice['allowed_purposes']), 'allowed purposes must be list')
    require(job['purpose'] in voice['allowed_purposes'], 'voice purpose not authorized')
    for key in ('model_revision','engine_revision','reference_sha256'):
        require(isinstance(voice.get(key),str) and SHA.fullmatch(voice[key]) is not None, f'{key} must pin SHA256')
    require(voice.get('locale') == 'zh-TW', 'voice locale mismatch')
    return voice

def plan(job, voice):
    identity = {'contract':VERSION,'job':job,'voice':{k:voice[k] for k in ('consent_id','engine','locale','model_revision','engine_revision','reference_sha256')}}
    identity['rights']={k:voice[k] for k in ('authorization_evidence_id','synthesis_authorized','revoked','expires_at','allowed_purposes','output_redistribution_allowed')}
    identity['reference_text_sha256']=hashlib.sha256(voice.get('reference_text','').encode()).hexdigest()
    key = hashlib.sha256(canonical(identity)).hexdigest()
    return {'state':'planned','key':key,'engine':job['engine'],'job_id':job['job_id'],
            'requires_human_listening':True,'speaker_reference_transmitted':False,
            'accent_guaranteed':False,'line_count':len(job['lines'])}

def wav_info(path):
    with wave.open(str(path),'rb') as w:
        require(w.getnframes() > 0 and w.getnchannels() in (1,2), 'empty/invalid WAV')
        require(w.getsampwidth() == 2, 'prototype accepts PCM16 WAV only')
        data=w.readframes(w.getnframes()); samples=struct.unpack('<'+'h'*(len(data)//2), data)
        require(any(samples), 'silent WAV')
        return {'sample_rate':w.getframerate(),'channels':w.getnchannels(),'frames':w.getnframes()}

def tone(path):
    with wave.open(str(path),'wb') as w:
        w.setparams((1,2,22050,0,'NONE','not compressed'))
        w.writeframes(b''.join(struct.pack('<h',int(1000*math.sin(i*2*math.pi*440/22050))) for i in range(2205)))

def verify_tree(root, manifest_path, expected_hash):
    root=Path(root).resolve(); manifest_path=Path(manifest_path)
    require(manifest_path.is_file() and digest(manifest_path)==expected_hash, 'snapshot manifest hash mismatch')
    manifest=read_json(manifest_path); require(isinstance(manifest,dict) and set(manifest)=={'files'},'invalid snapshot manifest')
    files=manifest['files']; require(isinstance(files,dict) and files,'empty snapshot')
    actual=set()
    for p in root.rglob('*'):
        relative=p.relative_to(root)
        if '.git' in relative.parts or '__pycache__' in relative.parts or p.suffix=='.pyc': continue
        require(not p.is_symlink(),'snapshot symlink not allowed')
        if p.is_file() and p.resolve()!=manifest_path.resolve(): actual.add(relative.as_posix())
    require(actual==set(files),'snapshot file inventory mismatch')
    for name,sha in files.items():
        require(isinstance(name,str) and not Path(name).is_absolute() and '..' not in Path(name).parts,'unsafe snapshot path')
        require(isinstance(sha,str) and SHA.fullmatch(sha),'invalid snapshot digest')
        require(digest(root/name)==sha,'snapshot bytes mismatch')

def breezy_command(job, line, voice, config, output):
    require(job['engine']=='breezyvoice','IndexTTS bridge not implemented: use existing separately validated adapter')
    require(config.get('enabled') is True, 'worker not explicitly enabled')
    require(config.get('network_mode') == 'offline', 'prototype requires preinstalled offline worker')
    reference=Path(voice.get('reference_path',''))
    require(reference.is_file() and digest(reference)==voice['reference_sha256'], 'reference bytes mismatch')
    script=Path(config.get('script','')); python=Path(config.get('python','')); model=Path(config.get('model_path',''))
    require(script.is_file() and python.is_file() and model.is_dir(), 'worker paths not configured')
    verify_tree(script.parent,config.get('engine_manifest',''),voice['engine_revision'])
    verify_tree(model,config.get('model_manifest',''),voice['model_revision'])
    require(isinstance(voice.get('reference_text'),str) and voice['reference_text'].strip(), 'reference transcription required')
    return [str(python),str(script),'--content_to_synthesize',line['text'],
            '--speaker_prompt_audio_path',str(reference),
            '--speaker_prompt_text_transcription',voice['reference_text'],
            '--model_path',str(model),'--output_path',str(output)]

def verify_bundle(folder, allow_mock=False, expected_key=None):
    folder=Path(folder).resolve(); m=read_json(folder/'manifest.json')
    require(m.get('state')=='completed', 'bundle not completed')
    require(isinstance(m.get('key'),str) and SHA.fullmatch(m['key']), 'invalid artifact identity')
    require(expected_key is None or m['key']==expected_key, 'wrong job artifact')
    require(m.get('mode')=='real' or (allow_mock and m.get('mode')=='mock'), 'mock is not production audio')
    require(isinstance(m.get('files'),list) and m['files'], 'bundle has no files')
    seen=set()
    for f in m['files']:
        require(isinstance(f.get('name'),str) and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}\.wav',f['name']), 'unsafe audio path')
        require(f['name'] not in seen,'duplicate artifact path'); seen.add(f['name'])
        p=folder/f['name']; require(p.resolve().parent==folder and not p.is_symlink(),'artifact escapes bundle')
        require(p.is_file() and digest(p)==f['sha256'],'artifact checksum mismatch'); wav_info(p)
    return m

def run(job, voice, root, mode='mock', config=None):
    p=plan(job,voice); root=Path(root); key=p['key']; base=root/key/mode
    base.mkdir(parents=True,exist_ok=True)
    # A lock is never forcibly removed; interrupted workers need operator review.
    lock=base/'worker.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.close(fd)
    try:
        previous=sorted(base.glob('attempt-*'))
        for folder in reversed(previous):
            if (folder/'manifest.json').exists():
                verify_bundle(folder,allow_mock=mode=='mock',expected_key=key)
                if mode=='real': breezy_command(job,job['lines'][0],voice,config or {},folder/'unused.wav')
                return folder
        require(len(previous)<3,'three attempts exhausted; operator review required')
        folder=base/f'attempt-{len(previous)+1:03d}'; folder.mkdir()
        write_json(folder/'state.json',{'state':'running','key':key,'mode':mode})
        files=[]
        try:
            base_argv=breezy_command(job,job['lines'][0],voice,config or {},folder/'unused.wav') if mode=='real' else None
            for line in job['lines']:
                dest=folder/(line['id']+'.wav')
                if mode=='mock': tone(dest)
                else:
                    argv=list(base_argv); argv[3]=line['text']; argv[-1]=str(dest.resolve())
                    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONUTF8='1')
                    # No shell, no raw output logs (may include scripts or reference transcript).
                    subprocess.run(argv,check=True,timeout=300,capture_output=True,env=env,cwd=str(Path(argv[1]).parent))
                info=wav_info(dest); files.append({'name':dest.name,'sha256':digest(dest),**info})
            manifest={'schema_version':1,'state':'completed','mode':mode,'is_speech':mode=='real',
                      'key':key,'project_id':job['project_id'],'job_id':job['job_id'],'revision':job['revision'],
                      'engine':job['engine'],'model_revision':voice['model_revision'],
                      'consent_id':job['consent_id'],'output_redistribution_allowed':voice['output_redistribution_allowed'],'listening_approved':False,'files':files}
            write_json(folder/'manifest.json',manifest)
            write_json(folder/'state.json',{'state':'completed','key':key,'mode':mode})
            return folder
        except Exception as exc:
            write_json(folder/'state.json',{'state':'failed','key':key,'mode':mode,'error_type':type(exc).__name__})
            raise
    finally:
        lock.unlink()

def pull(source,destination,allow_mock=False,expected_key=None):
    manifest=verify_bundle(source,allow_mock,expected_key); dest=Path(destination)
    dest.mkdir(parents=True,exist_ok=False)
    for entry in manifest['files']:
        shutil.copyfile(Path(source)/entry['name'],dest/entry['name'])
    shutil.copyfile(Path(source)/'manifest.json',dest/'manifest.json')
    verify_bundle(dest,allow_mock); return dest

def fetch(repo, run_id, artifact, destination, expected_key, allow_mock=False):
    require(isinstance(expected_key,str) and SHA.fullmatch(expected_key), 'expected SHA256 job key required')
    require(isinstance(repo,str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo), 'invalid GitHub repository')
    require(isinstance(run_id,str) and run_id.isdigit(), 'invalid run id')
    require(valid_id(artifact), 'invalid artifact name')
    require(shutil.which('gh') is not None, 'install official GitHub CLI and sign in to authorized repository first')
    require(not Path(destination).exists(), 'destination already exists')
    with tempfile.TemporaryDirectory(prefix='voice-fetch-') as tmp:
        subprocess.run(['gh','run','download',run_id,'--repo',repo,'--name',artifact,'--dir',tmp],
                       check=True,timeout=120,capture_output=True)
        return pull(tmp,destination,allow_mock,expected_key)

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='command',required=True)
    for name in ('plan','mock','run'):
        p=sub.add_parser(name); p.add_argument('job'); p.add_argument('--registry',required=True)
        if name!='plan': p.add_argument('--output',required=True)
        if name=='run': p.add_argument('--worker-config',required=True)
    p=sub.add_parser('pull'); p.add_argument('source'); p.add_argument('destination'); p.add_argument('--allow-mock',action='store_true')
    p=sub.add_parser('fetch'); p.add_argument('--repo',required=True); p.add_argument('--run-id',required=True); p.add_argument('--artifact',required=True); p.add_argument('--expected-key',required=True); p.add_argument('--destination',required=True); p.add_argument('--allow-mock',action='store_true')
    args=ap.parse_args()
    try:
        if args.command=='fetch': print(fetch(args.repo,args.run_id,args.artifact,args.destination,args.expected_key,args.allow_mock)); return
        if args.command=='pull': print(pull(args.source,args.destination,args.allow_mock)); return
        job=validate(read_json(args.job)); registry=read_json(args.registry)
        require(args.command!='run' or registry.get('fixture_only') is not True, 'fixture registry cannot synthesize real voice')
        voice=resolve_voice(job,registry)
        if args.command=='plan': print(json.dumps(plan(job,voice),ensure_ascii=False,indent=2))
        else: print(run(job,voice,args.output,'real' if args.command=='run' else 'mock',read_json(args.worker_config) if args.command=='run' else None))
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        print(f'Voice job stopped: {type(exc).__name__}',file=sys.stderr); sys.exit(1)

if __name__=='__main__': main()
