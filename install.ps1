<#
.SYNOPSIS
    GClaude Indexer installer (Phase 11, section 11.2; Phase 13, Task 13).

.DESCRIPTION
    Prepares this machine's environment: creates the local Python virtual
    environment (never inside the Drive-synced folder — section 11.1),
    installs the dependencies from `requirements.txt` (only reinstalling
    when the file changes), installs Tesseract and Ghostscript when missing
    (with confirmation) and offers to install Ollama and download the
    default model (asked separately, since they are large downloads).

    Phase 15, Task 4 removed the last manual step: **it installs Python
    3.12 itself.** Until then this script detected that the required
    version was missing and printed a winget command for the user to run by
    hand — which is not what running an installer is for. It now installs
    the pinned 3.12.10 (winget in user scope first, the hash-checked
    python.org installer as the fallback), side by side with whatever
    Python the machine already had, and carries on to create the virtual
    environment in the same run. Doing that correctly needs one thing this
    script did not do before: a process cannot see a PATH written after it
    started, so the interpreter is looked for again through the registry
    and the default install folders, not only through PATH. See section 1.

    Phase 15, Task 2 closed the two holes that stopped a freshly cloned
    repository from producing a working machine:

    * **Ghostscript no longer depends on winget.** The winget index no
      longer carries `ArtifexSoftware.GhostScript` under any id, so on a
      clean machine the old winget-only path could not install Ghostscript
      at all — and without `gswin64c` on PATH `ocrmypdf` refuses to run.
      winget is still tried first (it is the cheapest path when the package
      comes back); when it does not deliver the binary, the official
      Artifex build is downloaded from the pinned GitHub release and its
      SHA-256 is checked against the value pinned below.

      Phase 15, Task 5 then changed what happens to that file. It used to
      be *run*, with the NSIS flag `/S`, elevated, into `C:\Program Files`
      — and that cannot be done unattended: the flag no longer silences
      this build, which stops on a "Finish" page waiting for a click, and
      the manifest asks for an administrator whatever the destination is.
      It is now *unpacked* into `%LOCALAPPDATA%\GClaudeIndexer\gs`, where
      the virtual environment and the catalogue already live — no
      administrator, no window, no click, and `gswin64c` answering three
      seconds later. Running the installer survives as the fallback, and
      there it waits for the binary to answer rather than for the process
      to end, then closes the window itself. See section 4b.

    * **The OCR language is actually installed.** `winget`'s Tesseract
      package (and the UB-Mannheim installer behind it) ships `eng` and
      `osd` and nothing else, while this project's default is
      `ocr_language = "por"`. Every scanned PDF therefore failed with
      "OCR engine does not have language data for: por". The installer now
      reads the language the project is configured for, and installs any
      missing `.traineddata` from the pinned `tessdata_fast` commit —
      SHA-256 checked — straight into Tesseract's own `tessdata` folder
      (elevated when that folder is not writable). See the block itself for
      why `TESSDATA_PREFIX` was rejected.

    It then examines the machine's own hardware and does three things with
    what it finds:

    * Reports every GPU and says what Ollama actually needs for it, which
      on current hardware is nothing at all — CUDA ships inside Ollama for
      NVIDIA, and everything else (Intel, and the AMD cards outside
      Ollama's short Windows ROCm list) is served by the Vulkan backend the
      vendor driver already provides. It installs no CUDA, no ROCm, and
      never changes Ollama's runtime.

    * Verifies the claim instead of asserting it: with Ollama installed and
      a model downloaded, it loads the model and reads the PROCESSOR column
      of `ollama ps`. "100% GPU" is the answer we want, and it is printed
      on screen either way. Only when the answer is *not* GPU does it point
      at the community route for older AMD cards — as links to read, never
      as a third-party binary downloaded on the user's behalf.

    * Removes `HSA_OVERRIDE_GFX_VERSION` instead of writing it. Measured on
      an RX 5700 XT with Ollama 0.33.2: the runtime picks Vulkan, ROCm is
      never attempted, and the variable is inert — while two contradictory
      values (10.3.0 in the user scope, 10.1.0 in the machine scope) had
      accumulated from earlier versions of this script. The user-scope one
      is deleted outright; the machine-scope one needs elevation, and if
      that is refused the exact command is printed rather than the failure
      being swallowed.

    It also downloads and installs the seven sensor libraries that
    `gclaude_indexer.sensors` needs to read temperature, power draw and
    clocks (LibreHardwareMonitorLib plus its .NET Framework shims), from
    nuget.org into `%LOCALAPPDATA%\GClaudeIndexer\lib`. Versions are pinned
    and every file is checked against a pinned SHA-256: a file whose hash
    does not match is deleted and never installed. Sensors are optional, so
    a download failure only warns — it never aborts the installation.

    At the end, it offers to create a desktop shortcut to `Indexer.bat`,
    and then offers a second, optional one for the CPU sensor (Phase 15,
    Task 3). CPU temperature and power draw are the one reading that needs
    administrator rights, so the second shortcut passes `--cpu-sensor`,
    which makes the (still unprivileged) server start one small elevated
    child process that does nothing but read the sensors. The ordinary
    shortcut is unchanged and asks for nothing. Both obey -NoShortcut.

    Every download in this script obeys the same three rules as the sensor
    libraries: an exact pinned version (never "latest"), a URL checked
    against its expected prefix before the request is made, and a pinned
    SHA-256 that decides whether the file is installed or deleted. A
    download that fails degrades with a warning and never aborts the
    installation.

    Never installs anything without the user's confirmation, except with
    -AutoInstall.

    No PyInstaller — this only prepares the environment to run with
    `Indexer.bat` (or `launcher.py`). Can be run as many times as you like:
    idempotent (whatever is already present is neither reinstalled nor
    asked about again).

.PARAMETER NoShortcut
    Do not create the desktop shortcut at the end. Covers both of them —
    the ordinary one and the optional CPU-sensor one.

.PARAMETER CpuSensorShortcut
    Create the "GClaude Indexer (CPU sensor)" shortcut without asking.
    Exists so an unattended install can still opt in explicitly, because
    -AutoInstall on its own does *not* create it: everything else
    -AutoInstall says yes to is a one-off download, while this one arms a
    Windows administrator prompt on every launch from then on. That is not
    a decision to make on a user's behalf while they are away from the
    machine.

.PARAMETER AutoInstall
    Installs everything that is missing without asking (unattended
    install) — including Ollama and the default model. Use with care: the
    Ollama and model downloads can be large.

.PARAMETER OcrLanguage
    Tesseract language(s) to make sure are installed, in Tesseract's own
    syntax (`por`, or `por+eng` for more than one). Defaults to the value
    the project itself is configured with — `ProjectConfig.ocr_language` —
    so the machine ends up able to read exactly what the software will ask
    it to read. Only languages with a SHA-256 pinned in this script can be
    installed; anything else is reported, with instructions, and skipped.

.PARAMETER SkipGpuCheck
    Skip the end-of-install GPU verification. That check loads the default
    Ollama model into memory to read the PROCESSOR column of `ollama ps`,
    which on a large model costs a few seconds and a few GB of RAM/VRAM.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1 -AutoInstall

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1 -OcrLanguage por+eng
#>

param(
    [switch]$NoShortcut,
    [switch]$CpuSensorShortcut,
    [switch]$AutoInstall,
    [string]$OcrLanguage = "",
    [switch]$SkipGpuCheck
)

$ErrorActionPreference = "Stop"

function Invoke-NativeCommand {
    <#
    .SYNOPSIS
        Runs a scriptblock that calls an external .exe, without letting a
        line of its stderr kill the installer.

    .DESCRIPTION
        `$ErrorActionPreference = "Stop"` above is right for cmdlets, and
        actively wrong for external programs. Under "Stop", *any* line an
        .exe writes to stderr becomes a NativeCommandError that PowerShell
        treats as terminating — so a program that merely reports something
        and exits non-zero does not return a value we can test, it ends the
        script where it stands.

        Two real failures on the clean-machine test of Phase 15 came from
        exactly this, and neither had anything wrong with its own logic:

          * `py -3.12` on a machine with no 3.12 writes "No suitable Python
            runtime found" and exits 1. The installer died at that line,
            never printing the "install it with winget" guidance ten lines
            below that was written for precisely that case.
          * `ollama list` seconds after Ollama is installed, before its
            service has finished coming up, writes a connection error. The
            installer died there too — after installing Python, the venv,
            every dependency, Tesseract, Ghostscript and Ollama, and before
            the hardware analysis, the sensor libraries and the desktop
            shortcut. A from-zero install could not finish.

        Note that `2>$null` does not prevent this: it redirects the text
        after the error has already been raised. Lowering the preference
        for the duration of the call is what actually prevents it, and the
        `finally` puts it back so cmdlet errors keep stopping the script.

        Callers keep reading `$LASTEXITCODE` exactly as before — a program
        that fails goes back to being a value to test, not an accident.
    #>
    param(
        [Parameter(Mandatory)][scriptblock]$Body
    )
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Body
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

# --- Shared helpers ---------------------------------------------------------
#
# Defined here, before anything runs, because PowerShell resolves a function
# at the moment of the call: a helper used by section 4 cannot live in
# section 4d. `Test-FileMatchesHash` was originally written for the sensor
# DLLs and now also decides whether a Ghostscript installer and a Tesseract
# language file are installed or deleted — one implementation, three callers.

function Test-IsElevated {
    <#
    .SYNOPSIS
        $true when this process is already running with an elevated token.
    #>
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Test-FileMatchesHash {
    <#
    .SYNOPSIS
        $true when the file exists and its SHA-256 equals $ExpectedSha256.

    .DESCRIPTION
        Named for the question it answers, not for the cmdlet it calls:
        `Get-FileHash` is PowerShell's own and must not be shadowed.
    #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$ExpectedSha256
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    return $actual.ToLower() -eq $ExpectedSha256.ToLower()
}

function Start-ProcessElevated {
    <#
    .SYNOPSIS
        Runs a program with an administrator token and waits for it.

    .DESCRIPTION
        Tesseract's language files live in
        `C:\Program Files\Tesseract-OCR\tessdata`, a folder only an
        administrator can write; Ghostscript's own installer asks for an
        administrator too, though since Task 5 that is only the fallback —
        the normal route unpacks it into `%LOCALAPPDATA%` and never comes
        anywhere near this function. Rather than relaunching
        the whole installation elevated — which would run the venv, pip and
        the desktop shortcut as another user and leave files the real user
        cannot manage — only the two operations that need it are elevated,
        one child process each.

        Never throws. When the elevation is refused (the user says No to
        the UAC prompt, or policy forbids it) `Start-Process` raises a
        Win32Exception; that is caught and reported as `Elevated = $false`,
        so the caller can print the manual command instead of dying. A
        refused elevation is a decision, not a crash.

        Already elevated? Then no second token is needed and the program
        runs in this console, where its output is visible.
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [int]$TimeoutSeconds = 900
    )

    $startArguments = @{ FilePath = $FilePath; PassThru = $true; ErrorAction = "Stop" }
    if ($ArgumentList.Count -gt 0) { $startArguments["ArgumentList"] = $ArgumentList }
    if (Test-IsElevated) {
        $startArguments["NoNewWindow"] = $true
    } else {
        $startArguments["Verb"] = "RunAs"
    }

    try {
        $process = Start-Process @startArguments
    } catch {
        return [pscustomobject]@{ Elevated = $false; ExitCode = $null; Detail = $_.Exception.Message }
    }

    # Reading `.Handle` once, here, keeps the process handle open — and
    # that is what makes `$process.ExitCode` readable after the program
    # ends. Without it Windows PowerShell hands back a Process object
    # whose ExitCode is `$null` for ever (measured), and every
    # "returned code N" warning built on it is dead code. It can fail
    # for a process running with a token this one cannot open, which is
    # no worse than the situation it is trying to improve.
    try { $null = $process.Handle } catch { }

    # -Wait is not used: it gives no way to bound the wait, and an installer
    # that hangs would hang the whole script with it.
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        try { $process.Kill() } catch { }
        return [pscustomobject]@{
            Elevated = $true; ExitCode = $null
            Detail = "did not finish within $TimeoutSeconds s and was terminated"
        }
    }

    return [pscustomobject]@{ Elevated = $true; ExitCode = $process.ExitCode; Detail = $null }
}

function Start-QuietProcess {
    <#
    .SYNOPSIS
        Runs a program with this process's own token, invisibly, and waits
        for it. Returns the same shape as Start-ProcessElevated.

    .DESCRIPTION
        The counterpart of Start-ProcessElevated, for the installers that
        need no administrator at all — the python.org bundle installing
        into `%LOCALAPPDATA%` is the one that exists today. Keeping the two
        symmetrical means the caller reads one result shape either way.

        `-NoNewWindow` is not only about the window: it makes PowerShell
        launch the process with UseShellExecute = $false, so a freshly
        downloaded .exe cannot raise the "Open File - Security Warning"
        dialog that the shell shows for a file it considers to come from
        the internet. An unattended install must not stop on a dialog.

        Never throws, for the same reason Start-ProcessElevated does not:
        a program that will not start is a value to test, not a crash.
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [int]$TimeoutSeconds = 900
    )

    $startArguments = @{
        FilePath = $FilePath; PassThru = $true; ErrorAction = "Stop"; NoNewWindow = $true
    }
    if ($ArgumentList.Count -gt 0) { $startArguments["ArgumentList"] = $ArgumentList }

    try {
        $process = Start-Process @startArguments
    } catch {
        return [pscustomobject]@{ Started = $false; ExitCode = $null; Detail = $_.Exception.Message }
    }

    # Reading `.Handle` once, here, keeps the process handle open — and
    # that is what makes `$process.ExitCode` readable after the program
    # ends. Without it Windows PowerShell hands back a Process object
    # whose ExitCode is `$null` for ever (measured), and every
    # "returned code N" warning built on it is dead code. It can fail
    # for a process running with a token this one cannot open, which is
    # no worse than the situation it is trying to improve.
    try { $null = $process.Handle } catch { }

    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        try { $process.Kill() } catch { }
        return [pscustomobject]@{
            Started = $true; ExitCode = $null
            Detail = "did not finish within $TimeoutSeconds s and was terminated"
        }
    }

    return [pscustomobject]@{ Started = $true; ExitCode = $process.ExitCode; Detail = $null }
}

