@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Forge3D - UltraShape experimental
set "INSTALL_ROOT=%~dp0"
cd /d "%INSTALL_ROOT%"
echo.
echo [Forge3D] Instalacao experimental do UltraShape nativo.
echo Este modulo so sera habilitado apos a calibracao oficial passar.
echo.
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_ROOT%install-ultrashape-native-experimental.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
  echo [ERRO] UltraShape nao foi habilitado. Codigo: %EXIT_CODE%
  echo O TRELLIS continua disponivel normalmente.
  echo Log: "%INSTALL_ROOT%..\logs\install"
) else (
  echo [OK] UltraShape instalado e calibrado.
)
echo.
pause
endlocal & exit /b %EXIT_CODE%
