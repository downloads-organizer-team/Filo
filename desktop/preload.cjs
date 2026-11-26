const {contextBridge,ipcRenderer}=require("electron");
contextBridge.exposeInMainWorld("desktop",{
  call:(action,args)=>ipcRenderer.invoke("desktop",action,args),
  cancel:()=>ipcRenderer.send("cancel"),
  cancelSearch:()=>ipcRenderer.send("cancel-search"),
  appearance:(theme,size)=>ipcRenderer.invoke("appearance",theme,size),
  onThemeChanged:listener=>ipcRenderer.on("theme-changed",(_event,theme)=>listener(theme)),
  status:listener=>ipcRenderer.on("scan-status",(_event,text)=>listener(text))
});
