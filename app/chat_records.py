"""AI-prepared records, confirmed and optionally edited by a person."""
import json,secrets
from fastapi import HTTPException,Request
from workbench import basis

def setup(c):
 c.execute('CREATE TABLE IF NOT EXISTS chat_records(id TEXT PRIMARY KEY,message_id TEXT,session_id TEXT,origin_node TEXT,node_id TEXT,kind TEXT,title TEXT,content TEXT,reason TEXT,basis TEXT,evidence TEXT,status TEXT DEFAULT \'Entwurf\')')

def prepare(c,args,mid,sid,origin,snapshot,evidence,actor,now,log):
 if not sid:raise ValueError('Entwürfe sind nur in einer Werkstatt möglich.')
 kind=args['kind'];nid=args['node_id'];content=args['content'].strip();reason=args['reason'].strip();title=args['title'].strip()
 if kind not in ('statement','question','variant','working') or not content or len(content)>60000 or not reason or len(reason)>6000:raise ValueError('Ungültiger Entwurf')
 if not c.execute('SELECT 1 FROM nodes WHERE id=?',(nid,)).fetchone():raise ValueError('Thema nicht gefunden')
 if kind=='statement' and len(content)>6000:raise ValueError('Aussage bitte präziser formulieren')
 if kind=='question' and len(content)>6000:raise ValueError('Frage bitte kürzer formulieren')
 if kind=='variant' and (not title or len(title)>160):raise ValueError('Variantenname erforderlich')
 rid=secrets.token_hex(12)
 c.execute('INSERT INTO chat_records(id,message_id,session_id,origin_node,node_id,kind,title,content,reason,basis,evidence) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(rid,mid,sid,origin,nid,kind,title,content,reason,snapshot,json.dumps(list(evidence.values()))))
 log(c,actor,'KI-Entwurf vorbereitet',rid,None,{'kind':kind,'node_id':nid,'content':content})
 return {'draft_id':rid,'status':'Entwurf wartet auf menschliche Prüfung','saved_as_decision':False}

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
   if r['kind']=='statement':
    if len(content)>6000:raise HTTPException(400,'Aussage ist zu lang.')
    existing=c.execute("SELECT id FROM statements WHERE node_id=? AND content=? AND status='Beschlossen'",(nid,content)).fetchone()
    if existing:entity=existing['id']
    else:c.execute('INSERT INTO statements(id,node_id,content,status,actor,at) VALUES(?,?,?,?,?,?)',(entity,nid,content,'Beschlossen',actor,now()))
   elif r['kind']=='question':
    if len(content)>6000:raise HTTPException(400,'Frage ist zu lang.')
    existing=c.execute("SELECT id FROM work_questions WHERE node_id=? AND question=? AND status!='Geklärt'",(nid,content)).fetchone()
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
