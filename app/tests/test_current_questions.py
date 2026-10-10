import os,tempfile,secrets,json,time,hashlib,unittest
from unittest.mock import patch
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
import server,chat_records,chatgpt_auth as auth
from workbench import basis
from fastapi.testclient import TestClient
class CurrentQuestions(unittest.TestCase):
 def setUp(self):
  self.client=TestClient(server.app);t=secrets.token_hex(12)
  with server.db() as c:c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(t.encode()).hexdigest(),'test@example.com',int(time.time())+1000))
  self.client.cookies.set('mandraya_session',t)
  r=self.client.post('/api/work-questions',json={'node_id':'world','origin_node':'world','question':'Prüffrage '+t,'reason':'Test'});self.qid=r.json()['id']
  self.sid=self.client.post('/api/work-questions/'+self.qid+'/explore',json={}).json()['id']
 def draft(self):
  mid=secrets.token_hex(12)
  with server.db() as c:
   r=chat_records.prepare_resolution(c,{'question_id':self.qid,'answer':'Begründetes Ergebnis','decision':'Präzise Regel '+self.qid,'reason':'Gemeinsam geprüft'},mid,self.sid,'world',basis(c),{},'KI',server.now,server.log)
   c.execute('INSERT INTO chat_messages(id,node_id,role,content,actor,at,base_version,evidence,model,status,session_id,kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(mid,'world','assistant','Entwurf','KI',server.now(),1,'[]','test','completed',self.sid,'chat'))
  return r['draft_id']
 def test_question_session_reused_and_answer_without_decision(self):
  self.assertEqual(self.client.post('/api/work-questions/'+self.qid+'/explore',json={}).json()['id'],self.sid)
  self.assertEqual(self.client.get('/api/explorations/'+self.sid).json()['question']['id'],self.qid)
  rid=self.draft()
  with server.db() as c:before=c.execute('SELECT count(*) FROM statements').fetchone()[0]
  self.assertEqual(self.client.post('/api/chat-records/'+rid,json={'action':'confirm'}).status_code,200)
  with server.db() as c:
   q=c.execute('SELECT * FROM work_questions WHERE id=?',(self.qid,)).fetchone();self.assertEqual(q['status'],'Geklärt');self.assertEqual(q['answer'],'Begründetes Ergebnis');self.assertEqual(c.execute('SELECT count(*) FROM statements').fetchone()[0],before)
  self.assertTrue(any(q['id']==self.qid and q['answer']=='Begründetes Ergebnis' for q in server.chat_read_tool('project_overview',{}, {})['questions']))
 def test_atomic_decision_and_resolution_and_rejection(self):
  rid=self.draft();bad=self.client.post('/api/chat-records/'+rid,json={'action':'confirm','decide':True,'title':''});self.assertEqual(bad.status_code,400)
  with server.db() as c:self.assertEqual(c.execute('SELECT status FROM work_questions WHERE id=?',(self.qid,)).fetchone()[0],'Offen')
  self.assertEqual(self.client.post('/api/chat-records/'+rid,json={'action':'confirm','decide':True}).status_code,200)
  with server.db() as c:
   r=c.execute('SELECT * FROM question_resolutions WHERE question_id=?',(self.qid,)).fetchone();self.assertTrue(r['statement_id']);self.assertEqual(c.execute('SELECT status FROM statements WHERE id=?',(r['statement_id'],)).fetchone()[0],'Beschlossen')
 def test_rejected_or_changed_question_stays_open(self):
  rid=self.draft();self.assertEqual(self.client.post('/api/chat-records/'+rid,json={'action':'reject'}).status_code,200)
  with server.db() as c:self.assertEqual(c.execute('SELECT status FROM work_questions WHERE id=?',(self.qid,)).fetchone()[0],'Offen')
  rid=self.draft();self.client.post('/api/work-questions/'+self.qid,json={'action':'defer','version':1,'reason':'Später'})
  self.assertEqual(self.client.post('/api/chat-records/'+rid,json={'action':'confirm','decide':True}).status_code,409)
 def test_stream_rejects_change_and_receipt_stales(self):
  changed=[False]
  class Response:
   status_code=200
   def json(self):return {'models':[{'slug':'test-model','visibility':'list'}]}
  class Stream:
   status_code=200
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def aiter_lines(self):
    if changed[0]:
     n=server.node_detail('format');server.change('format',{'version':n['version'],'content':n['content']+'x','reason':'Anderer Nutzer'},'Test')
    yield 'data: '+json.dumps({'type':'response.output_text.delta','delta':'Antwort'})
    yield 'data: '+json.dumps({'type':'response.completed','response':{'output':[]}})
  class Client:
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def get(self,*a,**kw):return Response()
   def stream(self,*a,**kw):return Stream()
  async def token(owner):return 'test-only'
  with patch.object(auth,'token',token),patch.object(auth.httpx,'AsyncClient',return_value=Client()):
   r=self.client.post('/api/chat/world',json={'message':'Prüfen','model':'test-model','session_id':self.sid});self.assertEqual(json.loads(r.text.splitlines()[-1])['type'],'done')
   messages=self.client.get('/api/chat/world?session_id='+self.sid).json();self.assertFalse(messages[-1]['grounding']['stale'])
   changed[0]=True;r=self.client.post('/api/chat/world',json={'message':'Prüfen','model':'test-model','session_id':self.sid});self.assertEqual(json.loads(r.text.splitlines()[-1])['type'],'error')
  messages=self.client.get('/api/chat/world?session_id='+self.sid).json();self.assertEqual(messages[-1]['status'],'incomplete');self.assertTrue(messages[-3]['grounding']['stale'])

 def test_model_tool_prepares_only_a_resolution_draft(self):
  calls=[];qid=self.qid
  class Response:
   status_code=200
   def json(self):return {'models':[{'slug':'test-model','visibility':'list'}]}
  class Stream:
   status_code=200
   def __init__(self,events):self.events=events
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def aiter_lines(self):
    for e in self.events:yield 'data: '+json.dumps(e)
  class Client:
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def get(self,*a,**kw):return Response()
   def stream(self,*a,**kw):
    calls.append(kw['json'])
    if len(calls)==1:return Stream([{'type':'response.completed','response':{'output':[{'type':'function_call','namespace':'mandraya','name':'prepare_resolution','call_id':'resolution-call','arguments':json.dumps({'question_id':qid,'answer':'Geprüftes Ergebnis','decision':'Mögliche Regel','reason':'Gemeinsame Diskussion'})}]}}])
    return Stream([{'type':'response.output_text.delta','delta':'Bitte prüfe den Entwurf.'},{'type':'response.completed','response':{'output':[]}}])
  async def token(owner):return 'test-only'
  with patch.object(auth,'token',token),patch.object(auth.httpx,'AsyncClient',return_value=Client()):r=self.client.post('/api/chat/world',json={'message':'Ergebnis vorbereiten','model':'test-model','session_id':self.sid})
  self.assertEqual(json.loads(r.text.splitlines()[-1])['type'],'done',r.text)
  self.assertIn('prepare_resolution',[x['name'] for x in calls[0]['tools'][0]['tools']])
  records=self.client.get('/api/chat/world?session_id='+self.sid).json()[-1]['records'];self.assertEqual(records[0]['kind'],'resolution');self.assertEqual(records[0]['status'],'Entwurf')
  with server.db() as c:self.assertEqual(c.execute('SELECT status FROM work_questions WHERE id=?',(qid,)).fetchone()[0],'Offen')
