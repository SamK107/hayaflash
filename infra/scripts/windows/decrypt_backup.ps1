<#
.SYNOPSIS
  Dechiffre une sauvegarde HayaFlash (.tar.age) de D: vers un dossier choisi.

.DESCRIPTION
  Utilise age.exe et la CLE PRIVEE age du porteur du projet (fichier texte cree par
  age-keygen, conserve HORS du PC : cle USB separee + copie papier ou gestionnaire de
  mots de passe). Sans elle, les sauvegardes sont illisibles.

  Resultat : <Sortie>\<AAAA-MM-JJ_HHMM>\ contenant db.dump, media.tar.gz, backup.info
  et SHA256SUMS. Les empreintes SHA256 sont verifiees apres extraction.
  La sortie est EN CLAIR : choisir un dossier temporaire, ne pas la laisser sur D:.

.PARAMETER Sauvegarde  Fichier .tar.age a dechiffrer.
.PARAMETER Sortie      Dossier de destination (cree si besoin, doit etre vide ou absent pour
                       ce nom de sauvegarde).
.PARAMETER CleSecrete  Fichier de cle privee age (AGE-SECRET-KEY-...).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\decrypt_backup.ps1 `
    -Sauvegarde D:\Sauvegardes\HayaFlash\hayaflash-prod\2026-10-18_0300.tar.age `
    -Sortie C:\Temp\restauration -CleSecrete E:\cles\hayaflash-age.txt
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Sauvegarde,
    [Parameter(Mandatory = $true)][string]$Sortie,
    [Parameter(Mandatory = $true)][string]$CleSecrete
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    $ancien = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        return [pscustomobject]@{ Code = $LASTEXITCODE; Sortie = @($out) }
    } finally { $ErrorActionPreference = $ancien }
}

function Fail([string]$Message) { Write-Host "ERREUR : $Message" -ForegroundColor Red; exit 1 }

foreach ($exe in 'age.exe', 'tar.exe') {
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
        Fail "$exe introuvable (age : 'winget install FiloSottile.age')."
    }
}
if (-not (Test-Path -LiteralPath $Sauvegarde)) { Fail "Sauvegarde introuvable : $Sauvegarde" }
if ($Sauvegarde -notmatch '(\d{4}-\d{2}-\d{2}_\d{4})\.tar\.age$') { Fail "Nom inattendu (attendu AAAA-MM-JJ_HHMM.tar.age) : $Sauvegarde" }
$nom = $Matches[1]
if (-not (Test-Path -LiteralPath $CleSecrete)) { Fail "Cle privee introuvable : $CleSecrete (brancher la cle USB de secours)." }

if (Test-Path -LiteralPath (Join-Path $Sortie $nom)) { Fail "Le dossier $(Join-Path $Sortie $nom) existe deja : choisir une autre sortie." }
New-Item -ItemType Directory -Path $Sortie -Force | Out-Null

$tar = Join-Path $Sortie "$nom.tar"
try {
    $d = Invoke-Native 'age.exe' @('-d', '-i', $CleSecrete, '-o', $tar, $Sauvegarde)
    if ($d.Code -ne 0) { throw "dechiffrement impossible (mauvaise cle ?) : $($d.Sortie -join ' ')" }
    $x = Invoke-Native 'tar.exe' @('-xf', $tar, '-C', $Sortie)
    if ($x.Code -ne 0) { throw "extraction impossible : $($x.Sortie -join ' ')" }
    $dossier = Join-Path $Sortie $nom
    foreach ($l in (Get-Content -LiteralPath (Join-Path $dossier 'SHA256SUMS') | Where-Object { $_.Trim() })) {
        if ($l -notmatch '^([0-9a-fA-F]{64})\s+\*?(.+)$') { throw "ligne SHA256SUMS illisible : $l" }
        $attendu = $Matches[1].ToLower(); $fichier = $Matches[2].Trim()
        if ($fichier -match '[\\/]') { throw "nom suspect dans SHA256SUMS : $fichier" }
        $reel = (Get-FileHash -LiteralPath (Join-Path $dossier $fichier) -Algorithm SHA256).Hash.ToLower()
        if ($reel -ne $attendu) { throw "empreinte invalide pour $fichier" }
    }
    Write-Host "OK : sauvegarde dechiffree et verifiee dans $dossier" -ForegroundColor Green
    Write-Host "Rappel : ce dossier est EN CLAIR. Le supprimer apres usage." -ForegroundColor Yellow
} catch {
    Write-Host "ERREUR : $($_.Exception.Message)" -ForegroundColor Red
    exit 2
} finally {
    Remove-Item -LiteralPath $tar -Force -ErrorAction SilentlyContinue
}
