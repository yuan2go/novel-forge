import urllib.request, urllib.parse, hashlib,json,re,time
from pathlib import Path
from bs4 import BeautifulSoup
root=Path('/tmp/nf-corpus-wp3c-20260909/public');records=[]
for name,title in [('sanguo','三國演義/第001回'),('xiyou','西遊記/第001回')]:
 start=time.monotonic();url='https://zh.wikisource.org/wiki/'+urllib.parse.quote(title)
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'NovelForge-CorpusResearch/1.0'}),timeout=25) as r:
   discovery=r.read(1000001)
  if len(discovery)>1000000:raise ValueError('metadata page budget exceeded')
  soup=BeautifulSoup(discovery,'html.parser');link=soup.select_one('#t-permalink a')
  if not link:raise ValueError('immutable revision link missing')
  fixed=urllib.parse.urljoin(url,link['href'])
  if urllib.parse.urlsplit(fixed).hostname!='zh.wikisource.org' or 'oldid=' not in fixed:raise ValueError('unexpected permanent link')
  with urllib.request.urlopen(urllib.request.Request(fixed,headers={'User-Agent':'NovelForge-CorpusResearch/1.0'}),timeout=25) as r:
   content=r.read(1000001)
  if len(content)>1000000:raise ValueError('excerpt page budget exceeded')
  filename=name+'-wikisource-excerpt.html';(root/filename).write_bytes(content)
  records.append({'file':filename,'discovery_url':url,'fixed_url':fixed,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest(),'status':'VERIFIED_ACQUIRED_EXCERPT_ONLY','seconds':time.monotonic()-start})
 except Exception as e:records.append({'discovery_url':url,'status':'BLOCKED','reason':type(e).__name__+':'+str(e),'seconds':time.monotonic()-start})
(root/'independent-excerpt-receipts.json').write_text(json.dumps(records,ensure_ascii=False,indent=2));print(json.dumps(records,ensure_ascii=False))
