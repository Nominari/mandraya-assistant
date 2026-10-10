"""Document editions and archive status, separate from stored content revisions."""
import re,unicodedata
from pathlib import PurePosixPath

def edition(title):
 stem=re.sub(r'\.(docx?|pdf|xlsx?|txt|md)$','',title.strip(),flags=re.I)
 match=re.search(r'(?:[_\s-]+)v(\d+(?:[.,]\d+)*)\s*$',stem,re.I)
 version=tuple(int(x) for x in re.split('[.,]',match.group(1))) if match else None
 family=stem[:match.start()] if match else stem
 family=re.sub(r'[^\w]+',' ',unicodedata.normalize('NFKC',family).casefold()).strip()
 return family,version

def classify(rows):
 result={};groups={}
 for s in rows:
  family,v=edition(s['title']);path=s.get('path','').strip();parts=path.split('/');clean='/'.join(x for x in parts if x.strip().casefold() not in ('alt','archiv','archive'));key=clean.casefold()+'|'+family
  r={'source_id':s['id'],'family':key,'edition':'.'.join(map(str,v)) if v else '', 'status':'Aktuell','reason':'Eigenständiges Dokument; neueste gespeicherte Inhaltsfassung','successor_id':None}
  result[s['id']]=r
  if any(x.strip().casefold() in ('alt','archiv','archive') for x in path.split('/')):
   r.update(status='Archiv',reason='Liegt im ausdrücklich als Alt/Archiv bezeichneten Ordner');continue
  groups.setdefault(key,[]).append((s,v))
 for group in groups.values():
  if len(group)<2:continue
  ranked=sorted(group,key=lambda x:(x[1] or (),str(x[0].get('modified','')),x[0]['id']),reverse=True)
  highest=ranked[0][1]
  same=[x for x in ranked if x[1]==highest]
  # Same edition as Office/PDF representations: editable original is the working source.
  office=next((x for x in same if x[0]['title'].lower().endswith('.docx')),None)
  winner=office or ranked[0]
  for s,v in group:
   if s['id']==winner[0]['id']:continue
   duplicate=v==highest and v is not None
   result[s['id']].update(status='Formatduplikat' if duplicate else 'Abgelöst',reason='Gleiche Dokumentfassung in anderem Format; bearbeitbares Original bevorzugt' if duplicate else 'Ältere Fassung derselben Dokumentfamilie',successor_id=winner[0]['id'])
 winners={r['family']:r['source_id'] for r in result.values() if r['status']=='Aktuell'}
 for r in result.values():
  if r['status']=='Archiv' and r['family'] in winners:r['successor_id']=winners[r['family']]
 return result

def setup(c):
 c.execute('CREATE TABLE IF NOT EXISTS source_policy(source_id TEXT PRIMARY KEY,family TEXT,edition TEXT,status TEXT,reason TEXT,successor_id TEXT)')

def refresh(c):
 setup(c)
 rows=[dict(x) for x in c.execute('SELECT s.*,v.modified FROM sources s LEFT JOIN source_versions v ON v.id=(SELECT max(id) FROM source_versions WHERE source_id=s.id)')]
 for r in classify(rows).values():c.execute('INSERT INTO source_policy VALUES(?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET family=excluded.family,edition=excluded.edition,status=excluded.status,reason=excluded.reason,successor_id=excluded.successor_id',(r['source_id'],r['family'],r['edition'],r['status'],r['reason'],r['successor_id']))

def active(c,sid):
 r=c.execute('SELECT status FROM source_policy WHERE source_id=?',(sid,)).fetchone()
 return not r or r['status']=='Aktuell'
