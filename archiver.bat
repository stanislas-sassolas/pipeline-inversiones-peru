@echo off
rem Archivage du Banco de Inversiones (MEF), pour un lancement a la main. Journal : archiver.log dans le dossier des donnees.
rem L'environnement Python est attendu dans %USERPROFILE%\.venvs\inversiones-peru (a adapter si besoin).
"%USERPROFILE%\.venvs\inversiones-peru\Scripts\python.exe" "%~dp0archiver.py" --journal "%USERPROFILE%\data\inversiones-peru\archiver.log"
