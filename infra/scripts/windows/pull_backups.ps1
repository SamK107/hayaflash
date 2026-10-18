<#
.SYNOPSIS
  Rapatrie les sauvegardes HayaFlash du VPS vers le disque externe D: (PC Windows).

.DESCRIPTION
  PowerShell 5.1+, OpenSSH Windows integre (ssh.exe / scp.exe), aucune autre dependance.

  Pour chaque dossier de sauvegarde distant (AAAA-MM-JJ_HHMM) ABSENT en local :
    1. copie par scp dans un dossier temporaire ".tmp-<nom>" ;
    2. verifie les empreintes avec SHA256SUMS ;
    3. seulement alors, renomme le dossier : une sauvegarde partielle n'est
       jamais visible sous son nom definitif.
  Retention locale : 30 quotidiennes + 12 mensuelles (la derniere de chaque mois),
  configurable. AUCUNE suppression si la copie du jour a echoue.
  Journal : <racine du disque>\Sauvegardes\HayaFlash\pull.log (dossier parent de la destination).
  Alerte bien visible si la derniere sauvegarde locale a plus de 48 h.

  Code de sortie : 0 = succes ; 1 = disque absent / non inscriptible ; 2 = echec de
  copie ou de verification ; 3 = succes mais derniere sauvegarde locale trop vieille.

.PARAMETER HoteSsh        Utilisateur@hote du VPS.
.PARAMETER DossierDistant Dossier des sauvegardes sur le VPS.
.PARAMETER Destination    Dossier local de destination (sur le disque externe).
.PARAMETER CleSsh         Cle privee SSH dediee a ce transfert.
.PARAMETER GardeQuotidiennes  Nombre de jours conserves (defaut 30).
.PARAMETER GardeMensuelles    Nombre de mois conserves (defaut 12).
.PARAMETER AgeMaxHeures   Seuil de l'alerte de fraicheur (defaut 48).
.PARAMETER SimulationSeulement  Affiche ce qui serait fait, sans copier ni supprimer.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\pull_backups.ps1
#>
[CmdletBinding()]
param(
    [string]$HoteSsh        = 'sam@31.207.39.116',
    [string]$DossierDistant = '/srv/backups/hayaflash-prod',
    [string]$Destination    = 'D:\Sauvegardes\HayaFlash\hayaflash-prod',
    [string]$CleSsh         = (Join-Path $env:USERPROFILE '.ssh\hayaflash_backup_ed25519'),
    [int]$GardeQuotidiennes = 30,
    [int]$GardeMensuelles   = 12,
    [int]$AgeMaxHeures      = 48,
    [switch]$SimulationSeulement
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Racine  = Split-Path -Parent $Destination          # D:\Sauvegardes\HayaFlash
$Journal = Join-Path $Racine 'pull.log'
$Motif   = '^\d{4}-\d{2}-\d{2}_\d{4}$'

function Write-Log {
    param([string]$Message, [string]$Niveau = 'INFO')
    $ligne = '{0} [{1}] {2}' -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $Niveau, $Message
    switch ($Niveau) {
        'ERREUR' { Write-Host $ligne -ForegroundColor Red }
        'ALERTE' { Write-Host $ligne -ForegroundColor Yellow }
        default  { Write-Host $ligne }
    }
    if (Test-Path -LiteralPath $Racine) {
        try { Add-Content -LiteralPath $Journal -Value $ligne -Encoding UTF8 } catch { }
    }
}

function Stop-Script {
    param([string]$Message, [int]$Code)
    Write-Log $Message 'ERREUR'
    exit $Code
}

# Appel d'un executable natif : en PowerShell 5.1, « 2>&1 » transforme chaque ligne de
# stderr en erreur terminante quand $ErrorActionPreference = 'Stop' (meme quand
# la commande reussit : ex. avertissements ssh). On neutralise localement et on
# ne se fie qu'au code de sortie.
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    $ancien = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        return [pscustomobject]@{ Code = $LASTEXITCODE; Sortie = @($out) }
    } finally { $ErrorActionPreference = $ancien }
}

