# Demo environment for PowerShell.  Run it with a leading dot so the variables survive:
#
#     . .\run_demo_env.ps1
#
# The leading dot is not decoration - without it PowerShell runs this in a child scope and every
# variable vanishes when it exits, which looks exactly like the script having done nothing.
#
# `source run_demo_env.sh` is the bash spelling and PowerShell does not have `source`. This file
# is the same settings for the shell you are actually in.
#
# Not committed: it holds the grid key and the demo passwords. See .env.example for the full list.

$env:POSTGRES_DSN  = "postgresql://sentinel:sentinel@127.0.0.1:55433/sentinel"
$env:REDIS_URL     = "redis://localhost:56380/0"
$env:JWT_SECRET    = "prahari_dev_secret_at_least_32_chars_long"

$env:MINIO_ENDPOINT   = "http://localhost:9000"
$env:MINIO_ACCESS_KEY = "sentinel"
$env:MINIO_SECRET_KEY = "sentinel_dev_only"

$env:API_BASE = "http://127.0.0.1:8000"

# The console signs in to the core API as these two accounts. Two of them, because [C10] gives
# admin:audit to SYSTEM_ADMIN and denies that role live data - one account cannot serve both the
# map and the audit tab.
$env:PRAHARI_API                    = "http://127.0.0.1:8000"
$env:PRAHARI_CONSOLE_USER           = "field"
$env:PRAHARI_CONSOLE_PASSWORD       = "sentinel123"
$env:PRAHARI_CONSOLE_ADMIN_USER     = "console-audit"
$env:PRAHARI_CONSOLE_ADMIN_PASSWORD = "console_audit_dev_only"

# The camera grid. Both fields are required: the key on its own returns "Email or access password
# is incorrect", which reads exactly like an expired key.
$env:GRID_EMAIL = "neevmodh205@gmail.com"
$env:GRID_KEY   = "5HW4-N6KY-B64Q"

# The interpreter that has torch, ultralytics and the OCR engines. Anything you run by hand must
# use this one - a bare `python` gives you a detector that silently does nothing.
$env:PRAHARI_PY = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host "Prahari environment loaded." -ForegroundColor Green
Write-Host "  python  -> $env:PRAHARI_PY"
Write-Host "  postgres-> $env:POSTGRES_DSN"
Write-Host ""
Write-Host 'Use $env:PRAHARI_PY instead of python for anything touching the CV stack.'
