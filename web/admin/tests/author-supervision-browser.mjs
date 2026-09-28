import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.NOVEL_FORGE_WEB_BASE_URL;
if (!base) throw new Error('Set the isolated author UI URL');
const browser = await chromium.launch({headless:true, channel:'chrome'});
const context = await browser.newContext();
const page = await context.newPage();
const hash = 'sha256:'+'a'.repeat(64), reviewHash = 'sha256:'+'b'.repeat(64);
const requests = [], errors = [];
page.on('pageerror', e=>{errors.push(e.message);process.stderr.write(e.stack+'\n');});
const view = {book_modes:[{book_id:'trial-book',reason:'Isolated browser fixture'}],policy_hash:hash,policy_version:'fixture',authorizations:[{task_type:'review',model_revision:'fixture-reviewer',expires_at:'2020-01-01T00:00:00Z',maximum_tokens:1000,maximum_amount:'1',expired:true}],producers:[{routing_asset_version_id:'route:review:1',task_type:'review',producer_contract_hash:hash,operation_id:'review-op',status:'BLOCKED',budget:{scope:'execution_chain',tokens_used_or_reserved:20},review_requirement:{schema_version:'cross-model-review.v2',target_asset_version_id:'author-draft:2',target_content_hash:reviewHash,source:{kind:'MODEL_EDITED_BY_AUTHOR'},reviewer_policy:'EXPLICIT_AUTHORIZED_REVIEWER',authorized_reviewer:{}},candidates:[{candidate:{candidate_id:'reviewer:fixture',provider:'deepseek',model:'fixture',model_revision:'fixture-reviewer',pricing:{currency:'USD',accounting_basis:'PRICED'}},rejected_reasons:['CROSS_MODEL_REVIEW_SOURCE_POLICY_REQUIRED'],estimated_total_tokens:20,reservation_upper_bound:'0.01'}]}],
  controls:{book_control:{scope:'PROJECT_FUTURE_SUBJECTS',selected_policy:null,selected_boundaries:[],supervised_boundaries:['BOOK','CHAPTER','SCENE','FINAL_CANDIDATE','REALITY_COMMIT']},dispatch:{state:'PAUSED',api_process_suspended:true},budget_ledger:{scope:'PROJECT',rows:[{provider:'fixture',currency:'USD',status:'HELD_UNKNOWN',accounting_basis:'ACCOUNT_ENTITLEMENT',cost_status:'UNKNOWN',reservations:1,actual_tokens:12,estimated_tokens:20,reserved_amount:'1',settled_amount:null}]}},
  pending_designs:[{asset_version_id:'plan:1',content_hash:hash,content:{candidate_payload:{core_conflict:'工程测试候选：人物是否已知证人身份'}},qualification:'STRUCTURALLY_VALID',approval:'PENDING',planning_scope:'CHAPTER'}],model_reviews:[]};
