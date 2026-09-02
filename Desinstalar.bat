@echo off
rem GClaude Indexer -- runs uninstall.ps1.
rem
rem This file exists because of the execution policy, and it is the same
rem reason Indexer.bat exists for the installer.
rem
rem Google Drive marks every file it syncs as having come from the internet
rem (the Zone.Identifier alternate data stream, ZoneId=3). Windows' default
rem execution policy, RemoteSigned, then demands a digital signature before
rem running a .ps1 from that zone -- so double-clicking or typing
rem ".\uninstall.ps1" fails with "the file is not digitally signed", which
rem reads like the script is broken when nothing is wrong with it. It
rem applies to install.ps1 just as much; that one never showed the problem
rem only because it is always started through Indexer.bat, which passes the
rem switch below.
rem
rem -ExecutionPolicy Bypass applies to this one invocation only. It changes
rem no machine setting, needs no administrator, and leaves the policy
rem exactly as it was for every other script on the computer.

setlocal
set "ROOT=%~dp0"

rem Arguments are forwarded, so the switches documented in the README still
rem work: Desinstalar.bat -WhatIfOnly, -KeepDependencies, -RemoveAll.
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%uninstall.ps1" %*

echo.
pause
endlocal
