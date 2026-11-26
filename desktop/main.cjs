const {app, BrowserWindow, ipcMain, dialog, clipboard, shell} = require("electron");
const {spawn} = require("node:child_process");
const {existsSync} = require("node:fs");
const {createInterface} = require("node:readline");
const path = require("node:path");

const root = path.dirname(__dirname);
const allowed = new Set(["scan","options","sources","search","chooseFolder","detail","related","history","historyDetail","review","matrix","pair","preview","execute","edit","cover","openDownloads","bridge","beginRename","renameEntry","doubleClickTime"]);
const pending = new Map();
const iconCache = new Map();
const searchRows = new Map();
let reviewTypes = new Map();
let reviewGeneration = "";
let reviewFiles=new Map(), reviewFolders=new Map();

function rememberFolders(layout){
  reviewFolders=new Map();
  for(const row of layout){
    if(row.mode==="existing")reviewFolders.set(reviewFiles.get(row.id)?.group,path.dirname(row.target));
  }
}
let searchRevision=0, searchQuery=null;
let window, child, sequence=0, mutating=false;

function startService() {
  const packaged = path.join(root,"python","python.exe");
  const process = spawn(existsSync(packaged) ? packaged : "python.exe",
    ["-B","-X","utf8","-u",path.join(root,"desktop_service.py")],
    {cwd:root, windowsHide:true, stdio:["pipe","pipe","pipe"]});
  child=process;
  let errorText="";
  process.stderr.on("data",chunk=>{errorText=(errorText+chunk.toString()).slice(-1200);});
  function ended(message) {
    if (child!==process) return;
    child=null;
    for (const resolve of pending.values()) resolve({ok:false,error:message});
    pending.clear();
  }
  process.on("error",error=>ended(error.message));
  process.on("exit",()=>ended(errorText || "분석 엔진이 종료되었습니다. 다시 분석하세요."));
  process.stdin.on("error",error=>ended(error.message));
  createInterface({input:process.stdout}).on("line",line=>{
    let response;
    try {response=JSON.parse(line);} catch {return;}
    if (response.status) {
      if (window && !window.isDestroyed()) window.webContents.send("scan-status",response.status);
      return;
    }
    pending.get(response.id)?.(response);pending.delete(response.id);
  });
}
function call(action,args) {
  if (!child) startService();
  const id=++sequence;
  return new Promise(resolve=>{
    pending.set(id,resolve);
    child.stdin.write(JSON.stringify({id,action,args})+"\n");
  });
}
function isLocal(event) {return window && event.senderFrame===window.webContents.mainFrame;}
async function fileIcon(row) {
  const key=path.extname(row.name).toLowerCase();
  if(!iconCache.has(key)){
    if(iconCache.size>=256)iconCache.delete(iconCache.keys().next().value);
    const icon=app.getFileIcon(row.path,{size:"small"})
      .then(image=>image.isEmpty()?"":image.toDataURL()).catch(()=>"");
    iconCache.set(key,icon);
  }
  return iconCache.get(key);
}
ipcMain.handle("desktop",async(event,action,args={})=>{
  if (!isLocal(event)) return {ok:false,error:"지원하지 않는 작업입니다."};
  if(action==="openReviewEntry"){
    const source=args.entry==="file"?reviewFiles.get(args.id)?.path:reviewFolders.get(args.id);
    if(args.generation!==reviewGeneration||!source)return {ok:false,error:"목록에서 다시 선택하세요."};
    const error=await shell.openPath(source);
    return error?{ok:false,error}:{ok:true,value:true};
  }
  if(action==="beginRename"&&args.entry==="search"){
    const row=searchRows.get(args.id);
    if(!row)return {ok:false,error:"검색 결과에서 다시 선택하세요."};
    args={entry:"search",source:row.path};
  }
  if(action==="reviewIcons"){
    if(args.generation!==reviewGeneration)return {ok:true,value:{}};
    const icons=await Promise.all([...reviewTypes].map(async ([ext,row])=>[ext,await fileIcon(row)]));
    return {ok:true,value:args.generation===reviewGeneration?Object.fromEntries(icons):{}};
  }
  if(action==="openSearchResult"){
    const row=searchRows.get(args.id);
    if(!row||!path.isAbsolute(row.path))return {ok:false,error:"검색 결과가 바뀌었습니다. 이름을 다시 선택하세요."};
    const error=await shell.openPath(row.path);
    return error?{ok:false,error:"열 수 없습니다. 파일 위치와 기본 앱을 확인하세요. "+error}:{ok:true,value:true};
  }
  if(action==="searchIcons"){
    const revision=searchRevision;
    const icons=await Promise.all([...searchRows].filter(([,row])=>!row.isFolder)
      .map(async ([id,row])=>[id,await fileIcon(row)]));
    return {ok:true,value:revision===searchRevision?Object.fromEntries(icons):{}};
  }
  if (!allowed.has(action)) return {ok:false,error:"지원하지 않는 작업입니다."};
  const writes=action==="execute"||action==="renameEntry";
  if (writes && mutating) return {ok:false,error:"파일을 처리하고 있습니다."};
  if (writes) mutating=true;
  try {
    if (action==="chooseFolder") {
      const selected=await dialog.showOpenDialog(window,{title:"폴더 선택",properties:["openDirectory"]});
      return {ok:true,value:selected.canceled?null:selected.filePaths[0]||null};
    }
    if (action==="preview" && args.kind==="manual") {
      const selected=await dialog.showOpenDialog(window,{title:"파일을 이동할 기존 폴더",properties:["openDirectory"]});
      if (selected.canceled) return {ok:true,value:null};
      args={...args,destination:selected.filePaths[0]};
    }
    const revision=action==="search"?++searchRevision:null;
    if(revision!==null && args.query!==searchQuery){
      searchRows.clear();
      searchQuery=args.query;
    }
    const reply=await call(action,args);
    if(action==="scan" && reply.ok){
      reviewGeneration=reply.value.generation;
      reviewFiles=new Map(reply.value.files.map(f=>[f.id,f]));
      rememberFolders(reply.value.layout);
      reviewTypes=new Map();
      for(const row of reply.value.files){
        if(!reviewTypes.has(row.ext))reviewTypes.set(row.ext,row);
      }
    }
    if(action==="renameEntry" && reply.ok){
      const {old,path:next,layout,refresh}=reply.value;
      for(const row of searchRows.values()){
        const relative=path.relative(old,row.path);
        if(relative==="")Object.assign(row,{name:path.basename(next),path:next});
        else if(!relative.startsWith(".."+path.sep)&&relative!==".."&&!path.isAbsolute(relative))
          row.path=path.join(next,relative);
      }
      if(layout)rememberFolders(layout);
      if(refresh)reviewGeneration="";
    }
    if(action==="search" && reply.ok && revision===searchRevision){
      const previousIds=new Map([...searchRows].map(([id,row])=>[row.path,id]));
      searchRows.clear();
      reply.value.results.forEach((row,i)=>{
        row.id=previousIds.get(row.path)??(revision+"-"+i);
        searchRows.set(row.id,row);
      });
    }
    if (action==="bridge" && reply.ok) clipboard.writeText(reply.value);
    return reply;
  } finally {if (writes) mutating=false;}
});
ipcMain.on("cancel",event=>{if(isLocal(event) && child) child.stdin.write('{"action":"cancel"}\n');});
ipcMain.on("cancel-search",event=>{
  if(!isLocal(event))return;
  searchRevision++;searchRows.clear();
  if(child)child.stdin.write('{"action":"cancelSearch"}\n');
});

