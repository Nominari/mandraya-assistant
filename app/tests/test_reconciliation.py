import os,tempfile,json,secrets,time,hashlib,unittest
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
import server,reconciliation,impact
from workbench import basis
from fastapi.testclient import TestClient
class Reconciliation(unittest.TestCase):
 def setUp(self):
  self.client=TestClient(server.app);token=secrets.token_hex(12)
  with server.db() as c:
   c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),'test@example.com',int(time.time())+1000))
   c.execute("UPDATE nodes SET locked=0 WHERE id='digital'")
  self.client.cookies.set('mandraya_session',token)
  n=server.node_detail('digital');server.change('digital',{'version':n['version'],'content':'Bisheriger Ablauf mit alter Mechanik. Unberührte Information bleibt.','reason':'Test'},'Test')
  self.q=[]
  for text in ['Welcher Mechanismus gilt?','Wie setzen wir den alten Mechanismus um?','Bleibt der alte Mechanismus parallel?']:
   self.q.append(self.client.post('/api/work-questions',json={'node_id':'digital','origin_node':'play-2','question':text+' '+token,'reason':'Test'}).json()['id'])
 def prepare(self):
  with server.db() as c:
   node=dict(c.execute("SELECT * FROM nodes WHERE id='digital'").fetchone());proof={'node':{'node_id':'digital','version':node['version'],'title':'Website','complete':True}}
   raw=[]
   for q,action in zip(self.q,['resolve','revise','archive']):raw.append({'kind':'question','target_id':q,'action':action,'content':'Wie setzen wir den beschlossenen Mechanismus konkret um?' if action=='revise' else '', 'answer':'Neuer Mechanismus ist beschlossen; der Umsetzungsteil bleibt gegebenenfalls offen.','reason':'Folge eines bestätigten Beschlusses.','proof_keys':['node']})
   raw.append({'kind':'working','target_id':'digital','action':'update','content':'Neuer Mechanismus gilt. Unberührte Information bleibt.','answer':'','reason':'Beschluss redaktionell übernehmen.','proof_keys':['node']})
   updates=reconciliation.validate_updates(c,raw,proof);job={'id':secrets.token_hex(12),'basis':basis(c)};reconciliation.prepare(c,job,{'summary':'Vier bestehende Punkte abgleichen.'},updates,server.now,server.log)
   batch=reconciliation.batches(c)[0]
  return batch
 def test_preparation_does_not_change_project(self):
  before=server.node_detail('digital');b=self.prepare();self.assertEqual(server.node_detail('digital')['content'],before['content'])
  with server.db() as c:self.assertTrue(all(c.execute('SELECT status FROM work_questions WHERE id=?',(q,)).fetchone()[0]=='Offen' for q in self.q))
  self.assertEqual(len(b['items']),4)
 def test_batch_selection_preserves_ids_and_archives_working_draft(self):
  b=self.prepare();r=self.client.post('/api/reconcile/'+b['id'],json={'action':'apply','items':[{'id':i['id']} for i in b['items']],'reason':'Gemeinsam geprüft'});self.assertEqual(r.status_code,200,r.text)
  with server.db() as c:
   self.assertEqual([c.execute('SELECT status FROM work_questions WHERE id=?',(q,)).fetchone()[0] for q in self.q],['Geklärt','Offen','Archiviert'])
   self.assertTrue(c.execute("SELECT 1 FROM revisions WHERE node_id='digital' AND snapshot LIKE '%Bisheriger Ablauf%' ").fetchone())
   self.assertEqual(c.execute("SELECT content FROM nodes WHERE id='digital'").fetchone()[0],'Neuer Mechanismus gilt. Unberührte Information bleibt.')
  self.assertEqual(self.client.post('/api/reconcile/'+b['id'],json={'action':'apply','items':[],'reason':'Test'}).status_code,409)
 def test_partial_selection_leaves_other_items_reviewable(self):
  b=self.prepare();first=b['items'][0];self.assertEqual(self.client.post('/api/reconcile/'+b['id'],json={'action':'apply','items':[{'id':first['id']}],'reason':'Einzeln geprüft'}).status_code,200)
  with server.db() as c:r=next(x for x in reconciliation.batches(c) if x['id']==b['id']);self.assertEqual(len(r['items']),3);self.assertFalse(r['stale'])
 def test_stale_and_locked_targets_block_entire_batch(self):
  b=self.prepare()
  with server.db() as c:c.execute("UPDATE nodes SET locked=1 WHERE id='digital'")
  r=self.client.post('/api/reconcile/'+b['id'],json={'action':'apply','items':[{'id':i['id']} for i in b['items']],'reason':'Test'});self.assertEqual(r.status_code,423)
  with server.db() as c:
   self.assertEqual(c.execute('SELECT status FROM work_questions WHERE id=?',(self.q[0],)).fetchone()[0],'Offen');c.execute("UPDATE nodes SET locked=0,version=version+1 WHERE id='digital'")
  self.assertEqual(self.client.post('/api/reconcile/'+b['id'],json={'action':'apply','items':[{'id':b['items'][0]['id']}],'reason':'Test'}).status_code,409)
 def test_rejection_and_empty_selection_do_not_apply(self):
  b=self.prepare();self.assertEqual(self.client.post('/api/reconcile/'+b['id'],json={'action':'apply','items':[],'reason':'Test'}).status_code,400)
  self.assertEqual(self.client.post('/api/reconcile/'+b['id'],json={'action':'reject'}).status_code,200)
  with server.db() as c:self.assertEqual(c.execute('SELECT status FROM work_questions WHERE id=?',(self.q[0],)).fetchone()[0],'Offen')
  self.client.cookies.clear();self.assertEqual(self.client.post('/api/reconcile/'+b['id'],json={'action':'reject'}).status_code,401)
 def test_full_draft_requires_complete_target_context(self):
  with server.db() as c:
   with self.assertRaises(ValueError):reconciliation.validate_updates(c,[{'kind':'working','target_id':'digital','action':'update','content':'Neu','answer':'','reason':'Test','proof_keys':['partial']}],{'partial':{'node_id':'digital','complete':False}})
 def test_worker_result_generates_reconciliation_without_canonical_edits(self):
  b=self.prepare()
  with server.db() as c:
   c.execute('DELETE FROM reconcile_items WHERE batch_id=?',(b['id'],));c.execute('DELETE FROM reconcile_batches WHERE id=?',(b['id'],));jid=impact.enqueue(c,'test@example.com','save','digital');job=dict(c.execute('SELECT * FROM impact_jobs WHERE id=?',(jid,)).fetchone());job['basis']=basis(c)
   result={'summary':'Abgleich','findings':[],'updates':[{'kind':'question','target_id':self.q[0],'action':'resolve','content':'','answer':'Durch Beschluss beantwortet.','reason':'Test','proof_keys':['node']}]}
   impact.apply_result(c,job,result,{'node':{'node_id':'digital','version':c.execute("SELECT version FROM nodes WHERE id='digital'").fetchone()[0],'complete':True}},'test',server.now,server.log)
   self.assertTrue(reconciliation.batches(c));self.assertEqual(c.execute('SELECT status FROM work_questions WHERE id=?',(self.q[0],)).fetchone()[0],'Offen')
