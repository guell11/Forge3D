@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Forge3D - Reparar instalacao
set "INSTALL_ROOT=%~dp0"
cd /d "%INSTALL_ROOT%"
echo.
echo [Forge3D] Reparando a instalacao existente...
echo.
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_ROOT%install.ps1" -Repair -InstallBlender
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
  echo [ERRO] O reparo falhou. Codigo: %EXIT_CODE%
  echo Log: "%INSTALL_ROOT%..\logs\install"
) else (
  echo [OK] Reparo concluido. Execute run.bat na pasta principal.
)
echo.
pause
endlocal & exit /b %EXIT_CODE%