function Invoke-ElevatedScript {
    <#
    .SYNOPSIS
        Runs a block of PowerShell with an administrator token.

    .DESCRIPTION
        Written to a temporary .ps1 and launched with `-File` rather than
        passed on the command line with `-Command`: a path handed to a
        child process through `-Command` goes through two more rounds of
        quoting, and a folder name with a space or an apostrophe in it —
        `C:\Program Files`, for one — is exactly where that breaks. The
        file is deleted afterwards whatever happens.
    #>
    param(
        [Parameter(Mandatory)][string]$Script,
        [int]$TimeoutSeconds = 300
    )

    $scriptPath = Join-Path ([System.IO.Path]::GetTempPath()) ("GClaudeIndexer-elevated-{0}.ps1" -f ([guid]::NewGuid().ToString("N")))
    try {
        Set-Content -LiteralPath $scriptPath -Value $Script -Encoding utf8
        return Start-ProcessElevated -FilePath "powershell.exe" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $scriptPath) `
            -TimeoutSeconds $TimeoutSeconds
    } finally {
        Remove-Item -LiteralPath $scriptPath -Force -ErrorAction SilentlyContinue
    }
}

function Update-SessionPath {
    <#
    .SYNOPSIS
        Brings PATH entries written by an installer into this session.

    .DESCRIPTION
        An installer that appends to the machine or user PATH writes the
        registry; a process that is already running keeps the PATH it was
        born with. That is why the old script reported "not found after
        installation (you may need to open a new terminal)" for something
        it had just installed correctly. Re-reading both scopes and
        appending whatever is new lets the checks a few lines later see the
        binary that actually exists.

        Appends rather than replaces: anything this session added to its own
        PATH stays.
    #>
    $known = @($env:Path -split ';' | Where-Object { $_ })
    foreach ($scope in @("Machine", "User")) {
        $stored = [Environment]::GetEnvironmentVariable("Path", $scope)
        if (-not $stored) { continue }
        foreach ($entry in ($stored -split ';')) {
            if ($entry -and ($known -notcontains $entry)) {
                $known += $entry
                $env:Path = $env:Path.TrimEnd(';') + ';' + $entry
            }
        }
    }
}

function Publish-EnvironmentChange {
    <#
    .SYNOPSIS
        Tells the rest of Windows that the environment changed.

    .DESCRIPTION
        A PATH written to the registry is not seen by programs that are
        already running — Explorer included, and Explorer is what every
        console the user opens next inherits its environment from. Without
        this broadcast the folder added below would only take effect at the
        next sign-in, which is exactly the "open a new terminal and it still
        does not work" the rest of this script exists to avoid.

        Best effort by design: a machine where the broadcast fails still
        gets a correct registry, only later.
    #>
    try {
        if (-not ("GClaudeIndexer.EnvironmentBroadcast" -as [type])) {
            Add-Type -Namespace "GClaudeIndexer" -Name "EnvironmentBroadcast" -MemberDefinition @'
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(
    IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam,
    uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);
'@
        }
        $answer = [UIntPtr]::Zero
        # HWND_BROADCAST = 0xffff, WM_SETTINGCHANGE = 0x1A,
        # SMTO_ABORTIFHUNG = 2, and a 5 s ceiling so one frozen window
        # cannot hold the installation up.
        [GClaudeIndexer.EnvironmentBroadcast]::SendMessageTimeout(
            [IntPtr]0xffff, 0x1A, [UIntPtr]::Zero, "Environment", 2, 5000, [ref]$answer) | Out-Null
    } catch {
        # No user32, no broadcast, no problem: the registry is already right.
    }
}

function Add-UserPathEntry {
    <#
    .SYNOPSIS
        Adds a folder to this user's PATH — the registry one and this
        session's — and returns $true when PATH ends up containing it.

    .DESCRIPTION
        The user scope, never the machine scope: writing
        `HKLM\...\Session Manager\Environment` needs an administrator token,
        and the whole point of unpacking Ghostscript into
        `%LOCALAPPDATA%` is that nothing here asks for one.

        The value is read and written through the registry API rather than
        through `[Environment]::SetEnvironmentVariable`, and that is not
        style. The .NET call expands `%USERPROFILE%`-style entries on the
        way in and writes the expanded text back as a plain string, which
        silently freezes a PATH that was deliberately written with
        variables in it. `DoNotExpandEnvironmentNames` plus the original
        value kind keeps the user's PATH exactly as it was, plus one entry.

        Idempotent: an entry that is already there is not added twice, so
        running this installer a second time changes nothing.
    #>
    param([Parameter(Mandatory)][string]$Folder)

    # This session first: the check a few lines after the caller runs in
    # this very process, which will never see a registry write on its own.
    if (@($env:Path -split ';') -notcontains $Folder) {
        $env:Path = $env:Path.TrimEnd(';') + ';' + $Folder
    }

    try {
        $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $true)
        if (-not $key) { return $false }
        try {
            $stored = [string]$key.GetValue(
                "Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
            $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
            if ($stored) {
                try { $kind = $key.GetValueKind("Path") } catch { }
            }
            $entries = @($stored -split ';' | Where-Object { $_ })
            if ($entries -contains $Folder) { return $true }
            $key.SetValue("Path", (($entries + $Folder) -join ';'), $kind)
        } finally {
            $key.Close()
        }
    } catch {
        Write-Host "  could not add $Folder to your PATH ($($_.Exception.Message))." -ForegroundColor Yellow
        Write-Host "  Ghostscript is installed and works; add that folder to PATH by hand if OCR cannot find it." -ForegroundColor Yellow
        return $false
    }

    Publish-EnvironmentChange
    return $true
}

function Find-Command([string[]]$Names) {
    foreach ($name in $Names) {
        $found = Get-Command $name -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
    }
    return $null
}

function Test-WingetAvailable {
    return [bool](Get-Command winget -ErrorAction SilentlyContinue)
}

function Get-VerifiedDownload {
    <#
    .SYNOPSIS
        Downloads a file over HTTPS and returns its path only if the
        SHA-256 matches. Returns $null otherwise — and leaves nothing
        behind.

    .DESCRIPTION
        The single gate every third-party file in this script goes through,
        Ghostscript's installer and Tesseract's language data included. It
        enforces, in this order:

          1. The URL must start with $RequiredPrefix. Checked *before* the
             request, so a value that was reshaped somewhere upstream
             cannot become a request to another host.
          2. The response is written to disk and hashed. A file whose
             SHA-256 does not equal $ExpectedSha256 is deleted on the spot
             and never returned. There is no "warn and continue" branch
             here: an unverified binary is not installed, full stop.

        Never throws. A network failure returns $null with the reason
        printed, because none of the callers may abort the installation.
    #>
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$RequiredPrefix,
        [Parameter(Mandatory)][string]$ExpectedSha256,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$Label,
        [int]$TimeoutSeconds = 600
    )

    if (-not $Url.StartsWith($RequiredPrefix)) {
        Write-Host "  ${Label}: refusing a download URL outside $RequiredPrefix — nothing downloaded." -ForegroundColor Red
        return $null
    }

    # TLS 1.2 explicitly: Windows PowerShell 5.1 still negotiates whatever
    # the machine default is, and both hosts used here refuse anything older.
    try {
        [Net.ServicePointManager]::SecurityProtocol =
            [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch {
        # An older .NET without the Tls12 member: leave the default alone.
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue

    try {
        # -UseBasicParsing so this does not depend on Internet Explorer's
        # engine, which is absent on Server Core and on trimmed installs.
        Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing -TimeoutSec $TimeoutSeconds -ErrorAction Stop
    } catch {
        Write-Host "  ${Label}: download failed ($($_.Exception.Message))." -ForegroundColor Yellow
        Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
        return $null
    }

    if (-not (Test-FileMatchesHash -Path $Destination -ExpectedSha256 $ExpectedSha256)) {
        $measured = "(file missing)"
        if (Test-Path -LiteralPath $Destination -PathType Leaf) {
            $measured = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLower()
        }
        Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
        Write-Host "  ${Label}: SHA-256 DOES NOT MATCH — download deleted, nothing installed." -ForegroundColor Red
        Write-Host "    expected $ExpectedSha256" -ForegroundColor Red
        Write-Host "    measured $measured" -ForegroundColor Red
        return $null
    }

    Write-Host "  ${Label}: downloaded, SHA-256 verified." -ForegroundColor Green
    return $Destination
}

# Project root: the folder this script lives in — never a fixed path,
# because the drive letter can change between machines (section 11.5).
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LocalFolder = Join-Path $env:LOCALAPPDATA "GClaudeIndexer"
$VenvFolder = Join-Path $LocalFolder "venv"
$RequirementsPath = Join-Path $ProjectRoot "requirements.txt"
$HashPath = Join-Path $LocalFolder "requirements.sha256"

# Scratch space for every installer and data file this script downloads.
# Created here rather than next to the Tesseract/Ghostscript block because
# section 1 — the base Python itself — is now the first thing to use it.
# Emptied at the very end of the script.
$DownloadWorkFolder = Join-Path ([System.IO.Path]::GetTempPath()) "GClaudeIndexer-downloads"
New-Item -ItemType Directory -Force -Path $DownloadWorkFolder | Out-Null

Write-Host "=== GClaude Indexer Installer ===" -ForegroundColor Cyan
Write-Host "Project folder (synced):  $ProjectRoot"
Write-Host "This machine's local folder: $LocalFolder"
Write-Host ""

# --- 1. Base Python: installed when missing, only to create the venv -------

# The version matters, it is not a detail: `requirements.txt` pins versions
# that do not build on 3.13+. Taking the first Python on PATH is how a
# machine ends up with a virtual environment that looks fine and then fails
# at `pip install` with an error naming neither Python nor the version —
# this exact trap cost a working day when the project moved to a second
# machine whose PATH `python` was 3.14.
$RequiredPythonVersion = "3.12"

# Phase 15, Task 4: until now this section only *detected* the absence of
# 3.12 and printed a winget command for the user to run by hand. Detecting
# is not resolving — a person who runs an installer has said, by running
# it, that they want the machine prepared. So this section now installs
# Python itself, the same way the rest of the script installs Ghostscript:
# winget first, the vendor's own installer as the fallback, an exact pinned
# version, and a SHA-256 that decides whether the file is run or deleted.
#
# THE PIN, AND WHERE THE HASHES COME FROM
#
# 3.12.10 is the last 3.12 with binary installers — the releases after it
# are security-fix-only and ship source alone — so it is both the newest
# and the final Windows build of the line this project needs.
#
# Each SHA-256 below is the value Microsoft publishes in the winget
# manifest for `Python.Python.3.12` 3.12.10 (`Python.Python.3.12.installer.yaml`),
# and the amd64 one was additionally measured on the file downloaded from
# python.org while writing this — two sources, agreeing, neither of them
# this script. The arm64 and x86 values come from the manifest only, since
# there is no machine here to download them onto; they are pinned rather
# than omitted because an unpinned hash on those architectures would mean
# no verification at all, and that is worse than not being measured twice.
#
# (python.org stopped publishing MD5 sums for 3.12.10 in favour of Sigstore
# bundles, which is why the cross-check is against the winget manifest and
# not against a checksum on the download page.)
$PythonInstallerVersion = "3.12.10"
$PythonUrlPrefix = "https://www.python.org/ftp/python/"
$PythonWingetId = "Python.Python.$RequiredPythonVersion"
$PythonWingetCommand = "winget install --id $PythonWingetId -e --scope user --silent --accept-package-agreements --accept-source-agreements"

$PythonInstallerByArchitecture = @{
    "AMD64" = @{
        File = "python-$PythonInstallerVersion-amd64.exe"
        Sha256 = "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb"
    }
    "ARM64" = @{
        File = "python-$PythonInstallerVersion-arm64.exe"
        Sha256 = "377ac8fd478987940088e879441e702a71b53164d2a1e6f1d51ff77a7e470258"
    }
    "X86" = @{
        File = "python-$PythonInstallerVersion.exe"
        Sha256 = "fdfe385b94f5b8785a0226a886979527fd26eb65defdbf29992fd22cc4b0e31e"
    }
}

function Get-PythonVersion([string]$Executable) {
    # Returns the "major.minor" of an interpreter, or $null if it does not
    # answer (not a real Python, or a broken install).
    try {
        $version = Invoke-NativeCommand {
            & $Executable -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        }
        if ($LASTEXITCODE -eq 0 -and $version) { return "$version".Trim() }
    } catch {
        # An executable on PATH that is not a working interpreter is not an
        # error here — it just is not the one we are looking for.
    }
    return $null
}

function Get-PythonLauncherPath {
    <#
    .SYNOPSIS
        Every copy of the Windows Python launcher (`py.exe`) this machine
        actually has, whether or not PATH mentions it.

    .DESCRIPTION
        `Get-Command py` answers from $env:Path, and $env:Path is a copy
        this process was handed when it started. Right after an install
        that is exactly the wrong place to ask — so the two locations the
        launcher is ever installed to are checked directly as well:
        `C:\Windows\py.exe` for an all-users install, and
        `%LOCALAPPDATA%\Programs\Python\Launcher\py.exe` for a per-user one.
    #>
    $candidates = @()
    $onPath = Get-Command "py" -ErrorAction SilentlyContinue
    if ($onPath) { $candidates += $onPath.Source }
    if ($env:WINDIR) { $candidates += (Join-Path $env:WINDIR "py.exe") }
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher\py.exe")
    }
    return @(
        $candidates |
            Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
            Select-Object -Unique
    )
}

function Get-PythonFromRegistry {
    <#
    .SYNOPSIS
        Interpreters of $Version that the registry knows about, from the
        key PEP 514 defines and the `py` launcher itself reads.

    .DESCRIPTION
        This is the authoritative answer, and it does not depend on PATH at
        all: every Python installer records `InstallPath` under
        `Software\Python\PythonCore\<version>`, per user in HKCU and per
        machine in HKLM. Registry reads are not cached in this process the
        way the environment block is, so a key written a second ago is
        visible immediately — which is precisely the property this task
        needs.

        Every path it returns is still checked for an actual python.exe by
        the caller, because a *stale* key is a real thing: this machine had
        `HKCU\Software\Python\PythonCore\3.12` left behind by an uninstalled
        3.12, complete with Help, Idle and PythonPath entries, pointing at a
        folder with no interpreter in it. Trusting the key alone would have
        produced "found" for a Python that is not there.
    #>
    param([Parameter(Mandatory)][string]$Version)

    $roots = @(
        "HKCU:\Software\Python\PythonCore",
        "HKLM:\SOFTWARE\Python\PythonCore",
        "HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore"
    )
    $found = @()
    foreach ($root in $roots) {
        # The launcher's own tag suffixes: bare for the native build, -32
        # for the 32-bit one on a 64-bit machine, -arm64 on ARM.
        foreach ($tag in @($Version, "$Version-32", "$Version-arm64")) {
            $key = Join-Path (Join-Path $root $tag) "InstallPath"
            try {
                if (-not (Test-Path -LiteralPath $key)) { continue }
                $properties = Get-ItemProperty -LiteralPath $key -ErrorAction Stop
                $executable = $null
                if ($properties.PSObject.Properties.Name -contains "ExecutablePath") {
                    $executable = "$($properties.ExecutablePath)".Trim()
                }
                if (-not $executable) {
                    $folder = "$($properties.'(default)')".Trim()
                    if ($folder) { $executable = Join-Path $folder "python.exe" }
                }
                if ($executable -and (Test-Path -LiteralPath $executable -PathType Leaf)) {
                    $found += $executable
                }
            } catch {
                # A key we cannot read is a key we do not use.
            }
        }
    }
    return @($found | Select-Object -Unique)
}

function Get-PythonKnownFolder {
    <#
    .SYNOPSIS
        The folders a Python of $Version is installed into by default,
        filtered down to the ones that really contain a python.exe.

    .DESCRIPTION
        The last resort, for the case where PATH has not caught up *and*
        the registry entry is missing or unreadable. `3.12` becomes
        `Python312`, which is the folder name every python.org installer
        uses, under the per-user root, both Program Files, and the old
        `C:\Python312`.
    #>
    param([Parameter(Mandatory)][string]$Version)

    $folderName = "Python" + ($Version -replace '\.', '')
    $roots = @()
    if ($env:LOCALAPPDATA) { $roots += (Join-Path $env:LOCALAPPDATA "Programs\Python") }
    if ($env:ProgramFiles) { $roots += $env:ProgramFiles }
    if (${env:ProgramFiles(x86)}) { $roots += ${env:ProgramFiles(x86)} }
    if ($env:SystemDrive) { $roots += "$env:SystemDrive\" } else { $roots += "C:\" }

    $candidates = @()
    foreach ($root in $roots) {
        foreach ($suffix in @("", "-32", "-arm64")) {
            $candidates += (Join-Path (Join-Path $root ($folderName + $suffix)) "python.exe")
        }
    }
    return @(
        $candidates |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            Select-Object -Unique
    )
}

function Find-PythonBase {
    <#
    .SYNOPSIS
        The path to an interpreter of exactly $RequiredPythonVersion, or
        $null. Four routes, and every one of them ends in the interpreter
        being asked its own version before it is accepted.

    .DESCRIPTION
        Order matters. The Windows launcher comes first because it finds
        the right version even when PATH points at another one — the common
        case on a machine with several Pythons, which is this project's
        normal situation. Then PATH itself, then the registry, then the
        default install folders.

        The last two exist for one reason, and it is the whole point of
        Phase 15 Task 4: **this process cannot see a Python installed after
        it started.** PATH and the launcher's view of the world are read
        from the registry when a process is created, and installing
        something afterwards does not rewrite the environment block of a
        process that is already running. Re-running a PATH-only check after
        an install fails with "not found" on a machine that has just been
        given exactly what was asked for, and the user is told to install
        something they can see in Add/Remove Programs. Update-SessionPath
        re-reads both PATH scopes into this process, and these two routes
        do not need PATH to be right at all.

        Nothing here trusts a name or a key: `Get-PythonVersion` runs the
        candidate and reads `sys.version_info`. That is what separates a
        real 3.12 from a leftover registry entry, an empty folder or a
        Microsoft Store stub.
    #>
    foreach ($launcher in (Get-PythonLauncherPath)) {
        # Through Invoke-NativeCommand: with no 3.12 installed, `py -3.12`
        # writes to stderr and exits non-zero, and that used to kill the
        # installer here instead of falling through to the code below. See
        # that function's own comment.
        $target = Invoke-NativeCommand {
            & $launcher "-$RequiredPythonVersion" -c "import sys; print(sys.executable)" 2>$null
        }
        if ($LASTEXITCODE -eq 0 -and $target) {
            $executable = "$target".Trim()
            if ((Get-PythonVersion $executable) -eq $RequiredPythonVersion) { return $executable }
        }
    }

    foreach ($command in @("python", "py")) {
        $found = Get-Command $command -ErrorAction SilentlyContinue
        if ($found -and (Get-PythonVersion $found.Source) -eq $RequiredPythonVersion) {
            return $found.Source
        }
    }

    foreach ($executable in (Get-PythonFromRegistry -Version $RequiredPythonVersion)) {
        if ((Get-PythonVersion $executable) -eq $RequiredPythonVersion) { return $executable }
    }

    foreach ($executable in (Get-PythonKnownFolder -Version $RequiredPythonVersion)) {
        if ((Get-PythonVersion $executable) -eq $RequiredPythonVersion) { return $executable }
    }

    return $null
}

function Resolve-PythonAfterInstall {
    <#
    .SYNOPSIS
        Looks for the interpreter again, after refreshing what this process
        knows about the machine. Returns its path, or $null.

    .DESCRIPTION
        One line of code and the reason this task exists. Calling
        Find-PythonBase alone straight after an install is the bug: the
        environment block of a running process is a snapshot taken at
        creation, so the PATH entry the installer just wrote is invisible
        here. Update-SessionPath merges both registry PATH scopes into this
        session first; Find-PythonBase then has three further routes that
        do not depend on PATH at all.
    #>
    Update-SessionPath
    return Find-PythonBase
}

function Install-PythonRuntime {
    <#
    .SYNOPSIS
        Installs Python $PythonInstallerVersion and returns the path to the
        interpreter, or $null when every route has been exhausted.

    .DESCRIPTION
        Three routes, cheapest first, and the machine is re-examined after
        each one rather than assumed to have changed.

        ROUTE 1 — winget, `--scope user`.

        The scope is not decoration. Microsoft's manifest for
        `Python.Python.3.12` passes `PrependPath=1` in *both* scopes, so a
        machine-scope install would put Python 3.12 at the front of the
        **machine** PATH — ahead of whatever Python the user already had
        there. On this project's own reference machine that would silently
        demote a working 3.14 to second place, which is precisely what this
        installer promises not to do. User scope writes only to the user
        PATH, and Windows composes a process's PATH as machine-then-user,
        so the existing interpreter keeps winning `python`. It also needs
        no administrator token at all.

        ROUTE 2 — the python.org installer, downloaded, hash-checked, run
        for the current user.

        `InstallAllUsers=0` puts it in `%LOCALAPPDATA%\Programs\Python`,
        which this user can write without elevation. `PrependPath=0`,
        `AssociateFiles=0` and `Shortcuts=0` are the "side by side" promise
        spelled out as switches: PATH order unchanged, double-clicking a
        .py file still opens whatever it opened before, no Start Menu
        entries. Nothing needs PATH here — the registry key the installer
        writes is enough for `py -3.12` and for Get-PythonFromRegistry.

        The launcher is only requested when the machine has none.
        Re-installing a per-user launcher over an existing all-users one of
        a *newer* Python is how the python.org bundle produces
        "Another version of this product is already installed", and the
        launcher is not what we came for.

        ROUTE 3 — the same installer, elevated, machine-wide.

        Only reached when the unprivileged install did not produce a
        working interpreter (a policy forbidding per-user installs is the
        realistic case). Elevation goes through Start-ProcessElevated like
        the other two elevated operations in this script, and a refusal is
        a decision: it returns $null and the caller prints the manual
        instructions, which is the behaviour this section had before it
        could install anything at all.
    #>
    param([Parameter(Mandatory)][string]$WorkFolder)

    # Route 1 --------------------------------------------------------------
    if (Test-WingetAvailable) {
        Write-Host "  trying winget ($PythonWingetId, user scope) ..." -ForegroundColor Cyan
        # `| Out-Host`: inside a function winget's success stream would
        # otherwise become part of the return value (see Install-IfMissing).
        Invoke-NativeCommand {
            winget install --id $PythonWingetId -e --scope user --silent --accept-package-agreements --accept-source-agreements
        } | Out-Host
        $found = Resolve-PythonAfterInstall
        if ($found) {
            Write-Host "Python $RequiredPythonVersion installed via winget: $found" -ForegroundColor Green
            return $found
        }
        Write-Host "  winget did not deliver Python $RequiredPythonVersion." -ForegroundColor Yellow
    } else {
        Write-Host "  winget is not available on this machine." -ForegroundColor Yellow
    }

    # Route 2 --------------------------------------------------------------
    $architecture = "$env:PROCESSOR_ARCHITECTURE".ToUpperInvariant()
    $pin = $PythonInstallerByArchitecture[$architecture]
    if (-not $pin) {
        Write-Host "  no python.org installer is pinned for this architecture ($architecture)," -ForegroundColor Yellow
        Write-Host "  and nothing here downloads a file whose hash it cannot check." -ForegroundColor Yellow
        return $null
    }

    $url = "$PythonUrlPrefix$PythonInstallerVersion/$($pin.File)"
    Write-Host "  falling back to the official python.org installer $PythonInstallerVersion ($architecture) ..." -ForegroundColor Cyan
    $installerPath = Get-VerifiedDownload `
        -Url $url `
        -RequiredPrefix $PythonUrlPrefix `
        -ExpectedSha256 $pin.Sha256 `
        -Destination (Join-Path $WorkFolder $pin.File) `
        -Label "Python $PythonInstallerVersion"
    if (-not $installerPath) { return $null }

    try {
        $launcherSwitches = @("Include_launcher=0")
        if ((Get-PythonLauncherPath).Count -eq 0) {
            $launcherSwitches = @("Include_launcher=1", "InstallLauncherAllUsers=0")
        }

        Write-Host "  installing Python $PythonInstallerVersion for this user (no administrator needed) ..." -ForegroundColor Cyan
        $run = Start-QuietProcess -FilePath $installerPath -TimeoutSeconds 1800 -ArgumentList (
            @("/quiet", "InstallAllUsers=0", "PrependPath=0", "AssociateFiles=0",
              "Shortcuts=0", "Include_test=0") + $launcherSwitches
        )
        if (-not $run.Started) {
            Write-Host "  the installer would not start: $($run.Detail)" -ForegroundColor Yellow
        } elseif ($null -ne $run.ExitCode -and $run.ExitCode -ne 0) {
            Write-Host "  the Python installer returned code $($run.ExitCode)." -ForegroundColor Yellow
        }

        $found = Resolve-PythonAfterInstall
        if ($found) {
            Write-Host "Python $PythonInstallerVersion installed: $found" -ForegroundColor Green
            return $found
        }

        # Route 3 ----------------------------------------------------------
        Write-Host "  the per-user install did not produce a working Python $RequiredPythonVersion." -ForegroundColor Yellow
        Write-Host "  trying the machine-wide install, which needs administrator rights." -ForegroundColor Yellow
        if (-not (Test-IsElevated)) {
            Write-Host "  Windows will now ask you to approve it (UAC)." -ForegroundColor Yellow
        }
        $elevated = Start-ProcessElevated -FilePath $installerPath -TimeoutSeconds 1800 -ArgumentList @(
            "/quiet", "InstallAllUsers=1", "PrependPath=0", "AssociateFiles=0",
            "Shortcuts=0", "Include_test=0", "Include_launcher=0"
        )
        if (-not $elevated.Elevated) {
            Write-Host "  administrator rights were refused, so nothing was installed:" -ForegroundColor Yellow
            Write-Host "  $($elevated.Detail)" -ForegroundColor Yellow
            return $null
        }
        if ($null -ne $elevated.ExitCode -and $elevated.ExitCode -ne 0) {
            Write-Host "  the Python installer returned code $($elevated.ExitCode)." -ForegroundColor Yellow
        }

        $found = Resolve-PythonAfterInstall
        if ($found) {
            Write-Host "Python $PythonInstallerVersion installed (all users): $found" -ForegroundColor Green
            return $found
        }
        return $null
    } finally {
        # A ~26 MB installer is not meant to outlive the installation.
        Remove-Item -LiteralPath $installerPath -Force -ErrorAction SilentlyContinue
    }
}

