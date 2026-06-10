# Start backend (FastAPI) and frontend (Vite) dev servers, each in its own window.
$root = $PSScriptRoot

Start-Process powershell -ArgumentList @(
  '-NoExit', '-Command',
  "cd '$root'; .\venv\Scripts\Activate.ps1; python main.py"
)

Start-Process powershell -ArgumentList @(
  '-NoExit', '-Command',
  "cd '$root\frontend'; `$env:NO_PROXY='localhost,127.0.0.1,::1'; `$env:no_proxy='localhost,127.0.0.1,::1'; npx vite"
)