import os,tempfile,json,time,unittest,hashlib,asyncio
from unittest.mock import patch
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
os.environ.setdefault('MCP_TOKEN','test-only')
import server,chatgpt_auth as auth
from fastapi.testclient import TestClient
class Chat(unittest.TestCase):
 def setUp(self):
  self.client=TestClient(server.app);self.owner='person@example.com';token='test-session'
  with server.db() as c:c.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),self.owner,int(time.time())+1000))
  self.client.cookies.set('mandraya_session',token)
 def test_credentials_encrypted_and_accounts_separate(self):
  r={'access_token':'private-test-token','scopes':['resource.invoke','chatgpt.tokens.use.direct'],'email':'account@example.com','expires_at':time.time()+3600}
  auth.save(self.owner,r)
  self.assertNotIn(b'private-test-token',auth.filename(self.owner).read_bytes())
  self.assertEqual(auth.filename(self.owner).stat().st_mode&0o777,0o600)
  self.assertIsNone(auth.load('another@example.com'))
  s=self.client.get('/api/chatgpt/status').json();self.assertTrue(s['plan_enabled']);self.assertNotIn('access_token',s)
 def test_private_history(self):
  self.client.cookies.clear();self.assertEqual(self.client.get('/api/chat/world').status_code,401)
 def test_source_search_and_version_evidence(self):
  server.ingest({'id':'chat-src','title':'Testquelle','content':'Die Mondlaterne gehört zur Legende.','nodes':['world']},'Test')
  ev={};r=server.chat_read_tool('search_sources',{'query':'Mondlaterne'},ev)
  self.assertEqual(r['shown'][0]['id'],'chat-src');self.assertTrue(list(ev.values())[0]['version_id'])
 def test_chat_proposals_reject_changed_sources_and_duplicate(self):
  server.ingest({'id':'chat-version','title':'Quelle','content':'A'},'Test')
  n=server.node_detail('format')
  with server.db() as c:
   vid=c.execute("SELECT max(id) FROM source_versions WHERE source_id='chat-version'").fetchone()[0]
   c.execute('INSERT OR REPLACE INTO chat_messages VALUES(?,?,?,?,?,?,?,?,?,?)',('test-answer','format','assistant','Arbeitsfassung','KI',server.now(),n['version'],json.dumps([{'source_id':'chat-version','version_id':vid,'title':'Quelle'}]),'test','completed'))
  r=self.client.post('/api/chat/proposal/test-answer',json={});self.assertEqual(r.status_code,200)
  pid=r.json()['id'];self.assertEqual(self.client.post('/api/chat/proposal/test-answer',json={}).status_code,409)
  server.ingest({'id':'chat-version','title':'Quelle','content':'B'},'Test')
  self.assertEqual(self.client.post('/api/proposals/'+pid,json={'action':'accept'}).status_code,409)
  self.assertEqual(server.node_detail('format')['content'],n['content'])
 def test_refresh_keeps_registration(self):
  auth.save('refresh-owner',{'client_id':'registered','access_token':'old','refresh_token':'refresh-old','scopes':['resource.invoke','chatgpt.tokens.use.direct'],'expires_at':0})
  class Response:
   status_code=200
   def json(self):return {'access_token':'new','refresh_token':'rotated','expires_in':3600}
  class Client:
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
   async def post(self,url,data):return Response()
  with patch.object(auth.httpx,'AsyncClient',return_value=Client()):self.assertEqual(asyncio.run(auth.token('refresh-owner')),'new')
  self.assertEqual(auth.load('refresh-owner')['refresh_token'],'rotated')
 def test_stream_tools_and_incomplete_answers(self):
  class Response:
   status_code=200
   def json(self):return {'models':[{'slug':'test-model','visibility':'list'}]}
  class Stream:
   status_code=200
   def __init__(self,events):self.events=events
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
   async def aiter_lines(self):
    for e in self.events:yield 'data: '+json.dumps(e)
  calls=[]
  class Client:
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
   async def get(self,*args,**kwargs):return Response()
   def stream(self,*args,**kwargs):
    calls.append(kwargs['json'])
    if len(calls)==1:return Stream([{'type':'response.completed','response':{'output':[{'type':'function_call','namespace':'mandraya','name':'read_source','arguments':json.dumps({'source_id':'chat-src','offset':0}),'call_id':'c1'}]}}])
    return Stream([{'type':'response.output_text.delta','delta':'Prüfbare Antwort'}, {'type':'response.completed','response':{'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Prüfbare Antwort'}]}]}}])
  server.ingest({'id':'chat-src','title':'Testquelle','content':'Mondlaterne'},'Test')
  before=server.node_detail('world')['content']
  async def token(owner):return 'test-access'
  with patch.object(auth,'token',token),patch.object(auth.httpx,'AsyncClient',return_value=Client()):
   r=self.client.post('/api/chat/world',json={'message':'Prüfe Quellen','model':'test-model'})
  events=[json.loads(x) for x in r.text.splitlines()]
  self.assertEqual(events[-1]['type'],'done');self.assertEqual(len(calls),2)
  self.assertFalse(calls[0]['store']);self.assertTrue(any(x.get('type')=='function_call_output' for x in calls[1]['input']))
  self.assertTrue(events[-1]['evidence']);self.assertEqual(server.node_detail('world')['content'],before)
  class Broken(Client):
   def stream(self,*args,**kwargs):return Stream([{'type':'response.output_text.delta','delta':'Teilantwort'}])
  with patch.object(auth,'token',token),patch.object(auth.httpx,'AsyncClient',return_value=Broken()):
   r=self.client.post('/api/chat/world',json={'message':'Testabbruch','model':'test-model'})
  self.assertEqual(json.loads(r.text.splitlines()[-1])['type'],'error')
  last=self.client.get('/api/chat/world').json()[-1];self.assertEqual(last['status'],'incomplete')
  self.assertEqual(self.client.post('/api/chat/proposal/'+last['id'],json={}).status_code,404)
if __name__=='__main__':unittest.main()