$PythonBase = Find-PythonBase
if (-not $PythonBase) {
    $onPath = $null
    $anyPython = Get-Command "python" -ErrorAction SilentlyContinue
    if ($anyPython) { $onPath = Get-PythonVersion $anyPython.Source }

    if ($onPath) {
        Write-Host "Python $onPath found, but this project needs Python $RequiredPythonVersion." -ForegroundColor Yellow
        Write-Host "The pinned versions in requirements.txt do not build on newer releases." -ForegroundColor Yellow
        Write-Host "Python $PythonInstallerVersion goes in beside it: your $onPath is not changed, not moved" -ForegroundColor Yellow
        Write-Host "and stays the 'python' on your PATH." -ForegroundColor Yellow
    } else {
        Write-Host "Python $RequiredPythonVersion not found." -ForegroundColor Yellow
    }

    $InstallPython = [bool]$AutoInstall
    if (-not $AutoInstall) {
        Write-Host "  Python $PythonInstallerVersion is a ~26 MB download from python.org and installs" -ForegroundColor Yellow
        Write-Host "  into your own user folder, so Windows does not have to ask for administrator." -ForegroundColor Yellow
        $answer = Read-Host "  Install Python $RequiredPythonVersion now? (Y/N)"
        $InstallPython = $answer -match '^[SsYy]'
    }

    if ($InstallPython) {
        Write-Host "Installing Python $PythonInstallerVersion ..." -ForegroundColor Cyan
        $PythonBase = Install-PythonRuntime -WorkFolder $DownloadWorkFolder
    }
}

if (-not $PythonBase) {
    # Every automatic route is exhausted or was declined. This is the
    # message this section used to print immediately, and it is still the
    # right one when there is genuinely nothing left to do.
    Write-Host "Python $RequiredPythonVersion is missing and could not be installed automatically." -ForegroundColor Red
    Write-Host "Install it with:  $PythonWingetCommand" -ForegroundColor Yellow
    Write-Host "or download it from $PythonUrlPrefix$PythonInstallerVersion/ and run this installer again." -ForegroundColor Yellow
    Write-Host "Installing it side by side is fine: this installer picks $RequiredPythonVersion through the 'py' launcher and leaves your other versions alone." -ForegroundColor Yellow
    exit 1
}
Write-Host "Base Python found: $PythonBase (version $RequiredPythonVersion)"

# --- 2. Local virtual environment (section 11.1/11.2) -----------------------

if (Test-Path (Join-Path $VenvFolder "Scripts\python.exe")) {
    Write-Host "Virtual environment already exists at $VenvFolder."
} else {
    Write-Host "Creating virtual environment at $VenvFolder ..."
    New-Item -ItemType Directory -Force -Path $LocalFolder | Out-Null
    Invoke-NativeCommand { & $PythonBase -m venv $VenvFolder }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to create the virtual environment." -ForegroundColor Red
        exit 1
    }
    Write-Host "Virtual environment created." -ForegroundColor Green
}

$VenvPython = Join-Path $VenvFolder "Scripts\python.exe"

# --- 3. Python dependencies, only if requirements.txt changed (section 11.2)

function Get-FileChecksum([string]$Path) {
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
}

$CurrentHash = Get-FileChecksum $RequirementsPath
$PreviousHash = $null
if (Test-Path $HashPath) {
    $PreviousHash = (Get-Content -Path $HashPath -Raw).Trim()
}

if ($CurrentHash -eq $PreviousHash) {
    Write-Host "Python dependencies are already up to date."
} else {
    Write-Host "requirements.txt is new or has changed — installing dependencies ..."
    # pip routes plenty of ordinary chatter (deprecation and "new version
    # available" notices) through stderr, which under "Stop" would abort a
    # perfectly successful install. `$LASTEXITCODE` right below is what
    # actually decides whether it worked.
    Invoke-NativeCommand { & $VenvPython -m pip install --upgrade pip --quiet }
    Invoke-NativeCommand { & $VenvPython -m pip install -r $RequirementsPath }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to install Python dependencies." -ForegroundColor Red
        exit 1
    }
    Set-Content -Path $HashPath -Value $CurrentHash -Encoding utf8 -NoNewline
    Write-Host "Python dependencies installed." -ForegroundColor Green
}

# --- 4. Tesseract and Ghostscript, actually installed when missing ---------
# (section 10.3; Phase 13 Task 13: a warning alone was not enough on a new
# machine)

# `Find-Command` and `Test-WingetAvailable` were defined here until Phase 15
# Task 4. They now live in the shared-helpers section at the top of this file:
# section 1 installs Python itself, and PowerShell resolves a function at the
# moment of the call — a helper section 1 needs cannot be written in section 4.

function Install-IfMissing {
    <#
    .SYNOPSIS
        Installs a dependency via winget if it is not already present.

    .DESCRIPTION
        Idempotent: if `$Binaries` already resolves to a command, this does
        nothing (and does not ask). If it is missing and `winget` does not
        exist on this machine, it only reports the command — it never
        tries another download path. If it is missing and `winget` exists,
        it asks before installing, unless `-AutoInstall` (the script's own
        parameter) was passed.
    #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string[]]$Binaries,
        [Parameter(Mandatory)][string]$WingetId
    )

    $found = Find-Command $Binaries
    if ($found) {
        Write-Host "$Name OK: $found" -ForegroundColor Green
        return $true
    }

    $command = "winget install --id $WingetId -e --silent --accept-package-agreements --accept-source-agreements"
    Write-Host "$Name not found." -ForegroundColor Yellow

    if (-not (Test-WingetAvailable)) {
        Write-Host "  winget is not available on this machine. Install manually:" -ForegroundColor Yellow
        Write-Host "  $command" -ForegroundColor Yellow
        return $false
    }

    if (-not $AutoInstall) {
        $answer = Read-Host "  Install $Name now with winget? (Y/N)"
        if ($answer -notmatch '^[SsYy]') {
            Write-Host "  skipped. To install it later:" -ForegroundColor Yellow
            Write-Host "  $command" -ForegroundColor Yellow
            return $false
        }
    }

    Write-Host "  installing $Name ..." -ForegroundColor Cyan
    # `| Out-Host`, not a bare call: winget writes to the success stream,
    # and inside a function that stream *is* the return value. Without this
    # the function returned winget's output lines followed by $true/$false,
    # so `$GhostscriptOk` came back as a non-empty array — always truthy —
    # and `if (-not $GhostscriptOk)` never fired. The clean-machine test
    # showed the consequence: Ghostscript genuinely failed to install, and
    # the two warnings written for exactly that case (the ghostscript.com
    # download link, and the note about falling back to the 'rules' engine)
    # stayed silent. Out-Host still shows winget's progress on screen.
    Invoke-NativeCommand { winget install --id $WingetId -e --silent --accept-package-agreements --accept-source-agreements } | Out-Host
    # Update-SessionPath first, and this is not a nicety: winget's Tesseract
    # installer appends `C:\Program Files\Tesseract-OCR` to the machine PATH,
    # and this process was born with the old one. Without this line the check
    # below asks a stale copy of PATH about a binary that exists, prints "not
    # found after installation (you may need to open a new terminal)" for
    # something it installed correctly, and returns $false — which then makes
    # the OCR-language block skip a Tesseract that is right there. Same defect
    # the base-Python section was rewritten to avoid in Phase 15 Task 4; found
    # while watching that run, in the sibling function.
    Update-SessionPath
    $found = Find-Command $Binaries
    if ($found) {
        Write-Host "$Name installed: $found" -ForegroundColor Green
        return $true
    }
    Write-Host "$Name was not found after installation (you may need to open a new terminal for PATH to update)." -ForegroundColor Yellow
    return $false
}

# --- 4a. A verified download -----------------------------------------------
#
# `Get-VerifiedDownload` was defined here until Phase 15 Task 4 and now lives
# in the shared-helpers section at the top, for the same reason as the two
# helpers above: section 1 downloads the python.org installer through it.

