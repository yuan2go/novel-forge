from __future__ import annotations

import html
import json
import re
from typing import Any, Mapping

from novel_forge.modules.reader_calibration.manuscript_blind import content_digest


_DIMENSION_LABELS = {
    "character_credibility": "人物可信度",
    "action_consequence": "行动与后续结果",
    "dialogue_voice": "对白与人物声音",
    "repetition_skipping": "重复与跳读",
    "desire_to_continue": "继续阅读意愿",
    "editing_burden": "修改负担",
}


def manuscript_reading_page(public: Mapping[str, Any], *, project_id: str, workspace_id: str, pack_id: str) -> str:
    rows, navigation, rating_rows, preference = [], [], [], []
    for ordinal, manuscript in enumerate(public["manuscripts"], 1):
        name = html.escape(manuscript["display_name"])
        token = html.escape(manuscript["manuscript_token"], quote=True)
        navigation.append(f'<a href="#work-{ordinal}">{name}</a>')
        preference.append(f'<option value="{token}">{name}</option>')
        rows.append(f'<section id="work-{ordinal}" class="work"><h2>{name}</h2>')
        for chapter in manuscript["chapters"]:
            chapter_token = html.escape(chapter["chapter_token"], quote=True)
            title = html.escape(chapter["title"])
            text = html.escape(chapter["text"])
            rows.append(f'<article><h3>第 {chapter["chapter_number"]} 章 · {title}</h3>'
                        f'<div class="prose" data-chapter="{chapter_token}">{text}</div>'
                        '<button type="button" class="mark">记下选中文字的阅读感受</button></article>')
        rows.append('</section>')
        scores = []
        for dimension, label in _DIMENSION_LABELS.items():
            options = '<option value="">无法判断</option>' + ''.join(
                f'<option value="{score}">{score}</option>' for score in range(1, 6))
            scores.append(f'<label>{label}<select data-work="{token}" data-dimension="{dimension}">'
                          f'{options}</select></label>')
        rating_rows.append(f'<fieldset><legend>{name}</legend><div class="ratings">'
                           + ''.join(scores) + '</div></fieldset>')
    payload = {"project_id": project_id, "workspace_id": workspace_id,
               "pack_id": pack_id, "public_content_hash": content_digest(public),
               "response_template": public["response_template"],
               "chapters": {chapter["chapter_token"]: chapter["text"]
                            for row in public["manuscripts"] for chapter in row["chapters"]}}
    # SECURITY: Source prose and identifiers cannot terminate the script element.
    encoded = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    substitutions = {'__NAVIGATION__': ''.join(navigation), '__CHAPTERS__': ''.join(rows),
                     '__RATINGS__': ''.join(rating_rows), '__PREFERENCE__': ''.join(preference), '__PAYLOAD__': encoded}
    return re.sub(r'__(NAVIGATION|CHAPTERS|RATINGS|PREFERENCE|PAYLOAD)__',
                  lambda match: substitutions[match[0]], _PAGE)


