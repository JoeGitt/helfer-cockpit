# Helfer-Cockpit installieren oder aktualisieren (Windows, ohne Admin-Rechte)
#   powershell -ExecutionPolicy Bypass -File install.ps1
#   oder als Einzeiler:  irm https://raw.githubusercontent.com/JoeGitt/helfer-cockpit-2/main/packaging/install.ps1 | iex
param([string]$Repo = "JoeGitt/helfer-cockpit-2", [string]$Ziel = "$env:LOCALAPPDATA\HelferCockpit")
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Write-Host "Helfer-Cockpit: neueste Version von GitHub ($Repo) holen ..."
$rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "helfer-cockpit-installer" }
$asset = $rel.assets | Where-Object { $_.name -like "HelferCockpit-*-windows.zip" } | Select-Object -First 1
if (-not $asset) { throw "Kein Windows-Paket im Release $($rel.tag_name) gefunden." }
$tmp = Join-Path $env:TEMP $asset.name
Write-Host "Lade $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) MB) ..."
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tmp -UseBasicParsing
$entpackt = Join-Path $env:TEMP "HelferCockpit-entpackt"
if (Test-Path $entpackt) { Remove-Item $entpackt -Recurse -Force }
Expand-Archive -Path $tmp -DestinationPath $entpackt -Force
$app = Join-Path $Ziel "app"
New-Item -ItemType Directory -Force -Path $Ziel | Out-Null
if (Test-Path $app) {
    Get-Process | Where-Object { $_.Path -like "$app\*" } | ForEach-Object { Write-Host "Beende laufendes Cockpit ..."; $_ | Stop-Process -Force }
    Start-Sleep -Seconds 1
    Remove-Item $app -Recurse -Force
}
Move-Item (Join-Path $entpackt "HelferCockpit") $app
Remove-Item $tmp -Force; Remove-Item $entpackt -Recurse -Force
# Verknüpfungen: Desktop und Startmenü
$shell = New-Object -ComObject WScript.Shell
foreach ($ordner in @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
    $lnk = $shell.CreateShortcut((Join-Path $ordner "Helfer-Cockpit.lnk"))
    $lnk.TargetPath = Join-Path $app "Helfer-Cockpit.bat"
    $lnk.WorkingDirectory = $app
    $lnk.Description = "Helfer-Cockpit Pfadi Winterthur Handball"
    $lnk.IconLocation = "$env:SystemRoot\System32\shell32.dll,167"
    $lnk.Save()
}
Write-Host "Installiert: $app (Version $($rel.tag_name)). Verknüpfung «Helfer-Cockpit» liegt auf dem Desktop."
Write-Host "Starte das Cockpit ..."
Start-Process -FilePath (Join-Path $app "Helfer-Cockpit.bat") -WorkingDirectory $app
