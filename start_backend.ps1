# SASAA – Start Backend Server
# Run from the project root: .\start_backend.ps1
# Or double-click in Explorer after enabling PowerShell scripts.

Write-Host ""
Write-Host "Starting SASAA backend server..."
Write-Host "API docs: http://localhost:8000/docs"
Write-Host "Health:   http://localhost:8000/health"
Write-Host "Press Ctrl+C to stop."
Write-Host ""

Set-Location "$PSScriptRoot\backend"
python -m uvicorn app.main:app --reload --port 8000
