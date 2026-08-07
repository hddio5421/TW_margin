@echo off
chcp 65001 >nul
title 啟動台股市場廣度網頁儀表板
echo ====================================================
echo   正在啟動【台股市場廣度觀測站】網頁...
echo ====================================================
echo.

cd /d "%~dp0"
start http://localhost:8080
python -m http.server 8080