# ── 0. Prerequis ──────────────────────────────────────────────────────────────
foreach ($exe in 'ssh.exe', 'scp.exe') {
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
        Stop-Script "$exe introuvable : activer la fonctionnalite Windows « Client OpenSSH »." 1
    }
}
if (-not (Test-Path -LiteralPath $CleSsh)) {
    Stop-Script "Cle SSH introuvable : $CleSsh (voir docs/SAUVEGARDES.md pour la creer)." 1
}

# ── 1. Disque D: present et inscriptible ──────────────────────────────────────
$lecteur = Split-Path -Qualifier $Destination        # "D:"
if (-not (Test-Path -LiteralPath "$lecteur\")) {
    Stop-Script "Le disque $lecteur est absent : brancher le disque externe puis relancer." 1
}
try {
    if (-not (Test-Path -LiteralPath $Destination)) {
        if ($SimulationSeulement) { Write-Log "[simulation] creation de $Destination" }
        else { New-Item -ItemType Directory -Path $Destination -Force | Out-Null }
    }
    if (-not $SimulationSeulement) {
        $test = Join-Path $Destination ('.ecriture-' + [guid]::NewGuid().ToString('N'))
        Set-Content -LiteralPath $test -Value 'test' -Encoding ASCII
        Remove-Item -LiteralPath $test -Force
    }
} catch {
    Stop-Script "Le disque $lecteur n'est pas accessible en ecriture : $($_.Exception.Message)" 1
}

# ── 2. Liste distante ─────────────────────────────────────────────────────────
# Options SSH : cle dediee uniquement, pas de mot de passe, cle hote verifiee
# (la premiere connexion doit avoir ete faite a la main pour l'enregistrer).
$optionsSsh = @('-i', $CleSsh, '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
                '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=20')

Write-Log "Debut : $HoteSsh`:$DossierDistant -> $Destination"
$res = Invoke-Native 'ssh.exe' ($optionsSsh + @($HoteSsh, "ls -1 '$DossierDistant'"))
if ($res.Code -ne 0) {
    Stop-Script "Liste distante impossible (code $($res.Code)) : $($res.Sortie -join ' ')" 2
}
$distants = @($res.Sortie | ForEach-Object { "$_".Trim() } | Where-Object { $_ -match $Motif } | Sort-Object)
Write-Log "$($distants.Count) sauvegarde(s) sur le VPS"

# ── 3. Copie des sauvegardes manquantes ───────────────────────────────────────
$copieEchouee = $false
$locales = @(Get-ChildItem -LiteralPath $Destination -Directory -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -match $Motif } | ForEach-Object { $_.Name })
$manquantes = @($distants | Where-Object { $locales -notcontains $_ })
Write-Log "$($manquantes.Count) a copier"

# Nettoyage des restes d'un transfert interrompu (dossiers temporaires seulement).
Get-ChildItem -LiteralPath $Destination -Directory -Filter '.tmp-*' -ErrorAction SilentlyContinue | ForEach-Object {
    if ($SimulationSeulement) { Write-Log "[simulation] suppression du reste $($_.Name)" }
    else { Remove-Item -LiteralPath $_.FullName -Recurse -Force; Write-Log "Reste d'un transfert interrompu supprime : $($_.Name)" }
}

