const {contextBridge,ipcRenderer}=require("electron");
contextBridge.exposeInMainWorld("desktop",{
  call:(action,args)=>ipcRenderer.invoke("desktop",action,args),
  cancel:()=>ipcRenderer.send("cancel"),
  cancelSearch:()=>ipcRenderer.send("cancel-search"),
  status:listener=>ipcRenderer.on("scan-status",(_event,text)=>listener(text))
});