try {
  await page.addInitScript(()=>localStorage.setItem('novel-forge.author-production.v1',JSON.stringify({project:'trial-project',bookId:'trial-book'})));
  await page.route('http://127.0.0.1:8150/**',async route=>{
    const request=route.request(), url=new URL(request.url());
    const reply=(json,status=200)=>route.fulfill({status,json,headers:{'Access-Control-Allow-Origin':'*'}});
    if(request.method()==='OPTIONS') return route.fulfill({status:204,headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'GET,POST,OPTIONS','Access-Control-Allow-Headers':'content-type'}});
    if(url.pathname==='/product/projects') return reply([{project_id:'trial-project',workspace_id:'trial-workspace',title:'隔离测试项目'}]);
    if(url.pathname==='/product/system/health') return reply({summary:{},embedding:{ok:false}});
    if(url.pathname.endsWith('/reference-samples')) return reply({samples:[],actor_id:'fixture-author',can_annotate:false});
    if(url.pathname.endsWith('/author-workspace')) return reply({books:[{book_id:'trial-book',workspace_id:'trial-workspace',title:'监督流程隔离检查',version:1,status:'ACTIVE',production_profile:{},runtime_policy:{}}],profiles:[],snapshots:[],runs:[],budget_scopes:[]});
    if(url.pathname.endsWith('/author-supervision')) return reply(view);
    if(url.pathname.endsWith('/author-supervision/mode')) {
      requests.push({kind:'mode',body:request.postDataJSON()});
      if(requests.filter(r=>r.kind==='mode').length===1) {
        view.policy_hash=reviewHash;
        return reply({detail:{code:'ROUTING_POLICY_VERSION_CONFLICT',message:'Isolated concurrency conflict'}},409);
      }
      assert.equal(request.postDataJSON().expected_policy_hash,reviewHash);
      assert.notEqual(requests.at(-1).body.idempotency_key,requests.find(r=>r.kind==='mode').body.idempotency_key);
      return reply({mode:'AUTHOR_SUPERVISED'});
    }
    if(url.pathname.endsWith('/model-reviews')) {
      requests.push({kind:'review',body:request.postDataJSON()});
      view.model_reviews=[{asset_version_id:'review:1',content_hash:reviewHash,content:{candidate_asset_version_id:'plan:1',candidate_content_hash:hash,
        provider_execution:{provider_id:'deepseek',model_id:'fixture-reviewer'},evaluation:{evaluations:[{layer:'CAUSALITY',criteria:[{criterion:'knowledge',verdict:'FAIL',rationale:'工程模拟发现：身份披露先于目击。',evidence_refs:['paragraph:4'],repair_directive:'核对人物的信息来源。'}]}]}}}];
      if(requests.filter(r=>r.kind==='review').length===1) return route.abort('failed');
      assert.deepEqual(requests.at(-1).body,requests.find(r=>r.kind==='review').body);
      return reply({replayed:true,literary_qualification:'NOT_PROVEN'});
    }
    if(url.pathname.endsWith('/author-decisions')) {requests.push({kind:'decision',body:request.postDataJSON()});view.pending_designs=[];return reply({approval:'APPROVED'});}
    if(url.pathname==='/product/content-authority/commands' || url.pathname==='/product/content-authority/operations/brief-op') {
      if(request.method()==='POST') requests.push({kind:'brief',body:request.postDataJSON()});
      return reply({operation_id:'brief-op',status:'SUCCEEDED',outputs:[{asset_version_id:'brief:1',content_hash:hash}]});
    }
    if(url.pathname.endsWith('/author-creative-input')) {
      requests.push({kind:'direction',body:request.postDataJSON()});
      return reply({asset_version_id:'original-direction:1',content_hash:reviewHash,state:{lifecycle:'MATERIALIZED'},content:{candidate_payload:request.postDataJSON().design}});
    }
    if(url.pathname.endsWith('/author-creative-input/original-direction%3A1/decisions')) {
      requests.push({kind:'direction-decision',body:request.postDataJSON()});
      return reply({asset_version_id:'original-direction:1',content_hash:reviewHash,state:{lifecycle:'ACTIVE'}});
    }
    if(url.pathname.endsWith('/formation-runs') || url.pathname.endsWith('/formation-runs/formation%3A1')) {
      if(request.method()==='POST') requests.push({kind:'formation',body:request.postDataJSON()});
      return reply({formation_run_id:'formation:1',version:1,lifecycle:'PREPARING',current_stage:'THEME_CONTRACT',failure:null,recovery_instruction:null,candidates:[],book_design_asset_version_id:'',book_design_content_hash:''});
    }
    return reply({});
  });
  await page.goto(base+'/production');
  await page.waitForLoadState('networkidle');
  const panel=page.locator('section').filter({has:page.getByRole('heading',{name:'作者监督试生产',exact:true})});
  await panel.getByText(/项目派发状态：PAUSED/).waitFor();
  assert.match(await panel.innerText(), /已过期，需作者重新确认/);
  assert.match(await panel.innerText(), /旧冻结请求继续使用原政策/);
  assert.match(await panel.innerText(), /无需虚构新稿生成回执/);
  await panel.getByText('项目累计预算账本（含其他作品与历史记录）',{exact:true}).click();
  assert.match(await panel.innerText(), /结算金额 未知/);
  await panel.getByLabel('实际任务',{exact:true}).selectOption('route:review:1');
  await panel.getByLabel('限定模型',{exact:true}).selectOption('reviewer:fixture');
  assert.match(await panel.innerText(), /当前审读目标：author-draft:2/);
  assert.match(await panel.innerText(), /MODEL_EDITED_BY_AUTHOR/);
  assert.match(await panel.innerText(), /CROSS_MODEL_REVIEW_SOURCE_POLICY_REQUIRED/);
  await panel.getByRole('button',{name:'请求模型复核此精确版本',exact:true}).waitFor();
  assert.equal(await panel.getByRole('button',{name:'请求模型复核此精确版本',exact:true}).count(),1);
  await panel.getByLabel('批准理由 / 保留优点 / 修改意见').fill('隔离检查：明确选择监督模式。');
  await panel.getByRole('button',{name:'确认本作品采用作者监督模式',exact:true}).click();
  await panel.getByText('配置已有更新，此次决定被拒绝且已保留记录。请查询当前配置，核对后重新确认。',{exact:true}).waitFor();
  assert.equal(await panel.getByRole('button',{name:'恢复原监督决定（原幂等键）',exact:true}).count(),0);
  const retained=await page.evaluate(()=>JSON.parse(localStorage.getItem('novel-forge:author-supervision:trial-project:trial-book')));
  assert.equal(retained.rejected[0].code,'ROUTING_POLICY_VERSION_CONFLICT');
  await panel.getByRole('button',{name:'确认本作品采用作者监督模式',exact:true}).click();
  await page.waitForFunction(()=>!document.body.textContent.includes('恢复原监督决定（原幂等键）'));
  await panel.getByRole('button',{name:'请求模型复核此精确版本',exact:true}).click();
  await panel.getByRole('button',{name:'恢复原监督决定（原幂等键）',exact:true}).waitFor();
  await page.reload();
  await panel.getByRole('button',{name:'恢复原监督决定（原幂等键）',exact:true}).click();
  await panel.getByLabel('批准理由 / 保留优点 / 修改意见').fill('保留人物为证词承担代价的动机。');
  assert.equal(await panel.getByRole('button',{name:'批准并选择此计划',exact:true}).isDisabled(),true);
  await panel.getByLabel('作者判断：knowledge',{exact:true}).selectOption('DISMISSED_WITH_EVIDENCE');
  await panel.getByLabel('原文依据与处理理由：knowledge',{exact:true}).fill('第4段明确写出目击后的披露；本例仅验证争议处置输入。');
  await page.reload();
  await panel.getByRole('button',{name:'批准并选择此计划',exact:true}).click();
  await page.waitForFunction(()=>!document.body.textContent.includes('工程测试候选：人物是否已知证人身份'));
  const decision=requests.find(r=>r.kind==='decision').body;
  assert.equal(decision.content_hash,hash);
  assert.deepEqual(decision.findings,[{finding_id:'review:1:CAUSALITY:knowledge',disposition:'DISMISSED_WITH_EVIDENCE',reason:'第4段明确写出目击后的披露；本例仅验证争议处置输入。'}]);
  const creative=page.locator('section').filter({has:page.getByRole('heading',{name:'创作输入与设计准备',exact:true})});
  await creative.getByLabel('创作想法',{exact:true}).fill('隔离工程输入：保留证词与接回证人的两难。');
  await creative.getByLabel('类型',{exact:true}).fill('悬疑');
  await creative.getByLabel('目标读者',{exact:true}).fill('成年读者');
  await creative.getByLabel('素材使用边界',{exact:true}).fill('本例原创工程输入，不使用诊断候选。');
  await creative.getByRole('button',{name:'保存创作输入',exact:true}).click();
  await creative.getByText(/输入任务：SUCCEEDED/).waitFor();
  await creative.getByLabel('使用我已确定的原创方向，直接进入下层设计',{exact:true}).check();
  const direction=creative.getByRole('group',{name:'确认原创方向',exact:true});
  for(const label of ['故事目标','目标读者','为什么值得写','类型','细分类型','核心欲望','核心恐惧','核心冲突与代价','持续推动故事的机制','与同类作品的差异','阅读与情感承诺','后继叙事空间']) {
    await direction.getByLabel(label,{exact:true}).fill('工程输入：'+label);
  }
  await direction.getByLabel('内容贡献',{exact:true}).selectOption('AI_ASSISTED_AUTHOR_INPUT');
  await direction.getByRole('button',{name:'保存方向为待批准输入',exact:true}).click();
  await direction.getByLabel('确认依据与保留的阅读承诺',{exact:true}).fill('工程测试作者确认原文与代价；不声称文学质量。');
  await direction.getByLabel('故事目标',{exact:true}).fill('未保存的新方向');
  assert.equal(await direction.getByRole('button',{name:'批准此版本并选择为创作方向',exact:true}).isDisabled(),true);
  await page.reload();
  assert.equal(await direction.getByLabel('故事目标',{exact:true}).inputValue(),'未保存的新方向');
  await direction.getByLabel('故事目标',{exact:true}).fill('工程输入：故事目标');
  await direction.getByRole('button',{name:'批准此版本并选择为创作方向',exact:true}).click();
  await direction.getByText(/方向版本：.*ACTIVE/).waitFor();
  await creative.getByRole('button',{name:'启动设计准备（确认计划后推进）',exact:true}).click();
  await creative.getByText(/THEME_CONTRACT/).first().waitFor();
  const formation=requests.find(r=>r.kind==='formation').body;
  assert.equal(formation.generation_policy.contract_version,'formation-generation.v3');
  assert.equal(formation.generation_policy.creative_candidates,1);
  assert.deepEqual(formation.generation_policy.author_creative_foundation,{asset_version_id:'original-direction:1',content_hash:reviewHash});
  assert.equal(requests.filter(r=>r.kind==='direction').length,1);
  assert.equal(requests.find(r=>r.kind==='direction').body.contribution,'AI_ASSISTED_AUTHOR_INPUT');
  assert.equal(errors.length,0,errors.join('\n'));
  process.stdout.write(JSON.stringify({status:'PASS',evidence_kind:'BROWSER_WITH_ISOLATED_API_DOUBLES',checks:['three independent controls, expiry and unknown cumulative ledger displayed','source-aware exact-version review entry','confirmed policy conflict retained and reconfirmed against refreshed version','lost response keeps original idempotency key','unresolved model finding blocks approval','disposition survives reload','exact target and finding submitted','original author direction persisted and exact approval consumed by Formation v3','unsaved direction survives reload and cannot be approved'],real_model_calls:0})+'\n');
} catch(error) {process.stderr.write((await page.locator('body').innerText())+'\n');throw error;}
finally {await context.close();await browser.close();}
