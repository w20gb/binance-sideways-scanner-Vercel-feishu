@echo off
chcp 65001 > nul
title Squeeze Radar - Local Dashboard
echo =============================================
echo   Squeeze Radar - 横盘爆发雷达本地仪表盘
echo =============================================
echo.
echo [1/2] 正在检查依赖...
pip install fastapi uvicorn playwright pandas numpy requests >nul 2>&1
echo [OK] 依赖已就绪
echo.
echo [2/2] 启动仪表盘服务...
echo [TIP] 浏览器将自动打开 http://127.0.0.1:8000
echo [TIP] 按 Ctrl+C 停止服务
echo.

start "" http://127.0.0.1:8000
python server.py

echo.
echo 服务已停止。
pause
