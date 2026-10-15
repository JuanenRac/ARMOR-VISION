@echo off
REM ARMOR-VISION incremental build launcher. GPL-3.0-or-later.
call "%~dp0..\ARMOR-COMMON\scripts\armor-project.bat" build "%~dp0."
exit /b %ERRORLEVEL%
