<#
.SYNOPSIS
    Richtet einen self-hosted GitHub-Actions-Runner für dieses Repository ein.

.DESCRIPTION
    Warum überhaupt: Acht der 21 Shops weisen GitHub-eigene Runner-IPs ab
    (fünf mit HTTP 429, drei mit 403). Das ist kein Rate-Limit, das sich
    aussitzen ließe — ein Testlauf hat 46 Minuten gewartet und exakt dasselbe
    geliefert. Von diesem Rechner aus antworten dieselben Shops normal.

    Der Runner läuft also von Ihrer gewohnten IP. Das umgeht keine
    Schutzmaßnahme: Es ist derselbe Zugriff, den Sie beim lokalen Lauf ohnehin
    machen, nur zeitgesteuert.

    Das Registrierungs-Token wird zur Laufzeit über die GitHub-CLI geholt und
    nirgends gespeichert. Es ist eine Stunde gültig.

.NOTES
    Für die Installation als Dienst sind Administratorrechte nötig. Ohne
    Adminrechte läuft der Runner interaktiv (Fenster muss offen bleiben).

    Windows blockiert das Ausführen von .ps1-Dateien standardmäßig
    ("running scripts is disabled on this system"). Der Aufruf umgeht das
    einmalig, ohne eine dauerhafte Einstellung zu ändern:

        powershell -ExecutionPolicy Bypass -File .\runner_einrichten.ps1 -AlsDienst

    (in einer als Administrator gestarteten PowerShell)
#>

param(
    [string]$Repo    = "Fortuenchen/ebike-deals",
    [string]$Ordner  = "$env:USERPROFILE\actions-runner",
    [string]$Name    = "$env:COMPUTERNAME-ebike",
    [switch]$AlsDienst,
    [switch]$AlsAufgabe,
    [switch]$Entfernen
)

$ErrorActionPreference = "Stop"

function Schritt($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }

