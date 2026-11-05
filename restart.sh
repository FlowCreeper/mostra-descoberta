#!/usr/bin/env bash
# Reinicia o servidor da mostra (usa PID salvo em .server.pid)
cd "$(dirname "$0")"
if [ -f .server.pid ] && kill -0 "$(cat .server.pid)" 2>/dev/null; then kill "$(cat .server.pid)"; sleep 1; fi
nohup python3 server.py > server.log 2>&1 &
echo $! > .server.pid
sleep 1
curl -s -o /dev/null -w "servidor: HTTP %{http_code}\n" "http://localhost:${PORT:-8000}/"