# --- 4b. Ghostscript: unpacked into this user's own folder -----------------
#
# `ocrmypdf` will not start without `gswin64c` on PATH, so this is not an
# optional nicety: no Ghostscript means no OCR at all, which means the
# scanned PDFs this project exists to read never get converted.
#
# Phase 15, Task 5 changed how it gets there, because the way it used to be
# installed could not run unattended. Measured on this machine, today:
#
#   * `gs10071w64.exe` is manifested `requireAdministrator`. Started with
#     UseShellExecute = $false — what `-NoNewWindow` does — it fails before
#     running a line: "the requested operation requires elevation". Started
#     through the shell it raises a UAC prompt. No destination changes
#     that: the manifest is read first, and `%LOCALAPPDATA%` is read no
#     differently from `C:\Program Files`.
#   * Bypassing the manifest does not help either. Launched with the
#     RunAsInvoker compatibility shim (no prompt, no administrator) the
#     installer starts, ignores `/S`, and sits on its "Welcome to GPL
#     Ghostscript Setup" page waiting for Next — 300 s, zero files.
#   * Run elevated, `/S` does install, and then stops on the "Finish" page
#     until somebody clicks it (Task 4 measured that page's controls).
#     Artifex disabled silent installation in 10.01.0 and documents only
#     `/NCRC` and `/D`, so there is no better flag waiting to be found.
#
# So on the normal path the installer is not run at all. It is unpacked.
# What it carries is a plain file tree — bin, lib, Resource, iccprofiles —
# and Ghostscript resolves its resources relative to the executable: a copy
# at any path works with no registry key at all. That was measured too, by
# pointing `HKLM\SOFTWARE\GPL Ghostscript` at a folder that no longer
# existed and watching the copy answer anyway.
#
# Unpacking needs an extractor that understands NSIS, and Windows has none.
# 7-Zip's own MSI provides one without installing anything and without an
# administrator: `msiexec /a` is an *administrative install*, which only
# copies the package's files into a folder of our choosing. Both downloads
# are pinned by URL and checked by SHA-256 like every other file here.
#
# End to end, into folders whose names contain spaces:
#
#     msiexec /a  0,5 s  -> 7z.exe
#     7z x        2,2 s  -> 649 files in %LOCALAPPDATA%\GClaudeIndexer\gs
#     gswin64c --version answers 0,2 s later: 10.07.1
#
# against 93 s, one UAC prompt and one mouse click for the old route.
#
# The vendor's installer remains as the fallback, for the machine where the
# extractor cannot be had — and that is where the other half of Task 5
# lives: it waits for the *condition*, not for the process. The condition
# is the binary existing and answering `--version`; once that is true the
# installation is over and the window on screen is only waiting for a
# click, so the process is killed. The wait is bounded, and a timeout
# degrades with a warning like every other dependency here, never aborting
# the installation.

$GhostscriptVersion = "10.07.1"
$GhostscriptReleaseTag = "gs10071"
$GhostscriptInstallerFile = "gs10071w64.exe"
$GhostscriptUrlPrefix = "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/"
$GhostscriptUrl = "$GhostscriptUrlPrefix$GhostscriptReleaseTag/$GhostscriptInstallerFile"
# Measured on the downloaded file, and the same file's SHA-512 compared
# against Artifex's own `SHA512SUMS`, published as an asset of that release
# — so the pin is anchored to something the vendor signs off on, not just
# to whatever arrived the day it was written.
$GhostscriptSha256 = "3a4c28d0aac47aa7cccd35a5932c55110376e9dbd966898dde388b7faba444a4"
$GhostscriptBinaries = @("gswin64c", "gswin32c", "gs")

# Where the unpacked copy lives: beside the virtual environment, the sensor
# library and the catalogue. Everything this machine owns is already there.
$GhostscriptFolder = Join-Path $LocalFolder "gs"
$GhostscriptBinFolder = Join-Path $GhostscriptFolder "bin"
$GhostscriptExePath = Join-Path $GhostscriptBinFolder "gswin64c.exe"

# How long the fallback waits for the binary to answer before giving up.
# The measured install is ~90 s; this is that with room for a slow disk.
$GhostscriptWaitSeconds = 600

# 7-Zip is never installed, only unpacked and used as a tool: `msiexec /a`
# copies the MSI's payload into the download folder, which is emptied at the
# end of the script. The x64 build from the project's own repository — the
# same file, byte for byte, that www.7-zip.org/a serves; both hashes were
# compared before this line was written.
$SevenZipVersion = "26.02"
$SevenZipFile = "7z2602-x64.msi"
$SevenZipUrlPrefix = "https://github.com/ip7z/7zip/releases/download/"
$SevenZipUrl = "$SevenZipUrlPrefix$SevenZipVersion/$SevenZipFile"
$SevenZipSha256 = "db407a4f6d4999e5c7bc00ce8a882be94717b56e7fa68140fe3f12605d91643e"

function Test-GhostscriptAnswers {
    <#
    .SYNOPSIS
        $true when the file at $Path is a Ghostscript that runs.

    .DESCRIPTION
        Existing is not the same as working: a file can be half-copied, and
        an unpacked tree can be missing the DLL beside the executable. The
        only answer worth trusting comes from the program itself.
    #>
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try {
        $output = & $Path --version 2>$null
        return ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace("$output"))
    } catch {
        return $false
    }
}

function Get-SevenZipExtractor {
    <#
    .SYNOPSIS
        Returns the path to a 7z.exe that can read NSIS, or $null.

    .DESCRIPTION
        Nothing is installed and nothing is registered: `msiexec /a` is an
        administrative install, which unpacks the package into $TARGETDIR
        and stops there. It is started through Start-QuietProcess, whose
        `-NoNewWindow` means UseShellExecute = $false — a process launched
        that way *cannot* elevate even if it wanted to, so this step is
        provably free of UAC prompts rather than merely expected to be.

        The arguments are quoted here by hand because `Start-Process` joins
        an argument array with spaces and quotes nothing (measured): a user
        whose name has a space in it is exactly where the unquoted version
        falls apart.
    #>
    param([Parameter(Mandatory)][string]$WorkFolder)

    $package = Get-VerifiedDownload `
        -Url $SevenZipUrl `
        -RequiredPrefix $SevenZipUrlPrefix `
        -ExpectedSha256 $SevenZipSha256 `
        -Destination (Join-Path $WorkFolder $SevenZipFile) `
        -Label "7-Zip $SevenZipVersion (extractor only)"
    if (-not $package) { return $null }

    $target = Join-Path $WorkFolder "7zip"
    $run = Start-QuietProcess -FilePath "msiexec.exe" -TimeoutSeconds 300 -ArgumentList @(
        "/a", "`"$package`"", "/qn", "TARGETDIR=`"$target`""
    )
    if (-not $run.Started) {
        Write-Host "  msiexec would not start: $($run.Detail)" -ForegroundColor Yellow
        return $null
    }
    if ($null -ne $run.ExitCode -and $run.ExitCode -ne 0) {
        Write-Host "  unpacking 7-Zip returned code $($run.ExitCode)." -ForegroundColor Yellow
        return $null
    }

    $extractor = Join-Path $target "Files\7-Zip\7z.exe"
    if (Test-Path -LiteralPath $extractor -PathType Leaf) { return $extractor }
    Write-Host "  7-Zip was unpacked but 7z.exe is not where it was expected." -ForegroundColor Yellow
    return $null
}

function Expand-Ghostscript {
    <#
    .SYNOPSIS
        Unpacks the vendor's installer into $Destination. $true when the
        extractor reported success.

    .DESCRIPTION
        Two things are deliberately left out of the tree:

        `$PLUGINSDIR` is the NSIS scratch folder, of no use to anyone once
        the installer is not being run.

        `vcredist_x64.exe` is the Visual C++ runtime the installer would
        offer to install machine-wide — which needs an administrator, and
        is not needed here: `gswin64c.exe` imports `vcruntime140.dll`, and
        by the time this line runs the machine has the Python 3.12 of
        section 1, which imports the same runtime. On the machine where
        that assumption is somehow wrong the binary simply will not answer
        `--version`, and the caller falls through to the vendor's own
        installer, which does ship and run the redistributable.
    #>
    param(
        [Parameter(Mandatory)][string]$Extractor,
        [Parameter(Mandatory)][string]$InstallerPath,
        [Parameter(Mandatory)][string]$Destination
    )

    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    $run = Start-QuietProcess -FilePath $Extractor -TimeoutSeconds 600 -ArgumentList @(
        "x", "`"$InstallerPath`"", "`"-o$Destination`"", "-y", "-bso0", "-bsp0",
        "-x!`$PLUGINSDIR", "-xr!vcredist_x64.exe"
    )
    if (-not $run.Started) {
        Write-Host "  the extractor would not start: $($run.Detail)" -ForegroundColor Yellow
        return $false
    }
    if ($null -ne $run.ExitCode -and $run.ExitCode -ne 0) {
        Write-Host "  unpacking Ghostscript returned code $($run.ExitCode)." -ForegroundColor Yellow
        return $false
    }
    return $true
}

