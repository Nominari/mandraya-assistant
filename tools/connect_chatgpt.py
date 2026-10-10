#!/usr/bin/env python3
"""One-time laptop OAuth then SSH import. Credentials travel only over stdin."""
import argparse,asyncio,base64,hashlib,json,os,secrets,shlex,subprocess,sys,time,webbrowser
from pathlib import Path
from http.server import BaseHTTPRequestHandler,HTTPServer
from urllib.parse import urlencode,urlparse,parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
# A separate local store; never point at production data.
os.environ['DATA_DIR']=str(Path.home()/'.config'/'mandraya-assistant')
import httpx
from chatgpt_auth import AUTH,RESOURCE,REQUIRED,ROOT,atomic,host_id,verify

def main():
 p=argparse.ArgumentParser(description='ChatGPT-Abo sicher mit dem Mandraya Server verbinden')
 p.add_argument('--ssh',required=True,help='SSH-Ziel user@server');p.add_argument('--owner',required=True,help='Deine Google-Anmeldeadresse im Assistant');p.add_argument('--key');args=p.parse_args()
 if args.ssh.startswith('-'):raise SystemExit('Invalid SSH destination')
 owner=args.owner.strip().lower();registry=ROOT/(hashlib.sha256(owner.encode()).hexdigest()+'.registration.json')
 old=json.loads(registry.read_text()) if registry.exists() else {};client_id=old.get('client_id','dynamic_agent_client')
 state=secrets.token_urlsafe(32);nonce=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64);result={}
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_GET(self):
   u=urlparse(self.path);q={k:v[0] for k,v in parse_qs(u.query).items()}
   if u.path!='/auth/callback' or not secrets.compare_digest(q.get('state',''),state):
    self.send_response(400);self.end_headers();self.wfile.write(b'Invalid callback');return
   result.update(q);self.send_response(200);self.send_header('Content-Type','text/plain; charset=utf-8');self.end_headers();self.wfile.write('Anmeldung empfangen. Du kannst diesen Tab schließen. Die Verbindung wird jetzt geprüft und sicher auf deinen Server übertragen.'.encode())
 listener=HTTPServer(('127.0.0.1',0),Handler);listener.timeout=1
 redirect=f'http://127.0.0.1:{listener.server_port}/auth/callback'
 params={'client_id':client_id,'ext_agent_host_id':host_id(),'response_type':'code','redirect_uri':redirect,'scope':'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct','resource':RESOURCE,'state':state,'nonce':nonce,'code_challenge_method':'S256','code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')}
 if client_id=='dynamic_agent_client':params['agent_name_hint']='Mandraya Assistant'
 url=AUTH+'/api/accounts/authorize?'+urlencode(params)
 print('Bitte melde dich im Browser an und erlaube dem Mandraya Assistant die Nutzung deines ChatGPT-Abos.',flush=True)
 print('Anmeldelink: '+url,flush=True);webbrowser.open(url)
 deadline=time.time()+600
 while not result and time.time()<deadline:listener.handle_request()
 listener.server_close()
 if not result:raise ValueError('Anmeldung nach zehn Minuten abgelaufen.')
 if result.get('error'):raise ValueError('Anmeldung wurde nicht freigegeben.')
 issued=result.get('client_id',client_id)
 if issued=='dynamic_agent_client' or (client_id!='dynamic_agent_client' and issued!=client_id):raise ValueError('Registrierung nicht bestätigt.')
 atomic(registry,json.dumps({'client_id':issued,**({'subject':old['subject']} if old.get('subject') else {})}).encode())
 async def exchange():
  async with httpx.AsyncClient(timeout=25) as c:
   r=await c.post(AUTH+'/api/accounts/oauth/token',data={'grant_type':'authorization_code','client_id':issued,'code':result['code'],'code_verifier':verifier,'redirect_uri':redirect,'resource':RESOURCE})
   if r.status_code!=200:raise ValueError('Token-Austausch fehlgeschlagen. Bitte Anmeldung erneut starten.')
   t=r.json()
  ident=await verify(t['id_token'],issued,nonce)
  if old.get('subject') and ident['sub']!=old['subject']:raise ValueError('Anderes Konto: bitte ursprüngliches Konto verwenden.')
  scopes=t.get('scope','').split()
  if not REQUIRED.issubset(scopes) or not t.get('refresh_token'):raise ValueError('ChatGPT-Abo-Nutzung wurde nicht vollständig freigegeben.')
  return {**t,'client_id':issued,'subject':ident['sub'],'email':ident.get('email',''),'issuer':ident['iss'],'scopes':scopes,'expires_at':time.time()+int(t.get('expires_in',3600))}
 record=asyncio.run(exchange());atomic(registry,json.dumps({'client_id':issued,'subject':record['subject']}).encode())
 command=['ssh','-o','BatchMode=yes','-o','IdentitiesOnly=yes']
 if args.key:command+=['-i',str(Path(args.key).expanduser())]
 command+=[args.ssh,'docker exec -i -e '+shlex.quote('CHATGPT_OWNER='+owner)+' mandraya-assistant python import_chatgpt.py']
 imported=subprocess.run(command,input=json.dumps(record).encode(),capture_output=True)
 if imported.returncode!=0:raise ValueError('Serverimport fehlgeschlagen. Bitte Serververbindung prüfen und Anmeldung erneut starten.')
 print('ChatGPT-Konto verbunden. Im Assistant einen Baustein öffnen und den Tab KI-Chat wählen.',flush=True)

if __name__=='__main__':
 try:main()
 except Exception as e:
  # Never echo provider responses or OAuth secrets.
  print(str(e) if isinstance(e,ValueError) else 'Anmeldung konnte nicht abgeschlossen werden. Bitte erneut versuchen.',file=sys.stderr);sys.exit(1)
