"""Shared explorations, explicit review, questions and individual decisions."""
import hashlib,json,secrets
from fastapi import HTTPException,Request

def setup(db):
 with db() as c:
  c.executescript('''
CREATE TABLE IF NOT EXISTS question_explorations(session_id TEXT PRIMARY KEY,question_id TEXT REFERENCES work_questions(id));
CREATE TABLE IF NOT EXISTS question_resolutions(id TEXT PRIMARY KEY,question_id TEXT,record_id TEXT,statement_id TEXT,answer TEXT,basis TEXT,evidence TEXT,actor TEXT,at TEXT);
CREATE TABLE IF NOT EXISTS source_foundations(node_id TEXT PRIMARY KEY,content TEXT,evidence TEXT,at TEXT);
CREATE TABLE IF NOT EXISTS explorations(id TEXT PRIMARY KEY,node_id TEXT REFERENCES nodes(id),title TEXT,summary TEXT DEFAULT '',basis TEXT DEFAULT '',version INTEGER DEFAULT 1,actor TEXT,at TEXT);
CREATE TABLE IF NOT EXISTS work_reviews(id TEXT PRIMARY KEY,session_id TEXT,node_id TEXT,content TEXT,basis TEXT,evidence TEXT,at TEXT,applied INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS node_briefs(node_id TEXT PRIMARY KEY,content TEXT,basis TEXT,evidence TEXT,at TEXT);
CREATE TABLE IF NOT EXISTS statements(id TEXT PRIMARY KEY,node_id TEXT REFERENCES nodes(id),content TEXT,status TEXT,version INTEGER DEFAULT 1,actor TEXT,at TEXT);
CREATE TABLE IF NOT EXISTS work_questions(id TEXT PRIMARY KEY,node_id TEXT REFERENCES nodes(id),origin_node TEXT,session_id TEXT,question TEXT,reason TEXT,status TEXT,answer TEXT DEFAULT '',version INTEGER DEFAULT 1,actor TEXT,at TEXT);
CREATE TABLE IF NOT EXISTS work_variants(id TEXT PRIMARY KEY,node_id TEXT,session_id TEXT,title TEXT,content TEXT,status TEXT DEFAULT 'Offen',actor TEXT,at TEXT);
''')

def branch_ids(c,nid):
 return [x[0] for x in c.execute('WITH RECURSIVE tree(id) AS (SELECT ? UNION SELECT n.id FROM nodes n JOIN tree t ON n.parent=t.id) SELECT id FROM tree',(nid,))]

def basis(c):
 # A review must not silently use a project snapshot that has since changed.
 data={}
 for name,query in {
  'nodes':'SELECT id,version FROM nodes ORDER BY id',
  'workshop_summaries':"SELECT id,version FROM explorations WHERE summary!='' ORDER BY id",
  'sources':'SELECT s.id,s.title,s.path,s.coverage,max(v.id) FROM sources s LEFT JOIN source_versions v ON v.source_id=s.id GROUP BY s.id ORDER BY s.id',
  'source_nodes':'SELECT source_id,node_id FROM source_nodes ORDER BY source_id,node_id',
  'source_policy':'SELECT source_id,status,edition,successor_id FROM source_policy ORDER BY source_id',
  'edges':'SELECT * FROM edges ORDER BY a,b',
  'statements':'SELECT id,version FROM statements ORDER BY id',
  'questions':'SELECT id,version FROM work_questions ORDER BY id',
  'variants':'SELECT id,status FROM work_variants ORDER BY id'
 }.items():data[name]=[tuple(x) for x in c.execute(query)]
 return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

