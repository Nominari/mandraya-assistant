"""Admin-only credential import over stdin. Do not log the input."""
import asyncio,json,os,sys
from chatgpt_auth import import_record
owner=os.environ['CHATGPT_OWNER'].strip().lower()
allowed={x.strip().lower().replace('@googlemail.com','@gmail.com') for x in os.getenv('ALLOWED_EMAILS','').split(',')}
if owner.replace('@googlemail.com','@gmail.com') not in allowed:raise SystemExit('Owner not allowed')
try:asyncio.run(import_record(owner,json.load(sys.stdin)))
except Exception:raise SystemExit('Connection import failed; no credentials printed')
print('ChatGPT connection imported')
