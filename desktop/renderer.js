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
const titles={search:"파일 검색",review:"파일 정리",matrix:"유사도 행렬",flow:"분석 과정"};
let data=null,groups=new Map(),files=new Map(),view="search",scope=null,query="",groupQuery="";
let selected=new Set(),busy=false,scanBusy=false,renderId=0,toastTimer,dialogAction=null;
let mxRow=0,mxCol=0,pair=null,options={recursive:false,deep:true,covers:true,roots:[],folderMode:"reuse",minConfidence:0.7};
let sourceDraft=null,searchVersion=0,liveVersion=0,searchTimer,retryOnReturn=false;
let activeId=null,detailInfo=null,detailVersion=0,detailOpen=false,detailTab="evidence",relatedRows=null,relatedBusy=false,relatedError="";
const compactDetails=window.matchMedia("(max-width:1199px)");
const expanded = new Set();
let reviewIcons={},folderEditor=null,pickedKey="",renameTimer,doubleClickMs=500;
let shownSearchRows=[],searchBackend="",searchTotal=0;
let folderBranches = new Map(), originalLayout = new Map(), layout = new Map(), layoutKey = "", layoutReady = false;
function bytes(n){if(n<1024)return n+" B";if(n<1048576)return Math.round(n/1024)+" KB";return (n/1048576).toFixed(1)+" MB";}
function fileBadge(ext){
  const kind=ext==="pdf"?"pdf":/^(pptx?|zip|7z|rar)$/.test(ext)?"slides":/^(xlsx?|csv|tsv)$/.test(ext)?"sheet":/^(docx?|hwp[x]?|md|txt)$/.test(ext)?"word":"";
  return '<span class="doctype '+kind+'" aria-hidden="true">'+esc((ext||"FILE").toUpperCase().slice(0,4))+'</span>';
}

