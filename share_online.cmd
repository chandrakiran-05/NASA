@echo off
rem Share the locally running site on the internet through a free Cloudflare quick tunnel (no account).
rem Needs run_backend.cmd and run_frontend.cmd running. The public link is printed below
rem (https://....trycloudflare.com); it works while this window stays open. Ctrl+C stops sharing.
cd /d "%~dp0"
if not exist tools\cloudflared.exe (
  echo Downloading cloudflared from Cloudflare's GitHub releases...
  if not exist tools mkdir tools
  curl -fL -o tools\cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe || exit /b 1
)
tools\cloudflared.exe tunnel --no-autoupdate --url http://localhost:5180
