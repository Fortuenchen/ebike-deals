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
    # Ausweichzeit für -AlsAufgabe: Läuft der Rechner den ganzen Tag ohne
    # Neuanmeldung, stößt die Aufgabe den Lauf zu dieser Uhrzeit an. Beim
    # Hochfahren läuft sie ohnehin.
    [string]$Uhrzeit = "22:00",
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
    # Erzeugten Starter und Tagesmarke mit aufräumen.
    Remove-Item -Path (Join-Path $Ordner "lauf_einmal.ps1"), `
        (Join-Path $Ordner "letzter_lauf.txt") -ErrorAction SilentlyContinue
    # Einen noch laufenden Listener beenden, sonst kann config.cmd remove haken.
    Get-Process -Name "Runner.Listener" -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
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
# Nur konfigurieren, wenn der Runner es noch nicht ist. config.cmd bricht sonst
# mit "already configured" ab - und für eine geplante Aufgabe (-AlsAufgabe)
# braucht es gar keine Neukonfiguration, die startet nur das vorhandene run.cmd.
$konfiguriert = Test-Path "$Ordner\.runner"
if ($konfiguriert) {
    Schritt "Runner ist bereits angemeldet"
    Write-Host "Konfiguration übersprungen."
    if ($AlsDienst) {
        Write-Host "Hinweis: -AlsDienst richtet den Dienst bei der Konfiguration ein." -ForegroundColor Yellow
        Write-Host "Dafür zuerst abmelden:  .\runner_einrichten.ps1 -Entfernen" -ForegroundColor Yellow
        Write-Host "und danach erneut mit -AlsDienst." -ForegroundColor Yellow
    }
} else {
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
}

# --- Dauerbetrieb einrichten -----------------------------------------------
if ($AlsDienst) {
    Schritt "Als Dienst"
    Write-Host "Dienst installiert und gestartet." -ForegroundColor Green
    Write-Host "ACHTUNG: Der Dienst läuft als Systemkonto und sieht Ihren PATH nicht -"
    Write-Host "Python, Git-Bash und Chromium müssen dann systemweit erreichbar sein."
    Write-Host "Wenn die Jobs 'python nicht gefunden' melden, stattdessen -AlsAufgabe nutzen."
}
elseif ($AlsAufgabe) {
    # Geplante Aufgabe im Nutzerkontext (voller PATH, gh-Anmeldung, Chromium),
    # ohne Adminrechte. Statt eines Dauer-Listeners stößt sie den Lauf an und
    # lässt den Runner genau einen Job abarbeiten - danach geht er aus
    # (run.cmd --once). Für diesen Rechner der empfohlene Weg.
    Schritt "Als geplante Aufgabe (Lauf-einmal beim Hochfahren)"

    try { $zeit = [datetime]::ParseExact($Uhrzeit, 'HH:mm', $null) }
    catch { throw "Uhrzeit '$Uhrzeit' nicht im Format HH:mm (z. B. 22:00)." }

    # Kleiner Starter, den die Aufgabe aufruft. Eine Tagesmarke
    # (letzter_lauf.txt) hält es bei einem Lauf pro Kalendertag - der
    # Start-Auslöser feuert sonst bei jeder Anmeldung erneut.
    $wrapper = Join-Path $Ordner "lauf_einmal.ps1"
    $vorlage = @'
# Automatisch erzeugt von runner_einrichten.ps1 - nicht von Hand aendern.
# Stoesst den taeglichen ebike-deals-Lauf an und laesst den self-hosted Runner
# genau einen Job abarbeiten; danach beendet er sich. Hoechstens ein Lauf/Tag.
# (Bewusst ohne Umlaute: powershell -File liest .ps1 je nach Codepage sonst falsch.)
$ErrorActionPreference = "Stop"
$Repo   = "__REPO__"
$Ordner = "__ORDNER__"
$Marke  = Join-Path $Ordner "letzter_lauf.txt"
$heute  = (Get-Date).ToString("yyyy-MM-dd")

if ((Test-Path $Marke) -and ((Get-Content $Marke -Raw).Trim() -eq $heute)) {
    Write-Host "Heute ($heute) bereits gelaufen - nichts zu tun."
    exit 0
}

# Lauf auf GitHub anstossen (nutzt die vorhandene gh-Anmeldung).
gh workflow run taeglich.yml --repo $Repo
if ($LASTEXITCODE -ne 0) {
    Write-Host "Konnte den Lauf nicht anstossen - naechster Trigger versucht es erneut."
    exit 1
}

# Genau einen Job abarbeiten, dann beenden. run.cmd kehrt erst zurueck, wenn der
# Job fertig ist. Haengt es (kein Job), beendet das Zeitlimit der Aufgabe den
# ganzen Prozessbaum - dann bleibt die Tagesmarke ungesetzt und morgen erneut.
Set-Location $Ordner
& (Join-Path $Ordner "run.cmd") --once

Set-Content -Path $Marke -Value $heute
Write-Host "Lauf fuer $heute erledigt, Runner ist beendet."
'@
    $inhalt = $vorlage.Replace('__REPO__', $Repo).Replace('__ORDNER__', $Ordner)
    Set-Content -Path $wrapper -Value $inhalt -Encoding UTF8

    $aufgabe = "GitHubRunner-ebike"
    $aktion = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$wrapper`""
    # Zwei Auslöser: beim Anmelden (Hochfahren) und - falls der Rechner den Tag
    # über durchläuft - ersatzweise zur festen Uhrzeit.
    $beimStart = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $ersatz    = New-ScheduledTaskTrigger -Daily -At $zeit
    # ExecutionTimeLimit ist das Sicherheitsnetz: Wartet run.cmd auf einen Job,
    # der nie kommt, bricht die Aufgabe nach zwei Stunden den ganzen Baum ab -
    # kein hängender Listener. StartWhenAvailable holt einen verpassten
    # Ausweichlauf (Rechner war aus) beim nächsten Einschalten nach.
    $einst = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName $aufgabe -Action $aktion `
        -Trigger @($beimStart, $ersatz) -Settings $einst `
        -Description "Stößt den täglichen ebike-deals-Lauf an; der Runner beendet sich nach dem Job" `
        -Force | Out-Null

    Write-Host "Aufgabe '$aufgabe' angelegt." -ForegroundColor Green
    Write-Host "Sie läuft beim Hochfahren (und ersatzweise täglich um $Uhrzeit),"
    Write-Host "stößt den Lauf an und beendet den Runner nach dem Job - höchstens 1x pro Tag."
    Write-Host "Nicht sofort gestartet; der nächste Start bzw. $Uhrzeit übernimmt."
    Write-Host "Sofort testen:  powershell -ExecutionPolicy Bypass -File `"$wrapper`""
    Write-Host "Entfernen:      .\runner_einrichten.ps1 -Entfernen"
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
