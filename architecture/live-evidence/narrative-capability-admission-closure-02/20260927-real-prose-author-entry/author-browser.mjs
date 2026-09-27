import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {writeFile} from 'node:fs/promises';
import {chromium} from '/Volumes/DevSSD/Development/Workspace/projects/novel-forge/web/admin/node_modules/playwright/index.mjs';
const root='/tmp/novel-forge-real-prose-20260927';
const browser=await chromium.launch({headless:true,channel:'chrome'});
const steps=[];let page;
try {
 page=await browser.newPage({viewport:{width:1440,height:1100}}); page.on('console',m=>{if(m.type()==='error') console.log('CONSOLE',m.text())});page.on('requestfailed',r=>console.log('FAILED',r.url(),r.failure())); page.setDefaultTimeout(15000);
 await page.goto('http://127.0.0.1:3137/production');await page.waitForLoadState('networkidle');
 await page.getByLabel('项目',{exact:true}).selectOption('first-novel-pilot-20260912');
 await page.getByLabel('作品标题',{exact:true}).fill('隔离作者路径验证 '+Date.now());
 const title=await page.getByLabel('作品标题',{exact:true}).inputValue();
 await page.reload();await page.waitForLoadState('networkidle');
 await page.waitForFunction(t=>document.querySelector('input[aria-label="作品标题"]')?.value===t,title);
 steps.push('unsaved author title survives reload');
 const bookBodies=[];let lost=false;
 await page.route('**/authority/books',async route=>{bookBodies.push(route.request().postDataJSON());if(!lost){lost=true;const response=await route.fetch();assert.equal(response.status(),200,await response.text());await route.abort('failed');}else await route.continue();});
 await page.getByRole('button',{name:'登记作品',exact:true}).click();
 await page.getByRole('alert').filter({hasText:'Failed to fetch'}).waitFor();
 await page.reload();await page.waitForLoadState('networkidle');
 await page.getByRole('button',{name:'恢复上次提交（保留原输入和幂等键）',exact:true}).click();

 await page.getByLabel('创作想法',{exact:true}).waitFor();
 assert.deepEqual(bookBodies[0],bookBodies[1]);steps.push('book create committed with lost response; reload replays identical body and key');
 const bookId=bookBodies[0].book_id;
 await page.getByLabel('创作想法',{exact:true}).fill('隔离测试原创输入：证人必须决定是否公开付出代价的真相。此数据不用于正式作品或资格。');
 await page.getByLabel('类型',{exact:true}).fill('玄幻');
 await page.getByLabel('目标读者',{exact:true}).fill('成人');
 await page.getByLabel('创作约束',{exact:true}).fill('仅作作者接口测试');
 await page.getByLabel('素材使用边界',{exact:true}).fill('原创测试文本；不得作为正式文学效果或资格证据');
 const admission=page.waitForResponse(r=>r.url().endsWith('/product/content-authority/commands')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'保存创作输入',exact:true}).click();const result=await admission;assert.equal(result.status(),202,await result.text());
 const operationId=(await result.json()).operation_id;
 execFileSync('/Volumes/DevSSD/Development/Workspace/projects/novel-forge/.venv/bin/python',[root+'/run.py',root+'/execute-isolated-content.py',operationId]);
 await page.getByText('输入任务：SUCCEEDED',{exact:false}).waitFor({timeout:30000});
 steps.push('creative input admitted via registered Content API; exact isolated non-model command executed through native scheduler while general worker brake stays enabled');
 await page.screenshot({path:root+'/author-input-saved.png',fullPage:true});
 await page.getByRole('link',{name:'阅读正文、审稿与整稿版本',exact:true}).click();await page.waitForURL('**/editor?**');await page.waitForLoadState('networkidle');
 assert.equal(new URL(page.url()).searchParams.get('book_id'),bookId);
 assert.equal(await page.getByLabel('稿件版本',{exact:true}).locator('option').count(),1);
 assert.equal(await page.getByLabel('章节正文',{exact:true}).inputValue(),'');
 steps.push('editor respects same-book deep link; empty new book never opens another book draft');
 await writeFile(root+'/author-browser-result.json',JSON.stringify({status:'PASS',evidence_class:'ISOLATED_BROWSER_API_POSTGRES_NO_MODEL',bookId,operationId,steps},null,2));console.log(JSON.stringify({status:'PASS',steps}));
} catch(error) {if(page){await page.screenshot({path:root+'/author-browser-failed.png',fullPage:true});await writeFile(root+'/author-browser-failed-dom.txt',await page.locator('body').innerText());}throw error;}
finally {await browser.close();}
