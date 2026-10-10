from server import db,DATA,DB
import sqlite3,datetime,tarfile
name=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
folder=DATA/'backups';folder.mkdir(exist_ok=True)
out=folder/(name+'.sqlite')
a=sqlite3.connect(DB);b=sqlite3.connect(out);a.backup(b);b.close();a.close()
with tarfile.open(folder/(name+'.tar.gz'),'w:gz') as t:
 t.add(out,arcname='mandraya.sqlite')
 if (DATA/'files').exists():t.add(DATA/'files',arcname='files')
print('Backup created:',name)
