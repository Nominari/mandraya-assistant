"""AI-prepared records, confirmed and optionally edited by a person."""
import json,secrets
from fastapi import HTTPException,Request
from workbench import basis

def setup(c):
 c.execute('CREATE TABLE IF NOT EXISTS chat_records(id TEXT PRIMARY KEY,message_id TEXT,session_id TEXT,origin_node TEXT,node_id TEXT,kind TEXT,title TEXT,content TEXT,reason TEXT,basis TEXT,evidence TEXT,status TEXT DEFAULT \'Entwurf\')')

 c.execute('CREATE TABLE IF NOT EXISTS chat_grounding(message_id TEXT PRIMARY KEY,basis TEXT,at TEXT,receipt TEXT)')
 columns={x[1] for x in c.execute('PRAGMA table_info(chat_records)')}
 for name,typ in [('question_id','TEXT'),('question_version','INTEGER')]:
  if name not in columns:c.execute('ALTER TABLE chat_records ADD COLUMN '+name+' '+typ)

def prepare(c,args,mid,sid,origin,snapshot,evidence,actor,now,log):
 if not sid:raise ValueError('Entwürfe sind nur in einer Werkstatt möglich.')
 kind=args['kind'];nid=args['node_id'];content=args['content'].strip();reason=args['reason'].strip();title=args['title'].strip()
 if kind not in ('statement','question','variant','working') or not content or len(content)>60000 or not reason or len(reason)>6000:raise ValueError('Ungültiger Entwurf')
 if not c.execute('SELECT 1 FROM nodes WHERE id=?',(nid,)).fetchone():raise ValueError('Thema nicht gefunden')
 if kind=='statement' and len(content)>6000:raise ValueError('Aussage bitte präziser formulieren')
 if kind=='question' and len(content)>6000:raise ValueError('Frage bitte kürzer formulieren')
 if kind=='variant' and (not title or len(title)>160):raise ValueError('Variantenname erforderlich')
 if kind=='question':
  normalize=lambda text:' '.join(text.casefold().split())
  for q in c.execute("SELECT id,question FROM work_questions WHERE status NOT IN ('Geklärt','Archiviert')"):
   if normalize(q['question'])==normalize(content):return {'existing_question_id':q['id'],'status':'Diese offene Frage ist bereits festgehalten; keine Dublette vorbereitet.','saved_as_decision':False}
  for r in c.execute("SELECT id,content FROM chat_records WHERE kind='question' AND status='Entwurf' AND basis=?",(snapshot,)):
   if normalize(r['content'])==normalize(content):return {'existing_draft_id':r['id'],'status':'Dieser Fragenentwurf liegt bereits zur Prüfung vor.','saved_as_decision':False}
 rid=secrets.token_hex(12)
 c.execute('INSERT INTO chat_records(id,message_id,session_id,origin_node,node_id,kind,title,content,reason,basis,evidence) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(rid,mid,sid,origin,nid,kind,title,content,reason,snapshot,json.dumps(list(evidence.values()))))
 log(c,actor,'KI-Entwurf vorbereitet',rid,None,{'kind':kind,'node_id':nid,'content':content})
 return {'draft_id':rid,'status':'Entwurf wartet auf menschliche Prüfung','saved_as_decision':False}

def prepare_resolution(c,args,mid,sid,origin,snapshot,evidence,actor,now,log):
 q=c.execute('SELECT q.* FROM work_questions q JOIN question_explorations x ON x.question_id=q.id WHERE x.session_id=? AND q.id=?',(sid,args['question_id'])).fetchone()
 if not q or q['status'] in ('Geklärt','Archiviert'):raise ValueError('Nur die offene Frage dieser Werkstatt kann hier geklärt werden.')
 answer=args['answer'].strip();decision=args['decision'].strip();reason=args['reason'].strip()
 if not answer or len(answer)>12000 or len(decision)>6000 or not reason or len(reason)>6000:raise ValueError('Ungültiges Ergebnis')
 rid=secrets.token_hex(12)
 c.execute('INSERT INTO chat_records(id,message_id,session_id,origin_node,node_id,kind,title,content,reason,basis,evidence,question_id,question_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(rid,mid,sid,origin,q['node_id'],'resolution',decision,answer,reason,snapshot,json.dumps(list(evidence.values())),q['id'],q['version']))
 log(c,actor,'Klärungsentwurf vorbereitet',rid,None,{'question_id':q['id'],'answer':answer,'decision':decision})
 return {'draft_id':rid,'saved_as_decision':False,'status':'Ergebnis und optionaler Beschluss warten auf menschliche Bestätigung'}

def install(app,db,user,now,log):
 @app.post('/api/chat-records/{rid}')
 async def confirm(rid:str,req:Request):
  actor=user(req);p=await req.json()
  with db() as c:
   c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT * FROM chat_records WHERE id=?',(rid,)).fetchone()
   if not r or r['status']!='Entwurf':raise HTTPException(409,'Dieser Entwurf ist nicht mehr offen.')
   r=dict(r)
   if p.get('action')=='reject':
    c.execute("UPDATE chat_records SET status='Verworfen' WHERE id=?",(rid,));log(c,actor,'KI-Entwurf verworfen',rid,r,None);return {'ok':True}
   if p.get('action')!='confirm':raise HTTPException(400,'Ungültige Aktion.')
   m=c.execute("SELECT 1 FROM chat_messages WHERE id=? AND status='completed'",(r['message_id'],)).fetchone()
   if not m:raise HTTPException(409,'Bitte erst die vollständige Antwort abwarten.')
   if r['basis']!=basis(c):raise HTTPException(409,'Die Projektgrundlage hat sich geändert. Bitte den Entwurf im Chat neu prüfen lassen.')
   content=str(p.get('content',r['content'])).strip();reason=str(p.get('reason',r['reason'])).strip();title=str(p.get('title',r['title'])).strip();nid=str(p.get('node_id',r['node_id']))
   if not content or len(content)>60000 or not reason or len(reason)>6000:raise HTTPException(400,'Inhalt und Begründung erforderlich.')
   n=c.execute('SELECT * FROM nodes WHERE id=?',(nid,)).fetchone()
   if not n:raise HTTPException(404,'Thema nicht gefunden.')
   entity=secrets.token_hex(12)
   if r['kind']=='resolution':
    q=c.execute('SELECT * FROM work_questions WHERE id=?',(r['question_id'],)).fetchone()
    if not q or q['status'] in ('Geklärt','Archiviert') or q['version']!=r['question_version']:raise HTTPException(409,'Die Frage wurde geändert. Bitte das Ergebnis neu prüfen lassen.')
    if nid!=q['node_id'] or len(content)>12000:raise HTTPException(400,'Das Ergebnis muss bei der ursprünglichen Frage bleiben (maximal 12.000 Zeichen).')
    if p.get('decide',False) is not False and p.get('decide') is not True:raise HTTPException(400,'Beschluss ausdrücklich auswählen.')
    statement_id=None
    if p.get('decide') is True:
     if not title or len(title)>6000:raise HTTPException(400,'Bitte eine präzise Beschlussaussage formulieren.')
     existing=c.execute("SELECT id FROM statements WHERE node_id=? AND content=? AND status='Beschlossen'",(nid,title)).fetchone()
     statement_id=existing['id'] if existing else secrets.token_hex(12)
     if not existing:c.execute('INSERT INTO statements(id,node_id,content,status,actor,at) VALUES(?,?,?,?,?,?)',(statement_id,nid,title,'Beschlossen',actor,now()))
     log(c,actor,'Aussage beschlossen',statement_id,None,{'content':title,'question_id':q['id'],'reason':reason})
    c.execute("UPDATE work_questions SET answer=?,status='Geklärt',version=version+1 WHERE id=?",(content,q['id']))
    c.execute('INSERT INTO question_resolutions VALUES(?,?,?,?,?,?,?,?,?)',(entity,q['id'],rid,statement_id,content,r['basis'],r['evidence'],actor,now()))
    log(c,actor,'Frage Geklärt',q['id'],dict(q),{'answer':content,'statement_id':statement_id,'reason':reason})
   elif r['kind']=='statement':
    if len(content)>6000:raise HTTPException(400,'Aussage ist zu lang.')
    existing=c.execute("SELECT id FROM statements WHERE node_id=? AND content=? AND status='Beschlossen'",(nid,content)).fetchone()
    if existing:entity=existing['id']
    else:c.execute('INSERT INTO statements(id,node_id,content,status,actor,at) VALUES(?,?,?,?,?,?)',(entity,nid,content,'Beschlossen',actor,now()))
   elif r['kind']=='question':
    if len(content)>6000:raise HTTPException(400,'Frage ist zu lang.')
    existing=c.execute("SELECT id FROM work_questions WHERE node_id=? AND question=? AND status NOT IN ('Geklärt','Archiviert')",(nid,content)).fetchone()
    if existing:entity=existing['id']
    else:c.execute('INSERT INTO work_questions(id,node_id,origin_node,session_id,question,reason,status,actor,at) VALUES(?,?,?,?,?,?,?,?,?)',(entity,nid,r['origin_node'],r['session_id'],content,reason,'Offen',actor,now()))
   elif r['kind']=='variant':
    if not title or len(title)>160:raise HTTPException(400,'Variantenname erforderlich.')
    c.execute('INSERT INTO work_variants(id,node_id,session_id,title,content,actor,at) VALUES(?,?,?,?,?,?,?)',(entity,nid,r['session_id'],title,content,actor,now()))
   else:
    if n['locked']:raise HTTPException(423,'Gesamtfassung zuerst ausdrücklich wieder öffnen.')
    c.execute('INSERT INTO revisions(node_id,version,snapshot,actor,reason,at) VALUES(?,?,?,?,?,?)',(nid,n['version'],json.dumps(dict(n)),actor,reason,now()));c.execute("UPDATE nodes SET content=?,version=version+1,stage='In Bearbeitung' WHERE id=?",(content,nid));entity=nid
   c.execute("UPDATE chat_records SET status='Übernommen' WHERE id=?",(rid,))
   if content==r['content'] and nid==r['node_id'] and title==r['title']:
    c.execute("UPDATE chat_records SET basis=? WHERE message_id=? AND status='Entwurf' AND basis=?",(basis(c),r['message_id'],r['basis']))
   log(c,actor,'Chat-Entwurf bestätigt',entity,r,{'draft_id':rid,'kind':r['kind'],'content':content,'reason':reason,'node_id':nid})
  return {'ok':True,'entity_id':entity}
