<#
.SYNOPSIS
  Rapatrie les sauvegardes HayaFlash du VPS vers le disque D: (PC Windows), CHIFFREES avec age.

.DESCRIPTION
  PowerShell 5.1+, OpenSSH Windows integre (ssh.exe / scp.exe), tar.exe (Windows 10+)
  et age.exe (winget install FiloSottile.age).

  Pour chaque dossier de sauvegarde distant (AAAA-MM-JJ_HHMM) ABSENT sur D: (fichier
  <nom>.tar.age) :
    1. copie par scp dans un dossier temporaire du DISQUE SYSTEME (jamais sur D:) ;
    2. verifie les empreintes avec SHA256SUMS ;
    3. cree une archive tar puis la chiffre avec age (destinataire = cle PUBLIQUE age) ;
    4. ecrit le resultat chiffre sur D: sous ".tmp-<nom>.tar.age" puis le renomme en
       "<nom>.tar.age" : une sauvegarde partielle n'est jamais visible sous son nom
       definitif ;
    5. supprime les fichiers en clair du dossier temporaire, succes ou echec.
  AUCUNE copie en clair ne reste sur D:. Les sauvegardes du VPS restent en clair sur le VPS
  (restore_test.sh en a besoin). Pour dechiffrer : decrypt_backup.ps1.

  Retention locale : 30 quotidiennes + 12 mensuelles (la derniere de chaque mois),
  configurable. AUCUNE suppression si la copie du jour a echoue.
  Journal : <racine du disque>\Sauvegardes\HayaFlash\pull.log (dossier parent de la destination).
  Alerte bien visible si la derniere sauvegarde locale a plus de 48 h.

  Code de sortie : 0 = succes ; 1 = disque absent / non inscriptible / prerequis manquant
  (age, tar, ssh, cle) ; 2 = echec de copie, de verification ou de chiffrement ;
  3 = succes mais derniere sauvegarde locale trop vieille.

.PARAMETER HoteSsh        Utilisateur@hote du VPS.
.PARAMETER DossierDistant Dossier des sauvegardes sur le VPS.
.PARAMETER Destination    Dossier local de destination (sur D:) : ne contient que des .tar.age.
.PARAMETER CleSsh         Cle privee SSH dediee a ce transfert.
.PARAMETER CleAge         Destinataire age : cle PUBLIQUE (age1...) OU chemin d'un fichier de
                          destinataires. Jamais la cle privee. Defaut : variable d'environnement
                          HAYAFLASH_AGE_RECIPIENT.
.PARAMETER DossierTemp    Dossier de travail en clair, sur le disque systeme (defaut
                          %LOCALAPPDATA%\HayaFlash\tmp-backups).
.PARAMETER GardeQuotidiennes  Nombre de jours conserves (defaut 30).
.PARAMETER GardeMensuelles    Nombre de mois conserves (defaut 12).
.PARAMETER AgeMaxHeures   Seuil de l'alerte de fraicheur (defaut 48).
.PARAMETER SimulationSeulement  Affiche ce qui serait fait, sans copier ni supprimer.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\pull_backups.ps1 -CleAge age1xxxxxxxx
#>
[CmdletBinding()]
param(
    [string]$HoteSsh        = 'sam@31.207.39.116',
    [string]$DossierDistant = '/srv/backups/hayaflash-prod',
    [string]$Destination    = 'D:\Sauvegardes\HayaFlash\hayaflash-prod',
    [string]$CleSsh         = (Join-Path $env:USERPROFILE '.ssh\hayaflash_backup_ed25519'),
    [string]$CleAge         = $env:HAYAFLASH_AGE_RECIPIENT,
    [string]$DossierTemp    = (Join-Path $env:LOCALAPPDATA 'HayaFlash\tmp-backups'),
    [int]$GardeQuotidiennes = 30,
    [int]$GardeMensuelles   = 12,
    [int]$AgeMaxHeures      = 48,
    [switch]$SimulationSeulement
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Racine   = Split-Path -Parent $Destination         # D:\Sauvegardes\HayaFlash
$Journal  = Join-Path $Racine 'pull.log'
$Motif    = '^\d{4}-\d{2}-\d{2}_\d{4}$'
$MotifAge = '^(\d{4}-\d{2}-\d{2}_\d{4})\.tar\.age$'

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

# Appel d'un executable natif : en PowerShell 5.1, "2>&1" transforme chaque ligne de
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

# Noms (AAAA-MM-JJ_HHMM) des sauvegardes chiffrees presentes sur la destination.
function Get-LocalesAge {
    $noms = @()
    foreach ($f in @(Get-ChildItem -LiteralPath $Destination -File -ErrorAction SilentlyContinue)) {
        if ($f.Name -match $MotifAge) { $noms += $Matches[1] }
    }
    return $noms
}

# ── 0. Prerequis ──────────────────────────────────────────────────────────────
foreach ($exe in 'ssh.exe', 'scp.exe', 'tar.exe') {
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
        Stop-Script "$exe introuvable : activer la fonctionnalite Windows 'Client OpenSSH' (ssh/scp) ; tar.exe est fourni par Windows 10 1803+." 1
    }
}
if (-not (Get-Command 'age.exe' -ErrorAction SilentlyContinue)) {
    Stop-Script "age.exe introuvable : l'installer avec 'winget install FiloSottile.age' puis rouvrir PowerShell." 1
}
if (-not (Test-Path -LiteralPath $CleSsh)) {
    Stop-Script "Cle SSH introuvable : $CleSsh (voir docs/SAUVEGARDES.md pour la creer)." 1
}
if ([string]::IsNullOrWhiteSpace($CleAge)) {
    Stop-Script 'Destinataire age manquant : passer -CleAge age1... (cle PUBLIQUE) ou definir HAYAFLASH_AGE_RECIPIENT.' 1
}
if ($CleAge -match 'AGE-SECRET-KEY') {
    Stop-Script 'Une cle PRIVEE a ete fournie : donner la cle PUBLIQUE uniquement.' 1
}
$optionAge = @()
if (Test-Path -LiteralPath $CleAge) { $optionAge = @('-R', $CleAge) }
elseif ($CleAge -match '^age1[0-9a-z]{50,}$') { $optionAge = @('-r', $CleAge) }
else { Stop-Script "-CleAge n'est ni une cle publique age (age1...) ni un fichier existant." 1 }

