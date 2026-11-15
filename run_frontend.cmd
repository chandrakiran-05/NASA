@echo off
cd /d "%~dp0frontend"
set BACKEND_URL=http://127.0.0.1:8010
npm run dev -- --port 5180 --strictPort