function New-GhostscriptUnattendedScript {
    <#
    .SYNOPSIS
        The script that runs elevated when no extractor could be had: it
        starts the vendor's installer and waits for the result, not for the
        process. Exit code 0 means the binary answered.

    .DESCRIPTION
        Why a script instead of launching the installer from here and
        killing it from here: a process holding an administrator token
        cannot be killed by one that does not. The waiting and the killing
        have to happen on the same side of that line as the installer, so
        they are written into the elevated child.

        Why `-ArgumentList` gets one string: `/D=` must be the last thing on
        the command line and must not be quoted — NSIS reads the rest of the
        line literally, spaces included — and `Start-Process` passes a
        single string through untouched.

        Why killing it is safe: by the time `gswin64c --version` answers,
        every file has been written; what is left on screen is a "Finish"
        page whose only job is to wait for a click.
    #>
    param(
        [Parameter(Mandatory)][string]$InstallerPath,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$BinaryPath,
        [int]$TimeoutSeconds = 600
    )

    # Single quotes in the generated script, doubled inside, so a folder
    # named after someone called O'Brien cannot end the string early.
    $installerLiteral = $InstallerPath.Replace("'", "''")
    $destinationLiteral = $Destination.Replace("'", "''")
    $binaryLiteral = $BinaryPath.Replace("'", "''")

    return @"
`$ErrorActionPreference = 'Continue'
`$installer = '$installerLiteral'
`$destination = '$destinationLiteral'
`$binary = '$binaryLiteral'

function Test-Answers {
    if (-not (Test-Path -LiteralPath `$binary -PathType Leaf)) { return `$false }
    try {
        & `$binary --version > `$null 2>&1
        return (`$LASTEXITCODE -eq 0)
    } catch {
        return `$false
    }
}

`$process = Start-Process -FilePath `$installer -ArgumentList "/S /D=`$destination" -PassThru
`$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
`$ready = `$false
while (`$true) {
    if (Test-Answers) { `$ready = `$true; break }
    if (`$process.HasExited) { `$ready = Test-Answers; break }
    if ((Get-Date) -ge `$deadline) { break }
    Start-Sleep -Seconds 2
}

if (-not `$process.HasExited) {
    try { `$process.Kill(); `$process.WaitForExit(15000) | Out-Null } catch { }
}

if (`$ready) { exit 0 }
exit 3
"@
}

function Install-Ghostscript {
    <#
    .SYNOPSIS
        Makes sure `gswin64c` exists on this machine and answers. Returns
        $true when it does, $false when every route was exhausted.

    .DESCRIPTION
        Idempotent in the strict sense: a machine that already has
        Ghostscript — the user's own copy in `C:\Program Files`, or the one
        an earlier run of this script unpacked — is asked nothing, downloads
        nothing and runs nothing.
    #>
    param(
        [Parameter(Mandatory)][string]$WorkFolder
    )

    # Whatever the user already has wins: this never replaces a Ghostscript
    # that is on PATH, wherever it was installed from.
    $found = Find-Command $GhostscriptBinaries
    if (-not $found -and (Test-GhostscriptAnswers -Path $GhostscriptExePath)) {
        # Unpacked by an earlier run, but this process was born with a PATH
        # that predates it — or the user PATH entry was lost. Either way,
        # there is nothing to install.
        Add-UserPathEntry -Folder $GhostscriptBinFolder | Out-Null
        $found = $GhostscriptExePath
    }
    if ($found) {
        Write-Host "Ghostscript OK: $found" -ForegroundColor Green
        return $true
    }

    $wingetCommand = "winget install --id ArtifexSoftware.GhostScript -e --silent --accept-package-agreements --accept-source-agreements"
    Write-Host "Ghostscript not found." -ForegroundColor Yellow
    Write-Host "  Without it ocrmypdf cannot run, and every text-less (scanned) PDF fails to convert." -ForegroundColor Yellow

    if (-not $AutoInstall) {
        Write-Host "  Ghostscript $GhostscriptVersion is a ~62 MB download and is unpacked into" -ForegroundColor Yellow
        Write-Host "  $GhostscriptFolder, your own folder, so Windows does not have to ask for administrator." -ForegroundColor Yellow
        $answer = Read-Host "  Install Ghostscript now? (Y/N)"
        if ($answer -notmatch '^[SsYy]') {
            Write-Host "  skipped. To install it later, either run this installer again or download" -ForegroundColor Yellow
            Write-Host "  $GhostscriptUrl" -ForegroundColor Yellow
            return $false
        }
    }

    # Route 1: winget. Kept first on purpose — if the package is ever
    # reindexed, this is the path that keeps Ghostscript patched by the
    # machine's own package manager instead of by us.
    if (Test-WingetAvailable) {
        Write-Host "  trying winget ..." -ForegroundColor Cyan
        # `| Out-Host`: inside a function winget's success stream would
        # otherwise become part of the return value (see Install-IfMissing).
        Invoke-NativeCommand { winget install --id ArtifexSoftware.GhostScript -e --silent --accept-package-agreements --accept-source-agreements } | Out-Host
        Update-SessionPath
        $found = Find-Command $GhostscriptBinaries
        if ($found) {
            Write-Host "Ghostscript installed via winget: $found" -ForegroundColor Green
            return $true
        }
        Write-Host "  winget did not deliver Ghostscript (the package is no longer in the index)." -ForegroundColor Yellow
    } else {
        Write-Host "  winget is not available on this machine." -ForegroundColor Yellow
    }

    # Route 2: the vendor's own file, pinned and hash-checked, unpacked
    # rather than run.
    Write-Host "  downloading the official Artifex build $GhostscriptVersion ..." -ForegroundColor Cyan
    $installerPath = Get-VerifiedDownload `
        -Url $GhostscriptUrl `
        -RequiredPrefix $GhostscriptUrlPrefix `
        -ExpectedSha256 $GhostscriptSha256 `
        -Destination (Join-Path $WorkFolder $GhostscriptInstallerFile) `
        -Label "Ghostscript $GhostscriptVersion"
    if (-not $installerPath) {
        Write-Host "Ghostscript was not installed. Manual routes, in order of preference:" -ForegroundColor Yellow
        Write-Host "  $GhostscriptUrl" -ForegroundColor Yellow
        Write-Host "  https://ghostscript.com/releases/gsdnld.html" -ForegroundColor Yellow
        Write-Host "  $wingetCommand   (only if the package returns to the winget index)" -ForegroundColor Yellow
        return $false
    }

    try {
        Write-Host "  unpacking it into $GhostscriptFolder (no administrator needed) ..." -ForegroundColor Cyan
        $extractor = Get-SevenZipExtractor -WorkFolder $WorkFolder
        if ($extractor -and (Expand-Ghostscript -Extractor $extractor -InstallerPath $installerPath -Destination $GhostscriptFolder)) {
            if (Test-GhostscriptAnswers -Path $GhostscriptExePath) {
                Add-UserPathEntry -Folder $GhostscriptBinFolder | Out-Null
                Write-Host "Ghostscript $GhostscriptVersion unpacked: $GhostscriptExePath" -ForegroundColor Green
                return $true
            }
            Write-Host "  the unpacked Ghostscript does not answer --version." -ForegroundColor Yellow
        }

        # Route 3: the vendor's installer, run elevated, waited for by
        # condition. Reached only when the extractor could not be had or
        # what it produced does not run.
        Write-Host "  falling back to running the vendor's installer, which needs administrator rights." -ForegroundColor Yellow
        if (-not (Test-IsElevated)) {
            Write-Host "  Windows will now ask you to approve it (UAC)." -ForegroundColor Yellow
        }
        $run = Invoke-ElevatedScript -TimeoutSeconds ($GhostscriptWaitSeconds + 120) -Script (
            New-GhostscriptUnattendedScript `
                -InstallerPath $installerPath `
                -Destination $GhostscriptFolder `
                -BinaryPath $GhostscriptExePath `
                -TimeoutSeconds $GhostscriptWaitSeconds
        )
        if (-not $run.Elevated) {
            Write-Host "Ghostscript needs administrator rights for this route and the elevation was refused:" -ForegroundColor Yellow
            Write-Host "  $($run.Detail)" -ForegroundColor Yellow
            Write-Host "  Run this installer again from a PowerShell opened as administrator, or install" -ForegroundColor Yellow
            Write-Host "  Ghostscript by hand from $GhostscriptUrl" -ForegroundColor Yellow
            return $false
        }
        if ($null -ne $run.ExitCode -and $run.ExitCode -ne 0) {
            Write-Host "  the Ghostscript installer did not produce a working binary within $GhostscriptWaitSeconds s (code $($run.ExitCode))." -ForegroundColor Yellow
        }
    } finally {
        # A ~62 MB installer is not meant to outlive the installation.
        Remove-Item -LiteralPath $installerPath -Force -ErrorAction SilentlyContinue
    }

    # The elevated installer writes PATH entries of its own; this process
    # was born with the old PATH.
    Update-SessionPath
    if (Test-GhostscriptAnswers -Path $GhostscriptExePath) {
        Add-UserPathEntry -Folder $GhostscriptBinFolder | Out-Null
        Write-Host "Ghostscript $GhostscriptVersion installed: $GhostscriptExePath" -ForegroundColor Green
        return $true
    }
    $found = Find-Command $GhostscriptBinaries
    if ($found) {
        Write-Host "Ghostscript $GhostscriptVersion installed: $found" -ForegroundColor Green
        return $true
    }

    Write-Host "Ghostscript could not be installed automatically." -ForegroundColor Yellow
    Write-Host "  Download and run it yourself from $GhostscriptUrl" -ForegroundColor Yellow
    Write-Host "  then run this installer again." -ForegroundColor Yellow
    return $false
}

Write-Host ""
Write-Host "--- External dependencies ---"

# $DownloadWorkFolder is created at the top of the script now: section 1
# downloads the python.org installer into it, long before this line runs.

# Equivalent command to run manually, if you prefer:
#   winget install --id UB-Mannheim.TesseractOCR -e --silent --accept-package-agreements --accept-source-agreements
$TesseractOk = Install-IfMissing -Name "Tesseract" -Binaries @("tesseract") -WingetId "UB-Mannheim.TesseractOCR"
if ($TesseractOk) { Update-SessionPath }

$GhostscriptOk = Install-Ghostscript -WorkFolder $DownloadWorkFolder

if (-not $TesseractOk -or -not $GhostscriptOk) {
    Write-Host ""
    Write-Host "GClaude Indexer works without these tools, but falls back to the" -ForegroundColor Yellow
    Write-Host "'rules' engine for classification and fails to convert text-less PDFs (OCR)." -ForegroundColor Yellow
}

# --- 4c. The OCR language Tesseract does not ship --------------------------
#
# `winget install UB-Mannheim.TesseractOCR` produces a Tesseract that knows
# `eng` and `osd` and nothing else. This project's default is
# `ocr_language = "por"` (config.py) — it exists to read Brazilian court
# records — so on a machine installed by the previous version of this script
# every scanned PDF died with:
#
#     ocrmypdf failed (code 3): OCR engine does not have language data for
#     the following requested languages: por
#
# Whoever cloned the repository got a system that could not do the one thing
# it is for. This block is the fix, and it belongs to the installer rather
# than to the runtime: language data is a machine-level asset, like
# Ghostscript, not something the application should be downloading while a
# job is running.
#
# WHERE THE FILE GOES, AND WHY NOT TESSDATA_PREFIX
#
# The two candidates were a private folder plus `TESSDATA_PREFIX`, or
# Tesseract's own `tessdata` with elevation. The private folder was
# rejected, for reasons that are properties of the variable rather than
# matters of taste:
#
#   * `TESSDATA_PREFIX` does not *add* a search folder, it **replaces** the
#     one Tesseract was built with. Point it at a folder of ours and `eng`
#     and `osd` stop resolving unless we copy them in too — so the price of
#     adding one language is taking custody of every language, forever,
#     including the ones the user installs later through Tesseract's own
#     installer, which would land in the folder we just shadowed.
#   * It is a user-scope environment variable, so it changes the behaviour
#     of *every* Tesseract on the machine, including programs that have
#     nothing to do with this project. An installer that silently reroutes
#     another application's data folder is doing something it was not asked
#     to do.
#   * It ages badly. A later Tesseract upgrade refreshes `C:\Program
#     Files\Tesseract-OCR\tessdata`; our shadow copy would keep serving the
#     old files, and the symptom would surface as bad OCR, not as an error.
#
# Writing into Tesseract's own folder has exactly one cost — it needs an
# administrator token — and elevation is a thing this script now knows how
# to ask for, once, for one file copy. Everything else about it is better:
# no environment variable, no shadowing, no custody of files we did not
# choose, and the language becomes available to every program on the
# machine rather than to this one.
#
# When the folder happens to be writable already (a per-user Tesseract
# install), no elevation is requested at all.
#
# WHAT IS DOWNLOADED
#
# `tessdata_fast` at the pinned commit of tag 4.1.0 — the same build
# UB-Mannheim ships: the `eng.traineddata` and `osd.traineddata` already
# present in `C:\Program Files\Tesseract-OCR\tessdata` on this machine are
# byte-for-byte the 4.1.0 `tessdata_fast` files (verified by SHA-256), so
# adding `por` from the same source keeps one consistent set rather than
# mixing training data of different vintages.
#
# Only languages with a SHA-256 pinned below can be installed. That is a
# deliberate limit, not an oversight: the rule for every download in this
# script is that the hash decides, and a hash cannot be invented for a file
# nobody has measured. A language outside the table is reported with the
# exact URL and the exact command, and skipped.

$TessdataFastCommit = "65727574dfcd264acbb0c3e07860e4e9e9b22185"   # tag 4.1.0
$TessdataUrlPrefix = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/$TessdataFastCommit/"

# Language code -> SHA-256 of <code>.traineddata at the commit above.
# `por`, `eng` and `spa` are the OCR counterparts of the three interface
# languages the project ships (i18n.AVAILABLE_LANGUAGES); `osd` is
# Tesseract's orientation/script detection model, which page-layout
# analysis falls back on.
$TessdataLanguagePins = @{
    "por" = "c4932b937207a9514b7514d518b931a99938c02a28a5a5a553f8599ed58b7deb"
    "eng" = "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"
    "spa" = "6f2e04d02774a18f01bed44b1111f2cd7f3ba7ac9dc4373cd3f898a40ea6b464"
    "osd" = "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff"
}

function Get-TesseractLanguageReport {
    <#
    .SYNOPSIS
        Asks Tesseract itself which folder it reads and which languages it
        already has.

    .DESCRIPTION
        `tesseract --list-langs` answers both questions in one call, and its
        first line names the folder in use:

            List of available languages in "C:\Program Files\Tesseract-OCR/tessdata/" (2):

        Reading it from Tesseract beats deriving it from the .exe path: it
        is the folder Tesseract will actually search, including when the
        user already has a `TESSDATA_PREFIX` of their own set — in which
        case that is where the language has to go for Tesseract to find it,
        and guessing `<exe folder>\tessdata` would put it somewhere Tesseract
        never looks. Deriving from the .exe is only the fallback, for old
        builds whose header omits the path.

        Note the mixed separators in Tesseract's own output ("...\Tesseract-OCR/tessdata/");
        they are normalised here.
    #>
    param(
        [Parameter(Mandatory)][string]$TesseractPath
    )

    $lines = @()
    try {
        # 2>&1: this command writes its list to stderr on several builds.
        $lines = @(Invoke-NativeCommand { & $TesseractPath --list-langs 2>&1 } | ForEach-Object { "$_" })
    } catch {
        $lines = @()
    }

    $folder = $null
    foreach ($line in $lines) {
        if ($line -match 'available languages in\s+"(.+?)"') {
            $folder = ($Matches[1] -replace '/', '\').TrimEnd('\')
            break
        }
    }
    if (-not $folder) {
        $folder = Join-Path (Split-Path -Parent $TesseractPath) "tessdata"
    }

    $languages = @(
        $lines |
            ForEach-Object { "$_".Trim() } |
            Where-Object { $_ -and ($_ -notmatch 'available languages') }
    )

    return [pscustomobject]@{ Folder = $folder; Languages = $languages }
}

function Test-FolderIsWritable {
    <#
    .SYNOPSIS
        $true when this process can create a file in $Folder.

    .DESCRIPTION
        Decided by trying, not by reading the ACL: the effective answer
        depends on the token, on inherited denies and on virtualisation,
        and the only reliable test is the write itself. The probe file is
        removed either way.
    #>
    param([Parameter(Mandatory)][string]$Folder)
    if (-not (Test-Path -LiteralPath $Folder -PathType Container)) { return $false }
    $probe = Join-Path $Folder ("gclaude-write-probe-{0}.tmp" -f ([guid]::NewGuid().ToString("N")))
    try {
        [System.IO.File]::WriteAllText($probe, "probe")
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        return $true
    } catch {
        return $false
    }
}

function Install-TesseractLanguage {
    <#
    .SYNOPSIS
        Puts one verified `<language>.traineddata` into Tesseract's data
        folder. Returns $true when the language is in place.
    #>
    param(
        [Parameter(Mandatory)][string]$Language,
        [Parameter(Mandatory)][string]$TargetFolder,
        [Parameter(Mandatory)][string]$WorkFolder
    )

    $fileName = "$Language.traineddata"
    $targetPath = Join-Path $TargetFolder $fileName
    $expected = $TessdataLanguagePins[$Language]

    if (-not $expected) {
        Write-Host "  '$Language': no SHA-256 is pinned for this language, so it is not installed." -ForegroundColor Yellow
        Write-Host "    Nothing here downloads a file it cannot verify. To add it by hand, take" -ForegroundColor Yellow
        Write-Host "    $Language.traineddata from https://github.com/tesseract-ocr/tessdata_fast" -ForegroundColor Yellow
        Write-Host "    and copy it into $TargetFolder (as administrator)." -ForegroundColor Yellow
        return $false
    }

    if (Test-FileMatchesHash -Path $targetPath -ExpectedSha256 $expected) {
        Write-Host "  '$Language': already installed, hash matches." -ForegroundColor Green
        return $true
    }
    if (Test-Path -LiteralPath $targetPath -PathType Leaf) {
        # Someone else's copy of the same language: theirs stays. Replacing
        # a file this installer did not put there — possibly the slower,
        # more accurate `tessdata_best` build, deliberately chosen — would
        # be a downgrade performed behind the user's back.
        Write-Host "  '$Language': present with a different build; left exactly as it is." -ForegroundColor Green
        return $true
    }

    $downloaded = Get-VerifiedDownload `
        -Url "$TessdataUrlPrefix$fileName" `
        -RequiredPrefix $TessdataUrlPrefix `
        -ExpectedSha256 $expected `
        -Destination (Join-Path $WorkFolder $fileName) `
        -Label "OCR language '$Language'"
    if (-not $downloaded) { return $false }

    try {
        if (Test-FolderIsWritable $TargetFolder) {
            Copy-Item -LiteralPath $downloaded -Destination $targetPath -Force -ErrorAction Stop
        } else {
            if (-not (Test-IsElevated)) {
                Write-Host "  $TargetFolder needs administrator rights — Windows will ask you to approve the copy (UAC)." -ForegroundColor Yellow
            }
            $copyScript = @"
`$ErrorActionPreference = 'Stop'
Copy-Item -LiteralPath '$downloaded' -Destination '$targetPath' -Force
"@
            $run = Invoke-ElevatedScript -Script $copyScript -TimeoutSeconds 120
            if (-not $run.Elevated) {
                Write-Host "  '$Language': the elevation was refused ($($run.Detail))." -ForegroundColor Yellow
                Write-Host "    Run this installer again from a PowerShell opened as administrator, or copy" -ForegroundColor Yellow
                Write-Host "    the file yourself:" -ForegroundColor Yellow
                Write-Host "    Copy-Item '$TessdataUrlPrefix$fileName' -> '$targetPath'" -ForegroundColor Yellow
                return $false
            }
        }
    } catch {
        Write-Host "  '$Language': could not be copied into $TargetFolder ($($_.Exception.Message))." -ForegroundColor Yellow
        return $false
    } finally {
        Remove-Item -LiteralPath $downloaded -Force -ErrorAction SilentlyContinue
    }

    # Hash the installed copy, not the downloaded one: the file that will be
    # loaded is the only one whose integrity means anything.
    if (-not (Test-FileMatchesHash -Path $targetPath -ExpectedSha256 $expected)) {
        Write-Host "  '$Language': the installed copy did not verify — not usable." -ForegroundColor Red
        return $false
    }

    Write-Host "  '$Language': installed into $TargetFolder." -ForegroundColor Green
    return $true
}

Write-Host ""
Write-Host "--- OCR language data ---"

if (-not $TesseractOk) {
    Write-Host "Tesseract is not installed, so there is no language data to add yet." -ForegroundColor Yellow
    Write-Host "Install Tesseract and run this installer again." -ForegroundColor Yellow
} else {
    # The language comes from the project, not from a literal repeated here:
    # `ProjectConfig.ocr_language` is the single source of truth, and the
    # point of this block is that the machine can read what the software
    # will ask it to read. -OcrLanguage overrides it for anyone whose
    # collection is in another language.
    $ConfiguredOcrLanguage = $OcrLanguage
    if (-not $ConfiguredOcrLanguage) {
        $ConfiguredOcrLanguage = "$(Invoke-NativeCommand {
            & $VenvPython -B -c "import sys; sys.path.insert(0, r'$ProjectRoot'); from gclaude_indexer.config import ProjectConfig; print(ProjectConfig.__dataclass_fields__['ocr_language'].default)"
        })".Trim()
    }
    if (-not $ConfiguredOcrLanguage) {
        # Reading the project's own default failed (a venv that is not ready
        # yet, an import error). Falling back to the documented default is
        # better than skipping OCR language setup entirely.
        $ConfiguredOcrLanguage = "por"
        Write-Host "Could not read the project's configured OCR language; assuming '$ConfiguredOcrLanguage'." -ForegroundColor Yellow
    }

    $TesseractPath = Find-Command @("tesseract")
    $TesseractReport = Get-TesseractLanguageReport -TesseractPath $TesseractPath
    Write-Host "Tesseract data folder: $($TesseractReport.Folder)"
    Write-Host "Languages already installed: $(($TesseractReport.Languages | Sort-Object) -join ', ')"

    # Tesseract's own syntax: "por+eng" means both.
    $WantedLanguages = @($ConfiguredOcrLanguage -split '\+' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    Write-Host "Project needs: $($WantedLanguages -join ', ')  (ProjectConfig.ocr_language = '$ConfiguredOcrLanguage')"

    $LanguagesOk = $true
    foreach ($language in $WantedLanguages) {
        if ($TesseractReport.Languages -contains $language) {
            Write-Host "  '$language': already available." -ForegroundColor Green
            continue
        }
        if (-not (Install-TesseractLanguage -Language $language -TargetFolder $TesseractReport.Folder -WorkFolder $DownloadWorkFolder)) {
            $LanguagesOk = $false
        }
    }

    # Proof, not assumption: ask Tesseract again.
    $TesseractReport = Get-TesseractLanguageReport -TesseractPath $TesseractPath
    $StillMissing = @($WantedLanguages | Where-Object { $TesseractReport.Languages -notcontains $_ })
    if ($StillMissing.Count -eq 0) {
        Write-Host "OCR language data ready: tesseract --list-langs reports $(($TesseractReport.Languages | Sort-Object) -join ', ')." -ForegroundColor Green
    } else {
        $LanguagesOk = $false
        Write-Host "Still missing after installation: $($StillMissing -join ', ')." -ForegroundColor Yellow
        Write-Host "Scanned PDFs in those languages will fail to convert until this is resolved;" -ForegroundColor Yellow
        Write-Host "everything else in GClaude Indexer keeps working." -ForegroundColor Yellow
    }
}

# --- 4d. Ollama and default model (optional; large downloads) --------------
# Asked separately from the block above: Ollama itself is already a few
# dozen MB, and the default model is several GB — the user should be able
# to say no to this even after saying yes to Tesseract/Ghostscript.

Write-Host ""
Write-Host "--- Ollama (local classification engine, optional) ---"

$OllamaPath = Find-Command @("ollama")
if ($OllamaPath) {
    Write-Host "Ollama OK: $OllamaPath" -ForegroundColor Green
} else {
    Write-Host "Ollama not found." -ForegroundColor Yellow
    Write-Host "  Without Ollama, the system uses the 'rules' engine — it works, it just doesn't classify with a local model." -ForegroundColor Yellow
    $OllamaCommand = "winget install --id Ollama.Ollama -e --silent --accept-package-agreements --accept-source-agreements"

    if (-not (Test-WingetAvailable)) {
        Write-Host "  winget is not available on this machine. Install manually:" -ForegroundColor Yellow
        Write-Host "  $OllamaCommand" -ForegroundColor Yellow
    } else {
        $Proceed = [bool]$AutoInstall
        if (-not $AutoInstall) {
            Write-Host "  The Ollama installer is a few dozen MB." -ForegroundColor Yellow
            $answer = Read-Host "  Install Ollama now with winget? (Y/N)"
            $Proceed = $answer -match '^[SsYy]'
        }
        if ($Proceed) {
            Write-Host "  installing Ollama ..." -ForegroundColor Cyan
            Invoke-NativeCommand { winget install --id Ollama.Ollama -e --silent --accept-package-agreements --accept-source-agreements }
            # Same reason as in Install-IfMissing: Ollama's installer puts
            # itself on PATH, and this process still holds the PATH it started
            # with. Everything below here — the default model, the GPU
            # verification — is gated on $OllamaPath being found.
            Update-SessionPath
            $OllamaPath = Find-Command @("ollama")
            if ($OllamaPath) {
                Write-Host "Ollama installed: $OllamaPath" -ForegroundColor Green
            } else {
                Write-Host "Ollama was not found after installation (you may need to open a new terminal for PATH to update)." -ForegroundColor Yellow
            }
        } else {
            Write-Host "  skipped. To install it later:" -ForegroundColor Yellow
            Write-Host "  $OllamaCommand" -ForegroundColor Yellow
        }
    }
}

if ($OllamaPath) {
    # The default model name comes from `motor_local.MODELO_LOCAL_PADRAO`
    # (the single source of truth in the project) instead of being
    # repeated here as a literal, so there aren't two versions of the
    # model name that could drift apart.
    $DefaultModel = "$(Invoke-NativeCommand { & $VenvPython -B -c "import sys; sys.path.insert(0, r'$ProjectRoot'); from gclaude_indexer.engine_local import DEFAULT_LOCAL_MODEL; print(DEFAULT_LOCAL_MODEL)" })".Trim()

    if ($DefaultModel) {
        # Straight after Ollama is installed its service may still be
        # starting, and `ollama list` then writes a connection error and
        # exits non-zero. That used to end the installation right here.
        $ModelList = Invoke-NativeCommand { & $OllamaPath list 2>$null }
        $HasDefaultModel = ($LASTEXITCODE -eq 0) -and ($ModelList -match [regex]::Escape($DefaultModel))

        if ($HasDefaultModel) {
            Write-Host "Default model ($DefaultModel) is already downloaded." -ForegroundColor Green
        } else {
            Write-Host "Default model ($DefaultModel) is not downloaded." -ForegroundColor Yellow
            $ModelCommand = "ollama pull $DefaultModel"
            $Proceed = [bool]$AutoInstall
            if (-not $AutoInstall) {
                Write-Host "  The default model download is large (several GB)." -ForegroundColor Yellow
                $answer = Read-Host "  Download the default model now? (Y/N)"
                $Proceed = $answer -match '^[SsYy]'
            }
            if ($Proceed) {
                Write-Host "  downloading $DefaultModel (this can take a while) ..." -ForegroundColor Cyan
                Invoke-NativeCommand { & $OllamaPath pull $DefaultModel }
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "Model $DefaultModel downloaded." -ForegroundColor Green
                } else {
                    Write-Host "Failed to download model $DefaultModel. To try again later:" -ForegroundColor Yellow
                    Write-Host "  $ModelCommand" -ForegroundColor Yellow
                }
            } else {
                Write-Host "  skipped. To download it later:" -ForegroundColor Yellow
                Write-Host "  $ModelCommand" -ForegroundColor Yellow
            }
        }
    }
}

