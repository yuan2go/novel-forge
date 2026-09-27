import json,urllib.request,urllib.error
from pathlib import Path
base=Path('/tmp/novel-forge-real-prose-20260927');opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
api=json.load(opener.open('http://127.0.0.1:8137/openapi.json'))
prefix='/product/production/book-authority'
mapping={'start':prefix+'/commands','resume':prefix+'/runs/{book_run_id}/resume','pause':prefix+'/runs/{book_run_id}/pause','cancel':prefix+'/runs/{book_run_id}/cancel','recover':prefix+'/chapter-requests/{chapter_request_id}/recover'}
checks=[]
for name,path in mapping.items():
    assert path in api['paths'] and 'post' in api['paths'][path],(name,path)
    old='/product/production/chapter-run/'+name
    assert old not in api['paths']
    endpoint=api['paths'][path]['post']
    checks.append({'operation':name,'previous_path':old,'current_path':path,'method':'POST','request':endpoint.get('requestBody',{}),'responses':list(endpoint['responses']),'status':'REGISTERED','consumer_proof':'Book targeted integration checks; no real model production proven'})
(base/'api-route-check.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
print('5 native POST routes registered; 5 removed legacy paths absent')