def validate_review(raw,nodes):
 try:
  text=raw.strip()
  if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0]
  r=json.loads(text)
 except (ValueError,IndexError):raise ValueError('Der Zwischenstand war nicht strukturiert lesbar. Bitte erneut erstellen.')
 if not isinstance(r,dict):raise ValueError('Ungültiger Zwischenstand.')
 for k in ('summary','draft','next_steps'):
  if not isinstance(r.get(k),str) or len(r[k])>60000:raise ValueError('Ungültiger Zwischenstand.')
 for k in ('variants','statements','questions'):
  if not isinstance(r.get(k),list) or len(r[k])>12:raise ValueError('Zu viele Ergebnisse; bitte eingrenzen.')
 for x in r['statements']:
  if not isinstance(x,str) or not x.strip() or len(x)>6000:raise ValueError('Ungültige Aussage.')
 for x in r['variants']:
  if not isinstance(x,dict) or not all(isinstance(x.get(k),str) and 0<len(x[k])<=12000 for k in ('title','content')):raise ValueError('Ungültige Variante.')
 for x in r['questions']:
  if not isinstance(x,dict) or x.get('node_id') not in nodes or not all(isinstance(x.get(k),str) and 0<len(x[k])<=6000 for k in ('question','reason')):raise ValueError('Ungültige Frage oder Themenzuordnung.')
 return r

REVIEW_PROMPT='''Erstelle einen prüfbaren Zwischenstand unserer bisherigen Diskussion. Dies ist keine Entscheidung. Liefere ausschließlich ein JSON-Objekt mit summary (verständlicher Gesprächsstand), draft (vollständige vorgeschlagene Arbeitsfassung des ausgewählten Themas; leer, falls keine begründete Änderung), next_steps (Ansatz zum Fortsetzen), variants (Liste von {title,content}), statements (Liste präziser möglicher Beschlussaussagen), questions (Liste {node_id,question,reason}). Alle sechs Felder erforderlich. Nur tatsächlich diskutierte Ergebnisse; keine neuen Beschlüsse, Varianten oder Lücken erfinden. Bestehende Beschlüsse berücksichtigen. Die Menschen wählen und bearbeiten jedes Ergebnis. Bei Fragen nur konkrete entscheidungsbedürftige Auswirkungen aufnehmen, mögliche Zusammenhänge im summary belassen. Rückverweise und Unsicherheiten im Text nennen. Nur existierende node_id verwenden. Maximal zwölf Einträge je Liste. Kein Markdown-Codeblock.'''
BRIEF_PROMPT='''Erkläre den aktuellen Stand dieses Themas in maximal 180 Wörtern. Unterscheide ausdrücklich Beschlossenes, Arbeitsfassung, Quellenideen/Varianten und offene Fragen. Wenn etwas nicht vorliegt, bedeutet das nicht automatisch eine fachliche Lücke. Nenne die verwendeten Quellentitel und Fassungen. Keine Vorschläge als Beschlüsse ausgeben. Ein verständlicher Überblick, keine vollständige Dokumentprüfung behaupten.'''

