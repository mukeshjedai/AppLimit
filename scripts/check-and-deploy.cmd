@echo off
setlocal
title AppLimit - Check and Deploy
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-and-deploy.ps1" %*
set "EXITCODE=%ERRORLEVEL%"
echo.
if not "%EXITCODE%"=="0" (
  echo Check or deployment failed. Review the message above.
) else (
  echo Check and deployment completed successfully.
)
pause
endlocal & exit /b %EXITCODE%
