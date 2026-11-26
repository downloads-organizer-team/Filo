"""Register the per-user Chrome/Edge native host for this installed app directory."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import winreg
import storage

HOST="kr.ac.course_downloads"
EXTENSION=Path(__file__).resolve().with_name("browser_extension")
PRODUCTS=(r"Google\Chrome",r"Microsoft\Edge")

def launcher_text():
    python=Path(sys.executable).with_name("python.exe")
    script=Path(__file__).resolve().with_name("capture_host.py")
    batch='@echo off\n@chcp 65001 >nul\nsetlocal DisableDelayedExpansion\n"%s" -B -X utf8 "%s"\n'
    return batch%(str(python).replace("%","%%"),str(script).replace("%","%%"))

def register():
    key=json.loads((EXTENSION/"manifest.json").read_text(encoding="utf-8"))["key"]
    digest=hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    extension_id="".join(chr(ord("a")+int(ch,16)) for ch in digest)
    folder=storage.HOME/"BrowserBridge"
    folder.mkdir(parents=True,exist_ok=True)
    launcher=folder/"capture.cmd"
    launcher.write_text(launcher_text(),encoding="utf-8")
    manifest=folder/"host.json"
    storage.save(manifest,dict(name=HOST,description="LMS download context",path=str(launcher),
                               type="stdio",allowed_origins=[f"chrome-extension://{extension_id}/"]))
    for product in PRODUCTS:
        path=rf"Software\{product}\NativeMessagingHosts\{HOST}"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_WRITE) as reg:
            winreg.SetValueEx(reg,"",0,winreg.REG_SZ,str(manifest))
    return EXTENSION

def unregister():
    folder=storage.HOME/"BrowserBridge"
    launcher, manifest=folder/"capture.cmd", folder/"host.json"
    try:
        recorded=json.loads(manifest.read_text(encoding="utf-8"))
        if recorded.get("name")!=HOST or Path(recorded.get("path",""))!=launcher:
            return
        if launcher.read_text(encoding="utf-8")!=launcher_text():
            return  # Another installation owns the shared Chrome/Edge host.
    except (OSError,ValueError,TypeError,AttributeError):
        return
    for product in PRODUCTS:
        key=rf"Software\{product}\NativeMessagingHosts\{HOST}"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_READ|winreg.KEY_SET_VALUE) as reg:
                value,kind=winreg.QueryValueEx(reg,"")
                if kind!=winreg.REG_SZ or os.path.normcase(value)!=os.path.normcase(str(manifest)):
                    continue
                winreg.DeleteValue(reg,"")
                empty=winreg.QueryInfoKey(reg)[:2]==(0,0)
            if empty:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER,key)
        except FileNotFoundError:
            continue
    launcher.unlink(missing_ok=True)
    manifest.unlink(missing_ok=True)
    try:
        folder.rmdir()
    except OSError:
        pass  # Preserve any other files the user kept in this folder.

if __name__=="__main__":
    if sys.argv[1:]==["--unregister"]:
        unregister()
    else:
        print(register())
