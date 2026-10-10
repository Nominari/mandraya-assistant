"""Reviewable updates to existing questions and working drafts; no AI approvals."""
import json,secrets
from fastapi import Request,HTTPException
from workbench import basis

def setup(c):
 c.executescript('''CREATE TABLE IF NOT EXISTS reconcile_batches(id TEXT PRIMARY KEY,job_id TEXT,basis TEXT,summary TEXT,status TEXT,at TEXT);
CREATE TABLE IF NOT EXISTS reconcile_items(id TEXT PRIMARY KEY,batch_id TEXT,kind TEXT,target_id TEXT,action TEXT,before_json TEXT,after_json TEXT,reason TEXT,evidence TEXT,status TEXT);''')

def validate_updates(c,updates,proofs):
 if not isinstance(updates,list) or len(updates)>12:raise ValueError('Zu viele oder ungültige Abgleichsvorschläge.')
 result=[];seen=set()
 for u in updates:
  if not isinstance(u,dict) or u.get('kind') not in ('question','working'):raise ValueError('Ungültiger Abgleichstyp.')
  kind=u['kind'];target=u.get('target_id');action=u.get('action');keys=u.get('proof_keys')
  if not isinstance(target,str) or (kind,target) in seen:raise ValueError('Abgleichsziel fehlt oder ist doppelt.')
  seen.add((kind,target))
  if not isinstance(keys,list) or not keys or any(not isinstance(k,str) or k not in proofs for k in keys):raise ValueError('Abgleich benötigt gelesene Belege.')
  reason=u.get('reason');content=u.get('content','');answer=u.get('answer','')
  if not isinstance(reason,str) or not reason.strip() or len(reason)>6000 or not isinstance(content,str) or not isinstance(answer,str):raise ValueError('Begründung und gültiger Vorschlag erforderlich.')
  table='work_questions' if kind=='question' else 'nodes';r=c.execute('SELECT * FROM '+table+' WHERE id=?',(target,)).fetchone()
  if not r:raise ValueError('Abgleichsziel nicht gefunden.')
  before=dict(r);nid=before['node_id'] if kind=='question' else target
  context_version=c.execute('SELECT version FROM nodes WHERE id=?',(nid,)).fetchone()[0]
  if not any(proofs[k].get('node_id')==nid and not proofs[k].get('statement_id') and proofs[k].get('version')==context_version for k in keys):raise ValueError('Aktuellen Stand des betroffenen Themas zuerst nachladen.')
  if kind=='question':
   if before['status'] in ('Geklärt','Archiviert') or action not in ('resolve','revise','archive'):raise ValueError('Nur offene Fragen abgleichen.')
   if len(content)>6000 or not answer.strip() or len(answer)>12000:raise ValueError('Klärung bzw. verbleibende Frage verständlich erläutern.')
   if action=='revise' and not content.strip():raise ValueError('Verbleibende Frage erforderlich.')
   after={'question':content.strip() if action=='revise' else before['question'],'answer':answer.strip(),'status':'Geklärt' if action=='resolve' else 'Archiviert' if action=='archive' else before['status']}
  else:
   if any(proofs[k].get('node_id')==nid and proofs[k].get('complete') is False for k in keys):raise ValueError('Für einen vollständigen Ersatz muss die bisherige Fassung vollständig gelesen sein.')
   if action!='update' or before['locked'] or not content.strip() or len(content)>60000:raise ValueError('Nur ungeschützte Arbeitsfassungen können als vollständiger Entwurf aktualisiert werden.')
   after={'content':content.strip(),'stage':'In Bearbeitung'}
   if after['content']==before['content']:continue
  if kind=='question' and all(after[k]==before[k] for k in ('question','answer','status')):continue
  result.append({'kind':kind,'target_id':target,'action':action,'before':before,'after':after,'reason':reason.strip(),'evidence':[proofs[k] for k in keys]})
 return result

def prepare(c,job,result,updates,now,log):
 if not updates:return
 # Same target and replacement at the same basis are not proposed twice.
 pending=c.execute("SELECT i.*,b.basis FROM reconcile_items i JOIN reconcile_batches b ON b.id=i.batch_id WHERE i.status IN ('Offen','Verworfen')").fetchall()
 updates=[u for u in updates if not any(x['basis']==job['basis'] and x['kind']==u['kind'] and x['target_id']==u['target_id'] and json.loads(x['after_json'])==u['after'] for x in pending)]
 if not updates:return
 bid=secrets.token_hex(12);c.execute('INSERT INTO reconcile_batches VALUES(?,?,?,?,?,?)',(bid,job['id'],job['basis'],result['summary'],'Offen',now()))
 for u in updates:
  c.execute('INSERT INTO reconcile_items VALUES(?,?,?,?,?,?,?,?,?,?)',(secrets.token_hex(12),bid,u['kind'],u['target_id'],u['action'],json.dumps(u['before'],ensure_ascii=False),json.dumps(u['after'],ensure_ascii=False),u['reason'],json.dumps(u['evidence'],ensure_ascii=False),'Offen'))
 log(c,'Automatische KI-Prüfung','Abgleich vorbereitet',bid,None,{'items':len(updates),'job_id':job['id']})

