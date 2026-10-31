import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('jobs',Path(__file__).parents[1]/'voice_jobs.py'); j=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(j)
JOB={'schema_version':1,'project_id':'ranch','job_id':'greeting','revision':'v1','engine':'breezyvoice','locale':'zh-TW','voice_id':'fixture','consent_id':'fixture-only','purpose':'technical_evaluation','content_class':'public_fixture','lines':[{'id':'hello','text':'你好，歡迎來到牧場。','emotion':'natural','strength':0}]}
VOICE={'consent_id':'fixture-only','synthesis_authorized':True,'revoked':False,'authorization_evidence_id':'fixture-no-person','expires_at':'2099-01-01T00:00:00Z','output_redistribution_allowed':False,'engine':'breezyvoice','locale':'zh-TW','allowed_purposes':['technical_evaluation'],'model_revision':'a'*64,'engine_revision':'b'*64,'reference_sha256':'c'*64}
class Jobs(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); self.job=copy.deepcopy(JOB); self.voice=copy.deepcopy(VOICE)
 def tearDown(self): self.t.cleanup()
 def test_plan_no_artifacts(self):
  j.validate(self.job); v=j.resolve_voice(self.job,{'voices':{'fixture':self.voice}}); self.assertEqual(j.plan(self.job,v)['state'],'planned'); self.assertEqual(list(self.root.iterdir()),[])
 def test_breezy_rejects_emotion(self):
  self.job['lines'][0]['emotion']='happy'
  with self.assertRaises(ValueError): j.validate(self.job)
 def test_breezy_rejects_unimplemented_knob(self):
  self.job['speed']=1.2
  with self.assertRaises(ValueError): j.validate(self.job)
 def test_ids_traversal_and_duplicate(self):
  self.job['job_id']='../escape'
  with self.assertRaises(ValueError): j.validate(self.job)
  self.job=copy.deepcopy(JOB); self.job['lines']*=2
  with self.assertRaises(ValueError): j.validate(self.job)
 def test_malformed_types(self):
  for field,value in [('text',[]),('emotion',[]),('strength',True),('strength',float('nan'))]:
   x=copy.deepcopy(JOB); x['lines'][0][field]=value
   with self.assertRaises(ValueError): j.validate(x)
 def test_consent_and_purpose(self):
  for key,value in [('synthesis_authorized',False),('consent_id','different'),('allowed_purposes',[])]:
   v=copy.deepcopy(VOICE); v[key]=value
   with self.assertRaises(ValueError): j.resolve_voice(self.job,{'voices':{'fixture':v}})
 def test_revoked_expired_rights(self):
  for key,value in [('revoked',True),('expires_at','2000-01-01T00:00:00Z'),('authorization_evidence_id',None)]:
   v=copy.deepcopy(VOICE); v[key]=value
   with self.assertRaises(ValueError): j.resolve_voice(self.job,{'voices':{'fixture':v}})
 def test_wrong_job_artifact(self):
  p=j.run(self.job,self.voice,self.root)
  with self.assertRaises(ValueError): j.verify_bundle(p,True,'f'*64)
 def test_rights_changes_never_reuse_old_manifest(self):
  self.voice['output_redistribution_allowed']=True; old=j.run(self.job,self.voice,self.root)
  self.voice['output_redistribution_allowed']=False; new=j.run(self.job,self.voice,self.root)
  self.assertNotEqual(old,new); self.assertFalse(j.read_json(new/'manifest.json')['output_redistribution_allowed'])
 def test_content_changes_key(self):
  before=j.plan(self.job,self.voice)['key']; self.job['lines'][0]['text']='不同台詞'
  self.assertNotEqual(before,j.plan(self.job,self.voice)['key'])
 def test_reference_transcript_changes_key(self):
  before=j.plan(self.job,self.voice)['key']; self.voice['reference_text']='corrected transcript'
  self.assertNotEqual(before,j.plan(self.job,self.voice)['key'])
 def test_engine_revision_changes_key(self):
  before=j.plan(self.job,self.voice)['key']; self.voice['engine_revision']='d'*64
  self.assertNotEqual(before,j.plan(self.job,self.voice)['key'])
 def test_mock_idempotent_and_not_speech(self):
  p=j.run(self.job,self.voice,self.root); self.assertEqual(p,j.run(self.job,self.voice,self.root)); self.assertFalse(j.read_json(p/'manifest.json')['is_speech'])
  with self.assertRaises(ValueError): j.verify_bundle(p)
 def test_mock_pull_explicit(self):
  p=j.run(self.job,self.voice,self.root); target=self.root/'consumer'; j.pull(p,target,True); j.verify_bundle(target,True)
  with self.assertRaises(FileExistsError): j.pull(p,target,True)
 def test_corrupt_cache_fails_closed(self):
  p=j.run(self.job,self.voice,self.root); (p/'hello.wav').write_bytes(b'bad')
  with self.assertRaises(ValueError): j.run(self.job,self.voice,self.root)
 def test_path_escape_rejected(self):
  p=j.run(self.job,self.voice,self.root); m=j.read_json(p/'manifest.json'); m['files'][0]['name']='../hello.wav'; j.write_json(p/'manifest.json',m)
  with self.assertRaises(ValueError): j.verify_bundle(p,True)
 def test_real_disabled_fails_no_manifest(self):
  with self.assertRaises(ValueError): j.run(self.job,self.voice,self.root,'real',{})
  self.assertEqual(list(self.root.rglob('manifest.json')),[]); self.assertEqual(j.read_json(next(self.root.rglob('state.json')))['state'],'failed')
 def test_retry_is_new_attempt_and_bounded(self):
  for _ in range(3):
   with self.assertRaises(ValueError): j.run(self.job,self.voice,self.root,'real',{})
  self.assertEqual(len(list(self.root.rglob('attempt-*'))),3)
  with self.assertRaises(ValueError): j.run(self.job,self.voice,self.root,'real',{})
 def test_lock_does_not_get_stolen(self):
  base=self.root/j.plan(self.job,self.voice)['key']/'mock'; base.mkdir(parents=True); (base/'worker.lock').touch()
  with self.assertRaises(FileExistsError): j.run(self.job,self.voice,self.root)
  self.assertTrue((base/'worker.lock').exists())
 def test_cli_arguments_no_shell(self):
  engine=self.root/'engine'; engine.mkdir(); script=engine/'single_inference.py'; script.write_text('# fixture only'); ref=self.root/'ref.wav'; j.tone(ref); model=self.root/'model'; model.mkdir(); (model/'weights').write_bytes(b'fixture only')
  em=self.root/'engine.json'; mm=self.root/'model.json'; j.write_json(em,{'files':{'single_inference.py':j.digest(script)}}); j.write_json(mm,{'files':{'weights':j.digest(model/'weights')}})
  self.voice.update(reference_path=str(ref),reference_text='已授權測試',reference_sha256=j.digest(ref),engine_revision=j.digest(em),model_revision=j.digest(mm))
  config={'enabled':True,'network_mode':'offline','script':str(script),'python':'/usr/bin/python3','model_path':str(model),'engine_manifest':str(em),'model_manifest':str(mm)}
  self.job['lines'][0]['text']='你好; $(touch /tmp/nope)'
  argv=j.breezy_command(self.job,self.job['lines'][0],self.voice,config,self.root/'out.wav')
  self.assertIn(self.job['lines'][0]['text'],argv); self.assertNotIn('--emotion',argv)
  (model/'weights').write_bytes(b'changed')
  with self.assertRaises(ValueError): j.breezy_command(self.job,self.job['lines'][0],self.voice,config,self.root/'out.wav')
 def test_wrong_cached_identity(self):
  p=j.run(self.job,self.voice,self.root); m=j.read_json(p/'manifest.json'); m['key']='f'*64; j.write_json(p/'manifest.json',m)
  with self.assertRaises(ValueError): j.run(self.job,self.voice,self.root)
 def test_fetch_passes_exact_arguments(self):
  def fake(argv,**kwargs):
   self.assertEqual(argv[:4],['gh','run','download','123']); target=Path(argv[-1]); p=j.run(self.job,self.voice,self.root/'other');
   for f in p.iterdir():
    if f.is_file(): (target/f.name).write_bytes(f.read_bytes())
  with patch.object(j.shutil,'which',return_value='/usr/bin/gh'),patch.object(j.subprocess,'run',side_effect=fake):
   out=j.fetch('owner/repo','123','voice-fixture',self.root/'download',j.plan(self.job,self.voice)['key'],True); j.verify_bundle(out,True)
 def test_fetch_rejects_injection(self):
  for repo,run,artifact in [('o/r;bad','123','v'),('o/r','1;bad','v'),('o/r','123','../bad')]:
   with self.assertRaises(ValueError): j.fetch(repo,run,artifact,self.root/'d','a'*64)
if __name__=='__main__': unittest.main()