# --- 4e. Hardware analysis: every GPU, and what Ollama actually needs ------
#
# What this block is allowed to do is narrow on purpose: look at the
# hardware and say out loud what it found. It installs no CUDA, no ROCm and
# no driver, and it swaps no backend. Since Phase 15 Task 2 it also writes
# no environment variable — see the block below on why the one it used to
# write is now deleted instead.
#
# The vendor facts below come from Ollama's own hardware-support page
# (https://docs.ollama.com/gpu), read while writing this:
#
#   NVIDIA  compute capability 5.0+, driver 550+ (570+ for CC 5.0-6.2).
#           CUDA ships inside Ollama. Nothing to install, nothing to set.
#   AMD     Windows ROCm list covers RX 7000 / Radeon PRO W7000 only, and
#           wants a ROCm v7 / HIP7-capable driver. Everything else AMD —
#           RDNA1 included — reaches the GPU through the Vulkan backend.
#   Intel   No CUDA and no ROCm path at all; Intel runs through the same
#           Vulkan backend, which is enabled by default and comes bundled
#           with the vendor's Windows driver. Nothing to set.
#
# Every adapter is examined, not just the first: a laptop with Intel
# graphics plus a discrete NVIDIA card is two rows in Win32_VideoController,
# and reporting only row one is how a machine gets told it has no usable GPU.

Write-Host ""
Write-Host "--- Hardware analysis: GPU and the Ollama runtime ---"

function Get-VideoControllers {
    <#
    .SYNOPSIS
        Every video adapter Windows knows about, or an empty list.
    #>
    try {
        return @(Get-CimInstance Win32_VideoController -ErrorAction Stop |
            Select-Object Name, AdapterCompatibility, DriverVersion)
    } catch {
        return @()
    }
}

