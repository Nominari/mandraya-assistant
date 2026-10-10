import os,tempfile,json,time,hashlib,secrets,unittest
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
import server,source_policy,chat_records
from workbench import basis
from fastapi.testclient import TestClient
class RecordsSources(unittest.TestCase):
 def setUp(self):
  self.client=TestClient(server.app);t=secrets.token_hex(12)
  with server.db() as c:c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(t.encode()).hexdigest(),'person@example.com',int(time.time())+300))
  self.client.cookies.set('mandraya_session',t)
 def test_editions_and_alternatives(self):
  rows=[{'id':'old','title':'Rules_V0.14.docx','path':'Project'},{'id':'new','title':'Rules_V0.15.docx','path':'Project'},{'id':'v2','title':'Plan_V2.docx','path':'Project'},{'id':'v11','title':'Plan_V11.docx','path':'Project'},{'id':'A','title':'Story_Variante_A.docx','path':'Project'},{'id':'B','title':'Story_Variante_B.docx','path':'Project'},{'id':'arch','title':'Rules_V99.docx','path':'Project/Alt'}]
  r=source_policy.classify(rows);self.assertEqual(r['old']['successor_id'],'new');self.assertEqual(r['v2']['successor_id'],'v11');self.assertEqual(r['A']['status'],'Aktuell');self.assertEqual(r['B']['status'],'Aktuell');self.assertEqual(r['arch']['status'],'Archiv')
 def test_archived_sources_excluded_by_default(self):
  server.ingest({'id':'new-rule','title':'UniqueRules_V2.docx','content':'Mondschlüssel aktueller Stand'},'Test')
  server.ingest({'id':'old-rule','title':'UniqueRules_V1.docx','content':'Mondschlüssel alter Stand'},'Test')
  ev={};r=server.chat_read_tool('search_sources',{'query':'Mondschlüssel'},ev)
  self.assertEqual([x['id'] for x in r['shown']],['new-rule'])
  with self.assertRaises(ValueError):server.chat_read_tool('read_source',{'source_id':'old-rule','offset':0},ev)
  self.assertIn('alter Stand',server.chat_read_tool('read_source',{'source_id':'old-rule','offset':0,'include_archived':True},ev)['content'])
 def create(self,kinds):
  sid=self.client.post('/api/explorations',json={'node_id':'world'}).json()['id'];mid=secrets.token_hex(12);ids=[]
  with server.db() as c:
   snap=basis(c)
   for kind in kinds:
    r=chat_records.prepare(c,{'kind':kind,'node_id':'world','title':'Variante','content':'Präzise Aussage '+mid if kind=='statement' else 'Welche Variante verfolgen wir?','reason':'Gemeinsam geprüft'},mid,sid,'world',snap,{},'KI',server.now,server.log);ids.append(r['draft_id'])
   c.execute('INSERT INTO chat_messages(id,node_id,role,content,actor,at,base_version,evidence,model,status,session_id,kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(mid,'world','assistant','Bitte bestätige den Entwurf.','KI',server.now(),1,'[]','test','completed',sid,'chat'))
  return ids
 def test_chat_draft_only_and_sibling_confirmation(self):
  with server.db() as c:before=c.execute('SELECT count(*) FROM statements').fetchone()[0]
  ids=self.create(['statement','question'])
  with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM statements').fetchone()[0],before)
  r=self.client.post('/api/chat-records/'+ids[0],json={'action':'confirm'});self.assertEqual(r.status_code,200,r.text)
  r=self.client.post('/api/chat-records/'+ids[1],json={'action':'confirm'});self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(self.client.post('/api/chat-records/'+ids[0],json={'action':'confirm'}).status_code,409)
 def test_changed_project_blocks_draft(self):
  rid=self.create(['question'])[0];n=server.node_detail('format');server.change('format',{'version':n['version'],'content':n['content'],'reason':'Neue Grundlage'},'Test')
  self.assertEqual(self.client.post('/api/chat-records/'+rid,json={'action':'confirm'}).status_code,409)
  self.client.cookies.clear();self.assertEqual(self.client.post('/api/chat-records/'+rid,json={'action':'confirm'}).status_code,401)
if __name__=='__main__':unittest.main()
