@echo off
rem Start Mint, or control the running instance:
rem   mint-ctl.cmd            start (or show if already running)
rem   mint-ctl.cmd --toggle   show/hide
rem   mint-ctl.cmd --show ^| --hide ^| --quit
rem Needs `npm run build` once when not started through `npm run dev`.
set "DIR=%~dp0.."
"%DIR%\node_modules\electron\dist\electron.exe" "%DIR%" %*
