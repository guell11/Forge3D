@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Forge3D - Instalacao 16 GB VRAM
set "INSTALL_ROOT=%~dp0"
cd /d "%INSTALL_ROOT%"
echo.
echo [Forge3D] Instalacao para perfil de 16 GB VRAM.
echo.
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_ROOT%install.ps1" -Profile 16gb -InstallBlender
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
  echo [ERRO] A instalacao falhou. Codigo: %EXIT_CODE%
  echo Log: "%INSTALL_ROOT%..\logs\install"
) else (
  echo [OK] Instalacao concluida. Execute run.bat na pasta principal.
)
echo.
pause
endlocal & exit /b %EXIT_CODE%
