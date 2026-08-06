@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Forge3D - Blender 4.5 LTS portatil
set "INSTALL_ROOT=%~dp0"
cd /d "%INSTALL_ROOT%"
echo.
echo [Forge3D] Instalando Blender 4.5 LTS portatil...
echo.
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_ROOT%install-blender-4.5-lts-portable.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
  echo [ERRO] A instalacao do Blender falhou. Codigo: %EXIT_CODE%
  echo Log: "%INSTALL_ROOT%..\logs\install"
) else (
  echo [OK] Blender instalado e verificado.
)
echo.
pause
endlocal & exit /b %EXIT_CODE%
