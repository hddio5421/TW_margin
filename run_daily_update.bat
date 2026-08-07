@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Market Margin Daily Update
echo ====================================================
echo   Updating Daily Market Margin Data...
echo ====================================================
cd /d "%~dp0"
python fetch_real_data.py
echo.
echo ====================================================
echo Press any key to exit...
echo ====================================================
pause >nul
