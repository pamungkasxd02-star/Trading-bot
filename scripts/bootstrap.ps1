$ErrorActionPreference = "Stop"
py -3.11 -m venv .venv
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -e ".[dev]"
Write-Host "Selesai. Salin .env.example ke .env lalu ikuti README."