# --- Abbau -----------------------------------------------------------------
if ($Entfernen) {
    Schritt "Runner entfernen"
    if (-not (Test-Path $Ordner)) { Write-Host "Nichts zu entfernen."; exit 0 }
    # Geplante Aufgabe entfernen, falls vorhanden.
    Unregister-ScheduledTask -TaskName "GitHubRunner-ebike" -Confirm:$false `
        -ErrorAction SilentlyContinue
    Push-Location $Ordner
    try {
        $token = (gh api -X POST "repos/$Repo/actions/runners/remove-token" --jq .token)
        # config.cmd remove meldet den Runner ab und deinstalliert den Dienst,
        # falls er als solcher lief.
        cmd /c "config.cmd remove --token $token"
        Write-Host "Runner abgemeldet." -ForegroundColor Green
    } finally { Pop-Location }
    exit 0
}

# --- Vorprüfungen ----------------------------------------------------------
Schritt "Vorprüfungen"

foreach ($werkzeug in @("gh", "git", "python")) {
    if (-not (Get-Command $werkzeug -ErrorAction SilentlyContinue)) {
        throw "$werkzeug wurde nicht gefunden. Bitte installieren und erneut versuchen."
    }
}
Write-Host "gh, git, python vorhanden."

gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Nicht bei GitHub angemeldet. Zuerst 'gh auth login' ausführen." }
Write-Host "GitHub-Anmeldung aktiv."

$istAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($AlsDienst -and -not $istAdmin) {
    throw "Installation als Dienst braucht Administratorrechte. PowerShell als Administrator starten, oder ohne -AlsDienst aufrufen."
}

# --- Runner herunterladen --------------------------------------------------
Schritt "Runner-Paket besorgen"

if (-not (Test-Path $Ordner)) { New-Item -ItemType Directory -Path $Ordner | Out-Null }
Set-Location $Ordner

if (-not (Test-Path ".\config.cmd")) {
    $version = (gh api repos/actions/runner/releases/latest --jq .tag_name).TrimStart("v")
    $datei   = "actions-runner-win-x64-$version.zip"
    $url     = "https://github.com/actions/runner/releases/download/v$version/$datei"
    Write-Host "Lade Version $version …"
    Invoke-WebRequest -Uri $url -OutFile $datei
    Expand-Archive -Path $datei -DestinationPath $Ordner -Force
    Remove-Item $datei
    Write-Host "Entpackt nach $Ordner"
} else {
    Write-Host "Runner-Paket bereits vorhanden."
}

# --- Registrieren ----------------------------------------------------------
Schritt "Beim Repository anmelden"

# Kurzlebiges Token, direkt aus der API - es wird nirgends abgelegt.
$token = (gh api -X POST "repos/$Repo/actions/runners/registration-token" --jq .token)
if (-not $token) { throw "Konnte kein Registrierungs-Token holen. Fehlt der 'repo'-Scope?" }

# --runasservice installiert den Windows-Dienst gleich bei der Konfiguration.
# Das ist der korrekte Windows-Weg - es gibt kein svc.cmd wie unter Linux.
$labels = "self-hosted,windows,ebike"
$dienstFlag = if ($AlsDienst) { " --runasservice" } else { "" }
cmd /c "config.cmd --unattended --url https://github.com/$Repo --token $token --name `"$Name`" --labels $labels --work _work --replace$dienstFlag"
if ($LASTEXITCODE -ne 0) { throw "Registrierung fehlgeschlagen." }
Write-Host "Runner '$Name' registriert." -ForegroundColor Green

# --- Dauerbetrieb einrichten -----------------------------------------------
if ($AlsDienst) {
    Schritt "Als Dienst"
    Write-Host "Dienst installiert und gestartet." -ForegroundColor Green
    Write-Host "ACHTUNG: Der Dienst läuft als Systemkonto und sieht Ihren PATH nicht -"
    Write-Host "Python, Git-Bash und Chromium müssen dann systemweit erreichbar sein."
    Write-Host "Wenn die Jobs 'python nicht gefunden' melden, stattdessen -AlsAufgabe nutzen."
}
elseif ($AlsAufgabe) {
    # Geplante Aufgabe beim Anmelden - läuft im Nutzerkontext (voller PATH),
    # überlebt Neustarts und braucht keine Adminrechte. Für diesen Rechner der
    # empfohlene Weg.
    Schritt "Als geplante Aufgabe (beim Anmelden)"
    $aufgabe = "GitHubRunner-ebike"
    $aktion  = New-ScheduledTaskAction -Execute "$Ordner\run.cmd"
    $ausloeser = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $einst = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $aufgabe -Action $aktion -Trigger $ausloeser `
        -Settings $einst -Description "Startet den GitHub-Actions-Runner für ebike-deals" `
        -Force | Out-Null
    Start-ScheduledTask -TaskName $aufgabe
    Write-Host "Aufgabe '$aufgabe' angelegt und gestartet." -ForegroundColor Green
    Write-Host "Der Runner startet künftig automatisch bei Ihrer Anmeldung."
    Write-Host "Entfernen:  Unregister-ScheduledTask -TaskName $aufgabe -Confirm:`$false"
}
else {
    Schritt "Fertig - Runner läuft noch nicht"
    Write-Host "Wählen Sie, wie der Runner dauerhaft laufen soll:"
    Write-Host "  Empfohlen (kein Admin):  .\runner_einrichten.ps1 -AlsAufgabe"
    Write-Host "  Als Dienst (Admin):      .\runner_einrichten.ps1 -AlsDienst"
    Write-Host "  Nur zum Testen jetzt:    cd `"$Ordner`"; .\run.cmd"
}

# --- Repository umschalten -------------------------------------------------
Schritt "Workflow auf den eigenen Runner umstellen"
gh variable set RUNNER_LABEL --repo $Repo --body "self-hosted"
Write-Host "Variable RUNNER_LABEL=self-hosted gesetzt." -ForegroundColor Green
Write-Host "`nDer tägliche Lauf nutzt ab sofort diesen Rechner."
Write-Host "Zurück auf GitHub-Runner:  gh variable set RUNNER_LABEL --repo $Repo --body ubuntu-latest"
