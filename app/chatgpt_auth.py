"""OpenAI plan credentials: never exposed to browser clients or logs."""
import asyncio, hashlib, json, os, tempfile, time, uuid
from pathlib import Path
import httpx
import jwt
from cryptography.fernet import Fernet

AUTH='https://auth.openai.com'
RESOURCE='https://api.openai.com/v1'
REQUIRED={'resource.invoke','chatgpt.tokens.use.direct'}
ROOT=Path(os.getenv('DATA_DIR','/data'))/'chatgpt'
ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
os.chmod(ROOT,0o700)
_locks={}

def atomic(path,data):
 fd,tmp=tempfile.mkstemp(dir=path.parent)
 try:
  os.fchmod(fd,0o600)
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def host_id():
 p=ROOT/'host-id'
 if not p.exists():atomic(p,('urn:uuid:'+str(uuid.uuid4())).encode())
 return p.read_text()

def cipher():
 p=ROOT/'encryption-key'
 if not p.exists():atomic(p,Fernet.generate_key())
 return Fernet(p.read_bytes())

def filename(owner):return ROOT/(hashlib.sha256(owner.strip().lower().replace('@googlemail.com','@gmail.com').encode()).hexdigest()+'.enc')
def load(owner):
 p=filename(owner)
 return json.loads(cipher().decrypt(p.read_bytes())) if p.exists() else None

def save(owner,record):atomic(filename(owner),cipher().encrypt(json.dumps(record).encode()))

def connection(owner):
 r=load(owner)
 return {'connected':bool(r),'account':r.get('email','') if r else '', 'plan_enabled':bool(r and REQUIRED.issubset(r.get('scopes',[])))}

async def verify(id_token,client_id,nonce=None):
 async with httpx.AsyncClient(timeout=20) as c:
  discovery=await c.get(AUTH+'/.well-known/openid-configuration');discovery.raise_for_status();d=discovery.json()
  uri=d['jwks_uri']
  if not uri.startswith(AUTH+'/'):raise ValueError('Unexpected identity key endpoint')
  keys=await c.get(uri);keys.raise_for_status()
 header=jwt.get_unverified_header(id_token)
 if header.get('alg')!='RS256':raise ValueError('Unsupported ID token signature')
 matches=[k for k in keys.json()['keys'] if k.get('kid')==header.get('kid')]
 if len(matches)!=1:raise ValueError('Identity key not found')
 claims=jwt.decode(id_token,jwt.PyJWK.from_dict(matches[0]).key,algorithms=['RS256'],audience=client_id,issuer=AUTH,options={'require':['exp','iss','aud','sub']})
 if nonce is not None and claims.get('nonce')!=nonce:raise ValueError('Invalid identity nonce')
 return claims

async def import_record(owner,r):
 if not r.get('client_id') or r['client_id']=='dynamic_agent_client':raise ValueError('Missing issued registration')
 ident=await verify(r['id_token'],r['client_id'])
 if ident['sub']!=r.get('subject'):raise ValueError('Identity mismatch')
 if not REQUIRED.issubset(r.get('scopes',[])) or not r.get('access_token') or not r.get('refresh_token'):raise ValueError('Plan permission missing')
 # Each owner has one active registration. Replace only through explicit admin import.
 r['email']=ident.get('email','');r['issuer']=ident['iss'];r['ext_agent_host_id']=host_id()
 save(owner,r)

async def token(owner):
 async with _locks.setdefault(owner,asyncio.Lock()):
  r=load(owner)
  if not r or not REQUIRED.issubset(r.get('scopes',[])):raise ValueError('Bitte zuerst dein ChatGPT-Konto verbinden.')
  if r['expires_at']<=time.time()+90:
   async with httpx.AsyncClient(timeout=25) as c:
    response=await c.post(AUTH+'/api/accounts/oauth/token',data={'grant_type':'refresh_token','client_id':r['client_id'],'refresh_token':r['refresh_token'],'resource':RESOURCE})
   if response.status_code!=200:raise ValueError('ChatGPT-Verbindung muss erneuert werden. Bitte erneut verbinden.')
   t=response.json()
   if not t.get('access_token') or not t.get('refresh_token'):raise ValueError('Erneuerung unvollständig. Bitte erneut verbinden.')
   scopes=t.get('scope',' '.join(r['scopes'])).split()
   if not REQUIRED.issubset(scopes):raise ValueError('ChatGPT-Abo wurde nicht freigegeben.')
   r.update(access_token=t['access_token'],refresh_token=t['refresh_token'],scopes=scopes,expires_at=time.time()+int(t.get('expires_in',3600)))
   if t.get('id_token'):r['id_token']=t['id_token']
   save(owner,r)
  return r['access_token']

async def disconnect(owner):
 async with _locks.setdefault(owner,asyncio.Lock()):
  r=load(owner);confirmed=False
  if r:
   try:
    async with httpx.AsyncClient(timeout=20) as c:
     d=await c.get(AUTH+'/.well-known/openid-configuration');d.raise_for_status();uri=d.json()['revocation_endpoint']
     if not uri.startswith(AUTH+'/'):raise ValueError('Unexpected revocation endpoint')
     res=await c.post(uri,data={'token':r['refresh_token'],'token_type_hint':'refresh_token','client_id':r['client_id']})
     confirmed=res.status_code==200
   except (httpx.HTTPError,ValueError,KeyError):pass
   filename(owner).unlink(missing_ok=True)
  return confirmed