_PAGE = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>连续阅读 · 读者反馈</title><style>
:root{color-scheme:light;--page:#f5f8fc;--paper:#fff;--ink:#1e2b3a;--blue:#365e7b;--light:#e8f0f6;--line:#c6d4df}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:5rem}
body{margin:0;background:var(--page);color:var(--ink);font-family:"PingFang SC","Microsoft YaHei",sans-serif}
nav{position:sticky;top:0;z-index:1;display:flex;gap:1.4rem;justify-content:center;flex-wrap:wrap;padding:1rem;background:var(--paper);border-bottom:1px solid var(--line)}
a{color:var(--blue);text-underline-offset:.3em}main{max-width:52rem;margin:auto;padding:3rem 2.5rem;background:var(--paper)}
header{padding-bottom:2rem}h1{font-family:"Songti SC","Noto Serif CJK SC",serif;font-weight:500;font-size:2.1rem}
header p,.hint{line-height:1.8;color:var(--blue)}h2{padding:.75rem 0 .75rem 1rem;border-left:4px solid var(--blue);background:var(--light);font-weight:500}
h3{font-size:1.2rem;font-weight:500;margin:2.5rem 0 1.8rem}.prose{white-space:pre-wrap;overflow-wrap:anywhere;font-family:"Songti SC","Noto Serif CJK SC",serif;font-size:1.15rem;line-height:2.05;letter-spacing:.025em}
article{padding-bottom:2rem}.work{padding-bottom:3rem}button,input,select,textarea{font:inherit}button{cursor:pointer;border:1px solid var(--blue);border-radius:4px;background:var(--blue);color:white;padding:.7rem 1rem}
.mark{margin-top:1.3rem;background:var(--paper);color:var(--blue);font-size:.88rem}.ratings{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}label{display:block;line-height:1.7;margin-bottom:1rem}
input:not([type=checkbox]),select,textarea{display:block;max-width:100%;width:100%;border:1px solid var(--line);border-radius:4px;padding:.6rem;background:var(--paper);color:var(--ink)}textarea{min-height:8rem;resize:vertical}
fieldset{border:1px solid var(--line);padding:1.3rem;margin:1.5rem 0}legend{padding:0 .5rem}blockquote{margin:1rem 0;border-left:3px solid var(--line);padding-left:1rem;white-space:pre-wrap}
#feedback{border-top:1px solid var(--line);padding-top:2rem}.actions{display:flex;flex-wrap:wrap;gap:1rem}.secondary{background:var(--paper);color:var(--blue)}:focus-visible{outline:3px solid var(--blue);outline-offset:3px}#status{white-space:pre-wrap;line-height:1.8}
@media(max-width:600px){main{padding:1.8rem 1.1rem}.ratings{grid-template-columns:1fr}.prose{font-size:1.08rem}nav{gap:1rem;font-size:.9rem}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}@media print{nav,.mark,form{display:none}main{max-width:none;padding:0}.work{break-before:page}.prose{font-size:11pt}}
</style></head><body><nav aria-label="阅读目录">__NAVIGATION__<a href="#feedback">阅读反馈</a></nav><main>
<header><h1>读完，再说感受</h1><p>每篇作品连续阅读。可以暂时无法判断，也可以没有偏好。选中正文里的文字，可记下让你信服、困惑或想跳过的地方。</p></header>
__CHAPTERS__
<section id="feedback"><h2>你的阅读体验</h2><p class="hint">评分为 1—5。除修改负担外，分数越高体验越好：重复与跳读 5 表示很少需要跳过；修改负担 1 表示很小，5 表示很大。默认留空。</p>
<form id="response"><label>你的署名或昵称<input id="reviewer" required autocomplete="nickname"></label>
__RATINGS__<label>如果继续读，你更想读哪篇？<select id="preference"><option value="">没有偏好 / 无法判断</option>__PREFERENCE__</select></label>
<label>阅读感受与修改建议<textarea id="notes" required placeholder="哪里可信，哪里重复，哪里想继续读？"></textarea></label>
<div id="observations" aria-label="已选文字的阅读感受"></div>
<label>填写前是否知道各篇的生成方案？<select id="blinded" required><option value="">请选择</option><option value="true">不知道</option><option value="false">知道或已看过对应说明</option></select></label>
<label><input id="attestation" type="checkbox" required> 我本人阅读并填写了这些反馈</label>
<div class="actions"><button id="save" type="submit">保存阅读反馈</button><button id="download" type="button" class="secondary">下载已填反馈</button></div>
<p id="status" role="status" aria-live="polite"></p></form></section></main>
<script type="application/json" id="reading-data">__PAYLOAD__</script><script>
'use strict';
const data=JSON.parse(document.getElementById('reading-data').textContent), form=document.getElementById('response');
document.querySelectorAll('.prose').forEach(prose=>prose.textContent=data.chapters[prose.dataset.chapter]);
const marks=[], status=document.getElementById('status'); let submissionId=null, pendingPayload=null, saved=false;
const unicodeLength=text=>Array.from(text).length;
document.querySelectorAll('.mark').forEach(button=>button.addEventListener('click',()=>{
 const prose=button.previousElementSibling, selection=window.getSelection();
 if(!selection || !selection.rangeCount || selection.isCollapsed){status.textContent='请先选中同一章里的文字。';return;}
 const range=selection.getRangeAt(0);
 if(!prose.contains(range.startContainer)||!prose.contains(range.endContainer)){status.textContent='请选中同一章里的文字。';return;}
 const prefix=range.cloneRange();prefix.selectNodeContents(prose);prefix.setEnd(range.startContainer,range.startOffset);
 const quote=range.toString(),start=unicodeLength(prefix.toString()),end=start+unicodeLength(quote),token=prose.dataset.chapter;
 if(Array.from(data.chapters[token]).slice(start,end).join('')!==quote){status.textContent='所选文字无法定位，请重新选择。';return;}
 const section=document.createElement('fieldset'),legend=document.createElement('legend'),block=document.createElement('blockquote'),label=document.createElement('label'),note=document.createElement('textarea'),remove=document.createElement('button');
 legend.textContent='这一处的阅读感受';block.textContent=quote;label.textContent='为什么记下这里？';note.required=true;label.append(note);remove.type='button';remove.className='secondary';remove.textContent='移除此处';
 const mark={chapter_token:token,start,end,quote,note,section};marks.push(mark);remove.onclick=()=>{marks.splice(marks.indexOf(mark),1);section.remove();pendingPayload=null;};
 section.append(legend,block,label,remove);document.getElementById('observations').append(section);note.focus();pendingPayload=null;
}));
function responsePayload(){
 if(!form.reportValidity())return null;
 if(saved){status.textContent='此份反馈已保存。';return null;}
 if(pendingPayload)return pendingPayload;
 const response=structuredClone(data.response_template);response.reviewer_id=document.getElementById('reviewer').value.trim();response.human_attestation=document.getElementById('attestation').checked;response.was_blinded=document.getElementById('blinded').value==='true';
 response.preferred_manuscript_token=document.getElementById('preference').value||null;response.reading_notes=document.getElementById('notes').value;
 document.querySelectorAll('[data-dimension]').forEach(select=>response.ratings[select.dataset.work][select.dataset.dimension]=select.value?Number(select.value):null);
 response.evidence_spans=marks.map(({chapter_token,start,end,quote,note})=>({chapter_token,start,end,quote,observation:note.value}));
 submissionId=crypto.randomUUID();pendingPayload={project_id:data.project_id,workspace_id:data.workspace_id,pack_id:data.pack_id,public_content_hash:data.public_content_hash,feedback_id:submissionId,response};return pendingPayload;
}
function freezeResponse(frozen){form.querySelectorAll('input,select,textarea,button:not(#save):not(#download)').forEach(control=>control.disabled=frozen);document.querySelectorAll('.mark').forEach(control=>control.disabled=frozen);}
form.addEventListener('input',()=>{if(!saved)pendingPayload=null;});
document.getElementById('download').addEventListener('click',()=>{const payload=responsePayload();if(!payload)return;const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));link.download='reading-feedback-'+payload.feedback_id+'.json';link.click();URL.revokeObjectURL(link.href);status.textContent='反馈文件已下载，尚未保存到阅读入口。';});
if(location.protocol==='file:'){document.getElementById('save').disabled=true;status.textContent='此文件可以离线阅读和填写。下载已填反馈后，通过在线阅读入口保存。';}
form.addEventListener('submit',async event=>{event.preventDefault();const payload=responsePayload();if(!payload)return;const button=document.getElementById('save');button.disabled=true;status.textContent='正在保存阅读反馈……';
 freezeResponse(true);
 try{const result=await fetch('/api/quality-qualification/manuscript-feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!result.ok){if(result.status===422){freezeResponse(false);pendingPayload=null;button.disabled=false;status.textContent='这份反馈未被保存。请检查署名、阅读感受及所选文字，然后重新提交。';return;}throw new Error('save failed');}saved=true;form.querySelectorAll('input,select,textarea,button').forEach(control=>control.disabled=true);status.textContent='反馈已保存。你可以继续阅读正文。';}
 catch(error){status.textContent='保存结果尚未确认。请保持当前页面，重试会沿用同一份反馈；也可以先下载已填反馈。';button.disabled=false;}
});
</script></body></html>'''