def batches(c):
 snapshot=basis(c);out=[]
 for b in c.execute("SELECT * FROM reconcile_batches WHERE status='Offen' ORDER BY at DESC"):
  r=dict(b);r['stale']=r['basis']!=snapshot;r['items']=[]
  for i in c.execute("SELECT * FROM reconcile_items WHERE batch_id=? AND status='Offen'",(r['id'],)):
   item=dict(i);item['before']=json.loads(item.pop('before_json'));item['after']=json.loads(item.pop('after_json'));item['evidence']=json.loads(item['evidence']);r['items'].append(item)
  if r['items']:out.append(r)
 return out

def install(app,db,user,now,log):
 @app.post('/api/reconcile/{bid}')
 async def apply(bid:str,req:Request):
  actor=user(req);p=await req.json()
  with db() as c:
   c.execute('BEGIN IMMEDIATE');b=c.execute('SELECT * FROM reconcile_batches WHERE id=?',(bid,)).fetchone()
   if not b or b['status']!='Offen':raise HTTPException(409,'Dieser Abgleich ist nicht mehr offen.')
   if p.get('action')=='reject':
    c.execute("UPDATE reconcile_batches SET status='Verworfen' WHERE id=?",(bid,));c.execute("UPDATE reconcile_items SET status='Verworfen' WHERE batch_id=? AND status='Offen'",(bid,));log(c,actor,'Abgleich verworfen',bid,dict(b),None);return {'ok':True}
   if p.get('action')!='apply':raise HTTPException(400,'Ungültige Aktion.')
   if b['basis']!=basis(c):raise HTTPException(409,'Der Projektstand hat sich geändert. Bitte den Abgleich erneut prüfen lassen.')
   chosen=p.get('items');reason=str(p.get('reason','')).strip() or 'Ausgewählte Änderungen ausdrücklich bestätigt.'
   if not isinstance(chosen,list) or not chosen or len(chosen)>12 or not reason or len(reason)>6000:raise HTTPException(400,'Bitte Ergebnisse auswählen und die Übernahme begründen.')
   validated=[];seen=set();unchanged=True
   for edit in chosen:
    if not isinstance(edit,dict) or not isinstance(edit.get('id'),str) or edit['id'] in seen:raise HTTPException(400,'Ungültige Auswahl.')
    seen.add(edit['id']);i=c.execute("SELECT * FROM reconcile_items WHERE id=? AND batch_id=? AND status='Offen'",(edit['id'],bid)).fetchone()
    if not i:raise HTTPException(409,'Ein gewählter Vorschlag ist nicht mehr offen.')
    before=json.loads(i['before_json']);proposed=json.loads(i['after_json']);table='work_questions' if i['kind']=='question' else 'nodes';current=c.execute('SELECT * FROM '+table+' WHERE id=?',(i['target_id'],)).fetchone()
    if not current or current['version']!=before['version']:raise HTTPException(409,'Ein betroffener Stand wurde inzwischen geändert.')
    after=edit.get('after',proposed)
    if not isinstance(after,dict):raise HTTPException(400,'Ungültiger bearbeiteter Vorschlag.')
    if i['kind']=='question':
     if current['status'] in ('Geklärt','Archiviert'):raise HTTPException(409,'Die Frage ist bereits geklärt oder archiviert.')
     question=str(after.get('question',proposed['question'])).strip();answer=str(after.get('answer','')).strip()
     if not question or len(question)>6000 or not answer or len(answer)>12000:raise HTTPException(400,'Frage und nachvollziehbares Ergebnis erforderlich.')
     after={'question':question if i['action']=='revise' else current['question'],'answer':answer,'status':proposed['status']}
    else:
     if current['locked']:raise HTTPException(423,'Die Arbeitsfassung ist geschützt. Zuerst ausdrücklich wieder öffnen.')
     content=str(after.get('content','')).strip()
     if not content or len(content)>60000:raise HTTPException(400,'Vollständige Arbeitsfassung erforderlich.')
     after={'content':content,'stage':'In Bearbeitung'}
    unchanged=unchanged and after==proposed;validated.append((dict(i),dict(current),after))
   for i,old,after in validated:
    if i['kind']=='question':
     c.execute('UPDATE work_questions SET question=?,answer=?,status=?,version=version+1 WHERE id=?',(after['question'],after['answer'],after['status'],i['target_id']))
     action='Frage '+after['status']
    else:
     c.execute('INSERT INTO revisions(node_id,version,snapshot,actor,reason,at) VALUES(?,?,?,?,?,?)',(old['id'],old['version'],json.dumps(old),actor,reason,now()))
     c.execute('UPDATE nodes SET content=?,stage=?,version=version+1 WHERE id=?',(after['content'],after['stage'],old['id']));action='Arbeitsfassung übernommen'
    c.execute("UPDATE reconcile_items SET status='Übernommen' WHERE id=?",(i['id'],));log(c,actor,action,i['target_id'],old,{**after,'reason':reason,'batch_id':bid,'evidence':json.loads(i['evidence'])})
   pending=c.execute("SELECT 1 FROM reconcile_items WHERE batch_id=? AND status='Offen'",(bid,)).fetchone()
   if not pending:c.execute("UPDATE reconcile_batches SET status='Übernommen' WHERE id=?",(bid,))
   elif unchanged:c.execute('UPDATE reconcile_batches SET basis=? WHERE id=?',(basis(c),bid))
   log(c,actor,'Abgleich bestätigt',bid,dict(b),{'selected':[i[0]['id'] for i in validated],'reason':reason})
  return {'ok':True,'applied':len(validated)}