function toast(text){clearTimeout(toastTimer);$("#toast").textContent=text;$("#toast").hidden=false;toastTimer=setTimeout(()=>$("#toast").hidden=true,3200);}
function status(text,canCancel=false){const el=$("#status");el.hidden=!text;el.innerHTML=esc(text)+(canCancel?'<button data-action="cancel">분석 취소</button>':"");}
function setBusy(value){
  busy=value;document.querySelector('[data-action="scan"]').disabled=value;updateReviewBar();
  document.querySelectorAll("[data-folder-check],[data-check],#all-check").forEach(box=>box.disabled=value);
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
  if(!data)return sourcesDialog();
  view="review";scope=id==="all"?null:id;query="";
  if(scope)expanded.add(folderBranches.get(scope)||scope);
  render();
  if(scope)document.querySelector('[data-tree="'+CSS.escape(folderBranches.get(scope)||scope)+'"]')?.scrollIntoView({block:"nearest"});
}
function visibleFiles(){
  const q=query.trim().toLocaleLowerCase();
  return (data?.files||[]).filter(f=>!q||f.name.toLocaleLowerCase().includes(q));
}
async function scan(newOptions=options,openReview=true){
  if(busy)return;
  scanBusy=true;setBusy(true);status("선택한 폴더 분석 중",true);
  try {
    data=await call("scan",{...options,...newOptions});options={...options,...data.options,roots:data.roots||data.options?.roots||options.roots};
    groups=new Map(data.groups.map(g=>[g.id,g]));files=new Map(data.files.map(f=>[f.id,f]));
    if(scope && scope!=="hold"&&!groups.has(scope))scope=null;
    if((openReview&&view==="search")||(options.groupBy==="extension"&&["matrix","flow"].includes(view)))view="review";
    originalLayout=new Map(data.layout.map(row=>[row.id,row]));
    folderBranches=new Map();
    const destinations=new Map();
    for(const row of data.layout){
      const gid=files.get(row.id).group,path=parentPath(row.target).toLowerCase();
      if(!destinations.has(path))destinations.set(path,gid);
      folderBranches.set(gid,destinations.get(path));
    }
    selected=new Set(data.layout.filter(row=>!row.skip).map(row=>row.id));
    reviewIcons={};
    const scanned=data;
    call("reviewIcons").then(icons=>{
      if(data!==scanned)return;
      reviewIcons=icons;
      for(const slot of document.querySelectorAll("[data-review-ext]")){
        if(icons[slot.dataset.reviewExt])slot.outerHTML=reviewIcon(slot.dataset.reviewExt);
      }
    }).catch(()=>{});
    layoutKey="";expanded.clear();scope=null;
    activeId=null;detailInfo=null;detailVersion++;detailOpen=false;pair=null;mxRow=0;mxCol=0;status("");render();
  } catch(e){status(e.message);if(!data)$("#content").innerHTML='<div class="panel empty">분석 폴더를 확인하거나 다른 폴더를 추가한 뒤 다시 분석하세요.</div>'; }
  finally{scanBusy=false;setBusy(false);renderSources();}
}
const confidenceDescriptions=[
  "공통 주제 단서가 조금만 있어도 묶습니다.", "약한 단서가 있는 후보까지 넓게 봅니다.",
  "작은 공통점이 있는 파일도 검토합니다.", "공통 단어와 보조 단서가 있는 후보를 포함합니다.",
  "파일명이나 출처가 일부 겹치면 후보에 둡니다.", "여러 단서가 같은 주제를 가리키는 파일을 묶습니다.",
  "공통 주제와 주변 파일의 관계가 맞는 묶음을 남깁니다.", "같은 프로젝트라는 근거가 뚜렷한 파일을 묶습니다.",
  "소속이 뚜렷하고 다른 묶음과 잘 구분되는 파일만 남깁니다.", "이름이나 출처가 매우 강하게 일치해야 묶습니다.",
  "추천 신뢰도가 1.0인 파일만 자동으로 묶습니다."
];
function renderSources(){
  const roots=data?.roots||[];
  $("#root-path summary").textContent=roots.length?"선택한 경로 · "+roots[0]+(roots.length>1?" 외 "+(roots.length-1)+"개":""):"";
  $("#root-path ul").innerHTML=roots.map(p=>"<li>"+esc(p)+"</li>").join("");
  if(!sourceDraft||!$("#source-roots"))return;
  $("#source-roots").innerHTML=sourceDraft.roots.map((p,i)=>'<div class="source-root"><span>'+icon("folder-open")+esc(p)+'</span><button class="btn" data-remove-root="'+i+'" aria-label="'+esc(p)+' 제외">제외</button></div>').join("")||'<p class="muted">정리할 폴더를 추가하세요.</p>';
  $("#new-folder-parent").textContent=sourceDraft.roots.length?"새 묶음의 기본 상위 폴더 · "+sourceDraft.roots[0]:"";
  $('[data-action="submitDialog"]').disabled=!sourceDraft.roots.length;
}
async function sourcesDialog(){
  const saved=await call("options");
  sourceDraft={...saved,roots:[...saved.roots]};
  const deepOptions=[["deep","애매한 파일의 본문 일부 확인"],["covers","대표 문서 표지에서 묶음 이름 찾기"]];
  showDialog("파일 정리하기","선택한 폴더 바로 아래의 파일을 검토합니다.",
    '<div class="setup-section"><h3>정리할 위치</h3><div id="source-roots"></div>'+btn("addSource","폴더 추가","plus")+'<p class="muted source-note" id="new-folder-parent"></p></div>'+
    '<div class="setup-section"><label for="group-by">묶는 기준</label><select id="group-by"><option value="related">관련 작업별</option><option value="extension">확장자별</option></select><p class="muted" id="group-help"></p></div>'+
    '<fieldset class="destination-options"><legend>정리할 폴더</legend>'+[
      ["reuse","기존 폴더 활용","이름이나 안에 있는 파일이 잘 맞으면 그 폴더에 추가합니다."],
      ["new","새 폴더로만 정리","이번에 선택한 파일끼리 새 폴더를 만듭니다."]
    ].map(([v,t,d])=>'<label><input type="radio" name="folder-mode" value="'+v+'" '+(sourceDraft.folderMode===v?"checked":"")+'>'+t+'<small>'+d+'</small></label>').join("")+'</fieldset>'+
    '<div class="setup-section"><label for="min-confidence">최소 신뢰도 <output id="min-value" for="min-confidence"></output></label><input type="range" id="min-confidence" min="0" max="1" step="0.1" value="'+sourceDraft.minConfidence+'" aria-describedby="min-description"><p id="min-description" class="muted"></p></div>'+
    '<details class="setup-section"><summary>추가 분석 옵션</summary>'+deepOptions.map(([k,t])=>'<label class="setting">'+t+'<input type="checkbox" id="opt-'+k+'" '+(sourceDraft[k]?"checked":"")+'></label>').join("")+btn("bridge","브라우저 출처 연결","plugs-connected")+'</details>',
    btn("close","취소")+btn("submitDialog","분석 시작","arrow-right",true),()=>{
      const draft={...sourceDraft,groupBy:$("#group-by").value,folderMode:$('[name="folder-mode"]:checked').value,
        minConfidence:Number($("#min-confidence").value),deep:$("#opt-deep").checked,covers:$("#opt-covers").checked};
      close();return scan(draft);
    });
  const slider=$("#min-confidence");
  slider.oninput=()=>{const v=Number(slider.value);$("#min-value").textContent=v.toFixed(1);
    $("#min-description").textContent=confidenceDescriptions[Math.round(v*10)];};
  const grouping=$("#group-by");
  grouping.value=sourceDraft.groupBy||"related";
  grouping.onchange=()=>{
    const byExtension=grouping.value==="extension";
    slider.closest(".setup-section").hidden=byExtension;
    $("#opt-deep").closest("details").hidden=byExtension;
    $("#group-help").textContent=byExtension?"PDF, EXE처럼 같은 확장자의 파일을 한 폴더에 모읍니다.":"파일명과 다운로드 단서로 같은 작업에 쓰인 파일을 찾습니다.";
  };
  grouping.onchange();slider.oninput();renderSources();
}
async function addSource(){
  const chosen=await call("chooseFolder");
  if(chosen&&sourceDraft&&!sourceDraft.roots.some(p=>p.toLowerCase()===chosen.toLowerCase())){
    sourceDraft.roots.push(chosen);renderSources();
  }
}
function parentPath(path){const i=Math.max(path.lastIndexOf("\\"),path.lastIndexOf("/"));return i===2&&path[1]===":"?path.slice(0,3):i===0?"/":path.slice(0,i);}
async function showFileIcons(version){
  const icons=await call("searchIcons");
  if(version!==liveVersion)return;
  for(const slot of document.querySelectorAll("[data-file-icon]")){
    const src=icons[slot.dataset.fileIcon];
    if(!src)continue;
    const img=new Image();img.alt="";img.className="shell-icon";img.src=src;
    slot.replaceWith(img);
  }
}
function paintSearchRows(){
  const shown=shownSearchRows.length.toLocaleString("ko-KR");
  const count=searchTotal!==shownSearchRows.length?"색인 "+searchTotal.toLocaleString("ko-KR")+"건 · "+shown+"개 표시":"전체 "+shown+"개";
  $("#search-meta").textContent=searchBackend+" · "+count;
  $("#search-empty").hidden=shownSearchRows.length>0;
  $("#search-empty").textContent="일치하는 파일이나 폴더가 없습니다.";
  $("#search-rows").innerHTML=shownSearchRows.map(r=>{
    const glyph=r.isFolder?'<i class="result-folder" aria-hidden="true"></i>':
      '<i class="ph ph-file shell-icon" data-file-icon="'+esc(r.id)+'" aria-hidden="true"></i>';
    return '<tr><td><button class="search-name" data-entry="search" data-id="'+esc(r.id)+'" data-open-result="'+esc(r.id)+'" aria-label="'+esc(r.name)+(r.isFolder?' 폴더 열기':' 파일 열기')+'">'+
      glyph+'<span class="entry-text" title="'+esc(r.name)+'">'+esc(r.name)+'</span></button></td><td><div class="search-path"><span title="'+esc(r.path)+'">'+esc(r.path)+'</span>'+
      '<button class="icon-btn" data-copy-path="'+esc(r.path)+'" title="경로 복사" aria-label="'+esc(r.name)+' 경로 복사">'+icon("copy")+'</button></div></td></tr>';
  }).join("");
  markSelection();
}
function liveSearch(){
  shownSearchRows=[];searchBackend="";clearTimeout(renameTimer);
  clearTimeout(searchTimer);
  retryOnReturn=false;
  const version=++liveVersion,query=$("#external-query").value.trim();
  window.desktop.cancelSearch();
  const empty=$("#search-empty"),meta=$("#search-meta");
  $("#search-rows").replaceChildren();empty.hidden=false;
  meta.textContent="파일·폴더 이름 검색";
  empty.textContent=query?"검색 중…":"이름을 입력하면 파일과 폴더가 여기에 표시됩니다.";
  if(!query)return;
  let retryDelay=250;
  async function run(){
    if(version!==liveVersion)return;
    if(view!=="search"){retryOnReturn=true;return;}
    try{
      const result=await call("search",{query});
      if(version!==liveVersion)return;
      searchBackend=result.backend;
      searchTotal=result.total;
      shownSearchRows=result.results;
      paintSearchRows();
      if(result.results.some(r=>!r.isFolder))showFileIcons(version).catch(()=>{});
    }catch(e){
      if(version!==liveVersion)return;
      empty.textContent=e.message;
      if(e.code==="everythingUnavailable"){
        meta.textContent="검색 준비 중 · 자동 재시도";
        searchTimer=setTimeout(run,retryDelay);
        retryDelay=Math.min(retryDelay*2,2000);
      }
    }
  }
  searchTimer=setTimeout(run,60);
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
  document.body.classList.toggle("extension-review",options.groupBy==="extension");
  const searching=view==="search";
  $("#search-home").hidden=!searching;$("#content").hidden=searching;
  $(".review-bar").hidden=view!=="review";$("#root-path").hidden=searching||!data;
  $('[data-action="scan"]').hidden=searching||!data;
  $("#setup-label").textContent=searching?"파일 정리하기":"정리할 폴더 변경";
  document.querySelectorAll('.rail-section,.group-search,#group-nav,.advanced').forEach(el=>el.hidden=searching);
  if(searching){$("#external-query").focus();if(retryOnReturn)liveSearch();return;}
  if(!data)return;
  if(view==="review")review();
  else if(view==="matrix")matrix(generation).catch(errorDialog);
  else flow();
}
function editableIds(){
  const ids=visibleFiles().filter(f=>selected.has(f.id)).map(f=>f.id);
  return ids.length?ids:activeId!==null?[activeId]:[];
}
function moveCandidates(){
  return visibleFiles().filter(f=>f.group&&selected.has(f.id));
}
function updateReviewBar(){
  const candidates=moveCandidates();
  const ready=layoutReady;
  const current=layout;
  const eligible=candidates.filter(f=>current.has(f.id)&&!current.get(f.id).skip);
  $("#organize").disabled=busy||!ready||!candidates.length;
  $("#move-selected").disabled=busy||!ready||!eligible.length;
  const folders=new Set(candidates.map(f=>folderBranches.get(f.group)));
  $("#review-count").textContent="폴더 "+folders.size+"개 · 파일 "+candidates.length+"개 선택";
  const blocked=candidates.length-eligible.length;
  $("#review-hint").textContent=!ready?"이동 경로 확인 중…":blocked?eligible.length+"개 이동 가능 · "+blocked+"개 보류":
    eligible.length?"선택한 파일을 이동할 수 있습니다.":"이동할 폴더나 파일을 선택하세요.";
}
function review(){
  $("#content").innerHTML='<div class="review-workspace"><section class="file-pane" aria-label="정리 트리"><div class="file-pane-head"><label class="search">'+icon("magnifying-glass")+'<input id="search" type="search" placeholder="파일명 필터" aria-label="현재 목록에서 파일명 필터"><kbd>Ctrl K</kbd></label></div>'+
    '<div class="selection-bar"><label><input id="all-check" type="checkbox"> 표시 파일 전체 선택</label><div class="selection-actions"><button class="btn" data-file-edit="assign">다른 묶음</button><button class="btn" data-file-edit="unclassify">미분류로</button><button class="btn" data-file-edit="create">새 묶음</button>'+ib("groupMenu","dots-three","선택 파일 추가 편집")+'</div></div>'+
    '<div class="folder-tree" id="folder-tree"></div></section><button id="detail-scrim" data-action="closeDetail" aria-label="파일 목록으로 돌아가기" hidden></button><aside id="file-inspector" class="file-inspector" aria-label="파일 근거" tabindex="-1"><div class="inspector-heading"><h2>파일 근거</h2>'+btn("closeDetail","닫기","x")+'</div><div id="inspector-body" class="inspector-body"></div></aside></div>';
  $("#search").value=query;
  $("#search").oninput=e=>{query=e.target.value;rows();};
  rows();syncInspector();
  if(detailOpen&&activeId!==null)detail(activeId).catch(errorDialog);
}
function reviewIcon(ext){
  const src=Object.hasOwn(reviewIcons,ext)&&reviewIcons[ext];
  if(src)return '<img class="shell-icon" alt="" src="'+esc(src)+'">';
  return '<i class="ph ph-file shell-icon" data-review-ext="'+esc(ext)+'" aria-hidden="true"></i>';
}
function fileBranch(f){
  const move=layout.get(f.id)||originalLayout.get(f.id);
  const reason=!move?f.note:!selected.has(f.id)?"선택 제외":move.skip;
  const destination=move?move.target:"원래 위치 유지";
  return '<div class="branch-file"><input type="checkbox" data-check="'+f.id+'" aria-label="'+esc(f.name)+' 선택" '+(selected.has(f.id)?"checked":"")+'>'+
    '<button class="search-name" data-entry="file" data-id="'+f.id+'" aria-label="'+esc(f.name)+' 파일 열기">'+reviewIcon(f.ext)+'<span class="entry-text" title="'+esc(f.name)+'">'+esc(f.name)+'</span></button>'+
    '<span class="review-path" title="'+esc(f.path)+'">'+esc(parentPath(f.path))+'</span>'+
    '<span class="review-path'+(reason?' hold-reason':'')+'" title="'+esc([destination,reason].filter(Boolean).join("\n"))+'">'+
    esc(reason||parentPath(destination))+'</span><button class="entry-info" data-file="'+f.id+'" title="경로와 추천 근거" aria-label="'+esc(f.name)+' 정보">'+icon("info")+'</button></div>';
}
function paintTree(){
  if(!$("#folder-tree")||folderEditor)return;
  const focusedFolder=document.activeElement?.matches(".folder-tree summary")?document.activeElement.parentElement.dataset.tree:null;
  const focused=document.activeElement?.dataset;
  const visible=visibleFiles(), branches=new Map();
  for(const f of visible){
    const id=folderBranches.get(f.group)||"hold";
    if(!branches.has(id))branches.set(id,[]);
    branches.get(id).push(f);
  }
  const tree=$("#folder-tree");
  const position=tree.scrollTop;
  tree.replaceChildren();
  for(const id of new Set([...groups.keys()].map(gid=>folderBranches.get(gid)).concat("hold"))){
    const members=branches.get(id);
    if(!members)continue;
    const g=groups.get(id), node=document.createElement("details");
    node.dataset.tree=id;node.open=expanded.has(id);
    const destination=originalLayout.get(members[0].id);
    const count=members.filter(f=>layout.has(f.id)&&selected.has(f.id)&&!layout.get(f.id).skip).length;
    const folderTitle=destination?parentPath(destination.target).split(/[\\\\/]/).pop():"미분류";
    const kind=!g?"원래 위치 유지":destination?.mode==="existing"?"기존 폴더":"새 폴더";
    const kindOfEntry=destination?.mode==="existing"?"folder":"proposal";
    const nameControl=g?'<button class="entry-title" data-entry="'+kindOfEntry+'" data-id="'+esc(id)+'"><strong class="entry-text" title="'+esc(folderTitle)+'">'+esc(folderTitle)+'</strong></button>':'<strong>미분류</strong>';
    const checkbox=g?'<input type="checkbox" data-folder-check="'+esc(id)+'" aria-label="'+esc(folderTitle)+' 폴더 선택">':"";
    node.innerHTML='<summary><span class="disclosure-hit" aria-hidden="true"></span>'+checkbox+(g?'<i class="result-folder" aria-hidden="true"></i>':icon("tray"))+
      nameControl+'<small>'+kind+'</small><b>'+(g?(layoutReady?"이동 "+count+" / "+members.length:"확인 중"):members.length+"개")+'</b></summary><div class="tree-children"></div>';
    if(g){
      const box=node.querySelector("[data-folder-check]");
      const selectedCount=members.filter(f=>selected.has(f.id)).length;
      box.checked=selectedCount===members.length;
      box.indeterminate=selectedCount>0&&selectedCount<members.length;
      box.disabled=busy;
      box.onchange=()=>{
        for(const f of members){if(box.checked)selected.add(f.id);else selected.delete(f.id);}
        rows();
      };
    }
    const paint=()=>{
      const body=node.lastElementChild;
      if(!node.open||body.childElementCount)return;
      const notes=g?[...new Set(members.map(f=>groups.get(f.group)))].map(group=>
        '<div class="branch-note" title="'+esc(group.note)+'">'+esc(group.reason||group.note)+'</div>').join(""):"";
      body.innerHTML=notes+'<div class="branch-head"><span></span><span>이름</span><span>원래 폴더</span><span>이동할 폴더 · 상태</span></div>'+members.map(fileBranch).join("");
    };
    node.ontoggle=()=>{if(!node.isConnected)return;if(node.open)expanded.add(id);else expanded.delete(id);paint();markSelection();};
    paint();tree.append(node);
  }
  if(!visible.length)tree.textContent="표시할 파일이 없습니다.";
  tree.scrollTop=position;
  markSelection();
  const checked=visible.filter(f=>selected.has(f.id)).length;
  $("#all-check").checked=visible.length>0&&checked===visible.length;
  $("#all-check").indeterminate=checked>0&&checked<visible.length;
  document.querySelectorAll('[data-file-edit],[data-action="groupMenu"]').forEach(b=>b.disabled=busy||!editableIds().length);
  if(focused?.check!==undefined)$('[data-check="'+focused.check+'"]')?.focus({preventScroll:true});
  if(focused?.folderCheck)$('[data-folder-check="'+CSS.escape(focused.folderCheck)+'"]')?.focus({preventScroll:true});
  if(focusedFolder)$('[data-tree="'+CSS.escape(focusedFolder)+'"] summary')?.focus({preventScroll:true});
  updateReviewBar();
}
function entryKey(button){
  const {entry,id}=button.dataset;
  return [entry,entry==="search"?"":data?.generation,id].join("/");
}
function markSelection(){
  document.querySelectorAll("[data-entry]").forEach(el=>{
    const chosen=entryKey(el)===pickedKey;
    el.classList.toggle("entry-picked",chosen);
    el.setAttribute("aria-pressed",String(chosen));
  });
}
function entryArgs(button){
  return {entry:button.dataset.entry,id:button.dataset.entry==="file"?Number(button.dataset.id):button.dataset.id};
}
async function openEntry(button){
  if(button.dataset.entry==="proposal"){
    const folder=button.closest("details");
    folder.open=!folder.open;return;
  }
  if(button.dataset.entry==="search")return call("openSearchResult",{id:button.dataset.id});
  return call("openReviewEntry",entryArgs(button));
}
function renameSearchPaths(result){
  if(!searchBackend)return;
  const old=result.old.toLowerCase(), prefix=old+"\\";
  const query=$("#external-query").value.trim().toLowerCase();
  const previousCount=shownSearchRows.length;
  shownSearchRows=shownSearchRows.filter(row=>row.path.toLowerCase()!==old||result.name.toLowerCase().includes(query));
  searchTotal-=previousCount-shownSearchRows.length;
  for(const row of shownSearchRows){
    const current=row.path.toLowerCase();
    if(current===old)Object.assign(row,{name:result.name,path:result.path});
    else if(current.startsWith(prefix))row.path=result.path+row.path.slice(result.old.length);
  }
  if(view==="search"){
    paintSearchRows();
    showFileIcons(liveVersion).catch(()=>{});
  }else retryOnReturn=true;
}
async function applyRename(button,title,prepared){
  const {entry,id}=entryArgs(button);
  if(entry==="proposal"){
    const result=await call("edit",{kind:"folderTitle",group:id,title});
    Object.assign(groups.get(id),{title:result.title,note:result.note,reason:result.reason});
    data.layout=result.layout;
  }else{
    const result=await call("renameEntry",{token:prepared.token,title});
    renameSearchPaths(result);
    if(result.refresh&&data){
      const translate=p=>p===result.old?result.path:p.startsWith(result.old+"\\")?result.path+p.slice(result.old.length):p;
      const checked=new Set(data.files.filter(f=>selected.has(f.id)).map(f=>translate(f.path)));
      const openPaths=new Set(data.files.filter(f=>expanded.has(folderBranches.get(f.group)||"hold")).map(f=>translate(f.path)));
      const before=data;
      await scan({...options,roots:result.roots},false);
      if(data===before){
        data=null;groups.clear();files.clear();view="search";render();
        return;
      }
      selected=new Set(data.files.filter(f=>checked.has(f.path)).map(f=>f.id));
      for(const f of data.files){
        if(openPaths.has(f.path))expanded.add(folderBranches.get(f.group)||"hold");
        if(entry==="file"&&f.path===result.path){
          button.dataset.id=String(f.id);
          pickedKey=entryKey(button);
        }
      }
    }
    if(result.layout&&data){
      for(const g of result.groups)Object.assign(groups.get(g.id),g);
      data.layout=result.layout;
    }
  }
  if(data)originalLayout=new Map(data.layout.map(row=>[row.id,row]));
  layoutKey="";layoutReady=false;
}
async function editEntry(button){
  if(busy||folderEditor||!button.isConnected)return;
  clearTimeout(renameTimer);
  const original=button.querySelector(".entry-text").textContent;
  const input=document.createElement("input"),args=entryArgs(button);
  input.className="folder-title-input";input.value=original;input.maxLength=args.entry==="proposal"?100:255;
  input.setAttribute("aria-label","새 이름");
  let saving=false;
  folderEditor=input;
  const prepared=args.entry==="proposal"?Promise.resolve({name:original,isFolder:true}):call("beginRename",args);
  const finish=focus=>{
    if(folderEditor!==input)return;
    folderEditor=null;
    if(input.isConnected)input.replaceWith(button);
    if(data&&view==="review"){nav();rows();}
    if(focus)document.querySelector('[data-entry="'+args.entry+'"][data-id="'+CSS.escape(button.dataset.id)+'"]')?.focus({preventScroll:true});
  };
  button.replaceWith(input);input.focus();input.select();
  prepared.then(result=>{
    if(folderEditor!==input)return;
    const dot=original.lastIndexOf(".");
    if(!result.isFolder&&dot>0&&input.value===original)input.setSelectionRange(0,dot);
  }).catch(error=>{if(folderEditor===input){finish(true);errorDialog(error);}});
  input.addEventListener("click",e=>e.stopPropagation());
  input.addEventListener("blur",()=>{if(!saving)finish(false);});
  input.addEventListener("input",()=>input.setCustomValidity(""));
  input.addEventListener("keydown",async e=>{
    if(e.isComposing||e.keyCode===229||!["Enter","Escape"].includes(e.key))return;
    e.preventDefault();e.stopPropagation();
    if(saving)return;
    if(e.key==="Escape"||input.value===original){finish(true);return;}
    if(!input.value.trim()){input.setCustomValidity("새 이름을 입력하세요.");input.reportValidity();return;}
    saving=true;input.readOnly=true;
    try{
      await applyRename(button,input.value,await prepared);
      finish(true);
      toast(args.entry==="proposal"?"예상 이동 경로에 새 이름을 적용했습니다.":"디스크에 새 이름을 적용했습니다.");
    }catch(error){
      saving=false;input.readOnly=false;
      if(!input.isConnected){finish(false);errorDialog(error);return;}
      input.focus();input.setCustomValidity(error.message);input.reportValidity();
    }
  });
}
function rows(){
  if(!data||!$("#folder-tree"))return;
  const ids=moveCandidates().map(f=>f.id),key=data.generation+"/"+ids.join(",");
  if(key!==layoutKey){
    layoutKey=key;layoutReady=false;layout=new Map();
    call("review",{files:ids}).then(result=>{
      if(key!==layoutKey)return;
      layout=new Map(result.map(row=>[row.id,row]));layoutReady=true;paintTree();
    }).catch(error=>{if(key===layoutKey){layoutKey="";errorDialog(error);}});
  }
  paintTree();
}
function infoRows(items){return '<dl class="info-list">'+items.filter(([,v])=>v!==undefined && v!==null && v!=="").map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>').join("")+'</dl>';}
function syncInspector(){
  const el=$("#file-inspector");if(!el)return;
  el.closest(".review-workspace").classList.toggle("inspecting",detailOpen);el.classList.toggle("open",detailOpen);$("#detail-scrim").hidden=!compactDetails.matches||!detailOpen;
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
    (detailTab==="related"?relatedContent(f):'<section class="detail-section"><h3>추천 설명</h3><p class="info-note">'+esc(info.note||"추천 설명이 없습니다.")+(info.evidence?'<br>'+esc(info.evidence):"")+'</p>'+infoRows([["현재 묶음",groups.get(f.group)?.title||"미분류"],["판정",f.state],["신뢰도",f.confidence?.toFixed(2)]])+'</section><section class="detail-section"><h3>실제 파일 정보</h3>'+infoRows([["원래 경로",info.path||f.path],["예상 경로",originalLayout.get(f.id)?.target||"원래 위치 유지"],["수정 시각",info.modified],["생성 시각",info.created]])+'</section><details class="detail-more"><summary>추가 분석 정보</summary>'+infoRows([["정규화 이름",info.normalized],["핵심 단어",info.tokens?.join(" · ")],["역할",info.roles?.join(" · ")],["순번",info.sequence],["버전",info.versions?.join(" · ")],["강좌명",info.course],["다운로드 페이지",info.page],["출처 페이지",info.source_page],["다운로드 사이트",f.host],["본문 발췌",info.excerpt]])+'</details>');
}
function relatedContent(f){
  const center='<div class="relation-center">'+icon("file-text")+'<div><small>선택한 파일</small><strong>'+esc(f.name)+'</strong></div></div>';
  if(relatedBusy)return center+'<p class="empty" role="status">연결된 파일을 확인하는 중…</p>';
  if(relatedError)return center+'<p class="empty" role="alert">'+esc(relatedError)+'</p>'+btn("retryRelated","다시 시도","arrows-clockwise");
  const rows=relatedRows||[];
  return '<p class="related-caption">관련 파일 최대 5개 · 파일명을 누르면 상세 근거가 열립니다.</p>'+center+
    (rows.length?'<ol class="related-list">'+rows.map(r=>{
      const score=Number(r.score),band=score>=60?"high":score>=35?"medium":"low";
      const label=score>=60?"높음":score>=35?"보통":"낮음";
      return '<li><button class="related-file" data-related-file="'+esc(r.id)+'" aria-label="'+esc(r.name)+' 상세 보기, 관련도 '+score+'점, '+label+'"><span class="relation-score '+band+'" title="관련도 '+score+'/100 · '+label+'" aria-hidden="true">'+score+'</span><strong>'+esc(r.name)+'</strong></button></li>';
    }).join("")+'</ol><p class="relation-legend">관련도 / 100 · 초록 60 이상 · 노랑 35–59 · 빨강 34 이하</p>':'<p class="empty">현재 연결된 파일이 없습니다. 다른 파일을 선택해 살펴보세요.</p>');
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
  showDialog("정리 이력","","<div id='history-list' aria-live='polite'>기록을 불러오는 중…</div>",btn("close","닫기"),null,true);
  const batches=await call("history");
  if(version!==searchVersion||!$("#history-list"))return;
  $("#history-list").innerHTML=batches.map(batch=>{
    const operation=batch.operation==="rename"?"이름 변경":"이동";
    const summary=batch.readable?operation+" "+batch.moved+"개 · 복원 "+batch.undone+"개 · 복원 대기 "+batch.pending+"개":"이력 파일을 읽을 수 없습니다.";
    return '<article class="history-batch"><div class="history-head"><strong>'+esc(batch.time)+'</strong>'+
      '<button class="btn" data-history="'+esc(batch.id)+'" '+(batch.readable?"":"disabled")+'>파일과 경로 보기</button></div><p>'+summary+'</p></article>';
  }).join("")||"정리 기록이 없습니다.";
}
async function historyDetail(batch){
  const version=++searchVersion, records=await call("historyDetail",{batch});
  if(version!==searchVersion)return;
  const states={moved:"이동됨",undone:"복원됨",skipped:"건너뜀",failed:"실패",planned:"이동 미확인"};
  const body=records.map(r=>'<div class="move-row"><b>'+esc(r.operation==="rename"&&r.status==="moved"?"이름 변경됨":states[r.status]||r.status)+'</b>'+
    infoRows([["원래 경로",r.source],["대상 경로",r.target],["기록 당시 원본",r.recordedSource],["기록 당시 목적지",r.recordedTarget],["사유",r.reason]])+'</div>').join("");
  showDialog("정리 기록 상세","",body,btn("history","이력 목록")+
    (records.some(r=>r.pending)?btn("submitDialog","이 작업 복원 미리보기","arrow-counter-clockwise",true):""),()=>preview("undo",{batch}),true);
}
function groupMenu(){
  const items=[],ids=editableIds();
  const g=groups.get(files.get(ids[0])?.group)||groups.get(scope);
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
  if(kind==="rename"){
    const name=$('[data-tree="'+CSS.escape(folderBranches.get(gid)||gid)+'"] .entry-title');
    close();
    if(!name){toast("폴더를 목록에서 다시 선택하세요.");return;}
    name.scrollIntoView({block:"nearest"});pickedKey=entryKey(name);markSelection();
    return editEntry(name);
  }
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
  const title=({create:"새 그룹 만들기",split:"그룹 분리",course:"그룹 이름 확인"})[kind];
  showDialog(title,cover?.[1]||"",'<label>그룹 이름<input id="value" class="field" maxlength="140" value="'+esc(cover?.[0]||"")+'"></label>',
    btn("close","취소")+btn("submitDialog","저장","check",true),()=>{const val=$("#value").value.trim();if(!val){$("#value").focus();return;}return applyEdit({...args,title:val});});
  $("#value").focus();$("#value").select();
}
async function executePlan(token){
  close();setBusy(true);status("파일 처리 중");
  let report;
  try{report=await call("execute",{token});}finally{setBusy(false);status("");}
  if(data)await scan(options,false);
  if($("#external-query").value.trim()){
    if(view==="search")liveSearch();else retryOnReturn=true;
  }
  showDialog("파일 처리 결과","",'<div class="result-lines">'+esc(report.join("\n"))+'</div>',btn("close","닫기","check",true),null,true);
}
async function preview(kind,args={}){
  if(busy)return;
  const targetFiles=kind==="organize"?moveCandidates().map(f=>f.id):kind==="manual"?editableIds():[];
  let result;
  setBusy(true);status("파일과 경로 확인 중");
  try{result=await call("preview",{kind,files:targetFiles,...args});}
  finally{setBusy(false);status("");}
  if(!result)return;
  const rows=result.rows,move=rows.filter(r=>!r.skip),byFolder=new Map();
  rows.forEach(r=>{const path=parentPath(r.target);if(!byFolder.has(path))byFolder.set(path,[]);byFolder.get(path).push(r);});
  const title=kind==="undo"?"복원 경로 미리보기":"폴더 정리 미리보기";
  const body=[...byFolder].map(([p,fs])=>'<section class="move-group"><strong>'+icon("folder-notch")+esc(p)+'</strong>'+fs.map(f=>'<div class="move-row"><b>'+esc(f.name)+'</b>'+infoRows([["현재 경로",f.source],["이동할 경로",f.target]])+(f.skip?'<small>건너뜀 · '+esc(f.skip)+'</small>':"")+'</div>').join("")+'</section>').join("");
  showDialog(title,move.length+"개 파일 "+(kind==="undo"?"복원 예정":"이동 예정")+(rows.length>move.length?"   ·   "+(rows.length-move.length)+"개 건너뜀":""),
    body||'<p class="empty">처리할 파일이 없습니다.</p>',btn("close","취소")+
    (kind==="organize"&&move.length?btn("changeMoveParent","새 묶음의 상위 폴더 변경","folder-open"):"")+(move.length?btn("submitDialog",move.length+"개 파일 "+(kind==="undo"?"복원":"이동"),kind==="undo"?"arrow-counter-clockwise":"folder-simple-plus",true):""),
    ()=>executePlan(result.token),true);
  const change=$('[data-action="changeMoveParent"]');
  if(change)change.onclick=async()=>{
    try{
      const destination=await call("chooseFolder");
      if(destination)await preview(kind,{...args,destination});
    }catch(e){errorDialog(e);}
  };
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
    ["intersect","그룹 생성","완전 연결 계층 클러스터링으로 추천 그룹 "+data.groups.length+"개를 만들었어요. 최소 추천 신뢰도는 "+data.options.minConfidence.toFixed(1)+"이에요."],
    ["file-text","선택적 추가 분석","중간 신뢰도 "+data.medium+"개 중 "+data.attempted+"개에 본문 발췌를 시도했고 "+data.rescued+"개를 추가 추천했어요."],
    ["bookmark-simple","그룹 이름 확인","저장된 이름과 확인된 강좌명을 확인하고, 과목명 확인용 표지 "+data.covers+"개를 살펴봤어요."]];
  $("#content").innerHTML='<div class="panel"><div class="section-head"><h2>이번 분석 결과</h2><span class="muted">'+data.time+'   ·   '+(data.elapsed/1000).toFixed(2)+'초</span></div>'+cards.map(([i,t,s])=>'<div class="flow-row">'+icon(i)+'<div><h3>'+t+'</h3><p class="muted">'+s+'</p></div></div>').join("")+'</div>';
}
async function action(key){
  if(key==="close"){close();return;}
  if(key==="closeDetail"){closeDetail();return;}
  if(key==="cancel"){window.desktop.cancel();return;}
  if(key==="openDownloads"){await call("openDownloads");return;}
  if(busy)return;
  switch(key){
    case "scan":return scan();
    case "settings":return sourcesDialog();
    case "all":return setScope("all");
    case "moveSelected":{
      if(busy||$("#move-selected").disabled)return;
      setBusy(true);status("선택한 파일과 이동 경로 확인 중");
      try{
        const result=await call("preview",{kind:"organize",files:moveCandidates().map(f=>f.id),destinationMode:options.folderMode});
        if(!result?.rows.some(row=>!row.skip)){
          toast("이동할 파일이 없습니다. 미리보기에서 경로를 확인하세요.");return;
        }
        await executePlan(result.token);
      }finally{setBusy(false);status("");}
      return;
    }
    case "organize":return preview("organize",{destinationMode:options.folderMode});
    case "addSource":return addSource();
    case "sources":return sourcesDialog();
    case "history":return historyDialog();
    case "retryRelated":return loadRelated();
    case "undo":return preview("undo");
    case "groupMenu":return groupMenu();
    case "groupRename":return editForm("rename",scope);
    case "retryDetail":return detail(activeId);
    case "confirmCourse":return editForm("course",scope);
    case "submitDialog":{const fn=dialogAction;if(fn){const b=$('[data-action="submitDialog"]');if(b)b.disabled=true;try{await fn();}finally{if(b?.isConnected)b.disabled=false;}}return;}


    case "bridge":{const p=await call("bridge");showDialog("브라우저 출처 연결","확장 폴더 경로를 복사했어요.",
      '<p class="muted">Edge 또는 Chrome의 확장 관리에서 개발자 모드를 켜고 ‘압축 풀린 파일 로드’를 선택하세요. 아래 폴더를 지정한 뒤 다운로드한 웹페이지에서 확장 아이콘을 눌러 ‘이 사이트 연결’을 선택하세요. HTTPS 사이트의 페이지 제목과 출처를 이 PC에 기록합니다.</p><p class="preview-path" style="margin-top:12px">'+esc(p)+'</p>');return;}
  }
}
document.addEventListener("click",async e=>{
  try {
    const nameButton=e.target.closest("[data-entry]");
    if(nameButton){
      e.preventDefault();
      clearTimeout(renameTimer);
      if(busy||(!e.target.closest(".entry-text")&&e.detail!==0))return;
      const key=entryKey(nameButton),already=pickedKey===key;
      pickedKey=key;markSelection();
      if(e.detail===0)return await openEntry(nameButton);
      if(e.detail===1&&already)renameTimer=setTimeout(()=>{
        if(nameButton.isConnected&&pickedKey===key)editEntry(nameButton).catch(errorDialog);
      },doubleClickMs+30);
      return;
    }
    clearTimeout(renameTimer);
    const el=e.target.closest("button,input,tr[data-file]");if(!el)return;
    const d=el.dataset;
    if(d.history)return await historyDetail(d.history);
    if(d.copyPath){await navigator.clipboard.writeText(d.copyPath);toast("경로를 복사했어요.");return;}
    if(d.action)return await action(d.action);
    if(busy)return;
    if(d.removeRoot!==undefined){sourceDraft.roots.splice(Number(d.removeRoot),1);renderSources();return;}
    if(d.view){if(d.view!=="search"&&!data)return await sourcesDialog();status("");view=d.view;scope=null;detailOpen=false;detailVersion++;render();return;}
    if(d.scope){setScope(d.scope);return;}
    if(d.fileEdit){const ids=editableIds();if(!ids.length)return;if(d.fileEdit==="unclassify")return await applyEdit({kind:"assign",files:ids,target:""});return await editForm(d.fileEdit,scope);}
    if(d.detailTab){detailTab=d.detailTab;renderInspector();if(detailTab==="related"&&relatedRows===null)return await loadRelated();return;}
    if(d.relatedFile!==undefined){
      const id=Number(d.relatedFile),f=files.get(id);if(!f)return;
      query="";$("#search").value="";expanded.add(folderBranches.get(f.group)||"hold");rows();await detail(id);
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
document.addEventListener("pointerdown",e=>{
  const button=e.target.closest("[data-entry]");
  if(button&&!e.target.closest(".entry-text"))e.preventDefault();
});
document.addEventListener("dblclick",e=>{
  const button=e.target.closest(".entry-text")?.closest("[data-entry]");
  if(!button||busy)return;
  clearTimeout(renameTimer);e.preventDefault();openEntry(button).catch(errorDialog);
});
document.addEventListener("keydown",e=>{
  if(e.key==="F2"&&!folderEditor){
    const button=e.target.closest("[data-entry]")||e.target.closest(".folder-tree summary")?.querySelector("[data-entry]");
    if(button){
      e.preventDefault();pickedKey=entryKey(button);markSelection();editEntry(button).catch(errorDialog);return;
    }
  }
  if(e.ctrlKey&&e.key.toLowerCase()==="k"&&!$("#dialog").open){e.preventDefault();if(view==="review")$("#search")?.focus();else{view="search";render();$("#external-query").focus();}}
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
$("#external-query").oninput=liveSearch;
call("doubleClickTime").then(value=>{doubleClickMs=value;}).catch(()=>{});
render();
