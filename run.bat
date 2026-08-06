@echo off
setlocal EnableExtensions
title Forge3D - Iniciar
set "ENGINE_ROOT=%~dp0"
cd /d "%ENGINE_ROOT%"
echo.
echo [Forge3D] Iniciando a engine local...
echo.
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ENGINE_ROOT%scripts\run.ps1" -Restart
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
  echo [ERRO] Forge3D nao iniciou. Codigo: %EXIT_CODE%
  echo Veja os detalhes em "%ENGINE_ROOT%logs".
) else (
  echo [OK] Forge3D iniciou. Abra http://127.0.0.1:5173 se o navegador nao abriu.
)
echo.
pause
endlocal & exit /b %EXIT_CODE%
