import json,sys
from server import ingest
items=json.load(open(sys.argv[1]));results=[ingest(s,'Drive-Erstimport') for s in items]
print(json.dumps({'sources':len(results),'new_versions':sum(x['new_version'] for x in results)}))