foreach ($nom in $manquantes) {
    $tmp   = Join-Path $Destination ".tmp-$nom"
    $final = Join-Path $Destination $nom
    if ($SimulationSeulement) { Write-Log "[simulation] copierait $nom"; continue }
    try {
        New-Item -ItemType Directory -Path $tmp -Force | Out-Null
        # Fichiers un par un : evite les ambiguites de scp -r et de chemins.
        foreach ($f in 'db.dump', 'media.tar.gz', 'backup.info', 'SHA256SUMS') {
            $r = Invoke-Native 'scp.exe' ($optionsSsh + @("$HoteSsh`:$DossierDistant/$nom/$f", (Join-Path $tmp $f)))
            if ($r.Code -ne 0) { throw "scp de $f a echoue (code $($r.Code)) : $($r.Sortie -join ' ')" }
        }
        # Verification SHA256 d'apres SHA256SUMS (format « <hash>  <fichier> », sortie de sha256sum).
        $lignes = Get-Content -LiteralPath (Join-Path $tmp 'SHA256SUMS') | Where-Object { $_.Trim() }
        if (-not $lignes) { throw 'SHA256SUMS vide' }
        foreach ($l in $lignes) {
            if ($l -notmatch '^([0-9a-fA-F]{64})\s+\*?(.+)$') { throw "ligne SHA256SUMS illisible : $l" }
            $attendu = $Matches[1].ToLower(); $fichier = $Matches[2].Trim()
            if ($fichier -match '[\\/]') { throw "nom de fichier suspect dans SHA256SUMS : $fichier" }
            $reel = (Get-FileHash -LiteralPath (Join-Path $tmp $fichier) -Algorithm SHA256).Hash.ToLower()
            if ($reel -ne $attendu) { throw "empreinte invalide pour $fichier" }
        }
        Rename-Item -LiteralPath $tmp -NewName $nom      # visible seulement une fois valide
        Write-Log "Copie verifiee : $nom"
    } catch {
        $copieEchouee = $true
        Write-Log "Echec pour $nom : $($_.Exception.Message)" 'ERREUR'
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

# ── 4. Retention locale (jamais si une copie a echoue) ────────────────────────
$locales = @(Get-ChildItem -LiteralPath $Destination -Directory -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -match $Motif } | Sort-Object Name -Descending)
if ($copieEchouee) {
    Write-Log 'Retention SAUTEE : une copie a echoue, aucune sauvegarde locale ne sera supprimee.' 'ALERTE'
} elseif ($locales.Count -gt 0) {
    $garder = @{}
    $garder[$locales[0].Name] = $true                      # la plus recente, toujours
    $jours = @{}; $mois = @{}
    foreach ($d in $locales) {                             # ordre decroissant
        $jour = $d.Name.Substring(0, 10); $m = $d.Name.Substring(0, 7)
        if (-not $jours.ContainsKey($jour)) {
            $jours[$jour] = $true
            if ($jours.Count -le $GardeQuotidiennes) { $garder[$d.Name] = $true }
        }
        if (-not $mois.ContainsKey($m)) {
            $mois[$m] = $true
            if ($mois.Count -le $GardeMensuelles) { $garder[$d.Name] = $true }
        }
    }
    foreach ($d in $locales) {
        if ($garder.ContainsKey($d.Name)) { continue }
        # Garde-fou : on ne supprime que des dossiers de sauvegarde valides (SHA256SUMS present).
        if (-not (Test-Path -LiteralPath (Join-Path $d.FullName 'SHA256SUMS'))) {
            Write-Log "Retention : $($d.Name) sans SHA256SUMS, ignore" 'ALERTE'; continue
        }
        if ($SimulationSeulement) { Write-Log "[simulation] supprimerait $($d.Name)" }
        else { Remove-Item -LiteralPath $d.FullName -Recurse -Force; Write-Log "Retention : supprime $($d.Name)" }
    }
}

# ── 5. Fraicheur ──────────────────────────────────────────────────────────────
$locales = @(Get-ChildItem -LiteralPath $Destination -Directory -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -match $Motif } | Sort-Object Name -Descending)
$code = 0
if ($locales.Count -eq 0) {
    Write-Log 'ALERTE : AUCUNE sauvegarde locale sur le disque.' 'ALERTE'
    $code = 3
} else {
    $derniere = [datetime]::ParseExact($locales[0].Name, 'yyyy-MM-dd_HHmm', $null,
                    [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal)
    $ageH = [math]::Round(((Get-Date).ToUniversalTime() - $derniere).TotalHours, 1)
    if ($ageH -gt $AgeMaxHeures) {
        Write-Host ('=' * 70) -ForegroundColor Yellow
        Write-Log "ALERTE : la derniere sauvegarde locale ($($locales[0].Name) UTC) a $ageH h (> $AgeMaxHeures h). Verifier le cron du VPS." 'ALERTE'
        Write-Host ('=' * 70) -ForegroundColor Yellow
        $code = 3
    } else {
        Write-Log "Derniere sauvegarde locale : $($locales[0].Name) UTC ($ageH h)"
    }
}

if ($copieEchouee) { Write-Log 'Termine avec ECHEC de copie.' 'ERREUR'; exit 2 }
Write-Log "Termine ($($locales.Count) sauvegarde(s) locale(s))."
exit $code
