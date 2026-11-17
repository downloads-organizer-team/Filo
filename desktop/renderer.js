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
const folderArt='<span class="folder-art" aria-hidden="true"><span class="folder-back"></span><span class="paper"></span><span class="folder-front"></span></span>';
const titles={review:"파일 검토",matrix:"유사도 행렬",flow:"분석 과정"};
let data=null,groups=new Map(),files=new Map(),view="review",scope=null,tab="all",query="",shelfStart=0,page=0;
let selected=new Set(),busy=false,scanBusy=false,renderId=0,toastTimer,dialogAction=null;
let mxRow=0,mxCol=0,pair=null,options={recursive:false,deep:true,covers:true};
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
function setBusy(value){busy=value;$("#organize").disabled=value||!data?.groups.length||scope==="hold";document.querySelector('[data-action="scan"]').disabled=value;}
async function call(action,args={}){
  const r=await window.desktop.call(action,{generation:data?.generation,...args});
  if(!r.ok){const e=new Error(r.error||"작업을 완료하지 못했습니다.");e.code=r.code;throw e;}return r.value;
}
function showDialog(title,description,body,footer="",action=null,wide=false){
  const d=$("#dialog");dialogAction=action;d.classList.toggle("wide",wide);
  $("#dialog-frame").innerHTML='<div class="dhead"><div><h2>'+esc(title)+'</h2>'+(description?'<p class="muted">'+esc(description)+'</p>':"")+'</div>'+ib("close","x","닫기")+'</div><div class="dbody">'+body+'</div><div class="dfoot">'+(footer||btn("close","닫기"))+'</div>';
  d.setAttribute("aria-label",title);if(!d.open)d.showModal();
}
function close(){if($("#dialog").open)$("#dialog").close();dialogAction=null;}
function errorDialog(e){showDialog("작업을 확인해 주세요","",'<p class="muted">'+esc(e.message||String(e))+'</p>');}
function setScope(id){
  view="review";scope=id==="all"?null:id;tab="all";query="";page=0;selected.clear();render();
}
function scopeFiles(){return !data?[]:scope==="hold"?data.files.filter(f=>!f.group):scope?data.files.filter(f=>f.group===scope):data.files;}
function visibleFiles(){
  const q=query.trim().toLocaleLowerCase();
  return scopeFiles().filter(f=>(tab==="all"||(tab==="grouped"?Boolean(f.group):!f.group))&&(!q||f.name.toLocaleLowerCase().includes(q)));
}
async function scan(newOptions=options){
  if(busy)return;
  scanBusy=true;setBusy(true);status("다운로드 폴더 분석 중",true);
  try {
    data=await call("scan",newOptions);options=data.options;
    groups=new Map(data.groups.map(g=>[g.id,g]));files=new Map(data.files.map(f=>[f.id,f]));
    if(scope && scope!=="hold"&&!groups.has(scope))scope=null;
    selected.clear();pair=null;mxRow=0;mxCol=0;page=0;status("");render();
  } catch(e){status(e.message);if(!data)$("#content").innerHTML='<div class="panel empty">다운로드 폴더를 확인한 뒤 다시 분석하세요.</div>'; }
  finally{scanBusy=false;setBusy(false);}
}
function nav(){
  $("#rail-count").textContent=data?.groups.length??0;
  $("#group-nav").innerHTML=(data?.groups||[]).map(g=>'<button title="'+esc(g.title)+'" class="rail-group '+(scope===g.id&&view==="review"?"current":"")+'" data-scope="'+g.id+'" style="'+colors(g)+'"><span class="dot"></span><span>'+esc(g.title)+'</span><small>'+g.count+'</small></button>').join("")+
  (data?'<button class="rail-group '+(scope==="hold"?"current":"")+'" data-scope="hold"><span class="dot"></span><span>미분류</span><small>'+data.files.filter(f=>!f.group).length+'</small></button>':"");
  document.querySelectorAll("[data-view]").forEach(b=>b.classList.toggle("active",b.dataset.view===view));
}
function render(){
  const generation=++renderId;nav();$("#crumb").textContent=titles[view];
  $("#headline").textContent=view==="review"?"다운로드 정리":titles[view];
  $("#root-path span").textContent=data?.root||"다운로드 폴더 확인 중";
  $("#organize").innerHTML=icon("folder-simple-plus")+(scope&&scope!=="hold"&&view==="review"?"이 그룹 정리":"폴더로 정리");
  $("#organize").disabled=busy||!data?.groups.length||(view==="review"&&scope==="hold");
  if(!data)return;
  if(view==="review")review();
  else if(view==="matrix")matrix(generation).catch(errorDialog);
  else flow();
}
function shelfWidth(){return window.innerWidth<=1140?3:4;}
function shelf(){
  const n=data.groups.length,k=shelfWidth();shelfStart=Math.min(Math.max(0,n-k),shelfStart);
  if(!n)return "";
  const cards=data.groups.slice(shelfStart,shelfStart+k).map(g=>'<button class="group-card" style="'+colors(g)+'" data-scope="'+g.id+'" title="'+esc(g.title)+'"><span class="cover">'+folderArt+'</span><span class="card-body"><strong>'+esc(g.title)+'</strong><small>파일 '+g.count+'개'+icon("arrow-up-right")+'</small></span></button>').join("");
  return '<section><div class="section-head"><div class="hrow"><h2>추천 그룹</h2><span class="head-count">'+n+'</span></div>'+
    (n>k?'<div class="pager"><span>'+ (shelfStart+1)+'–'+Math.min(n,shelfStart+k)+' / '+n+'</span>'+ib("shelfPrev","caret-left","이전 그룹",shelfStart===0)+ib("shelfNext","caret-right","다음 그룹",shelfStart+k>=n)+'</div>':"")+'</div><div class="shelf">'+cards+'</div></section>';
}
function review(){
  const g=groups.get(scope),all=scopeFiles(),grouped=all.filter(f=>f.group).length;
  const confidence=g?.confidence!=null?"그룹 신뢰도 "+g.confidence.toFixed(2):"";
  const intro=g?'<div class="group-intro" style="'+colors(g)+'">'+folderArt+'<div><h3>'+esc(g.title)+'</h3><p>'+[g.note,confidence].filter(Boolean).map(esc).join(" · ")+'</p></div><div class="tools">'+btn("confirmCourse","파일명 변경","bookmark-simple")+btn("groupMenu","그룹 편집","pencil-simple")+'</div></div>':"";
  const tabs=!scope?'<div class="tabs">'+[["all","전체",all.length],["grouped","그룹 추천",grouped],["hold","미분류",all.length-grouped]].map(([v,l,n])=>'<button data-tab="'+v+'" class="chip-tab '+(v===tab?"active":"")+'">'+l+' <b>'+n+'</b></button>').join("")+'</div>':"";
  $("#content").innerHTML=(!scope?shelf():"")+intro+'<section class="table-panel"><div class="table-heading"><div class="hrow"><h2>'+esc(g?"그룹 파일":scope==="hold"?"미분류 파일":"파일 목록")+'</h2><span class="meta">'+all.length+'개</span></div><label class="search">'+icon("magnifying-glass")+'<input id="search" type="search" value="'+esc(query)+'" placeholder="파일명 검색" aria-label="파일명 검색"><kbd>Ctrl K</kbd></label></div>'+tabs+
  '<div id="selection-bar" class="selection-bar" hidden></div><div class="table-scroll"><table><thead><tr><th class="checkbox"><input id="all-check" type="checkbox" aria-label="검색 결과 전체 선택"></th><th class="name-col">파일명</th><th class="group-col">추천 그룹</th><th class="state-col">판정</th><th class="score-col">신뢰도</th><th class="size-col">크기</th><th class="open-col"></th></tr></thead><tbody id="file-rows"></tbody></table><div id="empty" class="empty" hidden></div></div><div class="table-foot"><span id="row-summary"></span><span id="page-tools"></span></div></section>';
  $("#search").oninput=e=>{query=e.target.value;page=0;rows();};rows();
}
function rows(){
  const arr=visibleFiles();page=Math.min(Math.max(0,Math.ceil(arr.length/PAGE_SIZE)-1),page);
  const chunk=arr.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE);
  $("#file-rows").innerHTML=chunk.map(f=>'<tr data-file="'+f.id+'" tabindex="0" aria-label="'+esc(f.name)+'"><td class="checkbox"><input type="checkbox" aria-label="'+esc(f.name)+' 선택" data-check="'+f.id+'" '+(selected.has(f.id)?"checked":"")+'></td><td><div class="filename" title="'+esc(f.name)+'">'+fileBadge(f.ext)+'<span>'+esc(f.name)+'</span></div></td><td>'+chip(f)+'</td><td class="state-text">'+esc(f.state)+'</td><td class="score-col">'+(f.confidence==null?"—":f.confidence.toFixed(2))+'</td><td class="size-col">'+bytes(f.size)+'</td><td class="open-col">'+icon("caret-right")+'</td></tr>').join("");
  $("#empty").hidden=!!arr.length;$("#empty").textContent=query?"검색 결과가 없습니다.":scope==="hold"||tab==="hold"?"미분류 파일이 없습니다.":"표시할 파일이 없습니다.";
  $("#row-summary").textContent="파일 "+arr.length+"개"+(query?" 검색됨":"");
  $("#page-tools").innerHTML=arr.length>PAGE_SIZE?ib("pagePrev","caret-left","이전 파일",page===0)+" "+(page+1)+" / "+Math.ceil(arr.length/PAGE_SIZE)+" "+ib("pageNext","caret-right","다음 파일",(page+1)*PAGE_SIZE>=arr.length):icon("clock")+" 마지막 분석 "+esc(data.time);
  const checked=arr.filter(f=>selected.has(f.id)).length;
  $("#all-check").checked=!!arr.length&&checked===arr.length;$("#all-check").indeterminate=checked>0&&checked<arr.length;
  $("#selection-bar").hidden=!selected.size;$("#selection-bar").innerHTML='<strong>'+selected.size+'개 선택</strong><button data-action="deselect">선택 해제</button>'+btn("groupMenu","선택 편집","pencil-simple");
}
function infoRows(items){return '<dl class="info-list">'+items.filter(([,v])=>v!==undefined && v!==null && v!=="").map(([k,v])=>'<dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd>').join("")+'</dl>';}
async function detail(id){
  const f=files.get(id),info=await call("detail",{id});
  showDialog(f.name,(f.ext.toUpperCase()||"파일")+"   ·   "+bytes(f.size),
    '<div class="info-note">'+esc(info.note)+"<br>"+esc(info.evidence)+'</div>'+infoRows([
      ["현재 그룹",groups.get(f.group)?.title||"미분류"],["판정",f.state],["추천 신뢰도",f.confidence?.toFixed(2)],
      ["정규화한 이름",info.normalized],["핵심 단어",info.tokens.join(" · ")],["역할",info.roles.join(" · ")],["순번",info.sequence],["버전",info.versions.join(" · ")],
      ["강좌명",info.course],["다운로드 페이지",info.page],["출처 페이지 주소",info.source_page],["다운로드 사이트",f.host],["2차 분석",info.excerpt],["생성",info.created],["수정",info.modified],["경로",info.path]]),
    btn("close","닫기")+btn("submitDialog","이 파일 편집","pencil-simple",true),()=>{selected=new Set([id]);if(view==="review")rows();groupMenu();});
}
function groupMenu(){
  const items=[],ids=[...selected];
  const g=groups.get(scope)||groups.get(files.get(ids[0])?.group);
  const add=(type,label,glyph)=>items.push('<button class="menu-btn" data-edit="'+type+'" data-group="'+esc(g?.id||"")+'">'+icon(glyph)+esc(label)+'</button>');
  if(ids.length){add("assign","다른 그룹으로 이동","folder-notch-open");add("create","새 그룹 만들기","folder-simple-plus");add("manual","체크한 파일을 폴더로 이동","arrow-square-out");}
  if(g){add("rename","그룹 이름 변경","pencil-simple");add("merge","두 그룹 병합","intersect");if(ids.length&&ids.length<g.count&&ids.every(id=>files.get(id).group===g.id))add("split","선택 파일로 그룹 분리","git-fork");}
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
  const ids=[...selected],g=groups.get(gid);
  if(kind==="manual"){close();return preview("manual");}
  const args={kind,files:ids,group:gid};
  if(["must","cannot","clear"].includes(kind))return applyEdit(args);
  if(["assign","merge"].includes(kind)){
    const choices=data.groups.filter(t=>kind!=="merge"||t.id!==gid);
    if(!choices.length&&kind==="merge"){toast("병합할 다른 그룹이 없습니다.");return;}
    const opts=(kind==="assign"?'<option value="">미분류</option>':"")+choices.map(t=>'<option value="'+t.id+'">'+esc(t.title)+" ("+t.count+'개)</option>').join("");
    showDialog(kind==="assign"?"다른 그룹으로 이동":"두 그룹 병합","","<label>대상 그룹<select id=\"value\" class=\"field\">"+opts+"</select></label>",
      btn("close","취소")+btn("submitDialog","적용","check",true),()=>applyEdit({...args,target:$("#value").value}));return;
  }
  const cover=kind==="course"?await call("cover",{group:gid}):null;
  const title=({rename:"그룹 이름 변경",create:"새 그룹 만들기",split:"그룹 분리",course:"파일명 변경"})[kind];
  showDialog(title,cover?.[1]||"",'<label>그룹 이름<input id="value" class="field" maxlength="140" value="'+esc(cover?.[0]||(kind==="rename"?g?.title:""))+'"></label>',
    btn("close","취소")+btn("submitDialog","저장","check",true),()=>{const val=$("#value").value.trim();if(!val){$("#value").focus();return;}return applyEdit({...args,title:val});});
  $("#value").focus();$("#value").select();
}
async function preview(kind){
  const result=await call("preview",{kind,group:view==="review"&&scope!=="hold"?scope:null,files:[...selected]});
  if(!result)return;
  const rows=result.rows,move=rows.filter(r=>!r.skip),byFolder=new Map();
  rows.forEach(r=>{const path=r.target.slice(0,r.target.lastIndexOf("\\"));if(!byFolder.has(path))byFolder.set(path,[]);byFolder.get(path).push(r);});
  const title=kind==="undo"?"최근 이동 되돌리기":"폴더 정리 미리보기";
  const body=[...byFolder].map(([p,fs])=>'<section class="move-group"><strong>'+icon("folder-notch")+esc(p)+'</strong>'+fs.map(f=>'<p class="move-row" title="'+esc(f.source)+'">'+esc(f.name)+(f.skip?'<small>건너뜀 · '+esc(f.skip)+'</small>':"")+'</p>').join("")+'</section>').join("");
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
  const toggles=[["recursive","하위 폴더 포함","다운로드 폴더 안의 하위 폴더까지 분석"],["deep","애매한 파일만 본문 분석","중간 신뢰도 파일의 앞부분을 읽어 그룹 재검토"],["covers","강의 표지로 과목명 찾기","대표 문서 한 개의 표지에서 그룹 이름 확인"]];
  showDialog("분석 설정","",toggles.map(([k,t,p])=>'<label class="setting"><span><b>'+t+'</b><small>'+p+'</small></span><input type="checkbox" id="opt-'+k+'" '+(options[k]?"checked":"")+'></label>').join("")+'<div style="padding-top:16px">'+btn("bridge","브라우저 출처 연결","plugs-connected")+'</div>',
    btn("close","취소")+btn("submitDialog","적용하고 다시 분석","arrows-clockwise",true),()=>{const val=Object.fromEntries(toggles.map(([k])=>[k,$("#opt-"+k).checked]));close();return scan(val);});
}
async function action(key){
  if(key==="close"){close();return;}
  if(key==="cancel"){window.desktop.cancel();return;}
  if(key==="openDownloads"){await call("openDownloads");return;}
  if(busy)return;
  switch(key){
    case "scan":return scan();
    case "settings":return settings();
    case "all":return setScope("all");
    case "organize":return preview("organize");
    case "undo":return preview("undo");
    case "groupMenu":return groupMenu();
    case "confirmCourse":return editForm("course",scope);
    case "submitDialog":{const fn=dialogAction;if(fn){const b=$('[data-action="submitDialog"]');if(b)b.disabled=true;try{await fn();}finally{if(b?.isConnected)b.disabled=false;}}return;}
    case "shelfPrev":shelfStart=Math.max(0,shelfStart-shelfWidth());return review();
    case "shelfNext":shelfStart=Math.min(data.groups.length-shelfWidth(),shelfStart+shelfWidth());return review();
    case "pagePrev":page=Math.max(0,page-1);return rows();
    case "pageNext":page++;return rows();
    case "deselect":selected.clear();return rows();
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
    if(d.view){view=d.view;scope=null;selected.clear();render();return;}
    if(d.scope){setScope(d.scope);return;}
    if(d.tab){tab=d.tab;page=0;selected.clear();review();return;}
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
});
let previousWidth=shelfWidth();window.addEventListener("resize",()=>{const k=shelfWidth();if(k!==previousWidth){previousWidth=k;if(view==="review"&&data)review();}});
window.desktop.status(t=>{if(busy)status(t,scanBusy);});
(async()=>{try{options=await call("options");await scan();}catch(e){errorDialog(e);}})();