# ── 1. Disque D: present et inscriptible ──────────────────────────────────────
$lecteur = Split-Path -Qualifier $Destination        # "D:"
if (-not (Test-Path -LiteralPath "$lecteur\")) {
    Stop-Script "Le disque $lecteur est absent : brancher le disque puis relancer." 1
}
# Le dossier de travail en clair ne doit jamais etre sur le disque des sauvegardes.
if ((Split-Path -Qualifier $DossierTemp) -ieq $lecteur) {
    Stop-Script "DossierTemp ($DossierTemp) est sur $lecteur : choisir un dossier du disque systeme (aucune copie en clair sur $lecteur)." 1
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

Write-Log "Debut : $HoteSsh`:$DossierDistant -> $Destination (chiffre avec age)"
$res = Invoke-Native 'ssh.exe' ($optionsSsh + @($HoteSsh, "ls -1 '$DossierDistant'"))
if ($res.Code -ne 0) {
    Stop-Script "Liste distante impossible (code $($res.Code)) : $($res.Sortie -join ' ')" 2
}
$distants = @($res.Sortie | ForEach-Object { "$_".Trim() } | Where-Object { $_ -match $Motif } | Sort-Object)
Write-Log "$($distants.Count) sauvegarde(s) sur le VPS"

# ── 3. Copie, verification, chiffrement ──────────────────────────────────────
$copieEchouee = $false
$locales = @(Get-LocalesAge)
$manquantes = @($distants | Where-Object { $locales -notcontains $_ })
Write-Log "$($manquantes.Count) a copier"

# Anciennes sauvegardes EN CLAIR laissees par une version precedente du script : on ne
# supprime rien, on previent (a supprimer a la main apres verification des .tar.age).
$enClair = @(Get-ChildItem -LiteralPath $Destination -Directory -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -match $Motif })
if ($enClair.Count -gt 0) {
    Write-Log "ALERTE : $($enClair.Count) dossier(s) de sauvegarde EN CLAIR sur $lecteur (ex. $($enClair[0].Name)) : a supprimer apres avoir verifie les .tar.age." 'ALERTE'
}

# Nettoyage des restes d'un transfert interrompu (temporaires seulement).
Get-ChildItem -LiteralPath $Destination -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like '.tmp-*' } | ForEach-Object {
    if ($SimulationSeulement) { Write-Log "[simulation] suppression du reste $($_.Name)" }
    else { Remove-Item -LiteralPath $_.FullName -Recurse -Force; Write-Log "Reste d'un transfert interrompu supprime : $($_.Name)" }
}
if ((Test-Path -LiteralPath $DossierTemp) -and -not $SimulationSeulement) {
    Get-ChildItem -LiteralPath $DossierTemp -Force -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

foreach ($nom in $manquantes) {
    $travail = Join-Path $DossierTemp $nom                 # dossier en clair, disque systeme
    $tar     = Join-Path $DossierTemp "$nom.tar"
    $tmpAge  = Join-Path $Destination ".tmp-$nom.tar.age"
    if ($SimulationSeulement) { Write-Log "[simulation] copierait puis chiffrerait $nom"; continue }
    try {
        New-Item -ItemType Directory -Path $travail -Force | Out-Null
        # Fichiers un par un : evite les ambiguites de scp -r et de chemins.
        foreach ($f in 'db.dump', 'media.tar.gz', 'backup.info', 'SHA256SUMS') {
            $r = Invoke-Native 'scp.exe' ($optionsSsh + @("$HoteSsh`:$DossierDistant/$nom/$f", (Join-Path $travail $f)))
            if ($r.Code -ne 0) { throw "scp de $f a echoue (code $($r.Code)) : $($r.Sortie -join ' ')" }
        }
        # Verification SHA256 d'apres SHA256SUMS (format "<hash>  <fichier>", sortie de sha256sum).
        $lignes = Get-Content -LiteralPath (Join-Path $travail 'SHA256SUMS') | Where-Object { $_.Trim() }
        if (-not $lignes) { throw 'SHA256SUMS vide' }
        foreach ($l in $lignes) {
            if ($l -notmatch '^([0-9a-fA-F]{64})\s+\*?(.+)$') { throw "ligne SHA256SUMS illisible : $l" }
            $attendu = $Matches[1].ToLower(); $fichier = $Matches[2].Trim()
            if ($fichier -match '[\\/]') { throw "nom de fichier suspect dans SHA256SUMS : $fichier" }
            $reel = (Get-FileHash -LiteralPath (Join-Path $travail $fichier) -Algorithm SHA256).Hash.ToLower()
            if ($reel -ne $attendu) { throw "empreinte invalide pour $fichier" }
        }
        # Archive puis chiffrement : le fichier chiffre est ecrit sur D: sous un nom temporaire.
        $t = Invoke-Native 'tar.exe' @('-cf', $tar, '-C', $DossierTemp, $nom)
        if ($t.Code -ne 0) { throw "tar a echoue (code $($t.Code)) : $($t.Sortie -join ' ')" }
        $a = Invoke-Native 'age.exe' ($optionAge + @('-o', $tmpAge, $tar))
        if ($a.Code -ne 0) { throw "age a echoue (code $($a.Code)) : $($a.Sortie -join ' ')" }
        if ((Get-Item -LiteralPath $tmpAge).Length -le 0) { throw 'fichier chiffre vide' }
        Rename-Item -LiteralPath $tmpAge -NewName "$nom.tar.age"   # visible seulement une fois complet
        Write-Log "Copie verifiee et chiffree : $nom.tar.age"
    } catch {
        $copieEchouee = $true
        Write-Log "Echec pour $nom : $($_.Exception.Message)" 'ERREUR'
        if (Test-Path -LiteralPath $tmpAge) { Remove-Item -LiteralPath $tmpAge -Force -ErrorAction SilentlyContinue }
    } finally {
        # Aucune copie en clair ne doit survivre, succes ou echec.
        Remove-Item -LiteralPath $travail -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tar -Force -ErrorAction SilentlyContinue
    }
}

# ── 4. Retention locale (jamais si une copie a echoue) ────────────────────────
$locales = @(Get-LocalesAge | Sort-Object -Descending)
if ($copieEchouee) {
    Write-Log 'Retention SAUTEE : une copie a echoue, aucune sauvegarde locale ne sera supprimee.' 'ALERTE'
} elseif ($locales.Count -gt 0) {
    $garder = @{}
    $garder[$locales[0]] = $true                           # la plus recente, toujours
    $jours = @{}; $mois = @{}
    foreach ($n in $locales) {                             # ordre decroissant
        $jour = $n.Substring(0, 10); $m = $n.Substring(0, 7)
        if (-not $jours.ContainsKey($jour)) {
            $jours[$jour] = $true
            if ($jours.Count -le $GardeQuotidiennes) { $garder[$n] = $true }
        }
        if (-not $mois.ContainsKey($m)) {
            $mois[$m] = $true
            if ($mois.Count -le $GardeMensuelles) { $garder[$n] = $true }
        }
    }
    foreach ($n in $locales) {
        if ($garder.ContainsKey($n)) { continue }
        $chemin = Join-Path $Destination "$n.tar.age"
        if ($SimulationSeulement) { Write-Log "[simulation] supprimerait $n.tar.age" }
        else { Remove-Item -LiteralPath $chemin -Force; Write-Log "Retention : supprime $n.tar.age" }
    }
}

# ── 5. Fraicheur ──────────────────────────────────────────────────────────────
$locales = @(Get-LocalesAge | Sort-Object -Descending)
$code = 0
if ($locales.Count -eq 0) {
    Write-Log "ALERTE : AUCUNE sauvegarde chiffree sur le disque." 'ALERTE'
    $code = 3
} else {
    $derniere = [datetime]::ParseExact($locales[0], 'yyyy-MM-dd_HHmm', $null,
                    [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal)
    $ageH = [math]::Round(((Get-Date).ToUniversalTime() - $derniere).TotalHours, 1)
    if ($ageH -gt $AgeMaxHeures) {
        Write-Host ('=' * 70) -ForegroundColor Yellow
        Write-Log "ALERTE : la derniere sauvegarde locale ($($locales[0]) UTC) a $ageH h (> $AgeMaxHeures h). Verifier le cron du VPS." 'ALERTE'
        Write-Host ('=' * 70) -ForegroundColor Yellow
        $code = 3
    } else {
        Write-Log "Derniere sauvegarde locale : $($locales[0]) UTC ($ageH h)"
    }
}

if ($copieEchouee) { Write-Log 'Termine avec ECHEC de copie.' 'ERREUR'; exit 2 }
Write-Log "Termine ($($locales.Count) sauvegarde(s) chiffree(s) locale(s))."
exit $code
