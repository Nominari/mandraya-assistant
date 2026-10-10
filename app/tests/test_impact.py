import os,tempfile,json,secrets,time,hashlib,asyncio,unittest
from unittest.mock import patch
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
import server,impact,chat_records
from workbench import basis
from fastapi.testclient import TestClient
class Impact(unittest.TestCase):
 def setUp(self):
  self.client=TestClient(server.app);self.owner='impact-test@example.com';t=secrets.token_hex(12)
  with server.db() as c:
   c.execute('DELETE FROM impact_findings');c.execute('DELETE FROM impact_jobs');c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(t.encode()).hexdigest(),self.owner,int(time.time())+1000))
  self.client.cookies.set('mandraya_session',t)
 def finding(self,target='digital',origin='operations-2'):
  with server.db() as c:
   jid=impact.enqueue(c,self.owner,'save',origin);job=dict(c.execute('SELECT * FROM impact_jobs WHERE id=?',(jid,)).fetchone());job['basis']=basis(c)
   result={'summary':'Auswirkung auf ein anderes Thema geprüft.','findings':[{'node_id':target,'origin_node':origin,'question':'Welche Daten muss die Verwaltung dafür bereitstellen? '+jid,'reason':'Geänderter Ablauf benötigt einen Abgleich mit der Verwaltung.','proof_keys':['proof']}]}
   proof={'proof':{'node_id':origin,'title':'Technik & Ausstattung','version':1}}
   impact.apply_result(c,job,result,proof,'test',server.now,server.log)
   return dict(c.execute('SELECT * FROM impact_findings WHERE job_id=?',(jid,)).fetchone())
 def test_subtopic_questions_visible_in_parent_and_context_without_copies(self):
  q=self.client.post('/api/work-questions',json={'node_id':'operations-2','origin_node':'operations-2','question':'GPS Test '+secrets.token_hex(8),'reason':'Ausstattung prüfen'}).json()['id']
  for nid in ('operations-2','operations','mandraya'):
   qs=self.client.get('/api/workbench/'+nid).json()['questions'];self.assertEqual(sum(x['id']==q for x in qs),1)
   self.assertTrue(any(x['id']==q for x in server.chat_read_tool('node_context',{'node_id':nid,'compact':True}, {})['questions']))
  self.assertFalse(any(x['id']==q for x in self.client.get('/api/workbench/digital').json()['questions']))
 def test_saved_inputs_and_changes_coalesce_and_keep_owner(self):
  src=secrets.token_hex(12);server.ingest({'id':src,'title':'Neuer Ablauf','content':'Neuer Input','nodes':['operations-2']},self.owner)
  n=server.node_detail('operations-2');server.change(n['id'],{'version':n['version'],'content':'Aktualisierter Ablauf','reason':'Prüfen'},self.owner)
  with server.db() as c:
   rows=c.execute('SELECT * FROM impact_jobs').fetchall();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['owner'],self.owner);self.assertEqual(len(json.loads(rows[0]['events'])),2)
 def test_findings_are_not_questions_or_decisions_until_confirmed(self):
  with server.db() as c:qbefore=c.execute('SELECT count(*) FROM work_questions').fetchone()[0];dbefore=c.execute('SELECT count(*) FROM statements').fetchone()[0]
  f=self.finding();r=self.client.post('/api/impact/findings/'+f['id'],json={'action':'discuss'});self.assertEqual(r.status_code,200)
  s=self.client.get('/api/explorations/'+r.json()['session_id']).json();self.assertEqual(s['impact']['id'],f['id'])
  with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM work_questions').fetchone()[0],qbefore)
  r=self.client.post('/api/impact/findings/'+f['id'],json={'action':'save'});self.assertEqual(r.status_code,200,r.text)
  with server.db() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM work_questions').fetchone()[0],qbefore+1);self.assertEqual(c.execute('SELECT count(*) FROM statements').fetchone()[0],dbefore)
   q=c.execute('SELECT * FROM work_questions WHERE id=?',(r.json()['question_id'],)).fetchone();self.assertEqual(q['node_id'],'digital');self.assertEqual(q['origin_node'],'operations-2')
 def test_reject_and_stale_findings_never_change_register(self):
  f=self.finding();self.assertEqual(self.client.post('/api/impact/findings/'+f['id'],json={'action':'reject'}).status_code,200)
  f=self.finding();n=server.node_detail('world');server.change('world',{'version':n['version'],'content':n['content']+'x','reason':'Neu'},self.owner)
  self.assertEqual(self.client.post('/api/impact/findings/'+f['id'],json={'action':'save'}).status_code,409)
  self.client.cookies.clear();self.assertEqual(self.client.get('/api/impact').status_code,401)
 def test_unproved_findings_rejected_and_changed_basis_overholt(self):
  with self.assertRaises(ValueError):impact.validate(json.dumps({'summary':'Prüfung','findings':[{'node_id':'world','origin_node':'world','question':'Warum?','reason':'Anlass','proof_keys':['invented']}]}),{'world'}, {})
  with server.db() as c:
   jid=impact.enqueue(c,self.owner,'save','world');job=dict(c.execute('SELECT * FROM impact_jobs WHERE id=?',(jid,)).fetchone());job['basis']='old'
   impact.apply_result(c,job,{'summary':'Kein Befund','findings':[]},{},'test',server.now,server.log)
   self.assertEqual(c.execute('SELECT state FROM impact_jobs WHERE id=?',(jid,)).fetchone()[0],'Überholt')
 def test_background_worker_uses_read_tools_and_saves_only_drafts(self):
  n=server.node_detail('operations-2');proof='N:operations-2@'+str(n['version'])
  with server.db() as c:jid=impact.enqueue(c,self.owner,'save','operations-2');c.execute('UPDATE impact_jobs SET due=0 WHERE id=?',(jid,))
  payload={'summary':'Technische Änderung betrifft die Website.','findings':[{'node_id':'digital','origin_node':'operations-2','question':'Wie berücksichtigt die Website diesen Ablauf? '+jid,'reason':'Geänderte Technik braucht einen Abgleich.','proof_keys':[proof,'N:digital@'+str(server.node_detail('digital')['version'])]}]}
  class Response:
   status_code=200
   def raise_for_status(self):pass
   def json(self):return {'models':[{'slug':'test','visibility':'list'}]}
  class Stream:
   status_code=200
   def __init__(self,first=False):self.first=first
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def aiter_lines(self):
    if self.first:
     yield 'data: '+json.dumps({'type':'response.completed','response':{'output':[{'type':'function_call','namespace':'mandraya','name':'node_context','call_id':'target','arguments':json.dumps({'node_id':'digital'})}]}});return
    yield 'data: '+json.dumps({'type':'response.output_text.delta','delta':json.dumps(payload)})
    yield 'data: '+json.dumps({'type':'response.completed','response':{'output':[]}})
  calls=[]
  class Client:
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def get(self,*a,**kw):return Response()
   def stream(self,*a,**kw):calls.append(kw['json']);return Stream(len(calls)==1)
  async def token(owner):self.assertEqual(owner,self.owner);return 'test-only'
  with patch.object(impact.auth,'connection',return_value={'plan_enabled':True}),patch.object(impact.auth,'token',token),patch.object(impact.httpx,'AsyncClient',return_value=Client()):self.assertTrue(asyncio.run(server.run_impact_once()))
  with server.db() as c:self.assertEqual(c.execute('SELECT state FROM impact_jobs WHERE id=?',(jid,)).fetchone()[0],'Geprüft');self.assertEqual(c.execute('SELECT status FROM impact_findings WHERE job_id=?',(jid,)).fetchone()[0],'Zu prüfen')
  self.assertNotIn('prepare_record',[x['name'] for x in calls[0]['tools'][0]['tools']])
 def test_proactive_question_drafts_deduplicate_existing_register(self):
  text='Gleiche Frage '+secrets.token_hex(8);q=self.client.post('/api/work-questions',json={'node_id':'world','origin_node':'world','question':text,'reason':'Test'}).json()['id']
  sid=self.client.post('/api/explorations',json={'node_id':'world'}).json()['id']
  with server.db() as c:
   r=chat_records.prepare(c,{'kind':'question','node_id':'world','title':'','content':text.upper(),'reason':'Test'},'test',sid,'world',basis(c),{},self.owner,server.now,server.log)
   self.assertEqual(r['existing_question_id'],q)

 def test_restored_document_content_is_a_new_current_version(self):
  sid=secrets.token_hex(12)
  for text in ('Erste Fassung','Geänderte Fassung','Erste Fassung'):self.assertTrue(server.ingest({'id':sid,'title':'Dokument','content':text},self.owner)['new_version'])
  self.assertFalse(server.ingest({'id':sid,'title':'Dokument','content':'Erste Fassung'},self.owner)['new_version'])
  with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM source_versions WHERE source_id=?',(sid,)).fetchone()[0],3)
  self.assertEqual(server.chat_read_tool('read_source',{'source_id':sid,'offset':0}, {})['content'],'Erste Fassung')
 def test_recheck_refreshes_stale_finding_without_duplicate(self):
  f=self.finding();n=server.node_detail('digital');server.change('digital',{'version':n['version'],'content':n['content']+'x','reason':'Neu'},self.owner)
  with server.db() as c:
   job=dict(c.execute('SELECT * FROM impact_jobs WHERE id=?',(f['job_id'],)).fetchone());job['basis']=basis(c)
   result={'summary':'Neu geprüft','findings':[{'node_id':f['node_id'],'origin_node':f['origin_node'],'question':f['question'],'reason':'Aktuelle Grundlage neu geprüft.','proof_keys':['fresh']}]}
   impact.apply_result(c,job,result,{'fresh':{'node_id':'digital','version':n['version']+1,'title':'Website & Infrastruktur'}},'test',server.now,server.log)
   rows=c.execute('SELECT * FROM impact_findings').fetchall();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['id'],f['id']);self.assertEqual(rows[0]['basis'],basis(c))

 def test_old_archive_schema_migrates_without_losing_revision_ids(self):
  import sqlite3,subprocess,sys
  folder=tempfile.mkdtemp();c=sqlite3.connect(folder+'/mandraya.sqlite')
  c.executescript("CREATE TABLE sources(id TEXT PRIMARY KEY,title TEXT,url TEXT,path TEXT,kind TEXT,coverage TEXT); CREATE TABLE source_versions(id INTEGER PRIMARY KEY,source_id TEXT REFERENCES sources(id),hash TEXT,content TEXT,modified TEXT,at TEXT,UNIQUE(source_id,hash)); INSERT INTO sources VALUES('migration','Document','','Eingang','Text','Text'); INSERT INTO source_versions VALUES(7,'migration','a','A','',''); INSERT INTO source_versions VALUES(9,'migration','b','B','','');")
  c.commit();c.close();env={**os.environ,'DATA_DIR':folder}
  code="import server; server.ingest({'id':'migration','title':'Document','content':'A'},'Test'); c=server.db(); db=c.__enter__(); assert db.execute('SELECT content FROM source_versions WHERE id=7').fetchone()[0]=='A'; assert db.execute('SELECT content FROM source_versions WHERE id=9').fetchone()[0]=='B'; assert db.execute('SELECT count(*) FROM source_versions').fetchone()[0]==3; assert not db.execute('PRAGMA foreign_key_check').fetchall(); c.__exit__(None,None,None)"
  r=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