function createWindow() {
  startService();
  window=new BrowserWindow({width:1380,height:920,minWidth:870,minHeight:630,show:false,
    title:"다운로드 정리",backgroundColor:"#f9f9fc",autoHideMenuBar:true,
    icon:path.join(root,"icons","brand.png"),titleBarStyle:"hidden",
    titleBarOverlay:{color:"#f8f8fb",symbolColor:"#55546a",height:38},
    webPreferences:{preload:path.join(__dirname,"preload.cjs"),sandbox:true,contextIsolation:true,nodeIntegration:false}});
  window.removeMenu();
  window.webContents.setWindowOpenHandler(()=>({action:"deny"}));
  window.webContents.on("will-navigate",event=>event.preventDefault());
  window.once("ready-to-show",()=>window.show());
  window.on("close",event=>{
    if(mutating){event.preventDefault();window.webContents.send("scan-status","파일 이동을 마친 뒤 창을 닫을 수 있어요.");}
  });
  window.loadFile(path.join(__dirname,"index.html"));
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance",()=>{if(window){if(window.isMinimized())window.restore();window.focus();}});
  app.whenReady().then(createWindow);
  app.on("window-all-closed",()=>app.quit());
  app.on("before-quit",()=>{if(child && !mutating) child.stdin.end();});
}
