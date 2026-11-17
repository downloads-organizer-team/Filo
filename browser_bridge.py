"""Register the per-user Chrome/Edge native host for this installed app directory."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import winreg
import storage

HOST="kr.ac.course_downloads"
EXTENSION=Path(__file__).resolve().with_name("browser_extension")

def register():
    key=json.loads((EXTENSION/"manifest.json").read_text(encoding="utf-8"))["key"]
    digest=hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    extension_id="".join(chr(ord("a")+int(ch,16)) for ch in digest)
    folder=storage.HOME/"BrowserBridge"
    folder.mkdir(parents=True,exist_ok=True)
    python=Path(sys.executable).with_name("python.exe")
    script=Path(__file__).resolve().with_name("capture_host.py")
    launcher=folder/"capture.cmd"
    batch='@echo off\n@chcp 65001 >nul\nsetlocal DisableDelayedExpansion\n"%s" -B -X utf8 "%s"\n'
    launcher.write_text(batch%(str(python).replace("%","%%"),str(script).replace("%","%%")),encoding="utf-8")
    manifest=folder/"host.json"
    storage.save(manifest,dict(name=HOST,description="LMS download context",path=str(launcher),
                               type="stdio",allowed_origins=[f"chrome-extension://{extension_id}/"]))
    for product in (r"Google\Chrome",r"Microsoft\Edge"):
        path=rf"Software\{product}\NativeMessagingHosts\{HOST}"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_WRITE) as reg:
            winreg.SetValueEx(reg,"",0,winreg.REG_SZ,str(manifest))
    return EXTENSION

if __name__=="__main__":print(register())
