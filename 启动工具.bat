@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 淘宝商品素材采集与创作工具
echo.
echo   淘宝商品素材采集与创作工具
echo   正在启动本地服务，请稍候...
echo.
python app.py
echo.
echo   服务已停止。
pause
