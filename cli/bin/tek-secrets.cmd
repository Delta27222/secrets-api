@echo off
:: Windows usa 'python' por defecto (instaladores oficiales configuran PATH)
where python >nul 2>&1
if %errorlevel% equ 0 (
    python -m tek_secrets.main %*
) else (
    python3 -m tek_secrets.main %*
)