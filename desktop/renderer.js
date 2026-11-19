"use strict";
const $=selector=>document.querySelector(selector);
const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const icon=name=>'<i aria-hidden="true" class="ph ph-'+name+'"></i>';
const btn=(action,label,glyph="",primary=false)=>'<button class="btn'+(primary?" primary":"")+'" data-action="'+action+'">'+(glyph?icon(glyph):"")+esc(label)+'</button>';
const ib=(action,glyph,label,disabled=false)=>'<button class="icon-btn" data-action="'+action+'" aria-label="'+esc(label)+'" title="'+esc(label)+'" '+(disabled?"disabled":"")+'>'+icon(glyph)+'</button>';
const palettes=[
  ["#efebfc","#ded6f5","#9182d3","#b1a0ee","#9380d9","#594599","#a197d7"],
  ["#e4f3ed","#cee9df","#69a792","#88cbb0","#68b598","#376e5b","#7bb9a3"],
  ["#fff0db","#f4e0bd","#d3a05a","#f3c37e","#e3af64","#8a6331","#d4a76c"],
  ["#e5edfc","#d3e1f8","#7d9fc9","#a2bff1","#80a4de","#4b659a","#879fd5"],
  ["#fce7e7","#f1d4d2","#c68989","#ebb0ad","#db9391","#955a5a","#d59c9c"],
  ["#e7f0f2","#cde0e3","#779fa7","#9dc7ce","#81b6be","#426e78","#80aeb6"]
];
const colors=g=>{const p=palettes[Math.max(0,data?.groups.indexOf(g)??0)%palettes.length];return ["wash","rim","back","front","fold","ink","dot"].map((k,i)=>"--"+k+":"+p[i]).join(";");};
const titles={review:"파일 검토",matrix:"유사도 행렬",flow:"분석 과정"};
let data=null,groups=new Map(),files=new Map(),view="review",scope=null,query="",groupQuery="",page=0;
let selected=new Set(),busy=false,scanBusy=false,renderId=0,toastTimer,dialogAction=null;
let mxRow=0,mxCol=0,pair=null,options={recursive:false,deep:true,covers:true,roots:[]};
let sourceBusy=false,searchVersion=0,destinationMode="new",destination=null;
let activeId=null,detailInfo=null,detailVersion=0,detailOpen=false,detailTab="evidence",relatedRows=null,relatedBusy=false,relatedError="";
const compactDetails=window.matchMedia("(max-width:1199px)");
const PAGE_SIZE=100;
function bytes(n){if(n<1024)return n+" B";if(n<1048576)return Math.round(n/1024)+" KB";return (n/1048576).toFixed(1)+" MB";}
function fileBadge(ext){
  const kind=ext==="pdf"?"pdf":/^(pptx?|zip|7z|rar)$/.test(ext)?"slides":/^(xlsx?|csv|tsv)$/.test(ext)?"sheet":/^(docx?|hwp[x]?|md|txt)$/.test(ext)?"word":"";
  return '<span class="doctype '+kind+'" aria-hidden="true">'+esc((ext||"FILE").toUpperCase().slice(0,4))+'</span>';
}
function chip(f){
  const g=groups.get(f.group);
  return '<button class="group-chip" data-scope="'+esc(g?.id||"hold")+'" style="'+(g?colors(g):"")+'"><span class="dot"></span><span class="ellipsis">'+esc(g?.title||"미분류")+'</span></button>';
}
function toast(text){clearTimeout(toastTimer);$("#toast").textContent=text;$("#toast").hidden=false;toastTimer=setTimeout(()=>$("#toast").hidden=true,3200);}
function status(text,canCancel=false){const el=$("#status");el.hidden=!text;el.innerHTML=esc(text)+(canCancel?'<button data-action="cancel">분석 취소</button>':"");}
function setBusy(value){
  busy=value;document.querySelector('[data-action="scan"]').disabled=value;updateReviewBar();
  document.querySelectorAll('[data-file-edit],[data-action="groupRename"],[data-action="groupMenu"]').forEach(b=>b.disabled=value||(!b.matches('[data-action="groupRename"]')&&!editableIds().length));
}
async function call(action,args={}){
  const r=await window.desktop.call(action,{generation:data?.generation,...args});
  if(!r.ok){const e=new Error(r.error||"작업을 완료하지 못했습니다.");e.code=r.code;throw e;}return r.value;
}
function showDialog(title,description,body,footer="",action=null,wide=false){
  const d=$("#dialog");dialogAction=action;d.classList.toggle("wide",wide);
  $("#dialog-frame").innerHTML='<div class="dhead"><div><h2>'+esc(title)+'</h2>'+(description?'<p class="muted">'+esc(description)+'</p>':"")+'</div>'+ib("close","x","닫기")+'</div><div class="dbody">'+body+'</div><div class="dfoot">'+(footer||btn("close","닫기"))+'</div>';
  d.setAttribute("aria-label",title);if(!d.open)d.showModal();
}
function close(){searchVersion++;if($("#dialog").open)$("#dialog").close();dialogAction=null;}
function errorDialog(e){showDialog("작업을 확인해 주세요","",'<p class="muted">'+esc(e.message||String(e))+'</p>');}
function setScope(id){
  view="review";scope=id==="all"?null:id;query="";page=0;selected.clear();activeId=null;detailInfo=null;detailOpen=false;detailVersion++;render();
}
function scopeFiles(){return !data?[]:scope==="hold"?data.files.filter(f=>!f.group):scope?data.files.filter(f=>f.group===scope):data.files;}
function visibleFiles(){
  const q=query.trim().toLocaleLowerCase();
  return scopeFiles().filter(f=>!q||f.name.toLocaleLowerCase().includes(q));
}
async function scan(newOptions=options){
  if(busy)return;
  scanBusy=true;setBusy(true);status("선택한 폴더 분석 중",true);renderSources();
  try {
    data=await call("scan",{...options,...newOptions});options={...options,...data.options,roots:data.roots||data.options?.roots||options.roots};
    groups=new Map(data.groups.map(g=>[g.id,g]));files=new Map(data.files.map(f=>[f.id,f]));
    if(scope && scope!=="hold"&&!groups.has(scope))scope=null;
    selected.clear();activeId=null;detailInfo=null;detailVersion++;detailOpen=false;pair=null;mxRow=0;mxCol=0;page=0;status("");render();
  } catch(e){status(e.message);if(!data)$("#content").innerHTML='<div class="panel empty">분석 폴더를 확인하거나 다른 폴더를 추가한 뒤 다시 분석하세요.</div>'; }
  finally{scanBusy=false;setBusy(false);renderSources();}
}
function renderSources(){
  if($("#source-roots"))$("#source-roots").innerHTML=options.roots.map((p,i)=>'<div class="source-root" role="listitem"><span>'+icon("folder-open")+esc(p)+(i===0?' <small>(기본)</small>':'')+'</span><button class="btn" data-remove-root="'+i+'" aria-label="'+esc(p)+' 분석 폴더에서 제외" '+(busy||sourceBusy||i===0?"disabled":"")+'>제외</button></div>').join("")||'<p class="muted">분석 폴더를 불러오지 못했습니다. 폴더를 추가해 시작하세요.</p>';
  if($('[data-action="addSource"]'))$('[data-action="addSource"]').disabled=busy||sourceBusy;
  $("#root-path span").textContent="분석 폴더 "+options.roots.length+"개";
}
function sourcesDialog(){
  showDialog("분석 폴더","다운로드 폴더와 추가한 위치의 파일을 함께 검토합니다.",'<div id="source-roots" role="list"></div><p class="muted source-note">기본 다운로드 폴더는 유지됩니다. 추가 폴더를 제외해도 실제 파일은 그대로 남습니다.</p>',btn("close","닫기")+btn("addSource","폴더 추가","plus",true));
  renderSources();
}
async function saveSources(roots){
  sourceBusy=true;renderSources();
  try{const result=await call("sources",{roots});options.roots=Array.isArray(result)?result:result.roots;return true;}
  finally{sourceBusy=false;renderSources();}
}
async function addSource(path=null){
  const chosen=path||await call("chooseFolder");if(!chosen)return;
  if(!options.roots.some(p=>p.toLocaleLowerCase()===chosen.toLocaleLowerCase()))await saveSources([...options.roots,chosen]);
  close();await scan();
}
function parentPath(path){const i=Math.max(path.lastIndexOf("\\"),path.lastIndexOf("/"));return i===2&&path[1]===":"?path.slice(0,3):i===0?"/":path.slice(0,i);}
function externalSearch(){
  showDialog("다른 위치에서 찾기","현재 목록 필터와 별개로 PC의 파일 이름을 검색합니다.",
    '<form id="external-search-form" class="external-search-form"><label for="external-query">찾을 파일 이름</label><div class="tools"><input id="external-query" class="field" type="search" required autocomplete="off" placeholder="예: 계약서, 여행, 프로젝트"><button class="btn primary" type="submit">찾기</button></div></form><p class="muted">결과는 자동으로 이동하지 않습니다. 필요한 파일의 상위 폴더를 분석 폴더에 추가한 뒤 추천을 검토하세요.</p><div id="external-results" aria-live="polite"></div>',btn("close","닫기"),null,true);
  $("#external-query").focus();$("#external-search-form").onsubmit=async e=>{
    e.preventDefault();const q=$("#external-query").value.trim();if(!q)return;
    const version=++searchVersion,submit=e.target.querySelector('button[type="submit"]');submit.disabled=true;
    $("#external-results").innerHTML='<p class="empty" role="status">다른 위치에서 찾는 중… 닫기를 누르면 결과 표시를 취소합니다.</p>';
    try{
      const result=await call("search",{query:q});if(version!==searchVersion||!$("#external-results"))return;
      $("#external-results").innerHTML='<p class="search-meta">'+esc(result.backend)+' · '+esc(result.elapsed)+' ms'+(result.truncated?' · 일부 결과만 표시':"")+'</p><p class="muted">'+esc(result.note)+'</p>'+
        (result.results.length?result.results.map(r=>'<article class="search-result"><strong>'+esc(r.name)+'</strong><p>'+esc(r.path)+'</p><button class="btn" data-add-parent="'+esc(parentPath(r.path))+'">이 상위 폴더 추가 후 분석</button></article>').join(""):'<p class="empty">일치하는 파일이 없습니다. 다른 파일 이름으로 찾아보세요.</p>');
    }catch(err){if(version===searchVersion&&$("#external-results"))$("#external-results").innerHTML='<p class="empty" role="alert">'+esc(err.message)+'</p>';}
    finally{if(submit.isConnected)submit.disabled=false;}
  };
}
function nav(){
  $("#rail-count").textContent=data?.groups.length??0;
  const q=groupQuery.trim().toLocaleLowerCase(),shown=(data?.groups||[]).filter(g=>!q||g.title.toLocaleLowerCase().includes(q));
  $("#group-nav").innerHTML='<button class="rail-group '+(!scope&&view==="review"?"current":"")+'" data-scope="all">'+icon("stack")+'<span>전체 파일</span><small>'+(data?.files.length??0)+'</small></button>'+
    '<button class="rail-group '+(scope==="hold"&&view==="review"?"current":"")+'" data-scope="hold">'+icon("tray")+'<span>미분류</span><small>'+(data?.files.filter(f=>!f.group).length??0)+'</small></button><div class="group-divider"></div>'+
    shown.map(g=>'<button title="'+esc(g.title)+'" class="rail-group '+(scope===g.id&&view==="review"?"current":"")+'" aria-current="'+(scope===g.id&&view==="review"?"true":"false")+'" data-scope="'+esc(g.id)+'" style="'+colors(g)+'"><span class="dot"></span><span>'+esc(g.title)+'</span><small>'+g.count+'</small></button>').join("")+
    (q&&!shown.length?'<p class="rail-empty">일치하는 묶음이 없습니다.</p>':"");
  document.querySelectorAll("[data-view]").forEach(b=>b.classList.toggle("active",b.dataset.view===view));
}
function render(){
  const generation=++renderId;nav();$("#crumb").textContent=titles[view];
  $("#headline").textContent=titles[view];renderSources();updateReviewBar();
  $("#content").classList.toggle("advanced-content",view!=="review");
  if(!data)return;
  if(view==="review")review();
  else if(view==="matrix")matrix(generation).catch(errorDialog);
  else flow();
}
function editableIds(){return selected.size?[...selected]:activeId!==null?[activeId]:[];}
function updateReviewBar(){
  const eligible=(view==="review"?scopeFiles():data?.files||[]).filter(f=>f.group);
  $("#organize").disabled=busy||!eligible.length;
  $("#review-count").textContent=(view==="review"&&scope?scope==="hold"?"미분류 파일":groups.get(scope)?.title||"현재 묶음":"전체 추천 묶음")+" · 이동 대상 "+eligible.length+"개";
  $("#review-hint").textContent=eligible.length?"위치를 선택하고 실제 이동 경로를 확인하세요.":"미분류 파일은 묶음을 지정하거나 선택 편집에서 개별 이동하세요.";
}
function review(){
  const g=groups.get(scope),all=scopeFiles();
  $("#content").innerHTML='<div class="review-workspace"><section class="file-pane" aria-label="파일 목록"><div class="file-pane-head"><div class="section-head"><div class="hrow"><h2>'+esc(g?.title||(scope==="hold"?"미분류":"전체 파일"))+'</h2><span class="head-count">'+all.length+'</span></div>'+(g?btn("groupRename","이름 변경","pencil-simple"):"")+'</div><p class="scope-note">'+esc(g?.note||(scope==="hold"?"묶음이 정해지지 않은 파일입니다. 선택해서 직접 분류할 수 있어요.":"왼쪽에서 묶음을 선택하거나, 파일을 눌러 추천 근거를 살펴보세요."))+'</p><label class="search">'+icon("magnifying-glass")+'<input id="search" type="search" value="'+esc(query)+'" placeholder="현재 목록에서 파일명 필터" aria-label="현재 목록에서 파일명 필터"><kbd>Ctrl K</kbd></label></div>'+
    '<div id="selection-bar" class="selection-bar"><span id="selection-count">파일 선택</span><div class="selection-actions"><button class="btn" data-file-edit="assign">'+icon("folder-notch-open")+'다른 묶음</button><button class="btn" data-file-edit="unclassify">미분류로</button><button class="btn" data-file-edit="create">'+icon("plus")+'새 묶음</button>'+ib("groupMenu","dots-three","선택 파일 추가 편집")+'</div></div>'+
    '<div class="table-scroll" tabindex="0" aria-label="파일 목록 스크롤"><table><thead><tr><th class="checkbox"><input id="all-check" type="checkbox" aria-label="필터 결과 전체 선택"></th><th class="name-col">파일명 · 원래 위치</th><th class="group-col">묶음</th><th class="score-col">신뢰도</th><th class="open-col"></th></tr></thead><tbody id="file-rows"></tbody></table><div id="empty" class="empty" hidden></div></div><div class="table-foot"><span id="row-summary"></span><span id="page-tools"></span></div></section>'+
    '<button id="detail-scrim" data-action="closeDetail" aria-label="파일 목록으로 돌아가기" hidden></button><aside id="file-inspector" class="file-inspector" aria-label="선택한 파일 근거" tabindex="-1"><div class="inspector-heading"><h2>파일 근거</h2>'+btn("closeDetail","목록으로","arrow-left")+'</div><div id="inspector-body" class="inspector-body"><div class="inspector-empty">'+icon("file-magnifying-glass")+'<h3>파일의 연결을 살펴보세요</h3><p>목록에서 파일을 선택하면 원래 위치와 수정 시각, 추천 근거를 확인할 수 있어요.</p></div></div></aside></div>';
  $("#search").oninput=e=>{query=e.target.value;page=0;rows();};rows();syncInspector();
  if(activeId!==null&&files.has(activeId))detail(activeId,false).catch(errorDialog);
}
function rows(){
  const focusedCheck=document.activeElement?.dataset.check;
  const arr=visibleFiles();page=Math.min(Math.max(0,Math.ceil(arr.length/PAGE_SIZE)-1),page);
  const chunk=arr.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE);
  $("#file-rows").innerHTML=chunk.map(f=>'<tr class="'+(activeId===f.id?"active-file ":"")+(selected.has(f.id)?"checked-file":"")+'" data-file="'+f.id+'" tabindex="0" aria-label="'+esc(f.name)+' 근거 보기" aria-selected="'+(activeId===f.id)+'"><td class="checkbox"><input type="checkbox" aria-label="'+esc(f.name)+' 선택" data-check="'+f.id+'" '+(selected.has(f.id)?"checked":"")+'></td><td><div class="filename" title="'+esc(f.name)+'">'+fileBadge(f.ext)+'<span><strong>'+esc(f.name)+'</strong><small title="'+esc(f.path)+'">'+esc(f.path?parentPath(f.path):"위치 정보 없음")+'</small></span></div></td><td>'+chip(f)+'</td><td class="score-col">'+(f.confidence==null?"—":f.confidence.toFixed(2))+'</td><td class="open-col">'+icon("caret-right")+'</td></tr>').join("");
  $("#empty").hidden=!!arr.length;$("#empty").textContent=query?"필터와 일치하는 파일이 없습니다.":scope==="hold"?"미분류 파일이 없습니다.":"표시할 파일이 없습니다.";
  $("#row-summary").textContent="파일 "+arr.length+"개"+(query?" 검색됨":"");
  $("#page-tools").innerHTML=arr.length>PAGE_SIZE?ib("pagePrev","caret-left","이전 파일",page===0)+" "+(page+1)+" / "+Math.ceil(arr.length/PAGE_SIZE)+" "+ib("pageNext","caret-right","다음 파일",(page+1)*PAGE_SIZE>=arr.length):icon("clock")+" 마지막 분석 "+esc(data.time);
  const checked=arr.filter(f=>selected.has(f.id)).length;
  $("#all-check").checked=!!arr.length&&checked===arr.length;$("#all-check").indeterminate=checked>0&&checked<arr.length;
  const ids=editableIds();
  $("#selection-count").innerHTML=ids.length?'<strong>'+ids.length+'개 선택</strong><button data-action="deselect">해제</button>':'파일을 선택해 분류';
  document.querySelectorAll('[data-file-edit],[data-action="groupMenu"]').forEach(b=>b.disabled=busy||!ids.length);
  if(focusedCheck!==undefined)$('[data-check="'+focusedCheck+'"]')?.focus();
}
function infoRows(items){return '<dl class="info-list">'+items.filter(([,v])=>v!==undefined && v!==null && v!=="").map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>').join("")+'</dl>';}
function syncInspector(){
  const el=$("#file-inspector");if(!el)return;
  el.classList.toggle("open",detailOpen);$("#detail-scrim").hidden=!compactDetails.matches||!detailOpen;
  el.setAttribute("role",compactDetails.matches?"dialog":"complementary");
  if(compactDetails.matches&&detailOpen)el.setAttribute("aria-modal","true");else el.removeAttribute("aria-modal");
}
function closeDetail(){
  detailOpen=false;syncInspector();$('[data-file="'+activeId+'"]')?.focus();
}
async function detail(id,open=true){
  const f=files.get(id);if(!f)return;
  const version=++detailVersion,generation=data.generation;
  activeId=id;detailInfo=null;relatedRows=null;relatedBusy=false;relatedError="";detailTab="evidence";detailOpen=open;rows();syncInspector();
  $("#inspector-body").innerHTML='<div class="empty" role="status">파일 근거를 불러오는 중…</div>';
  if(open&&compactDetails.matches)$("#file-inspector").focus();
  try{
    const info=await call("detail",{id});
    if(version!==detailVersion||data.generation!==generation||!$("#inspector-body"))return;
    detailInfo=info;renderInspector();
  }catch(e){if(version===detailVersion&&$("#inspector-body"))$("#inspector-body").innerHTML='<div class="empty" role="alert">'+esc(e.message)+btn("retryDetail","다시 시도","arrows-clockwise")+'</div>';}
}
function renderInspector(){
  const f=files.get(activeId),info=detailInfo;if(!f||!info||!$("#inspector-body"))return;
  $("#inspector-body").innerHTML='<div class="inspector-file">'+fileBadge(f.ext)+'<div><h3>'+esc(f.name)+'</h3><p>'+esc((f.ext||"파일").toUpperCase())+' · '+bytes(f.size)+'</p></div></div><div class="detail-tabs" role="group" aria-label="파일 근거 보기 방식"><button data-detail-tab="evidence" aria-pressed="'+(detailTab==="evidence")+'">파일 근거</button><button data-detail-tab="related" aria-pressed="'+(detailTab==="related")+'">'+icon("git-branch")+'관계 보기</button></div>'+
    (detailTab==="related"?relatedContent(f):'<section class="detail-section"><h3>추천 설명</h3><p class="info-note">'+esc(info.note||"추천 설명이 없습니다.")+(info.evidence?'<br>'+esc(info.evidence):"")+'</p>'+infoRows([["현재 묶음",groups.get(f.group)?.title||"미분류"],["판정",f.state],["신뢰도",f.confidence?.toFixed(2)]])+'</section><section class="detail-section"><h3>실제 파일 정보</h3>'+infoRows([["원래 경로",info.path||f.path],["수정 시각",info.modified],["생성 시각",info.created]])+'</section><details class="detail-more"><summary>추가 분석 정보</summary>'+infoRows([["정규화 이름",info.normalized],["핵심 단어",info.tokens?.join(" · ")],["역할",info.roles?.join(" · ")],["순번",info.sequence],["버전",info.versions?.join(" · ")],["강좌명",info.course],["다운로드 페이지",info.page],["출처 페이지",info.source_page],["다운로드 사이트",f.host],["본문 발췌",info.excerpt]])+'</details>');
}
function relatedContent(f){
  const center='<div class="relation-center">'+icon("file-text")+'<div><small>선택한 파일</small><strong>'+esc(f.name)+'</strong></div></div>';
  if(relatedBusy)return center+'<p class="empty" role="status">연결된 파일을 확인하는 중…</p>';
  if(relatedError)return center+'<p class="empty" role="alert">'+esc(relatedError)+'</p>'+btn("retryRelated","다시 시도","arrows-clockwise");
  const rows=relatedRows||[];
  return '<p class="related-caption">선택한 파일을 중심으로 관련 파일 최대 5개만 표시합니다. 연결은 실제 파일 이동을 뜻하지 않습니다.</p>'+center+
    (rows.length?'<ol class="related-list">'+rows.map(r=>'<li><button class="related-file" data-related-file="'+esc(r.id)+'"><span class="relation-node" aria-hidden="true"></span><strong>'+esc(r.name)+'</strong><span class="related-meta">'+esc(groups.get(r.group)?.title||"미분류")+' · 관련도 '+(Number(r.score)/100).toFixed(2)+'</span></button><p class="related-signals">'+esc(r.signals.join(" · ")||"현재 묶음에서 함께 검토하는 파일")+'</p></li>').join("")+'</ol>':'<p class="empty">현재 연결된 파일이 없습니다. 다른 파일을 선택해 살펴보세요.</p>');
}
async function loadRelated(){
  if(activeId===null||!detailInfo||relatedBusy)return;
  const id=activeId,version=detailVersion;relatedBusy=true;relatedError="";renderInspector();
  try{
    const result=await call("related",{id});if(version!==detailVersion||id!==activeId)return;
    relatedRows=result.slice(0,5);
  }catch(e){if(version===detailVersion)relatedError=e.message;}
  finally{if(version===detailVersion){relatedBusy=false;renderInspector();}}
}
async function historyDialog(){
  const version=++searchVersion;
  showDialog("최근 정리","이 앱에 실제로 저장된 최근 정리 기록입니다.",'<div id="history-list" aria-live="polite"><p class="empty">정리 기록을 불러오는 중…</p></div>',btn("close","닫기")+btn("undo","최근 이동 되돌리기","arrow-counter-clockwise"),null,true);
  try{
    const batches=await call("history");if(version!==searchVersion||!$("#history-list"))return;
    $("#history-list").innerHTML=batches.length?'<p class="muted history-note">이동 수에는 이후 되돌린 파일도 포함됩니다. 시각은 기록의 최근 변경 시각입니다.</p>'+batches.slice(0,10).map(batch=>'<article class="history-batch"><div class="history-head"><strong>이동 '+esc(batch.moved)+'개</strong><span>최근 변경 <time>'+esc(batch.time)+'</time></span></div><p>되돌림 '+esc(batch.undone)+'개 · 남은 이동 '+esc(batch.pending)+'개</p>'+(batch.files.length?'<details><summary>기록된 파일 보기 · 최대 8개</summary><ul>'+batch.files.map(name=>'<li>'+esc(name)+'</li>').join("")+'</ul></details>':"")+'</article>').join(""):'<p class="empty">저장된 정리 기록이 없습니다.<br>이 앱에서 실제로 이동한 파일만 기록됩니다.</p>';
  }catch(e){if(version===searchVersion&&$("#history-list"))$("#history-list").innerHTML='<p class="empty" role="alert">'+esc(e.message)+'</p>'+btn("history","다시 시도","arrows-clockwise");}
}
function groupMenu(){
  const items=[],ids=editableIds();
  selected=new Set(ids);
  const g=groups.get(scope)||groups.get(files.get(ids[0])?.group);
  const add=(type,label,glyph)=>items.push('<button class="menu-btn" data-edit="'+type+'" data-group="'+esc(g?.id||"")+'">'+icon(glyph)+esc(label)+'</button>');
  if(ids.length){add("assign","다른 그룹으로 이동","folder-notch-open");add("create","새 그룹 만들기","folder-simple-plus");add("manual","체크한 파일을 폴더로 이동","arrow-square-out");}
  if(g){add("rename","그룹 이름 변경","pencil-simple");add("course","그룹 이름 확인","bookmark-simple");add("merge","두 그룹 병합","intersect");if(ids.length&&ids.length<g.count&&ids.every(id=>files.get(id).group===g.id))add("split","선택 파일로 그룹 분리","git-fork");}
  if(ids.length===2){add("must","두 파일을 같은 그룹으로 지정","link");add("cannot","두 파일을 다른 그룹으로 지정","link-break");add("clear","두 파일의 관계 해제","eraser");}
  showDialog("그룹 편집",ids.length?ids.length+"개 파일 선택":g?.title||"",items.join(""));
}
async function applyEdit(args){
  try {await call("edit",args);}
  catch(e){if(e.code!=="courseConflict")throw e;
    showDialog("강좌 출처 확인","",'<p class="result-lines">'+esc(e.message)+'</p>',btn("close","취소")+btn("submitDialog","같은 그룹으로 지정","check",true),()=>applyEdit({...args,confirm:true}));return;}
  close();await scan();toast("그룹 편집을 저장했어요.");
}
async function editForm(kind,gid){
  const ids=editableIds(),g=groups.get(gid);
  if(kind==="manual"){close();return preview("manual");}
  const args={kind,files:ids,group:g?.id||null};
  if(["must","cannot","clear"].includes(kind))return applyEdit(args);
  if(["assign","merge"].includes(kind)){
    const choices=data.groups.filter(t=>kind!=="merge"||t.id!==gid);
    if(!choices.length&&kind==="merge"){toast("병합할 다른 그룹이 없습니다.");return;}
    const opts=(kind==="assign"?'<option value="">미분류</option>':"")+choices.map(t=>'<option value="'+t.id+'">'+esc(t.title)+" ("+t.count+'개)</option>').join("");
    showDialog(kind==="assign"?"다른 그룹으로 이동":"두 그룹 병합","","<label>대상 그룹<select id=\"value\" class=\"field\">"+opts+"</select></label>",
      btn("close","취소")+btn("submitDialog","적용","check",true),()=>applyEdit({...args,target:$("#value").value}));return;
  }
  const cover=kind==="course"?await call("cover",{group:gid}):null;
  const title=({rename:"그룹 이름 변경",create:"새 그룹 만들기",split:"그룹 분리",course:"그룹 이름 확인"})[kind];
  showDialog(title,cover?.[1]||"",'<label>그룹 이름<input id="value" class="field" maxlength="140" value="'+esc(cover?.[0]||(kind==="rename"?g?.title:""))+'"></label>',
    btn("close","취소")+btn("submitDialog","저장","check",true),()=>{const val=$("#value").value.trim();if(!val){$("#value").focus();return;}return applyEdit({...args,title:val});});
  $("#value").focus();$("#value").select();
}
function chooseDestination(){
  destinationMode="new";destination=null;destinationDialog();
}
function destinationDialog(){
  showDialog("정리할 위치 선택","추천 그룹을 검토한 뒤 원하는 위치로 정리하세요.",
    '<fieldset class="destination-options"><legend>폴더 구성</legend><label><input type="radio" name="destination-mode" value="new" '+(destinationMode==="new"?"checked":"")+'> 새 그룹 폴더 만들기 <small>그룹별로 새 하위 폴더를 만듭니다.</small></label><label><input type="radio" name="destination-mode" value="existing" '+(destinationMode==="existing"?"checked":"")+'> 기존 폴더에 모으기 <small>선택한 폴더로 파일을 함께 옮깁니다.</small></label></fieldset><p class="preview-path" id="destination-path">'+esc(destination||(destinationMode==="new"?"기본 위치: "+data.root:"아직 폴더를 선택하지 않았습니다."))+'</p><div class="tools">'+btn("pickDestination",destinationMode==="new"?"다른 상위 폴더 선택":"기존 폴더 선택","folder-open")+(destinationMode==="new"&&destination?btn("defaultDestination","기본 위치 사용"):"")+'</div><p class="muted">다음 화면에서 파일마다 정확한 현재 경로와 이동할 경로를 확인합니다.</p>',
    btn("close","취소")+btn("submitDialog","이동 경로 미리보기","arrow-right",true),()=>{
      if(destinationMode==="existing"&&!destination){$("#destination-path").textContent="기존 폴더를 먼저 선택해 주세요.";$('[data-action="pickDestination"]').focus();return;}
      return preview("organize",{destinationMode,...(destination?{destination}:{})});
    });
  document.querySelectorAll('[name="destination-mode"]').forEach(el=>el.onchange=()=>{destinationMode=el.value;destination=null;destinationDialog();});
}
async function preview(kind,args={}){
  const result=await call("preview",{kind,group:view==="review"&&scope!=="hold"?scope:null,files:[...selected],...args});
  if(!result)return;
  const rows=result.rows,move=rows.filter(r=>!r.skip),byFolder=new Map();
  rows.forEach(r=>{const path=parentPath(r.target);if(!byFolder.has(path))byFolder.set(path,[]);byFolder.get(path).push(r);});
  const title=kind==="undo"?"최근 이동 되돌리기":"폴더 정리 미리보기";
  const body=[...byFolder].map(([p,fs])=>'<section class="move-group"><strong>'+icon("folder-notch")+esc(p)+'</strong>'+fs.map(f=>'<div class="move-row"><b>'+esc(f.name)+'</b>'+infoRows([["현재 경로",f.source],["이동할 경로",f.target]])+(f.skip?'<small>건너뜀 · '+esc(f.skip)+'</small>':"")+'</div>').join("")+'</section>').join("");
  showDialog(title,move.length+"개 파일 "+(kind==="undo"?"복원 예정":"이동 예정")+(rows.length>move.length?"   ·   "+(rows.length-move.length)+"개 건너뜀":""),
    body||'<p class="empty">처리할 파일이 없습니다.</p>',btn("close","취소")+(move.length?btn("submitDialog",move.length+"개 파일 "+(kind==="undo"?"복원":"이동"),kind==="undo"?"arrow-counter-clockwise":"folder-simple-plus",true):""),
    async()=>{close();setBusy(true);status("파일 처리 중");let report;
      try{report=await call("execute",{token:result.token});}finally{setBusy(false);status("");}
      await scan();showDialog("파일 처리 결과","",'<div class="result-lines">'+esc(report.join("\n"))+'</div>',btn("openDownloads","다운로드 폴더 열기","folder-open")+btn("close","닫기","check",true),null,true);
    },true);
}
async function matrix(version){
  const n=data.files.length;mxRow=Math.min(mxRow,Math.max(0,Math.ceil(n/10)-1));mxCol=Math.min(mxCol,Math.max(0,Math.ceil(n/10)-1));
  const scores=await call("matrix",{start:mxRow*10,col:mxCol*10});
  if(version!==renderId||view!=="matrix")return;
  const range=Array.from({length:Math.ceil(n/10)},(_,i)=>i);
  const pageSelect=(key,index)=>'<select id="'+key+'" aria-label="'+(key==="mx-row"?"행 범위":"열 범위")+'">'+range.map(i=>'<option value="'+i+'" '+(index===i?"selected":"")+'>'+ (i*10+1)+'–'+Math.min(n,(i+1)*10)+'</option>').join("")+'</select>';
  const cols=data.files.slice(mxCol*10,mxCol*10+10),rs=data.files.slice(mxRow*10,mxRow*10+10);
  $("#content").innerHTML='<div class="panel"><div class="section-head"><h2>파일 간 관련도</h2><div class="matrix-controls">행 '+pageSelect("mx-row",mxRow)+' 열 '+pageSelect("mx-col",mxCol)+'</div></div><p class="muted">셀을 선택하면 두 파일이 연결된 근거를 볼 수 있어요.</p><div class="matrix-scroll"><table class="matrix"><thead><tr><th class="axis">파일명</th>'+cols.map(f=>'<th title="'+esc(f.name)+'">#'+(f.id+1)+'</th>').join("")+'</tr></thead><tbody>'+rs.map((a,i)=>'<tr><th class="axis" title="'+esc(a.name)+'">#'+(a.id+1)+' '+esc(a.name)+'</th>'+cols.map((b,j)=>{const v=scores[i][j];return '<td class="'+(pair?.[0]===a.id&&pair?.[1]===b.id?"selected":"")+'" style="background:hsl(251 47% '+(98-v*.54)+'%);color:'+(v>66?"white":"#3b3556")+'"><button data-pair="'+a.id+','+b.id+'" title="'+esc(a.name+" ↔ "+b.name)+'">'+(v/100).toFixed(2)+'</button></td>';}).join("")+'</tr>').join("")+'</tbody></table></div></div><div class="panel" id="pair-detail"></div>';
  $("#mx-row").onchange=e=>{mxRow=Number(e.target.value);pair=null;render();};$("#mx-col").onchange=e=>{mxCol=Number(e.target.value);pair=null;render();};
  if(!pair&&rs.length&&cols.length)pair=[rs[0].id,(cols[1]||cols[0]).id];
  if(pair)await pairDetail(version);
}
async function pairDetail(version){
  const [a,b]=pair,r=await call("pair",{a,b});if(version!==renderId||!$("#pair-detail")||a!==pair?.[0]||b!==pair?.[1])return;
  const ft=r.features;
  const relation=({must:"같은 그룹",cannot:"다른 그룹"})[r.rule]||"미지정";
  $("#pair-detail").innerHTML='<p class="pair-line">'+esc(files.get(a).name)+" ↔ "+esc(files.get(b).name)+'</p>'+
    '<p class="muted">1차 '+(r.primary/100).toFixed(2)+' → 최종 '+(r.score/100).toFixed(2)+'   ·   파일명 단어 '+ft.literal.toFixed(2)+'   ·   의미 '+ft.semantic.toFixed(2)+'   ·   강좌 출처 '+({"-1":"서로 다름","0":"단서 없음","1":"일치"})[ft.course]+(ft.source_page?"   ·   같은 출처 페이지":"")+(ft.task?"   ·   반복 작업명 일치":"")+'   ·   사용자 관계 '+relation+'</p>';
  if(a!==b)$("#pair-detail").insertAdjacentHTML("beforeend",'<div class="tools" style="margin-top:12px">'+[["must","같은 그룹"],["cannot","다른 그룹"],["clear","관계 해제"]].map(([k,l])=>'<button class="btn" data-relation="'+k+'">'+l+'</button>').join("")+'</div>');
}
function flow(){
  const cards=[
    ["folder-open","파일 스캔",data.files.length+"개 파일의 이름·크기·위치·시각과 남아 있는 출처 정보를 읽었어요."],
    ["grid-nine","유사도 계산",(data.files.length*(data.files.length-1)/2).toLocaleString()+"쌍의 파일명, 반복 작업명, 용어 관계와 강좌 문맥을 비교했어요."],
    ["intersect","그룹 생성","완전 연결 계층 클러스터링으로 추천 그룹 "+data.groups.length+"개를 만들었어요. 자동 병합 기준은 0.60이에요."],
    ["file-text","선택적 추가 분석","중간 신뢰도 "+data.medium+"개 중 "+data.attempted+"개에 본문 발췌를 시도했고 "+data.rescued+"개를 추가 추천했어요."],
    ["bookmark-simple","그룹 이름 확인","저장된 이름과 확인된 강좌명을 확인하고, 과목명 확인용 표지 "+data.covers+"개를 살펴봤어요."]];
  $("#content").innerHTML='<div class="panel"><div class="section-head"><h2>이번 분석 결과</h2><span class="muted">'+data.time+'   ·   '+(data.elapsed/1000).toFixed(2)+'초</span></div>'+cards.map(([i,t,s])=>'<div class="flow-row">'+icon(i)+'<div><h3>'+t+'</h3><p class="muted">'+s+'</p></div></div>').join("")+'</div>';
}
function settings(){
  const toggles=[["recursive","하위 폴더 포함","선택한 분석 폴더 안의 하위 폴더까지 분석"],["deep","애매한 파일만 본문 분석","중간 신뢰도 파일의 앞부분을 읽어 그룹 재검토"],["covers","문서 표지로 그룹 이름 찾기","대표 문서의 표지에서 이름 단서 확인 (예: 강의 자료)"]];
  showDialog("분석 설정","",toggles.map(([k,t,p])=>'<label class="setting"><span><b>'+t+'</b><small>'+p+'</small></span><input type="checkbox" id="opt-'+k+'" '+(options[k]?"checked":"")+'></label>').join("")+'<div style="padding-top:16px">'+btn("bridge","브라우저 출처 연결 (선택)","plugs-connected")+'<p class="muted">확장 프로그램 없이도 파일 분석과 정리를 사용할 수 있습니다.</p></div>',
    btn("close","취소")+btn("submitDialog","적용하고 다시 분석","arrows-clockwise",true),()=>{const val=Object.fromEntries(toggles.map(([k])=>[k,$("#opt-"+k).checked]));close();return scan(val);});
}
async function action(key){
  if(key==="close"){close();return;}
  if(key==="closeDetail"){closeDetail();return;}
  if(key==="cancel"){window.desktop.cancel();return;}
  if(key==="openDownloads"){await call("openDownloads");return;}
  if(busy)return;
  switch(key){
    case "scan":return scan();
    case "settings":return settings();
    case "all":return setScope("all");
    case "organize":return chooseDestination();
    case "pickDestination":{const p=await call("chooseFolder");if(p){destination=p;destinationDialog();}return;}
    case "defaultDestination":destination=null;return destinationDialog();
    case "addSource":return addSource();
    case "sources":return sourcesDialog();
    case "externalSearch":return externalSearch();
    case "history":return historyDialog();
    case "retryRelated":return loadRelated();
    case "undo":return preview("undo");
    case "groupMenu":return groupMenu();
    case "groupRename":return editForm("rename",scope);
    case "retryDetail":return detail(activeId);
    case "confirmCourse":return editForm("course",scope);
    case "submitDialog":{const fn=dialogAction;if(fn){const b=$('[data-action="submitDialog"]');if(b)b.disabled=true;try{await fn();}finally{if(b?.isConnected)b.disabled=false;}}return;}
    case "pagePrev":page=Math.max(0,page-1);return rows();
    case "pageNext":page++;return rows();
    case "deselect":selected.clear();activeId=null;detailInfo=null;detailVersion++;detailOpen=false;return review();
    case "bridge":{const p=await call("bridge");showDialog("브라우저 출처 연결","확장 폴더 경로를 복사했어요.",
      '<p class="muted">Edge 또는 Chrome의 확장 관리에서 개발자 모드를 켜고 ‘압축 풀린 파일 로드’를 선택하세요. 아래 폴더를 지정한 뒤 다운로드한 웹페이지에서 확장 아이콘을 눌러 ‘이 사이트 연결’을 선택하세요. HTTPS 사이트의 페이지 제목과 출처를 이 PC에 기록합니다.</p><p class="preview-path" style="margin-top:12px">'+esc(p)+'</p>');return;}
  }
}
document.addEventListener("click",async e=>{
  try {
    const el=e.target.closest("button,input,tr[data-file]");if(!el)return;
    const d=el.dataset;
    if(d.action)return await action(d.action);
    if(busy)return;
    if(d.removeRoot!==undefined){await saveSources(options.roots.filter((_,i)=>i!==Number(d.removeRoot)));close();await scan();return;}
    if(d.addParent)return await addSource(d.addParent);
    if(d.view){view=d.view;scope=null;selected.clear();detailOpen=false;detailVersion++;render();return;}
    if(d.scope){setScope(d.scope);return;}
    if(d.fileEdit){const ids=editableIds();if(!ids.length)return;if(d.fileEdit==="unclassify")return await applyEdit({kind:"assign",files:ids,target:""});return await editForm(d.fileEdit,scope);}
    if(d.detailTab){detailTab=d.detailTab;renderInspector();if(detailTab==="related"&&relatedRows===null)return await loadRelated();return;}
    if(d.relatedFile!==undefined){
      const id=Number(d.relatedFile),f=files.get(id);if(!f)return;
      if(!visibleFiles().some(x=>x.id===id)){scope=f.group||"hold";query="";selected.clear();activeId=null;page=0;render();}
      const index=visibleFiles().findIndex(x=>x.id===id);page=Math.floor(index/PAGE_SIZE);rows();await detail(id);
      $('[data-file="'+id+'"]')?.scrollIntoView({block:"nearest"});return;
    }
    if(d.check!==undefined||el.id==="all-check"){
      if(el.id==="all-check")visibleFiles().forEach(f=>el.checked?selected.add(f.id):selected.delete(f.id));
      else if(el.checked)selected.add(+d.check);else selected.delete(+d.check);rows();return;
    }
    if(d.file!==undefined)return await detail(+d.file);
    if(d.edit)return await editForm(d.edit,d.group||null);
    if(d.pair){pair=d.pair.split(",").map(Number);document.querySelectorAll(".matrix td.selected").forEach(x=>x.classList.remove("selected"));el.closest("td").classList.add("selected");return await pairDetail(renderId);}
    if(d.relation)return await applyEdit({kind:d.relation,files:pair});
  } catch(err){errorDialog(err);}
});
document.addEventListener("keydown",e=>{
  if(e.ctrlKey&&e.key.toLowerCase()==="k"&&!$("#dialog").open){e.preventDefault();if(view!=="review"){view="review";render();}$("#search")?.focus();}
  if(e.key==="Enter"&&e.target.matches("tr[data-file]")){e.preventDefault();detail(+e.target.dataset.file).catch(errorDialog);}
  if(e.key==="Enter"&&e.target.id==="value"&&e.target.tagName==="INPUT"){e.preventDefault();action("submitDialog").catch(errorDialog);}
  if(e.key==="Escape"&&!$("#dialog").open&&detailOpen){e.preventDefault();closeDetail();}
  if(e.key==="Tab"&&compactDetails.matches&&detailOpen&&!$("#dialog").open){
    const focusable=[...$("#file-inspector").querySelectorAll('button:not(:disabled),input,select,summary,[tabindex="0"]')];
    const first=focusable[0],last=focusable.at(-1);
    if(e.shiftKey&&(e.target===first||e.target===$("#file-inspector"))){e.preventDefault();last?.focus();}
    else if(!e.shiftKey&&e.target===last){e.preventDefault();first?.focus();}
  }
});
$("#group-search").oninput=e=>{groupQuery=e.target.value;nav();};
compactDetails.addEventListener("change",syncInspector);
window.desktop.status(t=>{if(busy)status(t,scanBusy);});
$("#dialog").addEventListener("cancel",()=>{searchVersion++;dialogAction=null;});
(async()=>{try{options={...options,...await call("options")};renderSources();await scan();}catch(e){renderSources();status(e.message);}})();
