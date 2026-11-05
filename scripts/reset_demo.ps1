# Remet la base de démo dans son état propre (avant une répétition ou l'entretien).
#
# Lancement depuis le dossier odoo-demo :
#     powershell -ExecutionPolicy Bypass -File scripts\reset_demo.ps1
#
# Ce que fait le script :
#   1. vérifie que Docker et Odoo tournent (et les démarre si besoin) ;
#   2. supprime la base `demo` et restaure backups\demo_pret_pour_demo.zip ;
#   3. contrôle que BTP Express est revenu à 4 500 d'encours, sans dérogation.

# Docker écrit ses messages normaux sur la sortie d erreur : on ne s arrête pas
# dessus, les vraies erreurs sont vérifiées explicitement à chaque étape.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$backup = Join-Path $root "backups\demo_pret_pour_demo.zip"
if (-not (Test-Path $backup)) { throw "Sauvegarde introuvable : $backup" }

# Docker Desktop installé dans le profil utilisateur : on l'ajoute au PATH si besoin.
$dockerBin = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin"
if ((Test-Path $dockerBin) -and -not ($env:Path -like "*$dockerBin*")) { $env:Path = "$dockerBin;$env:Path" }

Write-Host "1/4 Vérification de Docker..." -ForegroundColor Cyan
docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $exe = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"
    Write-Host "    Docker n'est pas démarré : lancement de Docker Desktop..."
    Start-Process $exe
    for ($i = 0; $i -lt 36; $i++) {
        Start-Sleep -Seconds 5
        docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
    }
    if ($LASTEXITCODE -ne 0) { throw "Docker ne répond pas après 3 minutes." }
}
docker compose up -d 2>&1 | Out-Null

Write-Host "2/4 Attente d'Odoo..." -ForegroundColor Cyan
for ($i = 0; $i -lt 30; $i++) {
    try { $r = Invoke-WebRequest "http://localhost:8069/web/login" -UseBasicParsing -TimeoutSec 5; if ($r.StatusCode -eq 200) { break } } catch { }
    Start-Sleep -Seconds 2
}

$masterPwd = ((Get-Content "config\odoo.conf" | Where-Object { $_ -match "^admin_passwd" }) -replace "^admin_passwd\s*=\s*", "").Trim()

Write-Host "3/4 Restauration de la base propre (environ 30 secondes)..." -ForegroundColor Cyan
curl.exe -s -o NUL -X POST -F "master_pwd=$masterPwd" -F "name=demo" http://localhost:8069/web/database/drop
curl.exe -s -o NUL -w "    restauration : HTTP %{http_code}`n" -X POST -F "master_pwd=$masterPwd" -F "name=demo" -F "copy=false" -F "backup_file=@$backup" http://localhost:8069/web/database/restore
docker compose restart odoo 2>&1 | Out-Null
Start-Sleep -Seconds 5

Write-Host "4/4 Contrôle des données de démo..." -ForegroundColor Cyan
# Contrôle en SQL : factures dues de BTP Express, dérogations et journal vides.
$sql = "select (select coalesce(sum(m.amount_residual), 0)::int from account_move m join res_partner p on p.id = m.commercial_partner_id where p.ref = 'DEMO-BTP' and m.state = 'posted' and m.payment_state in ('not_paid', 'partial')) || ' ' || (select count(*) from credit_override_log) || ' ' || (select count(*) from sale_order where credit_approval_state != 'none')"
$out = (docker compose exec -T db psql -U odoo -d demo -Atc $sql 2>$null | Out-String).Trim()
if ($out -eq "4500 0 0") {
    Write-Host ""
    Write-Host "Démo prête : BTP Express à 4 500 d'encours, aucune dérogation." -ForegroundColor Green
    Write-Host "Ouvrir http://localhost:8069 (admin) et une fenêtre privée (paul)."
} else {
    Write-Host "Attention, état inattendu (encours BTP, journal, dérogations) : $out" -ForegroundColor Yellow
}
