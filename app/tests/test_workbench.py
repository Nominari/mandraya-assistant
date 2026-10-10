import os,tempfile,hashlib,time,json,secrets,unittest
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp())
import server
from workbench import basis
from fastapi.testclient import TestClient
class Workbench(unittest.TestCase):
 def setUp(self):
  self.client=TestClient(server.app);token=secrets.token_hex(12)
  with server.db() as c:c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),'person-b@example.com',int(time.time())+300))
  self.client.cookies.set('mandraya_session',token)
  self.sid=self.client.post('/api/explorations',json={'node_id':'play'}).json()['id']
 def review(self):
  rid=secrets.token_hex(12);r={'summary':'Zwei Wege untersucht','draft':'Neue Arbeitsfassung','next_steps':'Beispiel ausprobieren','variants':[{'title':'Wahl','content':'Freie Auswahl'}],'statements':['Es gibt mehrere Lösungswege.'],'questions':[{'node_id':'finance','question':'Welche Betreuung braucht es?','reason':'Zwei Wege benötigen Betreuung.'}]}
  with server.db() as c:c.execute('INSERT INTO work_reviews VALUES(?,?,?,?,?,?,?,0)',(rid,self.sid,'play',json.dumps(r),basis(c),'[]',server.now()))
  return rid,r
 def test_explicit_selection_and_individual_decision(self):
  rid,r=self.review();before=server.node_detail('play')['content']
  payload={**r,'draft':None,'reason':'Geprüft'}
  res=self.client.post('/api/work-reviews/'+rid+'/apply',json=payload);self.assertEqual(res.status_code,200,res.text)
  self.assertEqual(server.node_detail('play')['content'],before)
  n=self.client.get('/api/workbench/play').json();self.assertTrue(n['statements']);self.assertTrue(n['variants'])
  d=n['statements'][-1]
  self.assertEqual(self.client.post('/api/statements/'+d['id'],json={'action':'decide','version':d['version'],'content':'Andere Aussage','reason':'Test'}).status_code,423)
  self.assertEqual(self.client.post('/api/statements/'+d['id'],json={'action':'reopen','version':d['version'],'reason':'Neu prüfen'}).status_code,200)
  self.assertEqual(self.client.post('/api/statements/'+d['id'],json={'action':'decide','version':d['version'],'content':'Andere Aussage','reason':'Test'}).status_code,409)
  self.assertEqual(self.client.post('/api/work-reviews/'+rid+'/apply',json=payload).status_code,409)
  self.assertIn('Beispiel ausprobieren',self.client.get('/api/explorations/'+self.sid).json()['summary'])
 def test_project_change_blocks_review_and_no_partial_writes(self):
  rid,r=self.review();old=server.node_detail('world');server.change('world',{'version':old['version'],'content':old['content'],'reason':'Andere Änderung'},'person-a')
  self.assertEqual(self.client.post('/api/work-reviews/'+rid+'/apply',json={**r,'reason':'Geprüft'}).status_code,409)
  with server.db() as c:self.assertEqual(c.execute('SELECT applied FROM work_reviews WHERE id=?',(rid,)).fetchone()[0],0)
 def test_questions_shared_deduplicated_and_deferred(self):
  p={'node_id':'finance','origin_node':'play','session_id':self.sid,'question':'Testfrage '+self.sid,'reason':'Konkrete Auswirkung'}
  a=self.client.post('/api/work-questions',json=p).json();b=self.client.post('/api/work-questions',json=p).json();self.assertEqual(a['id'],b['id'])
  target=self.client.get('/api/workbench/finance').json();q=next(q for q in target['questions'] if q['id']==a['id'])
  self.assertEqual(q['origin_node'],'play');self.assertEqual(q['session_id'],self.sid)
  self.assertEqual(self.client.post('/api/work-questions/'+q['id'],json={'action':'defer','version':q['version'],'reason':'Später'}).status_code,200)
  self.assertEqual(self.client.post('/api/work-questions/'+q['id'],json={'action':'resolve','version':q['version'],'reason':'Erledigt','answer':'Antwort'}).status_code,409)
  q=next(x for x in self.client.get('/api/work-questions').json() if x['id']==a['id']);self.assertEqual(q['status'],'Zurückgestellt')
 def test_private_routes_and_unselected_items(self):
  rid,r=self.review()
  res=self.client.post('/api/work-reviews/'+rid+'/apply',json={'summary':'Nur Gesprächsstand','next_steps':'Später','draft':None,'variants':[],'statements':[],'questions':[],'reason':'Zwischenstand'});self.assertEqual(res.status_code,200,res.text)
  with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM work_variants WHERE session_id=?',(self.sid,)).fetchone()[0],0)
  self.client.cookies.clear();self.assertEqual(self.client.get('/api/work-questions').status_code,401)
  self.assertEqual(self.client.get('/api/workbench/play').status_code,401)
if __name__=='__main__':unittest.main()
