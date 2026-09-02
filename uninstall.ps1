<#
.SYNOPSIS
    Removes GClaude Indexer from this machine, item by item, with
    confirmation.

.DESCRIPTION
    Explicit user request: the system had no uninstaller. This is it.

    It is organised around one distinction, and everything else follows
    from it.

    WHAT THIS INSTALLATION OWNS is removed on request without ceremony:
    the virtual environment, the desktop shortcuts, the local catalog and
    settings, the sensor DLLs, the unpacked Ghostscript, the PATH entries
    and environment variables the installer added. Nothing else on the
    machine put them there and nothing else uses them.

    WHAT THIS INSTALLATION MERELY INSTALLED is a different matter.
    Tesseract, Ghostscript, Ollama and Python are ordinary programs that
    other software on this machine may depend on — the installer chose
    them, it does not own them. Each is offered separately, with what is
    known about who else might be using it, and removed only if you say so.
    `-RemoveAll` says yes to all of them in one go; `-KeepDependencies`
    says no to all of them.

    WHAT IT NEVER TOUCHES, under any flag, is your work: the projects'
    output folders, the databases inside them, the OCR'd PDFs, the
    generated indexes. Those are documents, not installation artefacts.
    The script lists where they are so you can decide about them yourself,
    in your own time, with Explorer.

    Also never touched: the Ollama model store. Tens of gigabytes of
    downloaded weights are worth a deliberate decision, so removing it is
    its own separate question rather than a footnote to removing Ollama.

.PARAMETER RemoveAll
    Answers yes to every question, including the shared dependencies.
    Still never deletes project folders.

.PARAMETER KeepDependencies
    Answers no to every shared dependency (Tesseract, Ghostscript, Ollama,
    Python, the model store) and yes to everything this installation owns.
    The usual choice for a machine that uses those programs for other work.

.PARAMETER WhatIfOnly
    Lists exactly what would be removed and removes nothing. Run this
    first if you want to see the plan.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File uninstall.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File uninstall.ps1 -KeepDependencies

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File uninstall.ps1 -WhatIfOnly
#>

param(
    [switch]$RemoveAll,
    [switch]$KeepDependencies,
    [switch]$WhatIfOnly
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LocalFolder = Join-Path $env:LOCALAPPDATA "GClaudeIndexer"
$DesktopFolder = [Environment]::GetFolderPath("Desktop")

# Everything removed, for the summary at the end. A list, not a running
# count: a person deciding whether the machine is clean wants to see the
# names.
$Removed = New-Object System.Collections.Generic.List[string]
$Kept = New-Object System.Collections.Generic.List[string]

function Invoke-NativeCommand {
    <#
    .SYNOPSIS
        Runs a scriptblock calling an external .exe without letting a line
        of its stderr end the script.

    .DESCRIPTION
        Same reason as in install.ps1: under `$ErrorActionPreference =
        "Stop"`, any stderr output from a native program becomes a
        terminating NativeCommandError. An uninstaller is exactly where
        that must not happen — `winget uninstall` for a package that is not
        installed writes to stderr, and the script would die halfway
        through, having removed some things and not others.
    #>
    param([Parameter(Mandatory)][scriptblock]$Body)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Body } finally { $ErrorActionPreference = $previous }
}

function Confirm-Step {
    <#
    .SYNOPSIS
        Asks about one item. Returns $true to remove it.

    .DESCRIPTION
        The default is No for everything: an uninstaller that removes
        something because the user pressed Enter too quickly is worse than
        one that leaves a folder behind.
    #>
    param(
        [Parameter(Mandatory)][string]$Title,
        [string]$Detail = "",
        [switch]$IsSharedDependency
    )

    Write-Host ""
    Write-Host $Title -ForegroundColor Cyan
    if ($Detail) { Write-Host "  $Detail" }

    if ($WhatIfOnly) { return $false }
    if ($RemoveAll) { Write-Host "  yes (-RemoveAll)" -ForegroundColor Yellow; return $true }
    if ($IsSharedDependency -and $KeepDependencies) {
        Write-Host "  no (-KeepDependencies)" -ForegroundColor Yellow
        return $false
    }
    if ($KeepDependencies -and -not $IsSharedDependency) {
        Write-Host "  yes (-KeepDependencies removes what belongs to this installation)" -ForegroundColor Yellow
        return $true
    }

    $answer = Read-Host "  Remove it? (y/N)"
    return $answer -match '^[SsYy]'
}