def install(app,db,user,node_detail,now,log):
 def session(c,sid):
  r=c.execute('SELECT * FROM explorations WHERE id=?',(sid,)).fetchone()
  if not r:raise HTTPException(404,'Werkstatt nicht gefunden.')
  return dict(r)
 @app.get('/api/workbench/{nid}')
 def detail(nid:str,req:Request):
  user(req);n=node_detail(nid)
  with db() as c:
   f=c.execute('SELECT * FROM source_foundations WHERE node_id=?',(nid,)).fetchone();n['foundation']=dict(f) if f else None
   n['sessions']=[dict(r) for r in c.execute('SELECT * FROM explorations WHERE node_id=? ORDER BY at DESC',(nid,))]
   n['statements']=[dict(r) for r in c.execute('SELECT * FROM statements WHERE node_id=? ORDER BY at',(nid,))]
   ids=branch_ids(c,nid);n['questions']=[{**dict(r),'inherited':r['node_id']!=nid} for r in c.execute('SELECT * FROM work_questions WHERE node_id IN ('+','.join('?' for _ in ids)+') ORDER BY at',ids)]
   n['variants']=[dict(r) for r in c.execute('SELECT * FROM work_variants WHERE node_id=? ORDER BY at',(nid,))]
   r=c.execute('SELECT * FROM node_briefs WHERE node_id=?',(nid,)).fetchone()
   n['brief']=dict(r) if r else None
   if n['brief']:n['brief']['stale']=n['brief']['basis']!=basis(c)
  return n
 @app.post('/api/explorations')
 async def create(req:Request):
  actor=user(req);p=await req.json();n=node_detail(str(p.get('node_id','')))
  title=str(p.get('title','')).strip() or 'Gedanken weiterentwickeln'
  if len(title)>160:raise HTTPException(400,'Bitte einen kürzeren Titel verwenden.')
  sid=secrets.token_hex(12)
  with db() as c:
   c.execute('INSERT INTO explorations(id,node_id,title,actor,at) VALUES(?,?,?,?,?)',(sid,n['id'],title,actor,now()));log(c,actor,'Werkstatt begonnen',sid,None,{'node_id':n['id'],'title':title})
  return {'id':sid}
 @app.get('/api/explorations/{sid}')
 def get_session(sid:str,req:Request):
  user(req)
  with db() as c:
   r=session(c,sid);q=c.execute('SELECT q.* FROM work_questions q JOIN question_explorations x ON x.question_id=q.id WHERE x.session_id=?',(sid,)).fetchone();r['question']=dict(q) if q else None;f=c.execute('SELECT * FROM impact_findings WHERE session_id=? ORDER BY at DESC LIMIT 1',(sid,)).fetchone();r['impact']=dict(f) if f else None
   if r['impact']:r['impact']['stale']=r['impact']['basis']!=basis(c)
   r['stale']=bool(r['basis'] and r['basis']!=basis(c))
   rev=c.execute('SELECT * FROM work_reviews WHERE session_id=? ORDER BY rowid DESC LIMIT 1',(sid,)).fetchone()
   r['review']=dict(rev) if rev else None
   if r['review']:
    r['review']['stale']=r['review']['basis']!=basis(c);r['review']['content']=json.loads(r['review']['content'])
  return r
 @app.get('/api/work-questions')
 def questions(req:Request):
  user(req)
  with db() as c:return [dict(r) for r in c.execute('SELECT q.*,n.title node_title,o.title origin_title FROM work_questions q JOIN nodes n ON n.id=q.node_id JOIN nodes o ON o.id=q.origin_node ORDER BY q.at DESC')]
 @app.post('/api/work-questions')
 async def question_create(req:Request):
  actor=user(req);p=await req.json();nid=str(p.get('node_id',''));origin=str(p.get('origin_node',''));node_detail(nid);node_detail(origin)
  question=str(p.get('question','')).strip();reason=str(p.get('reason','')).strip();sid=p.get('session_id')
  if not question or not reason or len(question)>6000 or len(reason)>6000:raise HTTPException(400,'Frage und Begründung erforderlich (maximal 6.000 Zeichen).')
  with db() as c:
   c.execute('BEGIN IMMEDIATE')
   if sid and session(c,sid)['node_id']!=origin:raise HTTPException(400,'Diskussion gehört zu einem anderen Ursprungsthema.')
   existing=c.execute("SELECT id FROM work_questions WHERE node_id=? AND question=? AND status!='Geklärt'",(nid,question)).fetchone()
   if existing:return {'id':existing['id'],'existing':True}
   qid=secrets.token_hex(12);c.execute('INSERT INTO work_questions(id,node_id,origin_node,session_id,question,reason,status,actor,at) VALUES(?,?,?,?,?,?,?,?,?)',(qid,nid,origin,sid,question,reason,'Offen',actor,now()));log(c,actor,'Offene Frage festgehalten',qid,None,p)
  return {'id':qid}
 @app.post('/api/statements')
 async def statement_create(req:Request):
  actor=user(req);p=await req.json();nid=str(p.get('node_id',''));node_detail(nid);content=str(p.get('content','')).strip();reason=str(p.get('reason','')).strip()
  if not content or not reason or len(content)>6000 or len(reason)>6000:raise HTTPException(400,'Aussage und Begründung erforderlich (maximal 6.000 Zeichen).')
  with db() as c:
   c.execute('BEGIN IMMEDIATE')
   existing=c.execute("SELECT id FROM statements WHERE node_id=? AND content=? AND status='Beschlossen'",(nid,content)).fetchone()
   if existing:return {'id':existing['id'],'existing':True}
   did=secrets.token_hex(12);c.execute('INSERT INTO statements(id,node_id,content,status,actor,at) VALUES(?,?,?,?,?,?)',(did,nid,content,'Beschlossen',actor,now()));log(c,actor,'Aussage beschlossen',did,None,{'content':content,'node_id':nid,'reason':reason})
  return {'id':did}
 @app.post('/api/work-questions/{qid}/explore')
 async def explore_question(qid:str,req:Request):
  actor=user(req)
  with db() as c:
   c.execute('BEGIN IMMEDIATE');q=c.execute('SELECT * FROM work_questions WHERE id=?',(qid,)).fetchone()
   if not q:raise HTTPException(404,'Frage nicht gefunden.')
   if q['status']=='Geklärt':raise HTTPException(409,'Die Frage ist bereits geklärt. Zum Weiterbearbeiten zuerst wieder öffnen.')
   old=c.execute('SELECT session_id FROM question_explorations WHERE question_id=? ORDER BY rowid DESC LIMIT 1',(qid,)).fetchone()
   if old:return {'id':old[0]}
   sid=secrets.token_hex(12);c.execute('INSERT INTO explorations(id,node_id,title,actor,at) VALUES(?,?,?,?,?)',(sid,q['node_id'],'Klärung: '+q['question'][:145],actor,now()));c.execute('INSERT INTO question_explorations VALUES(?,?)',(sid,qid));log(c,actor,'Frage mit KI untersuchen',qid,None,{'session_id':sid})
  return {'id':sid}
 @app.post('/api/work-questions/{qid}')
 async def question_change(qid:str,req:Request):
  actor=user(req);p=await req.json();reason=str(p.get('reason','')).strip()
  if not reason or len(reason)>6000:raise HTTPException(400,'Bitte eine kurze Begründung angeben.')
  target={'defer':'Zurückgestellt','resolve':'Geklärt','reopen':'Offen'}.get(p.get('action'))
  if not target:raise HTTPException(400,'Ungültige Änderung.')
  answer=str(p.get('answer','')).strip()
  if target=='Geklärt' and (not answer or len(answer)>12000):raise HTTPException(400,'Bitte das Ergebnis der Klärung festhalten.')
  with db() as c:
   c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM work_questions WHERE id=?',(qid,)).fetchone()
   if not old:raise HTTPException(404,'Frage nicht gefunden.')
   if p.get('version')!=old['version']:raise HTTPException(409,'Die Frage wurde inzwischen geändert.')
   c.execute('UPDATE work_questions SET status=?,answer=?,version=version+1 WHERE id=?',(target,answer if target=='Geklärt' else old['answer'],qid));log(c,actor,'Frage '+target,qid,dict(old),{'status':target,'answer':answer,'reason':reason})
  return {'ok':True}
 @app.post('/api/statements/{did}')
 async def statement_change(did:str,req:Request):
  actor=user(req);p=await req.json();reason=str(p.get('reason','')).strip()
  if not reason or len(reason)>6000:raise HTTPException(400,'Bitte eine Begründung angeben.')
  with db() as c:
   c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM statements WHERE id=?',(did,)).fetchone()
   if not old:raise HTTPException(404,'Aussage nicht gefunden.')
   if old['version']!=p.get('version'):raise HTTPException(409,'Aussage wurde inzwischen geändert.')
   action=p.get('action')
   if action=='reopen':status='Wieder geöffnet';content=old['content']
   elif action=='decide' and old['status']=='Wieder geöffnet':
    status='Beschlossen';content=str(p.get('content','')).strip()
    if not content or len(content)>6000:raise HTTPException(400,'Bitte eine präzise Aussage formulieren.')
   else:raise HTTPException(423,'Beschlossene Aussage zuerst ausdrücklich wieder öffnen.')
   c.execute('UPDATE statements SET content=?,status=?,version=version+1 WHERE id=?',(content,status,did));log(c,actor,'Aussage '+status,did,dict(old),{'content':content,'status':status,'reason':reason})
  return {'ok':True}
 @app.post('/api/work-reviews/{rid}/apply')
 async def apply(rid:str,req:Request):
  actor=user(req);p=await req.json();reason=str(p.get('reason','')).strip()
  if not reason or len(reason)>6000:raise HTTPException(400,'Bitte eine Begründung angeben.')
  # The human submits only the edited items explicitly selected in the review UI.
  with db() as c:
   c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT * FROM work_reviews WHERE id=?',(rid,)).fetchone()
   if not r or r['applied']:raise HTTPException(409,'Dieser Zwischenstand wurde bereits übernommen.')
   receipt=json.loads(r['evidence'])
   session_versions=[x for x in receipt if x.get('session_version') is not None]
   if session_versions and session(c,r['session_id'])['version']!=session_versions[0]['session_version']:raise HTTPException(409,'Ein anderer Zwischenstand dieser Werkstatt wurde übernommen. Bitte neu prüfen.')
   if r['basis']!=basis(c):raise HTTPException(409,'Der Projektstand hat sich geändert. Bitte den Zwischenstand neu erstellen und prüfen.')
   n=c.execute('SELECT * FROM nodes WHERE id=?',(r['node_id'],)).fetchone()
   summary=str(p.get('summary','')).strip();next_steps=str(p.get('next_steps','')).strip()
   try:chosen=validate_review(json.dumps({'summary':summary,'next_steps':next_steps,'draft':str(p.get('draft') or ''),'variants':p.get('variants',[]),'statements':p.get('statements',[]),'questions':p.get('questions',[])},ensure_ascii=False),{x[0] for x in c.execute('SELECT id FROM nodes')})
   except ValueError as exc:raise HTTPException(400,str(exc))
   if not summary:raise HTTPException(400,'Bitte den Zwischenstand verständlich zusammenfassen.')
   if p.get('draft') is not None:
    if n['locked']:raise HTTPException(423,'Die bisherige Gesamtfassung ist geschützt. Zuerst ausdrücklich wieder öffnen.')
    c.execute('INSERT INTO revisions(node_id,version,snapshot,actor,reason,at) VALUES(?,?,?,?,?,?)',(n['id'],n['version'],json.dumps(dict(n)),actor,reason,now()))
    c.execute("UPDATE nodes SET content=?,version=version+1,stage='In Bearbeitung' WHERE id=?",(chosen['draft'],n['id']));log(c,actor,'Arbeitsfassung übernommen',n['id'],dict(n),{'content':chosen['draft'],'reason':reason})
   for content in chosen['statements']:
    if c.execute("SELECT 1 FROM statements WHERE node_id=? AND content=? AND status='Beschlossen'",(n['id'],content)).fetchone():continue
    did=secrets.token_hex(12);c.execute('INSERT INTO statements(id,node_id,content,status,actor,at) VALUES(?,?,?,?,?,?)',(did,n['id'],content,'Beschlossen',actor,now()));log(c,actor,'Aussage beschlossen',did,None,{'content':content,'node_id':n['id'],'reason':reason})
   for x in chosen['questions']:
    existing=c.execute("SELECT id FROM work_questions WHERE node_id=? AND question=? AND status!='Geklärt'",(x['node_id'],x['question'])).fetchone()
    if existing:continue
    qid=secrets.token_hex(12);c.execute('INSERT INTO work_questions(id,node_id,origin_node,session_id,question,reason,status,actor,at) VALUES(?,?,?,?,?,?,?,?,?)',(qid,x['node_id'],n['id'],r['session_id'],x['question'],x['reason'],'Offen',actor,now()));log(c,actor,'Offene Frage festgehalten',qid,None,x)
   for x in chosen['variants']:
    if c.execute('SELECT 1 FROM work_variants WHERE session_id=? AND title=? AND content=?',(r['session_id'],x['title'],x['content'])).fetchone():continue
    c.execute('INSERT INTO work_variants(id,node_id,session_id,title,content,actor,at) VALUES(?,?,?,?,?,?,?)',(secrets.token_hex(12),n['id'],r['session_id'],x['title'],x['content'],actor,now()))
   kept=summary+('\n\nWeiterarbeiten: '+next_steps if next_steps else '')
   c.execute('UPDATE explorations SET summary=?,basis=?,version=version+1 WHERE id=?',(kept,basis(c),r['session_id']))
   c.execute('UPDATE work_reviews SET applied=1 WHERE id=?',(rid,));log(c,actor,'Zwischenstand geprüft und übernommen',rid,json.loads(r['content']),{**chosen,'reason':reason})
  return {'ok':True}
