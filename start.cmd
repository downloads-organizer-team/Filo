@echo off
if exist "%~dp0runtime\organizer.exe" (
  start "" "%~dp0runtime\organizer.exe"
  exit /b
)
pushd "%~dp0" || exit /b 1
call npx.cmd --yes electron@45.3.3 ./desktop
set "organizer_exit=%errorlevel%"
popd
exit /b %organizer_exit%
