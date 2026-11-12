# Allows python.exe (and cTrader, if it is running) through Windows Security
# "Controlled folder access" (ransomware protection), so the US30 robot can save
# its memory and log in Documents. Protection stays ON for every other program.
# Run via permite_python.bat (it asks for administrator rights).

Write-Host ""
Write-Host "US30 Matrix - permit Python prin 'Acces controlat la foldere'" -ForegroundColor Cyan
Write-Host ""

$paths = @()
try {
    $py = (& python -c "import sys; print(sys.executable)" 2>$null)
    if ($py) { $paths += $py.Trim() }
} catch {}
$paths += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object FullName
$paths += Get-ChildItem "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object FullName
$paths += Get-Process -Name "cTrader*" -ErrorAction SilentlyContinue | ForEach-Object Path

$paths = $paths | Where-Object { $_ -and (Test-Path $_) -and ($_ -notlike "*WindowsApps*") } | Sort-Object -Unique

if (-not $paths) {
    Write-Host "Nu am gasit python.exe. Verifica instalarea Python (python --version)." -ForegroundColor Red
    exit 1
}

$ok = $true
foreach ($p in $paths) {
    try {
        Add-MpPreference -ControlledFolderAccessAllowedApplications $p -ErrorAction Stop
        Write-Host "  PERMIS: $p" -ForegroundColor Green
    } catch {
        $ok = $false
        Write-Host "  EROARE la $p : $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host ""
if ($ok) {
    Write-Host "Gata. Porneste din nou cBot-ul in cTrader." -ForegroundColor Cyan
} else {
    Write-Host "Daca folosesti alt antivirus decat Microsoft Defender, adauga python.exe manual in el." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Aplicatii permise acum:"
(Get-MpPreference).ControlledFolderAccessAllowedApplications | ForEach-Object { Write-Host "  - $_" }
