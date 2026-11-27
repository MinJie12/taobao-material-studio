@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 淘宝商品素材采集与创作工具
echo.
echo   淘宝商品素材采集与创作工具
echo   正在启动本地服务，请稍候...
echo.
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
  echo   首次启动，正在创建独立 Python 环境...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv "%~dp0.venv"
    if not errorlevel 1 goto environment_ready
  )
  where python >nul 2>nul
  if errorlevel 1 goto python_missing
  python -m venv "%~dp0.venv"
  if errorlevel 1 goto environment_failed
)

:environment_ready
"%VENV_PY%" -c "import flask, PIL, numpy, requests, jieba" >nul 2>nul
if errorlevel 1 (
  echo   正在安装或补齐运行依赖，请稍候...
  "%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
  if errorlevel 1 goto dependency_failed
)

"%VENV_PY%" app.py
if errorlevel 1 echo   服务异常退出，请查看上方错误信息。
echo.
echo   服务已停止。
pause
exit /b

:python_missing
echo   未找到 Python。请先安装 Python 3.12 或更高版本，并启用“Add Python to PATH”，然后重新启动。
goto failed

:environment_failed
echo   创建 Python 环境失败，请检查 Python 安装后重试。
goto failed

:dependency_failed
echo   依赖安装失败。请检查网络连接，或查看上方错误信息。
goto failed

:failed
echo.
pause