function Get-NvidiaDriverVersion {
    <#
    .SYNOPSIS
        Driver branch as NVIDIA itself reports it (e.g. "566.36"), or $null.

    .DESCRIPTION
        Read from `nvidia-smi`, which ships with the NVIDIA driver. Not
        derived from the Windows driver version in WMI: that one is an
        internal build number (32.0.15.6636) whose relationship to the
        branch is a convention, not a promise. If nvidia-smi is not on
        PATH we report that we could not read it, rather than guess.
    #>
    $nvidiaSmi = Get-Command "nvidia-smi" -ErrorAction SilentlyContinue
    if (-not $nvidiaSmi) { return $null }
    try {
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $reported = Invoke-NativeCommand { & $nvidiaSmi.Source "--query-gpu=driver_version" "--format=csv,noheader" 2>$null }
        if ($LASTEXITCODE -eq 0 -and $reported) {
            return ("$reported" -split "\r?\n")[0].Trim()
        }
    } catch {
        # A driver too old for this query, or a broken install: unknown,
        # which is a fine answer — it is not an installation failure.
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    return $null
}

$NvidiaMinimumDriver = 550

$VideoControllers = Get-VideoControllers
if ($VideoControllers.Count -eq 0) {
    Write-Host "No GPU identified — GClaude Indexer runs on CPU (it works, it is just slower)." -ForegroundColor Yellow
    Write-Host "  Nothing to adjust." -ForegroundColor Green
} else {
    foreach ($controller in $VideoControllers) {
        $GpuName = "$($controller.Name)".Trim()
        if (-not $GpuName) { continue }
        $GpuVendor = "$($controller.AdapterCompatibility)".Trim()

        Write-Host ""
        Write-Host "GPU detected: $GpuName"
        if ($GpuVendor) { Write-Host "  Vendor: $GpuVendor" }

        $IsNvidia = ($GpuVendor -match "NVIDIA") -or ($GpuName -match "NVIDIA|GeForce|Quadro|RTX|GTX|TITAN|Tesla")
        $IsAmd = ($GpuVendor -match "Advanced Micro Devices|ATI Technologies|AMD") -or ($GpuName -match "AMD|Radeon")
        $IsIntel = ($GpuVendor -match "Intel") -or ($GpuName -match "Intel|Iris|UHD Graphics|HD Graphics|Arc")

        if ($IsNvidia) {
            Write-Host "  Ollama drives NVIDIA cards through CUDA, and it ships CUDA itself." -ForegroundColor Green
            Write-Host "  Nothing to install and no environment variable to set — the requirement is on the driver alone:" -ForegroundColor Green
            Write-Host "  version $NvidiaMinimumDriver or newer (570+ on compute capability 5.0-6.2, the GTX 750/900/10 era)." -ForegroundColor Green

            $NvidiaDriver = Get-NvidiaDriverVersion
            if ($NvidiaDriver) {
                $DriverBranch = 0
                if ($NvidiaDriver -match "^(\d+)") { $DriverBranch = [int]$Matches[1] }
                if ($DriverBranch -ge $NvidiaMinimumDriver) {
                    Write-Host "  Installed driver: $NvidiaDriver — meets the minimum." -ForegroundColor Green
                } elseif ($DriverBranch -gt 0) {
                    Write-Host "  Installed driver: $NvidiaDriver — older than $NvidiaMinimumDriver." -ForegroundColor Yellow
                    Write-Host "  Update it at https://www.nvidia.com/download/index.aspx (this installer does not touch GPU drivers)." -ForegroundColor Yellow
                }
            } else {
                Write-Host "  Driver version not read here (nvidia-smi is not on PATH) — check it in the NVIDIA control panel." -ForegroundColor Yellow
            }
            Write-Host "  No adjustment applied: this GPU needs none." -ForegroundColor Green
        } elseif ($IsAmd) {
            # The families on Ollama's Windows ROCm list.
            $IsWindowsRocmListed = $GpuName -match "RX\s*7[6789]00|(PRO\s*)?W7[5-9]00"

            if ($IsWindowsRocmListed) {
                Write-Host "  On Ollama's Windows ROCm list. All it needs is a ROCm v7 / HIP7-capable Adrenalin driver," -ForegroundColor Green
                Write-Host "  which the normal AMD driver package provides. Ollama ships the ROCm runtime itself." -ForegroundColor Green
                Write-Host "  No adjustment applied: this GPU needs none." -ForegroundColor Green
            } else {
                Write-Host "  Outside Ollama's Windows ROCm list, so it is served by the Vulkan backend — enabled by" -ForegroundColor Green
                Write-Host "  default and bundled with the AMD Windows driver. Nothing to install, nothing to set." -ForegroundColor Green
                Write-Host "  No adjustment applied: this GPU needs none." -ForegroundColor Green
                Write-Host "  Whether that is true on this machine is not left as a claim — it is measured a few" -ForegroundColor Green
                Write-Host "  lines below, by loading a model and reading what Ollama reports." -ForegroundColor Green
            }
        } elseif ($IsIntel) {
            Write-Host "  Ollama has no CUDA or ROCm path for Intel graphics; it reaches them through the Vulkan" -ForegroundColor Green
            Write-Host "  backend, which is enabled by default and comes bundled with the Intel Windows driver." -ForegroundColor Green
            Write-Host "  Nothing to install and no environment variable to set — keep the graphics driver current." -ForegroundColor Green
            Write-Host "  No adjustment applied: this GPU needs none." -ForegroundColor Green
        } else {
            Write-Host "  Vendor not recognized by this installer. If Ollama cannot use it, the work falls back to" -ForegroundColor Yellow
            Write-Host "  the CPU — slower, but it works. No adjustment applied: none is known for this hardware." -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "Hardware analysis complete — this installer applies no GPU adjustment on any machine." -ForegroundColor Green

# --- 4f. HSA_OVERRIDE_GFX_VERSION: removed, not written --------------------
#
# Earlier versions of this script wrote HSA_OVERRIDE_GFX_VERSION=10.3.0 on
# AMD RDNA1, as a "harmless carry-over for the ROCm path". Phase 15 Task 1
# measured what actually happens, on an RX 5700 XT with Ollama 0.33.2:
#
#   llama_prepare_model_devices: using device Vulkan0 (AMD Radeon RX 5700 XT)
#   ollama ps -> 100% GPU, 66.9 tokens/s
#   telemetry under load -> GPU 100%, 178 W, 1966 MHz, 66 °C
#
# The runtime picks Vulkan and never attempts ROCm, so the variable changes
# nothing at all. Meanwhile two contradictory values had accumulated on that
# machine — 10.3.0 in the user scope from this script, 10.1.0 in the machine
# scope from somewhere else — which is what an inert setting looks like once
# it has been written by more than one thing over time.
#
# A variable that does nothing is not free: it is a false explanation left
# lying around for whoever debugs this machine next. So it goes, and nothing
# takes its place except the measurement below.
#
# The user scope is ours to delete. The machine scope belongs to the whole
# system and needs an administrator token; if that is refused, the exact
# command is printed. What must not happen is the removal failing silently.

Write-Host ""
Write-Host "--- HSA_OVERRIDE_GFX_VERSION ---"

$HsaUserValue = [Environment]::GetEnvironmentVariable("HSA_OVERRIDE_GFX_VERSION", "User")
$HsaMachineValue = [Environment]::GetEnvironmentVariable("HSA_OVERRIDE_GFX_VERSION", "Machine")

if (-not $HsaUserValue -and -not $HsaMachineValue) {
    Write-Host "Not set in either scope — nothing to clean up, and nothing is written." -ForegroundColor Green
} else {
    Write-Host "This variable is inert for Ollama on Windows (the runtime uses Vulkan, not ROCm)," -ForegroundColor Yellow
    Write-Host "so this installer removes it instead of writing it." -ForegroundColor Yellow
}

if ($HsaUserValue) {
    try {
        # .NET deletes the variable when the value is $null.
        [Environment]::SetEnvironmentVariable("HSA_OVERRIDE_GFX_VERSION", $null, "User")
        Write-Host "  user scope:    removed (was '$HsaUserValue')." -ForegroundColor Green
    } catch {
        Write-Host "  user scope:    could not be removed ($($_.Exception.Message))." -ForegroundColor Yellow
    }
}

if ($HsaMachineValue) {
    $HsaRemoved = $false
    if (Test-IsElevated) {
        try {
            [Environment]::SetEnvironmentVariable("HSA_OVERRIDE_GFX_VERSION", $null, "Machine")
            $HsaRemoved = $true
        } catch {
            $HsaRemoved = $false
        }
    } else {
        Write-Host "  machine scope: removing it needs administrator rights (UAC)." -ForegroundColor Yellow
        $HsaRun = Invoke-ElevatedScript -Script @'
$ErrorActionPreference = 'Stop'
[Environment]::SetEnvironmentVariable("HSA_OVERRIDE_GFX_VERSION", $null, "Machine")
'@ -TimeoutSeconds 120
        $HsaRemoved = $HsaRun.Elevated -and ($HsaRun.ExitCode -eq 0)
        if (-not $HsaRun.Elevated) {
            Write-Host "  machine scope: elevation refused ($($HsaRun.Detail))." -ForegroundColor Yellow
        }
    }

    # Read it back rather than trusting the call: this is the one the user
    # may have to finish by hand, so the screen must be right about it.
    if ([Environment]::GetEnvironmentVariable("HSA_OVERRIDE_GFX_VERSION", "Machine")) {
        $HsaRemoved = $false
    }

    if ($HsaRemoved) {
        Write-Host "  machine scope: removed (was '$HsaMachineValue')." -ForegroundColor Green
    } else {
        Write-Host "  machine scope: still set to '$HsaMachineValue' and NOT removed." -ForegroundColor Yellow
        Write-Host "  It is inert, so nothing is broken by leaving it — but to be rid of it, run this" -ForegroundColor Yellow
        Write-Host "  in a PowerShell opened as administrator:" -ForegroundColor Yellow
        Write-Host '    [Environment]::SetEnvironmentVariable("HSA_OVERRIDE_GFX_VERSION", $null, "Machine")' -ForegroundColor Yellow
    }
}

if ($HsaUserValue -or $HsaMachineValue) {
    Write-Host "  Environment changes reach new processes only — restart Ollama to be sure it is gone." -ForegroundColor Yellow
}

# --- 4g. GPU verification: measured, not asserted --------------------------
#
# The user's requirement, in their words: "faça um teste de verificação se o
# ollama está rodando modelos com uso de 100% da GPU."
#
# Everything above this point is a claim about what Ollama *should* do with
# this hardware. This block loads a real model and reads what Ollama says it
# actually did, from the PROCESSOR column of `ollama ps`:
#
#   NAME          ID    SIZE    PROCESSOR   CONTEXT  UNTIL
#   gemma4:e4b    ...   9.6 GB  100% GPU    4096     4 minutes from now
#
# which is one of "100% GPU", "100% CPU" or a split like "48%/52% CPU/GPU".
# The result is printed either way — a verification that only speaks up when
# it fails is a verification nobody trusts.
#
# When the answer is not GPU, the script explains the route that exists for
# older AMD cards, as links to read. It does not download it. That is a
# recorded decision by the user and it is not a detail: ollama-for-amd is a
# third-party rebuild of Ollama with extra ROCm libraries, and an installer
# that silently replaces the user's inference runtime with a community build
# is doing something no installer should do on its own.
#
# It also does not fail the installation. A machine running on CPU is slower,
# not broken.

Write-Host ""
Write-Host "--- GPU verification (Ollama) ---"

function Get-OllamaBackend {
    <#
    .SYNOPSIS
        The compute device Ollama last chose ("Vulkan0", "CUDA0", "ROCm0"),
        or $null when the log does not say.

    .DESCRIPTION
        Read from Ollama's own server log, which names the device it bound
        to when it loaded a model:

            llama_prepare_model_devices: using device Vulkan0 (AMD Radeon RX 5700 XT) ...

        This is a read of a log file and nothing else. It never touches the
        model store — the folder holding tens of gigabytes of downloaded
        weights is not something an installer has any business writing to.
    #>
    $logPath = Join-Path $env:LOCALAPPDATA "Ollama\server.log"
    if (-not (Test-Path -LiteralPath $logPath -PathType Leaf)) { return $null }
    try {
        $line = Get-Content -LiteralPath $logPath -Tail 2000 -ErrorAction Stop |
            Select-String -Pattern 'using device (\S+)' | Select-Object -Last 1
        if ($line -and $line.Matches.Count -gt 0) { return $line.Matches[0].Groups[1].Value }
    } catch {
        # A log being written to while we read it is not an error worth
        # reporting: the PROCESSOR column below is the real answer anyway.
    }
    return $null
}

function Get-OllamaProcessorSplit {
    <#
    .SYNOPSIS
        Parses one `ollama ps` row into CPU and GPU percentages.

    .DESCRIPTION
        Not by splitting on whitespace: the PROCESSOR value itself contains
        a space ("100% GPU"), so column counting gets it wrong. Matching the
        three shapes Ollama actually prints is both shorter and right.
    #>
    param([Parameter(Mandatory)][string]$Row)

    if ($Row -match '(\d+)%\s*/\s*(\d+)%\s+CPU/GPU') {
        return [pscustomobject]@{ Cpu = [int]$Matches[1]; Gpu = [int]$Matches[2] }
    }
    if ($Row -match '(\d+)%\s+GPU') {
        return [pscustomobject]@{ Cpu = 0; Gpu = [int]$Matches[1] }
    }
    if ($Row -match '(\d+)%\s+CPU') {
        return [pscustomobject]@{ Cpu = [int]$Matches[1]; Gpu = 0 }
    }
    return $null
}

if ($SkipGpuCheck) {
    Write-Host "Skipped (-SkipGpuCheck)." -ForegroundColor Yellow
} elseif (-not $OllamaPath) {
    Write-Host "Ollama is not installed, so there is nothing to measure." -ForegroundColor Yellow
    Write-Host "  Classification falls back to the 'rules' engine, which needs no GPU at all." -ForegroundColor Yellow
} else {
    # Prefer the model the product actually uses; any other downloaded model
    # answers the same question if that one is not there.
    $GpuTestModel = $null
    $InstalledModels = @(Invoke-NativeCommand { & $OllamaPath list 2>$null })
    if ($LASTEXITCODE -eq 0) {
        foreach ($line in $InstalledModels) {
            $name = (("$line" -split '\s+') | Where-Object { $_ })[0]
            if (-not $name -or $name -eq "NAME") { continue }
            if ($name -eq $DefaultModel) { $GpuTestModel = $name; break }
            if (-not $GpuTestModel) { $GpuTestModel = $name }
        }
    }

    if (-not $GpuTestModel) {
        $SuggestedModel = $DefaultModel
        if (-not $SuggestedModel) { $SuggestedModel = "<a model>" }
        Write-Host "No model is downloaded yet, so there is nothing to load." -ForegroundColor Yellow
        Write-Host "  Run 'ollama pull $SuggestedModel' and then this installer again." -ForegroundColor Yellow
    } else {
        Write-Host "Loading $GpuTestModel to see where Ollama actually runs it (this takes a few seconds) ..." -ForegroundColor Cyan
        # A one-token answer is all that is needed: the point is to get the
        # model resident, not to generate anything. --keepalive keeps it
        # loaded just long enough for `ollama ps` to report on it.
        Invoke-NativeCommand { & $OllamaPath run $GpuTestModel --keepalive 2m "ok" 2>$null } | Out-Null

        $PsRows = @(Invoke-NativeCommand { & $OllamaPath ps 2>$null } | ForEach-Object { "$_" })
        $ModelRow = $PsRows | Where-Object { $_ -like "$GpuTestModel*" } | Select-Object -First 1
        $Split = $null
        if ($ModelRow) { $Split = Get-OllamaProcessorSplit -Row $ModelRow }

        $Backend = Get-OllamaBackend
        if ($Backend) { Write-Host "Backend chosen by Ollama: $Backend" }

        if (-not $Split) {
            Write-Host "Could not read the PROCESSOR column of 'ollama ps' for $GpuTestModel." -ForegroundColor Yellow
            Write-Host "  This says nothing bad about the machine — only that the check could not read" -ForegroundColor Yellow
            Write-Host "  its answer. Run 'ollama ps' yourself right after using the system to see it." -ForegroundColor Yellow
        } elseif ($Split.Gpu -ge 100) {
            Write-Host "$GpuTestModel is running on 100% GPU. Nothing to adjust." -ForegroundColor Green
        } elseif ($Split.Gpu -gt 0) {
            Write-Host "$GpuTestModel is split: $($Split.Gpu)% GPU / $($Split.Cpu)% CPU." -ForegroundColor Yellow
            Write-Host "  That is normally a memory question, not a driver one: the model does not fit" -ForegroundColor Yellow
            Write-Host "  entirely in this GPU's VRAM, so Ollama keeps part of it on the CPU. A smaller" -ForegroundColor Yellow
            Write-Host "  model, or a shorter context, moves the split towards the GPU." -ForegroundColor Yellow
        } else {
            Write-Host "$GpuTestModel is running on the CPU — the GPU is not being used." -ForegroundColor Yellow
            Write-Host "  It still works, it is just slower, and classification can also fall back to" -ForegroundColor Yellow
            Write-Host "  the 'rules' engine, which needs no GPU." -ForegroundColor Yellow
            Write-Host ""
            Write-Host "  First check the ordinary causes: a current vendor GPU driver (the Vulkan runtime" -ForegroundColor Yellow
            Write-Host "  ships with it), and enough free VRAM for the model you chose." -ForegroundColor Yellow
            Write-Host ""
            Write-Host "  If this is an older AMD card (pre-RDNA2, or any card outside Ollama's short" -ForegroundColor Yellow
            Write-Host "  Windows ROCm list) and it is still unused, there is a community rebuild of" -ForegroundColor Yellow
            Write-Host "  Ollama that adds ROCm libraries for those GPUs. This installer will not" -ForegroundColor Yellow
            Write-Host "  download or install it for you — it replaces your inference runtime with a" -ForegroundColor Yellow
            Write-Host "  third-party build, and that is your decision to make, after reading:" -ForegroundColor Yellow
            Write-Host "    https://github.com/likelovewant/ollama-for-amd/wiki" -ForegroundColor Yellow
            Write-Host "    https://github.com/ollama/ollama/issues/2503" -ForegroundColor Yellow
        }

        # Leave the machine as we found it: a model loaded by a verification
        # has no business staying resident afterwards.
        Invoke-NativeCommand { & $OllamaPath stop $GpuTestModel 2>$null } | Out-Null
    }
}

# --- 4h. Sensor libraries: temperature, power and clocks -------------------
#
# `sensors.py` reads GPU/CPU temperature, power draw and clocks through
# LibreHardwareMonitorLib plus the .NET Framework shims it needs at load
# time. Until now nothing installed those seven DLLs — they had been put in
# `%LOCALAPPDATA%\GClaudeIndexer\lib` by hand, so anyone cloning the
# repository got a Run screen with the sensors permanently unavailable and
# no way to fix it. This block closes that gap.
#
# Three rules govern what follows, and none of them bends:
#
#   1. The hash decides. Every file is third-party code arriving over the
#      network, so it is only installed when its SHA-256 matches the value
#      pinned below. A mismatch deletes the download and installs nothing —
#      we never ship a binary we could not verify.
#   2. A network failure is not an installation failure. Sensors are an
#      optional readout and `sensors.py` already degrades on its own when a
#      DLL is absent ("unavailable" — never a fabricated zero). So this
#      block warns and moves on; it can never abort the install.
#   3. Versions are pinned, never "latest". Each entry names the exact
#      nuget package, version and path inside the package, and each hash
#      below was measured against a known-good installation of this project
#      where the sensors worked.
#
# Source: nuget.org's flat container, which serves the immutable .nupkg
# (a zip) directly, with no redirect to follow. Only PowerShell's own
# Invoke-WebRequest / Expand-Archive / Get-FileHash are used — the brief
# for this task rules out adding a dependency to requirements.txt for it.
#
# LibreHardwareMonitorLib ships one build per architecture, and the pinned
# hash is the win-x64 one, measured on the working installation. On any
# other architecture we say so and skip, rather than install a build whose
# hash we have no attested value for.

Write-Host ""
Write-Host "--- Sensor libraries (temperature, power, clocks) ---"

$SensorLibFolder = Join-Path $LocalFolder "lib"
$NugetFlatContainer = "https://api.nuget.org/v3-flatcontainer"

# File name, nuget package, version, path inside the .nupkg, SHA-256.
$SensorLibraries = @(
    [pscustomobject]@{
        FileName = "LibreHardwareMonitorLib.dll"
        Package  = "LibreHardwareMonitorLib"
        Version  = "0.9.6"
        PathInPackage = "runtimes\win-x64\lib\net472\LibreHardwareMonitorLib.dll"
        Sha256   = "6ebc194316536ba61af5be24508ad9fcbb2ecc685e716c12e787c79530f66bf0"
    },
    [pscustomobject]@{
        FileName = "HidSharp.dll"
        Package  = "HidSharp"
        Version  = "2.6.4"
        PathInPackage = "lib\net35\HidSharp.dll"
        Sha256   = "d86690efde30ea9179f669320f39148853793b743a98b531afeaf30598e22f54"
    },
    [pscustomobject]@{
        FileName = "System.Buffers.dll"
        Package  = "System.Buffers"
        Version  = "4.5.1"
        PathInPackage = "lib\net461\System.Buffers.dll"
        Sha256   = "accccfbe45d9f08ffeed9916e37b33e98c65be012cfff6e7fa7b67210ce1fefb"
    },
    [pscustomobject]@{
        FileName = "System.Memory.dll"
        Package  = "System.Memory"
        Version  = "4.5.5"
        PathInPackage = "lib\net461\System.Memory.dll"
        Sha256   = "bf3fb84664f4097f1a8a9bc71a51dcf8cf1a905d4080a4d290da1730866e856f"
    },
    [pscustomobject]@{
        FileName = "System.Numerics.Vectors.dll"
        Package  = "System.Numerics.Vectors"
        Version  = "4.5.0"
        PathInPackage = "lib\netstandard2.0\System.Numerics.Vectors.dll"
        Sha256   = "17924e5dc87e0d6229d2dd0bcfc1fdfabd820901b13a68baa89fcb80c4d1a67f"
    },
    [pscustomobject]@{
        FileName = "System.Runtime.CompilerServices.Unsafe.dll"
        Package  = "System.Runtime.CompilerServices.Unsafe"
        Version  = "6.0.0"
        PathInPackage = "lib\net461\System.Runtime.CompilerServices.Unsafe.dll"
        Sha256   = "37768488e8ef45729bc7d9a2677633c6450042975bb96516e186da6cb9cd0dcf"
    },
    [pscustomobject]@{
        FileName = "System.Threading.AccessControl.dll"
        Package  = "System.Threading.AccessControl"
        Version  = "6.0.0"
        PathInPackage = "lib\net461\System.Threading.AccessControl.dll"
        Sha256   = "de92b6292da9300744bc3bf5495fcced945b8df0cc24b788337a1a6a014e22ed"
    }
)

# `Test-FileMatchesHash` used to be defined here. It now lives with the other
# shared helpers at the top of the script, because the Ghostscript and
# Tesseract-language blocks above need the same check and a function must
# exist before the line that calls it runs.

function Install-SensorLibrary {
    <#
    .SYNOPSIS
        Downloads one pinned DLL from nuget.org and installs it only if its
        SHA-256 matches. Returns $true when the file is in place and
        verified, $false otherwise.

    .DESCRIPTION
        Idempotent: a file already present with the right hash is left
        exactly as it is — not re-downloaded, not overwritten, not
        downgraded. Never throws: a download that fails is reported and
        returns $false, because a missing sensor DLL must not take the
        whole installation down with it.
    #>
    param(
        [Parameter(Mandatory)][psobject]$Library,
        [Parameter(Mandatory)][string]$TargetFolder,
        [Parameter(Mandatory)][string]$WorkFolder
    )

    $targetPath = Join-Path $TargetFolder $Library.FileName

    if (Test-FileMatchesHash -Path $targetPath -ExpectedSha256 $Library.Sha256) {
        Write-Host "  $($Library.FileName) $($Library.Version): already installed, hash matches." -ForegroundColor Green
        return $true
    }

    $alreadyThere = Test-Path -LiteralPath $targetPath -PathType Leaf
    if ($alreadyThere) {
        Write-Host "  $($Library.FileName): present but not the pinned build — replacing with $($Library.Version)." -ForegroundColor Yellow
    }

    $packageId = $Library.Package.ToLower()
    $fileName = "$packageId.$($Library.Version).nupkg"
    # Built by hand instead of interpolated in one piece so the URL cannot
    # be silently reshaped by a value with a slash in it.
    $url = "$NugetFlatContainer/$packageId/$($Library.Version)/$fileName"
    if (-not $url.StartsWith("https://api.nuget.org/")) {
        Write-Host "  $($Library.FileName): refusing a download URL outside nuget.org — not installed." -ForegroundColor Red
        return $false
    }

    # Expand-Archive on Windows PowerShell 5.1 insists on a .zip extension,
    # and a .nupkg is a zip.
    $archivePath = Join-Path $WorkFolder "$packageId.$($Library.Version).zip"
    $extractFolder = Join-Path $WorkFolder $Library.Package

    try {
        Invoke-WebRequest -Uri $url -OutFile $archivePath -UseBasicParsing -TimeoutSec 120 -ErrorAction Stop
    } catch {
        Write-Host "  $($Library.FileName): download failed ($($_.Exception.Message))." -ForegroundColor Yellow
        return $false
    }

    try {
        Expand-Archive -LiteralPath $archivePath -DestinationPath $extractFolder -Force -ErrorAction Stop
    } catch {
        Write-Host "  $($Library.FileName): the downloaded package could not be opened ($($_.Exception.Message))." -ForegroundColor Yellow
        Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
        return $false
    }

    $extractedPath = Join-Path $extractFolder $Library.PathInPackage
    if (-not (Test-Path -LiteralPath $extractedPath -PathType Leaf)) {
        Write-Host "  $($Library.FileName): '$($Library.PathInPackage)' is not in the package — not installed." -ForegroundColor Red
        return $false
    }

    if (-not (Test-FileMatchesHash -Path $extractedPath -ExpectedSha256 $Library.Sha256)) {
        # The one outcome with no second chance: a third-party binary whose
        # hash does not match is deleted, never installed.
        $measured = (Get-FileHash -LiteralPath $extractedPath -Algorithm SHA256).Hash.ToLower()
        Remove-Item -LiteralPath $extractedPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
        Write-Host "  $($Library.FileName): SHA-256 DOES NOT MATCH — download deleted, nothing installed." -ForegroundColor Red
        Write-Host "    expected $($Library.Sha256)" -ForegroundColor Red
        Write-Host "    measured $measured" -ForegroundColor Red
        return $false
    }

    try {
        Copy-Item -LiteralPath $extractedPath -Destination $targetPath -Force -ErrorAction Stop
    } catch {
        Write-Host "  $($Library.FileName): could not be copied into $TargetFolder ($($_.Exception.Message))." -ForegroundColor Yellow
        return $false
    }

    # Hash the installed copy too, not just the extracted one: what matters
    # is the file that will actually be loaded.
    if (-not (Test-FileMatchesHash -Path $targetPath -ExpectedSha256 $Library.Sha256)) {
        Remove-Item -LiteralPath $targetPath -Force -ErrorAction SilentlyContinue
        Write-Host "  $($Library.FileName): the installed copy did not verify — removed." -ForegroundColor Red
        return $false
    }

    Write-Host "  $($Library.FileName) $($Library.Version): downloaded, hash verified, installed." -ForegroundColor Green
    return $true
}

$SensorArchitecture = "$env:PROCESSOR_ARCHITECTURE"
if ($SensorArchitecture -ne "AMD64") {
    Write-Host "Windows on $SensorArchitecture — the sensor libraries are pinned to the verified 64-bit x86 build," -ForegroundColor Yellow
    Write-Host "so they are not installed here. Everything else works; the Run screen will simply report" -ForegroundColor Yellow
    Write-Host "temperature, power and clocks as unavailable." -ForegroundColor Yellow
} else {
    New-Item -ItemType Directory -Force -Path $SensorLibFolder | Out-Null
    $SensorWorkFolder = Join-Path ([System.IO.Path]::GetTempPath()) "GClaudeIndexer-sensor-libs"
    New-Item -ItemType Directory -Force -Path $SensorWorkFolder | Out-Null

    # TLS 1.2 explicitly: Windows PowerShell 5.1 still negotiates whatever
    # the machine's default is, and nuget.org refuses anything older.
    try {
        [Net.ServicePointManager]::SecurityProtocol =
            [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch {
        # An older .NET without the Tls12 member: leave the default alone.
    }

    Write-Host "Target folder: $SensorLibFolder"
    $SensorLibrariesInstalled = 0
    foreach ($library in $SensorLibraries) {
        if (Install-SensorLibrary -Library $library -TargetFolder $SensorLibFolder -WorkFolder $SensorWorkFolder) {
            $SensorLibrariesInstalled++
        }
    }

    Remove-Item -LiteralPath $SensorWorkFolder -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host ""
    if ($SensorLibrariesInstalled -eq $SensorLibraries.Count) {
        Write-Host "Sensor libraries ready: $SensorLibrariesInstalled of $($SensorLibraries.Count), every hash verified." -ForegroundColor Green
    } else {
        Write-Host "Sensor libraries: $SensorLibrariesInstalled of $($SensorLibraries.Count) installed." -ForegroundColor Yellow
        Write-Host "This does not stop the installation and breaks nothing: temperature, power and clocks" -ForegroundColor Yellow
        Write-Host "will read as unavailable on the Run screen. Run this installer again to retry." -ForegroundColor Yellow
    }
}

# --- 5. Desktop shortcut ----------------------------------------------------

function New-DesktopShortcut {
    <#
    .SYNOPSIS
        Creates (or replaces) a .lnk shortcut on the user's desktop.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [string]$ShortcutName = "GClaude Indexer.lnk",
        [string]$WorkingDirectory = (Split-Path -Parent $TargetPath),
        [string]$IconPath = "",
        [string]$Arguments = "",
        [string]$Description = ""
    )

    $DesktopFolder = [Environment]::GetFolderPath("Desktop")
    $ShortcutPath = Join-Path $DesktopFolder $ShortcutName

    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $TargetPath
    $Shortcut.WorkingDirectory = $WorkingDirectory
    if ($Arguments) {
        $Shortcut.Arguments = $Arguments
    }
    if ($Description) {
        $Shortcut.Description = $Description
    }
    if ($IconPath) {
        $Shortcut.IconLocation = $IconPath
    }
    $Shortcut.Save()

    return $ShortcutPath
}

Write-Host ""
if ($NoShortcut) {
    Write-Host "Desktop shortcut not created (-NoShortcut)."
} else {
    # The shortcut points to Indexer.vbs, not directly to Indexer.bat: it is
    # the .vbs that decides whether to run Indexer.bat hidden or visible
    # (visible only the first time, if the installer still needs to run) —
    # version 1.0, an explicit user request so no console window flashes
    # when opening the system.
    $IndexerVbsPath = Join-Path $ProjectRoot "Indexer.vbs"
    $ShortcutIconPath = Join-Path $ProjectRoot "logo.ico"
    $CreatedShortcutPath = New-DesktopShortcut -TargetPath $IndexerVbsPath -WorkingDirectory $ProjectRoot -IconPath $ShortcutIconPath
    Write-Host "Shortcut created: $CreatedShortcutPath" -ForegroundColor Green
}

# --- 5b. Optional CPU-sensor shortcut (phase 15, task 3) ---------------------
#
# CPU temperature and power draw are the only readings in this system that
# cannot be taken without administrator rights: LibreHardwareMonitor loads a
# kernel driver to reach those sensors, and without it every CPU sensor
# returns 0.0. GPU temperature, power and clock need none of this and are
# already read by the ordinary shortcut.
#
# So this is offered, never imposed. The shortcut above stays exactly as it
# was, and the system is complete without this one.
#
# Note what this shortcut does NOT do: it does not carry the "run as
# administrator" flag, and it does not elevate the server. It passes
# `--cpu-sensor` to the same Indexer.vbs, which makes the still
# unprivileged server spawn one small administrator child process
# (`gclaude_indexer.sensor_service`) that reads five numbers and writes them
# to a file. uvicorn, the document parsers, Ghostscript, Tesseract, the
# Ollama client and every file being indexed stay on an ordinary token —
# the same reason this installer elevates two operations rather than
# relaunching itself whole.
if (-not $NoShortcut) {
    Write-Host ""
    Write-Host "Optional: a second shortcut that also reads the CPU sensors." -ForegroundColor Cyan
    Write-Host "  What you gain: CPU temperature and power draw on the Run screen."
    Write-Host "                 (GPU temperature, power and clock already work without it.)"
    Write-Host "  What you pay:  Windows asks for administrator every time you open it."
    Write-Host "                 Only the sensor reader is elevated; the server, the indexing"
    Write-Host "                 and your documents keep running without privileges."
    Write-Host "  Saying No to that prompt is safe: the system opens as usual, just without"
    Write-Host "                 CPU temperature and power."

    $CpuSensorShortcutName = "GClaude Indexer (CPU sensor).lnk"
    $WScriptExe = Join-Path $env:WINDIR "System32\wscript.exe"
    $CpuSensorArguments = """$IndexerVbsPath"" --cpu-sensor"
    $ManualCommand = "powershell -ExecutionPolicy Bypass -File install.ps1 -CpuSensorShortcut"

    $CreateCpuSensorShortcut = [bool]$CpuSensorShortcut
    if (-not $CreateCpuSensorShortcut) {
        if ($AutoInstall) {
            # -AutoInstall says yes to downloads. It does not say yes to
            # arming a UAC prompt on every future launch of the system, on
            # a machine whose owner is not watching. -CpuSensorShortcut is
            # how an unattended install asks for this on purpose.
            Write-Host "  skipped (-AutoInstall does not create this one). To create it later:" -ForegroundColor Yellow
            Write-Host "  $ManualCommand" -ForegroundColor Yellow
        } else {
            $answer = Read-Host "  Create the ""GClaude Indexer (CPU sensor)"" shortcut too? (Y/N)"
            $CreateCpuSensorShortcut = $answer -match '^[SsYy]'
            if (-not $CreateCpuSensorShortcut) {
                Write-Host "  skipped. To create it later:" -ForegroundColor Yellow
                Write-Host "  $ManualCommand" -ForegroundColor Yellow
            }
        }
    }

    if ($CreateCpuSensorShortcut) {
        $CreatedCpuSensorPath = New-DesktopShortcut -TargetPath $WScriptExe `
            -ShortcutName $CpuSensorShortcutName `
            -Arguments $CpuSensorArguments `
            -WorkingDirectory $ProjectRoot `
            -IconPath $ShortcutIconPath `
            -Description "GClaude Indexer with the CPU sensor: asks for administrator once, for the sensor reader only."
        Write-Host "Shortcut created: $CreatedCpuSensorPath" -ForegroundColor Green
    }
} else {
    Write-Host "CPU sensor shortcut not created (-NoShortcut)."
}

# --- 5c. Record where the tools are, so the first run needs no reboot -------
#
# The reported symptom: after installing on a new computer, nothing worked
# until the machine was rebooted. The cause is not the installation. It is
# that `Add-UserPathEntry` writes PATH into the registry and broadcasts
# WM_SETTINGCHANGE, and Explorer frequently ignores the broadcast — so
# every process Explorer starts (the desktop shortcut, Indexer.vbs,
# Indexer.bat, the server, everything the server spawns) keeps the
# environment Explorer had before the install. `shutil.which("ollama")`
# returns nothing, OCR cannot find Tesseract, and only logging out or
# rebooting — which restarts Explorer — fixes it.
#
# Writing the absolute paths down here removes the dependency entirely.
# This is the one moment where the locations are known for certain, from
# the process that just installed them, with no environment variable in
# between; `gclaude_indexer/tools.py` reads this file before it consults
# PATH. Indexer.bat separately rebuilds PATH from the registry, so the two
# fixes are independent and either one is enough.
Write-Host ""
Write-Host "Recording where the installed programs are (removes the need to reboot)..." -ForegroundColor Cyan

$ToolsRecord = [ordered]@{}
foreach ($tool in @(
    @{ Key = "tesseract"; Names = @("tesseract") },
    @{ Key = "gswin64c";  Names = @("gswin64c", "gswin32c", "gs") },
    @{ Key = "ollama";    Names = @("ollama") },
    @{ Key = "nvidia-smi"; Names = @("nvidia-smi") }
)) {
    $found = Find-Command $tool.Names
    if ($found) {
        $ToolsRecord[$tool.Key] = $found
        Write-Host ("  {0}: {1}" -f $tool.Key, $found)
    } else {
        Write-Host ("  {0}: not found (the system will look it up at runtime)" -f $tool.Key) -ForegroundColor Yellow
    }
}

if ($ToolsRecord.Count -gt 0) {
    $ToolsPath = Join-Path $LocalFolder "tools.json"
    try {
        New-Item -ItemType Directory -Force -Path $LocalFolder | Out-Null
        $ToolsRecord | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $ToolsPath -Encoding UTF8
        Write-Host "Recorded in: $ToolsPath" -ForegroundColor Green
    } catch {
        # A record that cannot be written is a lost optimisation, not a
        # failed install: PATH and the known install locations still
        # resolve every one of these.
        Write-Host "Could not write $ToolsPath — the system will fall back to PATH." -ForegroundColor Yellow
    }
}

# --- 5d. Ollama settings that decide how much of the GPU gets used ----------
#
# Explicit user request: fill the VRAM before spilling into RAM. Asking
# Ollama for "as much GPU as possible" per request (`num_gpu = -1`) does
# not achieve it, because the sizes that decide what fits are read once by
# `ollama serve` at startup, from its environment — and the defaults are
# deliberately conservative. `OLLAMA_NUM_PARALLEL` alone reserves KV cache
# for four concurrent requests when this program only ever sends one, which
# is VRAM that could have held several more layers of the model.
#
# Written as *user* environment variables because the Ollama server is
# normally started by Windows, not by us: `gclaude_indexer/gpu_budget.py`
# passes the same values to any server it has to start itself, and the two
# have to agree. See that module for what each one does and why it is safe.
Write-Host ""
Write-Host "Setting the Ollama options that let the GPU be filled..." -ForegroundColor Cyan

$OllamaSettings = [ordered]@{
    "OLLAMA_MAX_LOADED_MODELS" = "1"
    "OLLAMA_NUM_PARALLEL"      = "1"
    "OLLAMA_FLASH_ATTENTION"   = "1"
    "OLLAMA_KV_CACHE_TYPE"     = "q8_0"
    "OLLAMA_GPU_OVERHEAD"      = "0"
    "OLLAMA_KEEP_ALIVE"        = "30m"
}

$OllamaSettingsChanged = $false
foreach ($name in $OllamaSettings.Keys) {
    $wanted = $OllamaSettings[$name]
    $current = [Environment]::GetEnvironmentVariable($name, "User")
    if ($current -eq $wanted) {
        Write-Host ("  {0} = {1} (already set)" -f $name, $wanted)
        continue
    }
    if ($current) {
        # Someone set it by hand, to something else. That is a decision,
        # and this installer does not overrule it — it says what it would
        # have used and moves on.
        Write-Host ("  {0} = {1} kept (this system would use {2})" -f $name, $current, $wanted) -ForegroundColor Yellow
        continue
    }
    try {
        [Environment]::SetEnvironmentVariable($name, $wanted, "User")
        Set-Item -Path ("Env:{0}" -f $name) -Value $wanted
        $OllamaSettingsChanged = $true
        Write-Host ("  {0} = {1}" -f $name, $wanted) -ForegroundColor Green
    } catch {
        Write-Host ("  could not set {0}: {1}" -f $name, $_.Exception.Message) -ForegroundColor Yellow
    }
}

if ($OllamaSettingsChanged) {
    Publish-EnvironmentChange
    # Ollama reads these once, at startup. A server already running has the
    # old values, and would go on leaving VRAM unused until the next reboot
    # — the very thing this section exists to avoid. Stopping it is safe:
    # Ollama starts again on demand, on the first request the system makes.
    $OllamaProcesses = Get-Process -Name "ollama", "ollama app" -ErrorAction SilentlyContinue
    if ($OllamaProcesses) {
        Write-Host "  restarting Ollama so it picks the new values up..." -ForegroundColor Cyan
        try {
            $OllamaProcesses | Stop-Process -Force -ErrorAction Stop
            Write-Host "  done — Ollama will start again on the first use." -ForegroundColor Green
        } catch {
            Write-Host "  could not stop Ollama; it will pick them up after the next restart." -ForegroundColor Yellow
        }
    }
}

# --- 5e. Uninstaller: no desktop shortcut ------------------------------------
#
# Explicit user decision: the uninstaller gets no shortcut on the desktop.
# The desktop is for what you open often, and an uninstaller is the
# opposite of that — a button you never mean to press, sitting next to the
# one you press every day, wearing the same icon.
#
# It stays two clicks away all the same: `Desinstalar.bat`, in this project
# folder, next to `Indexer.bat`. That file exists because Google Drive
# marks synced files as internet-sourced and Windows then refuses to run a
# .ps1 without a signature — see the note inside it.

# --- 5f. Unblock this folder's own scripts ----------------------------------
#
# Google Drive marks every file it syncs with `Zone.Identifier` /
# `ZoneId=3` — "came from the internet". Windows' default execution policy
# (RemoteSigned) then refuses to run a .ps1 from that zone without a digital
# signature, with a message that reads like the script is broken:
#
#     uninstall.ps1 is not digitally signed. You cannot run this script on
#     the current system.
#
# Every launcher in this project already passes `-ExecutionPolicy Bypass`,
# which is why the installer never hit it; the uninstaller did, the first
# time someone ran it the obvious way, straight from a PowerShell prompt.
#
# `Unblock-File` removes that mark. It is not a substitute for the launchers
# — Drive can re-apply it on the next sync of a file it re-materialises —
# but it fixes the copy sitting on this machine right now, which is the one
# the user is about to run. Nothing here changes the execution policy: that
# is a machine-wide security setting and not an installer's to touch.
Write-Host ""
Write-Host "Unblocking this folder's scripts (Google Drive marks synced files as internet-sourced)..." -ForegroundColor Cyan
try {
    $Unblocked = 0
    foreach ($script in (Get-ChildItem -LiteralPath $ProjectRoot -Filter "*.ps1" -File -ErrorAction Stop)) {
        if (Get-Content -LiteralPath $script.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue) {
            Unblock-File -LiteralPath $script.FullName -ErrorAction Stop
            Write-Host ("  unblocked: {0}" -f $script.Name) -ForegroundColor Green
            $Unblocked++
        }
    }
    if ($Unblocked -eq 0) {
        Write-Host "  nothing was marked."
    }
} catch {
    # A folder that does not support alternate data streams, or a file
    # locked by the sync client. The .bat launchers cover this case anyway.
    Write-Host "  could not unblock ($($_.Exception.Message)). Use Desinstalar.bat, which does not need it." -ForegroundColor Yellow
}

# Nothing downloaded here is meant to outlive the installation: the
# Ghostscript installer and the language files are each deleted as soon as
# they have been used, and this removes the (by now empty) folder itself.
Remove-Item -LiteralPath $DownloadWorkFolder -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== Installation complete ===" -ForegroundColor Cyan
Write-Host "To run GClaude Indexer, use the shortcut you created or Indexer.bat."
