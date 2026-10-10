import os,tempfile,unittest,json
os.environ['DATA_DIR']=tempfile.mkdtemp()
os.environ['MCP_TOKEN']='test-only'
import server
from fastapi import HTTPException
from fastapi.testclient import TestClient
class Core(unittest.TestCase):
 def test_01_version_lock_and_restore(self):
  n=server.node_detail('finance-0'); original=n['content']
  n=server.change(n['id'],{'version':n['version'],'content':'Konkrete Arbeitsfassung','reason':'Test','action':'save'},'Person A')
  n=server.change(n['id'],{'version':n['version'],'reason':'Beschluss','action':'lock'},'Person B')
  with self.assertRaises(HTTPException) as e:server.change(n['id'],{'version':n['version'],'reason':'Test','action':'save','content':'Überschreiben'},'KI')
  self.assertEqual(e.exception.status_code,423)
  with self.assertRaises(HTTPException) as e:server.change(n['id'],{'version':1,'reason':'Test','action':'unlock'},'Person A')
  self.assertEqual(e.exception.status_code,409)
  n=server.change(n['id'],{'version':n['version'],'reason':'Neue Grundlage','action':'unlock'},'Person B')
  n=server.change(n['id'],{'version':n['version'],'content':original,'reason':'Wiederherstellung','action':'save'},'Person A')
  self.assertGreaterEqual(len(server.node_detail(n['id'])['revisions']),4)
 def test_02_sources_deduplicate_and_preserve(self):
  p={'id':'drive-1','title':'Quelle','content':'Version A','nodes':['finance']}
  self.assertTrue(server.ingest(p,'Import')['new_version']);self.assertFalse(server.ingest(p,'Import')['new_version'])
  p['content']='Version B';server.ingest(p,'Import')
  with server.db() as c:self.assertEqual(c.execute("SELECT count(*) FROM source_versions WHERE source_id='drive-1'").fetchone()[0],2)
 def test_03_private_api_and_mcp(self):
  c=TestClient(server.app)
  self.assertEqual(c.get('/api/graph').status_code,401)
  self.assertEqual(c.post('/mcp',json={'id':1,'method':'tools/list'}).status_code,401)
  r=c.post('/mcp',headers={'Authorization':'Bearer test-only'},json={'jsonrpc':'2.0','id':1,'method':'initialize'})
  self.assertEqual(r.json()['result']['serverInfo']['name'],'mandraya-assistant')
  r=c.post('/mcp',headers={'Authorization':'Bearer test-only'},json={'jsonrpc':'2.0','id':2,'method':'tools/list'})
  self.assertEqual(len(r.json()['result']['tools']),3)
 def test_04_proposal_cannot_change_concept(self):
  n=server.node_detail('world');p=server.proposal({'node_id':'world','content':'Vorschlag','reason':'Test'},'KI')
  self.assertEqual(server.node_detail('world')['content'],n['content'])
  self.assertTrue(p['id'])
if __name__=='__main__':unittest.main()
