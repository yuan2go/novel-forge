import urllib.request,hashlib,json,time,concurrent.futures
from pathlib import Path
root=Path('/tmp/nf-corpus-wp3c-20260909/public');root.mkdir(exist_ok=True)
urls=[(f'{book}.{suffix}',f'https://www.gutenberg.org/ebooks/{book}.{route}') for book in (23950,23962,24264) for suffix,route in [('txt','txt.utf-8'),('epub','epub3.images')]]
urls += [('catalogue-5401635.html','https://zh.wikisource.org/w/index.php?oldid=5401635&title=%E4%B8%89%E5%9C%8B%E6%BC%94%E7%BE%A9')]
def acquire(item):
 name,url=item;started=time.monotonic();target=root/name
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'NovelForge-Corpus-Research/1.0'}),timeout=30) as response,target.open('wb') as out:
   size=0;digest=hashlib.sha256()
   while chunk:=response.read(65536):
    size+=len(chunk)
    if size>20_000_000:raise ValueError('bounded sample exceeds 20MB')
    digest.update(chunk);out.write(chunk)
  return {'name':name,'url':url,'resolved_url':response.url,'bytes':size,'sha256':digest.hexdigest(),'seconds':time.monotonic()-started,'status':'ACQUIRED_LOCAL_VALIDATION_RECEIPT'}
 except Exception as exc:return {'name':name,'url':url,'status':'BLOCKED','error':str(exc),'seconds':time.monotonic()-started}
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(acquire,urls))
(root/'receipts.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));print(json.dumps(results,ensure_ascii=False))