function Remove-PathEntry {
    <#
    .SYNOPSIS
        Takes a folder out of this user's PATH, in the registry.

    .DESCRIPTION
        Read and written with `DoNotExpandEnvironmentNames` and the
        original value kind, for the same reason `Add-UserPathEntry` does
        in install.ps1: the .NET convenience API expands `%USERPROFILE%`
        entries and writes the expanded text back, silently freezing a
        PATH the user deliberately wrote with variables in it. Removing an
        entry must not rewrite the other twenty.
    #>
    param([Parameter(Mandatory)][string]$Folder)
    try {
        $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $true)
        if (-not $key) { return $false }
        try {
            $stored = [string]$key.GetValue(
                "Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
            if (-not $stored) { return $false }
            $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
            try { $kind = $key.GetValueKind("Path") } catch { }
            $entries = @($stored -split ';' | Where-Object { $_ })
            $kept = @($entries | Where-Object { $_.TrimEnd('\') -ne $Folder.TrimEnd('\') })
            if ($kept.Count -eq $entries.Count) { return $false }
            $key.SetValue("Path", ($kept -join ';'), $kind)
            return $true
        } finally { $key.Close() }
    } catch {
        Write-Host "  could not edit PATH ($($_.Exception.Message)); remove $Folder by hand." -ForegroundColor Yellow
        return $false
    }
}

function Publish-EnvironmentChange {
    <#
    .SYNOPSIS
        Tells running programs that the environment changed.
    #>
    try {
        if (-not ("GClaudeIndexer.EnvironmentBroadcast" -as [type])) {
            Add-Type -Namespace "GClaudeIndexer" -Name "EnvironmentBroadcast" -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll", SetLastError = true, CharSet = System.Runtime.InteropServices.CharSet.Auto)]
public static extern System.IntPtr SendMessageTimeout(System.IntPtr hWnd, uint Msg, System.IntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out System.UIntPtr lpdwResult);
'@
        }
        $result = [System.UIntPtr]::Zero
        [GClaudeIndexer.EnvironmentBroadcast]::SendMessageTimeout(
            [System.IntPtr]0xffff, 0x1A, [System.IntPtr]::Zero, "Environment", 2, 5000, [ref]$result) | Out-Null
    } catch {
        # Cosmetic: the values are already out of the registry either way.
    }
}

function Remove-ItemSafely {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        $Removed.Add($Label)
        Write-Host "  removed: $Path" -ForegroundColor Green
        return $true
    } catch {
        Write-Host "  could not remove $Path ($($_.Exception.Message))." -ForegroundColor Yellow
        Write-Host "  Close the system (and any window using the folder) and run this again." -ForegroundColor Yellow
        return $false
    }
}

function Get-FolderSizeMb {
    param([Parameter(Mandatory)][string]$Path)
    try {
        $bytes = (Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
        if (-not $bytes) { return 0 }
        return [math]::Round($bytes / 1MB)
    } catch { return 0 }
}

function Get-KnownProjectFolders {
    <#
    .SYNOPSIS
        The output folders of every project this machine knows about.

    .DESCRIPTION
        Read from the catalogs, local and shared, purely to *list* them.
        Nothing in this script deletes any of them — that is the point of
        reading them: an uninstaller that leaves gigabytes of a user's
        indexed documents behind without saying where is not finished, and
        one that deletes them is unforgivable.
    #>
    $folders = New-Object System.Collections.Generic.List[string]
    $catalogs = @(Join-Path $LocalFolder "projects.json")

    $settingsPath = Join-Path $LocalFolder "settings.json"
    if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
        try {
            $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($settings.shared_catalog_folder) {
                $catalogs += (Join-Path $settings.shared_catalog_folder "projects.json")
            }
        } catch { }
    }

    foreach ($catalog in $catalogs) {
        if (-not (Test-Path -LiteralPath $catalog -PathType Leaf)) { continue }
        try {
            $entries = Get-Content -LiteralPath $catalog -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($entry in @($entries)) {
                if ($entry.output_folder -and -not $folders.Contains($entry.output_folder)) {
                    $folders.Add($entry.output_folder)
                }
            }
        } catch { }
    }
    return $folders
}

function Uninstall-WingetPackage {
    <#
    .SYNOPSIS
        Removes a package through winget. $true when winget reports success.
    #>
    param([Parameter(Mandatory)][string]$Id)
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }
    Invoke-NativeCommand {
        winget uninstall --id $Id -e --silent --disable-interactivity | Out-Null
    }
    return ($LASTEXITCODE -eq 0)
}

# --- 0. What is on this machine ---------------------------------------------

Write-Host "=== GClaude Indexer Uninstaller ===" -ForegroundColor Cyan
Write-Host "Project folder (synced, never touched): $ProjectRoot"
Write-Host "This machine's local folder:            $LocalFolder"
if ($WhatIfOnly) {
    Write-Host ""
    Write-Host "-WhatIfOnly: listing what would be removed. Nothing will be deleted." -ForegroundColor Yellow
}

$ProjectFolders = Get-KnownProjectFolders
Write-Host ""
Write-Host "Your indexed projects (NEVER removed by this uninstaller):" -ForegroundColor Cyan
if ($ProjectFolders.Count -eq 0) {
    Write-Host "  none recorded in the catalog."
} else {
    foreach ($folder in $ProjectFolders) {
        if (Test-Path -LiteralPath $folder) {
            Write-Host ("  {0}  ({1} MB)" -f $folder, (Get-FolderSizeMb $folder))
        } else {
            Write-Host ("  {0}  (not on this machine)" -f $folder)
        }
    }
    Write-Host "  Delete these yourself if you want to, once you are sure." -ForegroundColor Yellow
}

# Stop the running system first. Every removal below either holds a file
# open or is invalidated by a process that will rewrite it a second later.
$Running = Get-Process -Name "pythonw", "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($LocalFolder, [System.StringComparison]::OrdinalIgnoreCase) }
if ($Running -and -not $WhatIfOnly) {
    Write-Host ""
    Write-Host "The GClaude Indexer server is running. Closing it..." -ForegroundColor Cyan
    try {
        $Running | Stop-Process -Force -ErrorAction Stop
        Start-Sleep -Milliseconds 500
        Write-Host "  closed." -ForegroundColor Green
    } catch {
        Write-Host "  could not close it; close the browser window and run this again." -ForegroundColor Yellow
    }
}

# --- 1. What this installation owns -----------------------------------------

if (Confirm-Step -Title "Desktop shortcuts" -Detail "GClaude Indexer, (CPU sensor) and (uninstall).") {
    foreach ($name in @(
        "GClaude Indexer.lnk",
        "GClaude Indexer (CPU sensor).lnk",
        "GClaude Indexer (uninstall).lnk"
    )) {
        Remove-ItemSafely -Path (Join-Path $DesktopFolder $name) -Label "shortcut: $name" | Out-Null
    }
} else { $Kept.Add("desktop shortcuts") }

$VenvFolder = Join-Path $LocalFolder "venv"
if (Confirm-Step -Title "Python virtual environment" `
        -Detail ("$VenvFolder ({0} MB) — every Python package this system installed." -f (Get-FolderSizeMb $VenvFolder))) {
    Remove-ItemSafely -Path $VenvFolder -Label "virtual environment" | Out-Null
} else { $Kept.Add("virtual environment") }

$LibFolder = Join-Path $LocalFolder "lib"
if (Confirm-Step -Title "Sensor libraries (LibreHardwareMonitor + .NET shims)" `
        -Detail "$LibFolder — only this system reads them.") {
    Remove-ItemSafely -Path $LibFolder -Label "sensor libraries" | Out-Null
} else { $Kept.Add("sensor libraries") }

# The unpacked Ghostscript, as opposed to a system-wide one: this copy was
# put here by install.ps1 and nothing else on the machine knows about it,
# so it is not a shared dependency and is offered here rather than below.
$LocalGhostscript = Join-Path $LocalFolder "gs"
if (Test-Path -LiteralPath $LocalGhostscript) {
    if (Confirm-Step -Title "Ghostscript unpacked into this system's own folder" `
            -Detail ("$LocalGhostscript ({0} MB) — this copy is private to GClaude Indexer." -f (Get-FolderSizeMb $LocalGhostscript))) {
        if (Remove-ItemSafely -Path $LocalGhostscript -Label "local Ghostscript") {
            $binFolder = Join-Path $LocalGhostscript "bin"
            if (Remove-PathEntry -Folder $binFolder) {
                Write-Host "  removed from PATH: $binFolder" -ForegroundColor Green
                Publish-EnvironmentChange
            }
        }
    } else { $Kept.Add("local Ghostscript") }
}

if (Confirm-Step -Title "Local settings, project catalog and cached state" `
        -Detail ("$LocalFolder — the project list, the shared-catalog setting, tools.json, " +
                 "the sensor snapshot and the server log. Your projects themselves are NOT here.")) {
    # The remaining contents, one by one rather than the folder wholesale:
    # something above may have been kept, and this must not take it with it.
    foreach ($name in @(
        "projects.json", "settings.json", "tools.json", "sincronizacao.json",
        "requirements.sha256", "sensor_snapshot.json", "sensor_helper_status.txt",
        "servidor.log", "helper"
    )) {
        $path = Join-Path $LocalFolder $name
        if (Test-Path -LiteralPath $path) {
            Remove-ItemSafely -Path $path -Label "local state: $name" | Out-Null
        }
    }
    # And the folder itself, only if nothing was kept inside it.
    if ((Test-Path -LiteralPath $LocalFolder) -and
        -not (Get-ChildItem -LiteralPath $LocalFolder -Force -ErrorAction SilentlyContinue)) {
        Remove-ItemSafely -Path $LocalFolder -Label "local folder" | Out-Null
    }
} else { $Kept.Add("local settings and catalog") }

# The environment variables install.ps1 wrote for Ollama's benefit. Removed
# only when they still hold the values this installation set: a user who
# changed one afterwards meant it, and it is not this script's to undo.
$OllamaSettings = [ordered]@{
    "OLLAMA_MAX_LOADED_MODELS" = "1"
    "OLLAMA_NUM_PARALLEL"      = "1"
    "OLLAMA_FLASH_ATTENTION"   = "1"
    "OLLAMA_KV_CACHE_TYPE"     = "q8_0"
    "OLLAMA_GPU_OVERHEAD"      = "0"
    "OLLAMA_KEEP_ALIVE"        = "30m"
}
$OwnedVariables = @($OllamaSettings.Keys | Where-Object {
    [Environment]::GetEnvironmentVariable($_, "User") -eq $OllamaSettings[$_]
})
if ($OwnedVariables.Count -gt 0) {
    if (Confirm-Step -Title "Ollama environment variables set by the installer" `
            -Detail ($OwnedVariables -join ", ")) {
        foreach ($name in $OwnedVariables) {
            try {
                [Environment]::SetEnvironmentVariable($name, $null, "User")
                $Removed.Add("environment variable: $name")
                Write-Host "  removed: $name" -ForegroundColor Green
            } catch {
                Write-Host "  could not remove $name ($($_.Exception.Message))." -ForegroundColor Yellow
            }
        }
        Publish-EnvironmentChange
    } else { $Kept.Add("Ollama environment variables") }
}

# --- 2. Shared dependencies -------------------------------------------------

Write-Host ""
Write-Host "--- Shared programs ---" -ForegroundColor Cyan
Write-Host "These were installed for GClaude Indexer but are ordinary programs."
Write-Host "Other software on this machine may be using them. Each is asked separately."

$SharedDependencies = @(
    @{
        Title = "Tesseract OCR"
        Detail = "The OCR engine. Also used by other scanning and PDF tools."
        Command = "tesseract"
        WingetId = "UB-Mannheim.TesseractOCR"
    },
    @{
        Title = "Ghostscript (system-wide install)"
        Detail = "PDF/PostScript processing. Used by many PDF and printing tools."
        Command = "gswin64c"
        WingetId = "ArtifexSoftware.GhostScript"
    },
    @{
        Title = "Ollama"
        Detail = "The local model server. Removing it does NOT remove the downloaded models — that is the next question."
        Command = "ollama"
        WingetId = "Ollama.Ollama"
    },
    @{
        # Offered by winget id rather than by looking for `python` on PATH:
        # this is specifically the 3.12 the installer may have put here, and
        # a machine can easily have three other Pythons that must not be
        # matched by a `Get-Command python`.
        Title = "Python 3.12 (the version this installer may have added)"
        Detail = "The interpreter. Almost certainly used by other things on this machine — say no unless you are sure."
        Command = $null
        WingetId = "Python.Python.3.12"
    }
)

foreach ($dependency in $SharedDependencies) {
    if ($dependency.Command) {
        $found = Get-Command $dependency.Command -ErrorAction SilentlyContinue
        if (-not $found) {
            Write-Host ""
            Write-Host ("{0}: not installed (nothing to remove)." -f $dependency.Title)
            continue
        }
    }
    if (Confirm-Step -Title $dependency.Title -Detail $dependency.Detail -IsSharedDependency) {
        Write-Host "  removing through winget..."
        if (Uninstall-WingetPackage -Id $dependency.WingetId) {
            $Removed.Add($dependency.Title)
            Write-Host "  removed." -ForegroundColor Green
        } else {
            Write-Host "  winget could not remove it. Use Settings > Apps > Installed apps." -ForegroundColor Yellow
        }
    } else { $Kept.Add($dependency.Title) }
}

# The model store, asked separately from Ollama itself: this is tens of
# gigabytes that took hours to download, and re-downloading it is the most
# expensive mistake this script could cause.
$ModelStore = Join-Path $env:USERPROFILE ".ollama\models"
if (Test-Path -LiteralPath $ModelStore) {
    if (Confirm-Step -Title "Downloaded Ollama models" `
            -Detail ("$ModelStore ({0} MB). Re-downloading these takes hours." -f (Get-FolderSizeMb $ModelStore)) `
            -IsSharedDependency) {
        Remove-ItemSafely -Path $ModelStore -Label "Ollama models" | Out-Null
    } else { $Kept.Add("Ollama models") }
}

# --- 3. Summary --------------------------------------------------------------

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
if ($WhatIfOnly) {
    Write-Host "Nothing was removed (-WhatIfOnly)."
    Write-Host "Run without that switch to be asked about each item."
} else {
    if ($Removed.Count -eq 0) {
        Write-Host "Nothing was removed."
    } else {
        Write-Host "Removed:" -ForegroundColor Green
        foreach ($item in $Removed) { Write-Host "  - $item" }
    }
    if ($Kept.Count -gt 0) {
        Write-Host "Kept:" -ForegroundColor Yellow
        foreach ($item in $Kept) { Write-Host "  - $item" }
    }
}

Write-Host ""
Write-Host "The project folder itself ($ProjectRoot) was not touched." -ForegroundColor Cyan
Write-Host "It is synced by Google Drive: delete it there if you want it gone from every computer,"
Write-Host "and remember that doing so removes it for the other machines too."
if ($ProjectFolders.Count -gt 0) {
    Write-Host ""
    Write-Host "Your indexed projects are still where they were, listed at the top of this run." -ForegroundColor Cyan
}
