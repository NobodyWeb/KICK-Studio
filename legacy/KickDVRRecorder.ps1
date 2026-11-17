
# Kick Studio — Windows Server v2.6
# Uses Kick's in-progress VOD/DVR playlist via the open-source UnofficialKickApp proxy.
# No Docker, WSL, system-wide Go installation, Python installation, or admin rights required.
# First run downloads a portable Go toolchain + FFmpeg, builds the proxy locally, then runs it on loopback only.

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:Runtime = Join-Path $script:Root "Runtime"
$script:Backend = Join-Path $script:Root "Backend"
$script:Downloads = Join-Path $script:Root "Recordings"
$script:Logs = Join-Path $script:Root "Logs"
$script:ApiPort = 18081
$script:ApiBase = "http://127.0.0.1:$($script:ApiPort)"
$script:ApiExe = Join-Path $script:Backend "kick-dvr-api.exe"
$script:FfmpegExe = $null
$script:ApiProcess = $null
$script:RecorderProcess = $null
$script:SetupJob = $null
$script:PendingRequest = $null
$script:CurrentTs = $null
$script:CurrentMp4 = $null
$script:CurrentErrLog = $null
$script:CurrentOutLog = $null
$script:StartedAt = $null
$script:ManualStop = $false
$script:Finishing = $false
$script:LastLog = ""
$script:ApiStartedByApp = $false
$script:PendingAction = $null
$script:CurrentTaskType = "Live DVR recording"
$script:CurrentProfile = "Original (copy)"
$script:CurrentTempFormat = "mpegts"
$script:HasLibX264 = $null

foreach ($p in @($script:Runtime, $script:Backend, $script:Downloads, $script:Logs)) {
    New-Item -ItemType Directory -Force -Path $p | Out-Null
}

function Add-Log([string]$message) {
    $stamp = (Get-Date).ToString("HH:mm:ss")
    if ($script:logBox) {
        $script:logBox.AppendText("[$stamp] $message`r`n")
        $script:logBox.SelectionStart = $script:logBox.TextLength
        $script:logBox.ScrollToCaret()
    }
}

function Quote-Arg([string]$value) {
    if ($null -eq $value) { return '""' }
    if ($value -match '[\s"]') { return '"' + $value.Replace('"', '\"') + '"' }
    return $value
}

function Get-ChannelSlug([string]$url) {
    try {
        $uri = [System.Uri]$url.Trim()
        if ($uri.Scheme -notin @("http", "https")) { return $null }
        if ($uri.Host.ToLowerInvariant() -notin @("kick.com", "www.kick.com")) { return $null }
        $parts = $uri.AbsolutePath.Trim("/").Split("/")
        if ($parts.Count -lt 1 -or [string]::IsNullOrWhiteSpace($parts[0])) { return $null }
        if ($parts[0].ToLowerInvariant() -in @("video", "videos", "categories", "clips", "search")) { return $null }
        return [regex]::Replace($parts[0], '[^A-Za-z0-9_-]', '')
    } catch { return $null }
}

function Find-LocalTools {
    $script:GoExe = Join-Path $script:Runtime "go\bin\go.exe"
    if (-not (Test-Path $script:GoExe)) {
        $foundGo = Get-ChildItem -Path $script:Runtime -Filter "go.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($foundGo) { $script:GoExe = $foundGo.FullName }
    }
    $ff = Get-ChildItem -Path $script:Runtime -Filter "ffmpeg.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($ff) { $script:FfmpegExe = $ff.FullName }
    return ((Test-Path $script:ApiExe) -and ($script:FfmpegExe -and (Test-Path $script:FfmpegExe)))
}

function Test-LibX264 {
    if ($null -ne $script:HasLibX264) { return [bool]$script:HasLibX264 }
    if (-not $script:FfmpegExe -or -not (Test-Path $script:FfmpegExe)) { return $false }
    $encoderList = (& $script:FfmpegExe -hide_banner -encoders 2>&1 | Out-String)
    $script:HasLibX264 = ($encoderList -match '(?m)\blibx264\b')
    return [bool]$script:HasLibX264
}

function Start-FirstRunSetup {
    if ($script:SetupJob) { return }

    $script:statusLabel.Text = "Initializing: downloading the DVR engine and FFmpeg..."
    $script:statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(235, 184, 82)
    $script:startButton.Enabled = $false
    Add-Log "First run: downloading portable Go, FFmpeg, and the DVR source from GitHub."
    $script:SetupJob = Start-Job -ArgumentList $script:Root -ScriptBlock {
        param($appRoot)
        $ErrorActionPreference = "Stop"
        $ProgressPreference = "SilentlyContinue"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

        $runtime = Join-Path $appRoot "Runtime"
        $backend = Join-Path $appRoot "Backend"
        $logs = Join-Path $appRoot "Logs"
        $setupLog = Join-Path $logs "setup.log"
        New-Item -ItemType Directory -Force -Path $runtime, $backend, $logs | Out-Null

        function LogSetup([string]$m) {
            Add-Content -Path $setupLog -Value ("[{0}] {1}" -f (Get-Date).ToString("HH:mm:ss"), $m)
        }

        # 1) Prefer Go installed through the official Windows MSI.
        # Check PATH first, then the standard MSI install locations.
        $goExe = $null
        $systemGo = Get-Command "go.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($systemGo -and $systemGo.Source) {
            $goExe = $systemGo.Source
        }

        if (-not $goExe) {
            $programFiles = [Environment]::GetFolderPath("ProgramFiles")
            $programFilesX86 = [Environment]::GetFolderPath("ProgramFilesX86")
            $systemCandidates = @(
                (Join-Path $programFiles "Go\bin\go.exe"),
                (Join-Path $programFilesX86 "Go\bin\go.exe")
            )
            foreach ($candidate in $systemCandidates) {
                if ($candidate -and (Test-Path $candidate)) {
                    $goExe = $candidate
                    break
                }
            }
        }

        if ($goExe) {
            $goVersionText = (& $goExe version 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -ne 0 -or $goVersionText -notmatch 'windows/amd64') {
                throw "Go was found, but it is not a valid Windows x64 build: $goVersionText"
            }
            LogSetup "Using MSI/system-installed Go: $goVersionText ($goExe)"
        }

        # If MSI-installed Go was not found, fall back to the portable archive.
        if (-not $goExe) {
            $goExe = Join-Path $runtime "go\bin\go.exe"
        }

        if (-not (Test-Path $goExe)) {
            $goZip = Join-Path $runtime "go1.27.4.windows-amd64.zip"
            $expectedGo = "178ab98950ac69ab25069307dc6ade79f3816e414cce95b4da166a115cde1e7e"
            $goUrls = @(
                "https://dl.google.com/go/go1.27.4.windows-amd64.zip",
                "https://go.dev/dl/go1.27.4.windows-amd64.zip",
                "https://golang.google.cn/dl/go1.27.4.windows-amd64.zip",
                "https://mirror.nju.edu.cn/golang/go1.27.4.windows-amd64.zip"
            )

            $goArchiveReady = $false
            if (Test-Path $goZip) {
                $existingHash = (Get-FileHash -Path $goZip -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($existingHash -eq $expectedGo) {
                    LogSetup "Using existing Go archive; SHA-256 verified."
                    $goArchiveReady = $true
                } else {
                    LogSetup "Removing incomplete or invalid Go archive."
                    Remove-Item $goZip -Force -ErrorAction SilentlyContinue
                }
            }

            if (-not $goArchiveReady) {
                $curlCmd = Get-Command "curl.exe" -ErrorAction SilentlyContinue
                foreach ($goUrl in $goUrls) {
                    Remove-Item $goZip -Force -ErrorAction SilentlyContinue
                    LogSetup "Trying Go download source: $goUrl"
                    try {
                        if ($curlCmd) {
                            $curlOutput = & $curlCmd.Source -fL --retry 2 --connect-timeout 25 --max-time 900 -A "KickDVRRecorder/2.6" -o $goZip $goUrl 2>&1
                            $curlExit = $LASTEXITCODE
                            foreach ($line in $curlOutput) { LogSetup ([string]$line) }
                            if ($curlExit -ne 0) { throw "curl exited with code $curlExit" }
                        } else {
                            Invoke-WebRequest -Uri $goUrl -OutFile $goZip -UseBasicParsing -TimeoutSec 900 -Headers @{ "User-Agent" = "Mozilla/5.0 KickDVRRecorder/2.6" }
                        }

                        if (-not (Test-Path $goZip) -or (Get-Item $goZip).Length -lt 50000000) {
                            throw "Downloaded file is missing or smaller than expected."
                        }
                        $actualGo = (Get-FileHash -Path $goZip -Algorithm SHA256).Hash.ToLowerInvariant()
                        if ($actualGo -ne $expectedGo) {
                            throw "SHA-256 mismatch: expected $expectedGo but received $actualGo"
                        }
                        $goArchiveReady = $true
                        LogSetup "Go archive downloaded and SHA-256 verified."
                        break
                    } catch {
                        LogSetup "This Go source failed: $($_.Exception.Message)"
                        Remove-Item $goZip -Force -ErrorAction SilentlyContinue
                    }
                }
            }

            if (-not $goArchiveReady) {
                throw "No MSI-installed Go was found and the portable ZIP download failed. Install Go using the official MSI, then restart the application."
            }

            Expand-Archive -Path $goZip -DestinationPath $runtime -Force
            Remove-Item $goZip -Force -ErrorAction SilentlyContinue
            $goExe = Join-Path $runtime "go\bin\go.exe"
            LogSetup "Portable Go extracted."
        } else {
            LogSetup "Using already installed Go; skipping Go ZIP download."
        }

        # 2) FFmpeg essentials, checksum fetched from the same publisher.
        $ffmpeg = Get-ChildItem -Path $runtime -Filter "ffmpeg.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $ffmpeg) {
            LogSetup "Downloading FFmpeg Essentials for Windows..."
            $ffZip = Join-Path $runtime "ffmpeg-release-essentials.zip"
            $shaText = (Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256" -UseBasicParsing).Content
            $expectedFF = [regex]::Match($shaText, '(?i)\b[0-9a-f]{64}\b').Value.ToLowerInvariant()
            if (-not $expectedFF) { throw "Could not retrieve the official FFmpeg SHA-256 checksum." }
            Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $ffZip -UseBasicParsing
            $actualFF = (Get-FileHash -Path $ffZip -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actualFF -ne $expectedFF) {
                Remove-Item $ffZip -Force -ErrorAction SilentlyContinue
                throw "SHA-256 The FFmpeg archive SHA-256 does not match the publisher checksum."
            }
            $ffDir = Join-Path $runtime "ffmpeg"
            New-Item -ItemType Directory -Force -Path $ffDir | Out-Null
            Expand-Archive -Path $ffZip -DestinationPath $ffDir -Force
            Remove-Item $ffZip -Force -ErrorAction SilentlyContinue
            LogSetup "FFmpeg extracted."
        } else {
            LogSetup "FFmpeg already exists; skipping download."
        }

        # 3) Pin a reviewed upstream commit, download source, patch bind address to loopback.
        $commit = "0e647c4a334d14f3e910cd46ace58832f27f2e19"
        $goMod = Get-ChildItem -Path $backend -Filter "go.mod" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $goMod) {
            LogSetup "Downloading UnofficialKickApp source at pinned commit $commit..."
            $srcZip = Join-Path $runtime "unofficial-kick-app.zip"
            $srcUrl = "https://codeload.github.com/orkunevran/UnofficialKickApp/zip/$commit"
            Invoke-WebRequest -Uri $srcUrl -OutFile $srcZip -UseBasicParsing
            Expand-Archive -Path $srcZip -DestinationPath $backend -Force
            Remove-Item $srcZip -Force -ErrorAction SilentlyContinue
            $goMod = Get-ChildItem -Path $backend -Filter "go.mod" -File -Recurse | Select-Object -First 1
            if (-not $goMod) { throw "go.mod was not found in the DVR source." }
        }

        $sourceDir = Split-Path -Parent $goMod.FullName
        $mainFile = Join-Path $sourceDir "cmd\server\main.go"
        $mainText = [IO.File]::ReadAllText($mainFile)
        if ($mainText -match 'Addr:\s+fmt\.Sprintf\(":%d",\s*cfg\.Port\)') {
            $mainText = [regex]::Replace(
                $mainText,
                'Addr:\s+fmt\.Sprintf\(":%d",\s*cfg\.Port\)',
                'Addr: fmt.Sprintf("127.0.0.1:%d", cfg.Port)'
            )
            [IO.File]::WriteAllText($mainFile, $mainText, (New-Object System.Text.UTF8Encoding($false)))
            LogSetup "Patched local proxy to listen on 127.0.0.1 only."
        } elseif ($mainText -notmatch '127\.0\.0\.1:%d') {
            throw "The server bind configuration differs from the reviewed version. Build stopped to prevent exposing the service to the network."
        }

        # 4) Build a self-contained Windows x64 backend using MSI Go or portable Go.
        if (-not $goExe -or -not (Test-Path $goExe)) {
            $goExe = Join-Path $runtime "go\bin\go.exe"
        }
        if (-not (Test-Path $goExe)) {
            $foundGo = Get-ChildItem -Path $runtime -Filter "go.exe" -File -Recurse | Select-Object -First 1
            if (-not $foundGo) { throw "go.exe was not found. Install Go using the official MSI and try again." }
            $goExe = $foundGo.FullName
        }

        $apiExe = Join-Path $backend "kick-dvr-api.exe"
        if (-not (Test-Path $apiExe)) {
            LogSetup "Preparing persistent Go module/build caches..."
            $moduleCache = Join-Path $appRoot "GoModules"
            $buildCache = Join-Path $appRoot "GoBuildCache"
            New-Item -ItemType Directory -Force -Path $moduleCache, $buildCache | Out-Null

            LogSetup "Building Kick DVR proxy for Windows x64. Go module downloads use fallback proxies."
            Push-Location $sourceDir
            try {
                $env:PATH = (Split-Path -Parent $goExe) + ";" + $env:PATH
                $env:GOTOOLCHAIN = "local"
                $env:CGO_ENABLED = "0"
                $env:GOOS = "windows"
                $env:GOARCH = "amd64"
                # Pipe separators make Go try the next proxy after timeouts and other errors,
                # not only after 404/410 responses.
                $env:GOPROXY = "https://goproxy.cn|https://proxy.golang.org|direct"
                $env:GOSUMDB = "sum.golang.org"
                $env:GOMODCACHE = $moduleCache
                $env:GOCACHE = $buildCache

                $buildStdout = Join-Path $logs "build.stdout.log"
                $buildStderr = Join-Path $logs "build.stderr.log"
                Remove-Item $buildStdout, $buildStderr -Force -ErrorAction SilentlyContinue

                # Start-Process captures native stdout/stderr as files. This avoids
                # Windows PowerShell treating Go's normal "go: downloading ..." stderr
                # progress lines as terminating RemoteException records.
                $buildArgumentLine = 'build -trimpath -ldflags "-s -w" -o "' + $apiExe + '" ./cmd/server'
                $buildProcess = Start-Process -FilePath $goExe `
                    -ArgumentList $buildArgumentLine `
                    -WorkingDirectory $sourceDir `
                    -PassThru -WindowStyle Hidden -Wait `
                    -RedirectStandardOutput $buildStdout `
                    -RedirectStandardError $buildStderr

                if (Test-Path $buildStdout) {
                    Get-Content -Path $buildStdout -ErrorAction SilentlyContinue |
                        ForEach-Object { LogSetup ("[go stdout] " + $_) }
                }
                if (Test-Path $buildStderr) {
                    Get-Content -Path $buildStderr -ErrorAction SilentlyContinue |
                        ForEach-Object { LogSetup ("[go stderr] " + $_) }
                }

                if ($buildProcess.ExitCode -ne 0 -or -not (Test-Path $apiExe)) {
                    $stderrTail = ""
                    if (Test-Path $buildStderr) {
                        $stderrTail = (Get-Content -Path $buildStderr -Tail 25 -ErrorAction SilentlyContinue | Out-String)
                    }
                    $stdoutTail = ""
                    if (Test-Path $buildStdout) {
                        $stdoutTail = (Get-Content -Path $buildStdout -Tail 15 -ErrorAction SilentlyContinue | Out-String)
                    }
                    throw "Kick DVR build failed. ExitCode=$($buildProcess.ExitCode). Details were saved to Logs\build.stderr.log and Logs\build.stdout.log.`r`n$stderrTail`r`n$stdoutTail"
                }
            } finally {
                Pop-Location
                Remove-Item Env:\GOOS -ErrorAction SilentlyContinue
                Remove-Item Env:\GOARCH -ErrorAction SilentlyContinue
            }
            LogSetup "Kick DVR proxy build completed."
        } else {
            LogSetup "Kick DVR proxy binary already exists; skipping build."
        }

        $ffmpeg = Get-ChildItem -Path $runtime -Filter "ffmpeg.exe" -File -Recurse | Select-Object -First 1
        if (-not $ffmpeg) { throw "ffmpeg.exe was not found." }

        [pscustomobject]@{
            ApiExe = $apiExe
            FfmpegExe = $ffmpeg.FullName
            SourceDir = $sourceDir
        }
    }

    $script:timer.Start()
}

function Ensure-ApiServer {
    try {
        $health = Invoke-RestMethod -Uri "$($script:ApiBase)/health/live" -TimeoutSec 2
        if ($health) { return $true }
    } catch {}

    if (-not (Test-Path $script:ApiExe)) {
        throw "The DVR engine has not been built yet."
    }

    $portCheck = Get-NetTCPConnection -LocalPort $script:ApiPort -State Listen -ErrorAction SilentlyContinue
    if ($portCheck) {
        throw "Port $($script:ApiPort) is already in use by another application."
    }

    $apiOut = Join-Path $script:Logs "proxy.stdout.log"
    $apiErr = Join-Path $script:Logs "proxy.stderr.log"
    $oldPort = $env:PORT
    $env:PORT = [string]$script:ApiPort
    try {
        $script:ApiProcess = Start-Process -FilePath $script:ApiExe `
            -WorkingDirectory $script:Backend `
            -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $apiOut `
            -RedirectStandardError $apiErr
        $script:ApiStartedByApp = $true
    } finally {
        if ($null -eq $oldPort) { Remove-Item Env:\PORT -ErrorAction SilentlyContinue }
        else { $env:PORT = $oldPort }
    }

    $deadline = (Get-Date).AddSeconds(35)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri "$($script:ApiBase)/health/live" -TimeoutSec 2
            if ($health) { return $true }
        } catch {}
        if ($script:ApiProcess.HasExited) {
            $tail = if (Test-Path $apiErr) { (Get-Content $apiErr -Tail 12 | Out-String) } else { "" }
            throw "The local Kick DVR server failed to start. $tail"
        }
        Start-Sleep -Milliseconds 700
    }
    throw "The local Kick DVR server did not become ready in time."
}

function Convert-HttpContentToText($response) {
    # Windows PowerShell may expose an HLS response as byte[] rather than text.
    # Casting byte[] directly to [string] produces "35 69 88 ..." (decimal bytes),
    # which is not an HLS playlist and cannot be parsed.
    $content = $response.Content
    if ($null -eq $content) { return "" }

    if ($content -is [byte[]]) {
        return ([System.Text.Encoding]::UTF8.GetString($content)).TrimStart([char]0xFEFF)
    }

    # Be defensive with other array types containing byte values.
    if ($content -is [System.Array]) {
        $isByteArray = $true
        foreach ($value in $content) {
            if ($value -isnot [byte]) { $isByteArray = $false; break }
        }
        if ($isByteArray) {
            $bytes = [byte[]]$content
            return ([System.Text.Encoding]::UTF8.GetString($bytes)).TrimStart([char]0xFEFF)
        }
    }

    $text = [string]$content

    # Some wrappers stringify byte arrays as space-separated decimal values.
    # Recover those too, but only when the whole payload unambiguously matches.
    if ($text -match '^\s*(?:\d{1,3}\s+){8,}\d{1,3}\s*$') {
        $byteMatches = [regex]::Matches($text, '\d{1,3}')
        $bytes = New-Object byte[] $byteMatches.Count
        for ($i = 0; $i -lt $byteMatches.Count; $i++) {
            $number = [int]$byteMatches[$i].Value
            if ($number -gt 255) { return $text }
            $bytes[$i] = [byte]$number
        }
        return ([System.Text.Encoding]::UTF8.GetString($bytes)).TrimStart([char]0xFEFF)
    }

    return $text.TrimStart([char]0xFEFF)
}

function Get-DvrInfo([string]$slug) {
    $url = "$($script:ApiBase)/streams/dvr/$slug"
    return Invoke-RestMethod -Uri $url -TimeoutSec 25
}

function Get-DvrVariants([string]$slug) {
    $masterUrl = "$($script:ApiBase)/streams/dvr/$slug/master.m3u8"
    $master = Invoke-WebRequest -Uri $masterUrl -UseBasicParsing -TimeoutSec 25 -Headers @{ "Accept-Encoding" = "identity" }
    $body = Convert-HttpContentToText $master

    if ([string]::IsNullOrWhiteSpace($body)) {
        throw "The master playlist is empty. HTTP status: $($master.StatusCode)"
    }

    # Save the exact response for diagnosis if Kick changes its playlist format.
    $debugPath = Join-Path $script:Logs ("{0}_master_playlist.txt" -f $slug)
    [IO.File]::WriteAllText($debugPath, $body, (New-Object System.Text.UTF8Encoding($false)))

    # Remove a possible UTF-8 BOM and normalize line endings.
    $body = $body.TrimStart([char]0xFEFF)
    $lines = $body -split "`r?`n"
    $items = @()
    $seen = @{}
    $pending = $null

    foreach ($raw in $lines) {
        $line = ([string]$raw).Trim().TrimStart([char]0xFEFF)
        if (-not $line) { continue }

        # Some HLS encoders put URI directly in the STREAM-INF attribute list.
        if ($line -match '(?i)^#EXT-X-STREAM-INF:') {
            $pending = $line
            $inlineUri = [regex]::Match($line, '(?i)\bURI="([^"]+)"')
            if ($inlineUri.Success) {
                $uriValue = $inlineUri.Groups[1].Value
                $variantMatch = [regex]::Match($uriValue, '(?i)(?:^|/)([a-z0-9_]{1,24})/playlist\.m3u8(?:[?#].*)?$')
                if ($variantMatch.Success) {
                    $variantName = $variantMatch.Groups[1].Value.ToLowerInvariant()
                    if (-not $seen.ContainsKey($variantName)) {
                        $height = 0; $bandwidth = 0
                        if ($line -match '(?i)RESOLUTION=\d+x(\d+)') { $height = [int]$Matches[1] }
                        if ($line -match '(?i)BANDWIDTH=(\d+)') { $bandwidth = [int]$Matches[1] }
                        $items += [pscustomobject]@{
                            Name = $variantName
                            Height = $height
                            Bandwidth = $bandwidth
                            Label = if ($height -gt 0) { "$($height)p / $variantName" } else { $variantName }
                            Url = "$($script:ApiBase)/streams/dvr/$slug/$variantName/playlist.m3u8"
                        }
                        $seen[$variantName] = $true
                    }
                }
            }
            continue
        }

        # Audio/video rendition URIs may be carried in EXT-X-MEDIA attributes.
        if ($line -match '(?i)^#EXT-X-MEDIA:') {
            $mediaUri = [regex]::Match($line, '(?i)\bURI="([^"]+)"')
            if ($mediaUri.Success) {
                $uriValue = $mediaUri.Groups[1].Value
                $variantMatch = [regex]::Match($uriValue, '(?i)(?:^|/)([a-z0-9_]{1,24})/playlist\.m3u8(?:[?#].*)?$')
                if ($variantMatch.Success) {
                    $variantName = $variantMatch.Groups[1].Value.ToLowerInvariant()
                    if (-not $seen.ContainsKey($variantName)) {
                        $items += [pscustomobject]@{
                            Name = $variantName
                            Height = 0
                            Bandwidth = 0
                            Label = $variantName
                            Url = "$($script:ApiBase)/streams/dvr/$slug/$variantName/playlist.m3u8"
                        }
                        $seen[$variantName] = $true
                    }
                }
            }
            continue
        }

        # Normal HLS master playlists put the variant URI on the next non-comment line.
        if (-not $line.StartsWith("#")) {
            $variantMatch = [regex]::Match($line, '(?i)(?:^|/)([a-z0-9_]{1,24})/playlist\.m3u8(?:[?#].*)?$')
            if ($variantMatch.Success) {
                $variantName = $variantMatch.Groups[1].Value.ToLowerInvariant()
                if (-not $seen.ContainsKey($variantName)) {
                    $height = 0
                    $bandwidth = 0
                    if ($pending -and $pending -match '(?i)RESOLUTION=\d+x(\d+)') { $height = [int]$Matches[1] }
                    if ($pending -and $pending -match '(?i)BANDWIDTH=(\d+)') { $bandwidth = [int]$Matches[1] }
                    $items += [pscustomobject]@{
                        Name = $variantName
                        Height = $height
                        Bandwidth = $bandwidth
                        Label = if ($height -gt 0) { "$($height)p / $variantName" } else { $variantName }
                        Url = "$($script:ApiBase)/streams/dvr/$slug/$variantName/playlist.m3u8"
                    }
                    $seen[$variantName] = $true
                }
            }
            $pending = $null
        }
    }

    if (-not $items -or $items.Count -eq 0) {
        $contentType = ""
        try { $contentType = [string]$master.Headers["Content-Type"] } catch {}
        $previewLines = @($lines | Select-Object -First 14)
        $preview = ($previewLines -join " | ")
        if ($preview.Length -gt 1200) { $preview = $preview.Substring(0, 1200) }
        $contentTypeName = if ($null -ne $master.Content) { $master.Content.GetType().FullName } else { "null" }
        Add-Log "Master playlist was received but no recognizable rendition was found. HTTP=$($master.StatusCode), Content-Type=$contentType, ContentTypeRuntime=$contentTypeName"
        Add-Log "Raw playlist saved to: $debugPath"
        Add-Log "Response preview: $preview"
        throw "Unrecognized master playlist structure. HTTP=$($master.StatusCode), Content-Type=$contentType. Raw response saved to Logs\$($slug)_master_playlist.txt."
    }

    Add-Log "Detected DVR renditions: $($items.Name -join ', ')"
    return @($items | Sort-Object Height, Bandwidth -Descending)
}

function Get-PlaylistDiagnostics([string]$mediaUrl) {
    $resp = Invoke-WebRequest -Uri $mediaUrl -UseBasicParsing -TimeoutSec 25 -Headers @{ "Accept-Encoding" = "identity" }
    $body = Convert-HttpContentToText $resp
    $segments = ([regex]::Matches($body, '(?m)^#EXTINF:')).Count
    $sequence = -1
    if ($body -match '(?m)^#EXT-X-MEDIA-SEQUENCE:(\d+)') { $sequence = [int]$Matches[1] }
    $isEvent = $body -match '(?m)^#EXT-X-PLAYLIST-TYPE:EVENT'
    $hasEndList = $body -match '(?m)^#EXT-X-ENDLIST'
    $duration = 0.0
    foreach ($m in [regex]::Matches($body, '(?m)^#EXTINF:([0-9.]+)')) {
        $v = 0.0
        if ([double]::TryParse($m.Groups[1].Value, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$v)) {
            $duration += $v
        }
    }
    return [pscustomobject]@{
        Segments = $segments
        Sequence = $sequence
        IsEvent = $isEvent
        HasEndList = $hasEndList
        DurationSeconds = $duration
    }
}

function Get-EncodingProfile([string]$profileName) {
    switch ($profileName) {
        "Balanced (720p)" {
            return [pscustomobject]@{
                Name = $profileName; TempExtension = ".mkv"; Format = "matroska"
                Description = "H.264 720p, capped near 2.8 Mbps"
                Args = @("-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=-2:min(720\,ih):flags=lanczos", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "2800k", "-bufsize", "5600k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k")
            }
        }
        "Compact (720p)" {
            return [pscustomobject]@{
                Name = $profileName; TempExtension = ".mkv"; Format = "matroska"
                Description = "H.264 720p, capped near 1.8 Mbps"
                Args = @("-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=-2:min(720\,ih):flags=lanczos", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-maxrate", "1800k", "-bufsize", "3600k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k")
            }
        }
        "Compact (480p)" {
            return [pscustomobject]@{
                Name = $profileName; TempExtension = ".mkv"; Format = "matroska"
                Description = "H.264 480p, capped near 1 Mbps"
                Args = @("-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=-2:min(480\,ih):flags=lanczos", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-maxrate", "1000k", "-bufsize", "2000k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "80k")
            }
        }
        default {
            return [pscustomobject]@{
                Name = "Original (copy)"; TempExtension = ".ts"; Format = "mpegts"
                Description = "Original source quality; no video re-encoding"
                Args = @("-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy", "-c:a", "copy")
            }
        }
    }
}

function Start-FFmpegJob([string]$inputUrl, [string]$baseName, [string]$taskType, [bool]$isLive, [string]$detail) {
    $profileName = [string]$script:encodingBox.SelectedItem
    $profile = Get-EncodingProfile $profileName
    if ($profile.Name -ne "Original (copy)" -and -not (Test-LibX264)) {
        throw "This FFmpeg build does not include the libx264 encoder. Choose Original (copy) or use an FFmpeg build that includes libx264."
    }
    $script:CurrentProfile = $profile.Name
    $script:CurrentTempFormat = $profile.Format
    $script:CurrentTs = Join-Path $script:PendingRequest.Folder ($baseName + $profile.TempExtension)
    $script:CurrentMp4 = Join-Path $script:PendingRequest.Folder ($baseName + ".mp4")
    $script:CurrentErrLog = Join-Path $script:Logs ($baseName + ".ffmpeg.stderr.log")
    $script:CurrentOutLog = Join-Path $script:Logs ($baseName + ".ffmpeg.stdout.log")
    $script:StartedAt = Get-Date
    $script:ManualStop = $false
    $script:Finishing = $false
    $script:CurrentTaskType = $taskType
    $script:LastLog = ""

    Remove-Item $script:CurrentTs, $script:CurrentMp4 -Force -ErrorAction SilentlyContinue
    $ffArgs = @("-hide_banner", "-loglevel", "info", "-stats_period", "1", "-progress", "pipe:1", "-nostats", "-nostdin", "-y")
    if ($isLive) { $ffArgs += @("-live_start_index", "0") }
    $ffArgs += @("-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36", "-referer", "https://kick.com/", "-i", $inputUrl)
    $ffArgs += $profile.Args
    $ffArgs += @("-max_muxing_queue_size", "2048", "-f", $profile.Format, $script:CurrentTs)
    $ffLine = ($ffArgs | ForEach-Object { Quote-Arg ([string]$_) }) -join " "

    $script:RecorderProcess = Start-Process -FilePath $script:FfmpegExe `
        -ArgumentList $ffLine `
        -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $script:CurrentOutLog `
        -RedirectStandardError $script:CurrentErrLog

    $script:startButton.Enabled = $false
    $script:stopButton.Enabled = $true
    $script:globalStopButton.Enabled = $true
    $script:statusLabel.Text = "$taskType is running..."
    $script:statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(87, 218, 157)
    $script:fileLabel.Text = "Output: $($script:CurrentMp4)"
    $script:qualityInfo.Text = "$detail  |  Profile: $($profile.Description)"
    Add-Log "FFmpeg started for $taskType. Profile: $($profile.Name). Input: $inputUrl"
    Add-Log "The DVR may backfill earlier minutes faster than real time. Media duration and wall-clock duration are shown separately."
    $script:timer.Start()
}

function Start-DVRRecording {
    if (-not (Ensure-ApiServer)) { throw "The local DVR API is not ready." }
    $request = $script:PendingRequest
    $url = $request.Url
    $slug = Get-ChannelSlug $url
    $script:statusLabel.Text = "Checking channel DVR availability..."
    $script:statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(235, 184, 82)
    Add-Log "Checking DVR availability for channel: $slug"

    $info = Get-DvrInfo $slug
    if (-not $info.data.available) {
        throw "Kick has not exposed an in-progress DVR recording for this channel yet. Retry shortly; the recording may not have been registered by Kick."
    }

    $startedAt = [string]$info.data.started_at
    Add-Log "DVR source detected. Reported start time: $startedAt"
    $variants = Get-DvrVariants $slug
    $qualityWanted = $request.Quality
    $chosen = $variants | Select-Object -First 1
    if ($qualityWanted -and $qualityWanted -ne "best") {
        $match = $variants | Where-Object { $_.Name -eq $qualityWanted -or $_.Label -eq $qualityWanted } | Select-Object -First 1
        if ($match) { $chosen = $match }
        else { Add-Log "The selected rendition is unavailable; the highest available rendition will be used." }
    }

    $diag = Get-PlaylistDiagnostics $chosen.Url
    if ($diag.Segments -lt 1) { throw "The DVR playlist does not contain any downloadable segments yet." }
    if ($diag.Sequence -eq 0 -and $diag.IsEvent) {
        Add-Log "DVR verified: EVENT playlist with MEDIA-SEQUENCE=0 and $($diag.Segments) segments."
        Add-Log ("Available backfill at startup: {0:N1} minutes." -f ($diag.DurationSeconds / 60))
    } else {
        Add-Log "Warning: the playlist could not be verified as starting at the beginning (sequence=$($diag.Sequence), EVENT=$($diag.IsEvent))."
        Add-Log "The recorder will start from the oldest segment currently exposed by Kick."
    }

    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $baseName = "${slug}_${stamp}_DVR"
    Start-FFmpegJob -inputUrl $chosen.Url -baseName $baseName -taskType "Live DVR recording" -isLive $true -detail "Rendition: $($chosen.Label) | Live start: $startedAt"
    Add-Log "Capture mode: start at segment zero, then follow the growing playlist until ENDLIST."
}

function Get-VodLibrary([string]$slug) {
    $response = Invoke-RestMethod -Uri "$($script:ApiBase)/streams/vods/$slug" -TimeoutSec 45
    if ($response.data -and $response.data.vods) { return @($response.data.vods) }
    return @()
}

function Get-ClipLibrary([string]$slug) {
    $response = Invoke-RestMethod -Uri "$($script:ApiBase)/streams/clips/$slug" -TimeoutSec 45
    if ($response.data -and $response.data.clips) { return @($response.data.clips) }
    return @()
}

function Format-MediaDuration($seconds) {
    $value = 0.0
    if ($null -ne $seconds) { [void][double]::TryParse([string]$seconds, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$value) }
    if ($value -le 0) { return "Duration unavailable" }
    return ([TimeSpan]::FromSeconds($value)).ToString("hh\:mm\:ss")
}

function Load-VodLibrary {
    $slug = Get-ChannelSlug $script:urlBox.Text
    if (-not $slug) { throw "Enter a valid channel URL, for example https://kick.com/channelname." }
    if (-not (Ensure-ApiServer)) { throw "The local API server is not ready." }
    $script:startButton.Enabled = $true
    $script:statusLabel.Text = "Loading VOD library..."
    $script:vodListBox.Items.Clear()
    $items = @(Get-VodLibrary $slug)
    foreach ($item in $items) {
        $id = [string]$item.vod_id
        if ([string]::IsNullOrWhiteSpace($id)) { continue }
        $title = [string]$item.title
        if ([string]::IsNullOrWhiteSpace($title)) { $title = "Untitled VOD" }
        $duration = Format-MediaDuration $item.duration_seconds
        $entry = [pscustomobject]@{ DisplayName = "$title  |  $duration  |  ID $id"; Id = $id; Title = $title; Kind = "VOD" }
        [void]$script:vodListBox.Items.Add($entry)
    }
    if ($script:vodListBox.Items.Count -eq 0) {
        $script:statusLabel.Text = "No VODs were returned for this channel."
        Add-Log "No VODs found for channel $slug."
    } else {
        $script:statusLabel.Text = "Loaded $($script:vodListBox.Items.Count) VOD item(s). Select one to download."
        Add-Log "Loaded $($script:vodListBox.Items.Count) VOD item(s) for $slug."
    }
}

function Load-ClipLibrary {
    $slug = Get-ChannelSlug $script:urlBox.Text
    if (-not $slug) { throw "Enter a valid channel URL, for example https://kick.com/channelname." }
    if (-not (Ensure-ApiServer)) { throw "The local API server is not ready." }
    $script:startButton.Enabled = $true
    $script:statusLabel.Text = "Loading clip library..."
    $script:clipListBox.Items.Clear()
    $items = @(Get-ClipLibrary $slug)
    foreach ($item in $items) {
        $id = [string]$item.clip_id
        if ([string]::IsNullOrWhiteSpace($id)) { continue }
        $title = [string]$item.title
        if ([string]::IsNullOrWhiteSpace($title)) { $title = "Untitled clip" }
        $duration = Format-MediaDuration $item.duration_seconds
        $entry = [pscustomobject]@{ DisplayName = "$title  |  $duration  |  ID $id"; Id = $id; Title = $title; Kind = "Clip" }
        [void]$script:clipListBox.Items.Add($entry)
    }
    if ($script:clipListBox.Items.Count -eq 0) {
        $script:statusLabel.Text = "No clips were returned for this channel."
        Add-Log "No clips found for channel $slug."
    } else {
        $script:statusLabel.Text = "Loaded $($script:clipListBox.Items.Count) clip(s). Select one to download."
        Add-Log "Loaded $($script:clipListBox.Items.Count) clip(s) for $slug."
    }
}

function Start-MediaDownload([string]$kind) {
    if ($script:RecorderProcess) { throw "Another FFmpeg task is already running." }
    if (-not (Ensure-ApiServer)) { throw "The local API server is not ready." }
    $slug = Get-ChannelSlug $script:urlBox.Text
    if (-not $slug) { throw "Enter a valid channel URL, for example https://kick.com/channelname." }

    if ($kind -eq "VOD") { $selected = $script:vodListBox.SelectedItem }
    else { $selected = $script:clipListBox.SelectedItem }
    if (-not $selected) { throw "Select a $kind from the list first." }

    if ($kind -eq "VOD") { $inputUrl = "$($script:ApiBase)/streams/vods/$slug/$($selected.Id)" }
    else { $inputUrl = "$($script:ApiBase)/streams/clip/$slug/$($selected.Id)" }

    $folder = $script:folderBox.Text.Trim()
    if (-not $folder) { $folder = $script:Downloads }
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $script:PendingRequest = [pscustomobject]@{ Folder = $folder }

    $safeTitle = [regex]::Replace([string]$selected.Title, '[\\/:*?"<>|]', '_')
    $safeTitle = $safeTitle.Trim(' ', '.')
    if (-not $safeTitle) { $safeTitle = $kind }
    if ($safeTitle.Length -gt 80) { $safeTitle = $safeTitle.Substring(0, 80) }
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $baseName = "$($slug)_$($kind)_$($selected.Id)_$($safeTitle)_$($stamp)"
    $taskType = if ($kind -eq "VOD") { "VOD download" } else { "Clip download" }
    Start-FFmpegJob -inputUrl $inputUrl -baseName $baseName -taskType $taskType -isLive $false -detail "Title: $($selected.Title) | ID: $($selected.Id)"
}

function Stop-DVRRecording {
    if ($script:RecorderProcess) {
        try {
            $script:RecorderProcess.Refresh()
            if (-not $script:RecorderProcess.HasExited) {
                $script:ManualStop = $true
                Stop-Process -Id $script:RecorderProcess.Id -Force -ErrorAction SilentlyContinue
                Add-Log "Stop requested. The current temporary media file will be finalized if possible."
            }
        } catch {}
    }
}

function Finalize-Recording {
    if ($script:Finishing) { return }
    $script:Finishing = $true
    $script:timer.Stop()
    $script:stopButton.Enabled = $false
    if ($script:globalStopButton) { $script:globalStopButton.Enabled = $false }
    $script:startButton.Enabled = $true

    if ($script:CurrentTs -and (Test-Path $script:CurrentTs)) {
        $size = (Get-Item $script:CurrentTs).Length
        if ($size -gt 0) {
            $script:statusLabel.Text = "Finalizing MP4..."
            $script:statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(235, 184, 82)
            $muxArgs = @("-y", "-i", $script:CurrentTs, "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart", "-f", "mp4", $script:CurrentMp4)
            $argLine = ($muxArgs | ForEach-Object { Quote-Arg ([string]$_) }) -join " "
            try {
                $mux = Start-Process -FilePath $script:FfmpegExe -ArgumentList $argLine -PassThru -WindowStyle Hidden -Wait `
                    -RedirectStandardError (Join-Path $script:Logs (([IO.Path]::GetFileNameWithoutExtension($script:CurrentMp4)) + ".finalize.stderr.log"))
                if ($mux.ExitCode -eq 0 -and (Test-Path $script:CurrentMp4) -and (Get-Item $script:CurrentMp4).Length -gt 0) {
                    $completedText = if ($script:ManualStop) { "$($script:CurrentTaskType) stopped; partial MP4 saved." } else { "$($script:CurrentTaskType) completed; MP4 saved." }
                    $script:statusLabel.Text = $completedText
                    $script:statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(87, 218, 157)
                    Add-Log "MP4 created: $($script:CurrentMp4)"
                    if (-not ($script:keepSourceCheck -and $script:keepSourceCheck.Checked)) {
                        Remove-Item $script:CurrentTs -Force -ErrorAction SilentlyContinue
                        Add-Log "Temporary source file removed to save disk space."
                    } else {
                        Add-Log "Temporary source file retained: $($script:CurrentTs)"
                    }
                } else {
                    $script:statusLabel.Text = "MP4 finalization failed; source file was preserved."
                    $script:statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(235, 184, 82)
                    Add-Log "MP4 remux failed. Source file preserved at: $($script:CurrentTs)"
                }
            } catch {
                $script:statusLabel.Text = "Finalization failed; source file was preserved."
                Add-Log "Finalization error: $($_.Exception.Message)"
            }
        } else {
            $script:statusLabel.Text = "The media file is empty."
            $script:statusLabel.ForeColor = [System.Drawing.Color]::Tomato
        }
    } else {
        $script:statusLabel.Text = "FFmpeg ended; no output file was found."
        $script:statusLabel.ForeColor = [System.Drawing.Color]::Tomato
    }

    $script:RecorderProcess = $null
    $script:Finishing = $false
    $script:qualityInfo.Text = "Ready for another task. Choose Live DVR, VOD Library, or Clip Library."
}

function Show-ActionError([string]$title, [string]$message) {
    $script:statusLabel.Text = $title
    $script:statusLabel.ForeColor = [System.Drawing.Color]::Tomato
    Add-Log "$title $message"
    [System.Windows.Forms.MessageBox]::Show($message, $title, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    $script:startButton.Enabled = $true
}

function Invoke-PendingAction {
    $action = $script:PendingAction
    $script:PendingAction = $null
    switch ($action) {
        "StartLive" { Start-DVRRecording }
        "LoadVods" { Load-VodLibrary }
        "LoadClips" { Load-ClipLibrary }
        default { $script:statusLabel.Text = "Initialization completed. Select an action." }
    }
}

# ------------------------- UI -------------------------
$form = New-Object System.Windows.Forms.Form
$form.Text = "Kick Studio | Live DVR & Media Downloader"
$form.StartPosition = "CenterScreen"
$form.Size = New-Object System.Drawing.Size(1120, 940)
$form.MinimumSize = New-Object System.Drawing.Size(1040, 860)
$form.BackColor = [System.Drawing.Color]::FromArgb(10, 15, 27)
$form.ForeColor = [System.Drawing.Color]::FromArgb(235, 241, 250)
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9.5)
$form.RightToLeft = [System.Windows.Forms.RightToLeft]::No
$form.RightToLeftLayout = $false
$form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Dpi

function Add-Label($parent, [string]$text, [int]$x, [int]$y, [int]$w, [int]$h, [int]$size = 9, [bool]$bold = $false) {
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $text
    $l.Location = New-Object System.Drawing.Point($x, $y)
    $l.Size = New-Object System.Drawing.Size($w, $h)
    $l.ForeColor = [System.Drawing.Color]::FromArgb(205, 216, 235)
    $style = if ($bold) { [System.Drawing.FontStyle]::Bold } else { [System.Drawing.FontStyle]::Regular }
    $l.Font = New-Object System.Drawing.Font("Segoe UI", $size, $style)
    $l.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
    $parent.Controls.Add($l)
    return $l
}

function Add-Button($parent, [string]$text, [int]$x, [int]$y, [int]$w, [int]$h, [System.Drawing.Color]$back, [int]$fontSize = 9) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $text
    $b.Location = New-Object System.Drawing.Point($x, $y)
    $b.Size = New-Object System.Drawing.Size($w, $h)
    $b.BackColor = $back
    $b.ForeColor = [System.Drawing.Color]::White
    $b.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $b.FlatAppearance.BorderSize = 0
    $b.FlatAppearance.MouseOverBackColor = [System.Drawing.Color]::FromArgb([Math]::Min(255, $back.R + 18), [Math]::Min(255, $back.G + 18), [Math]::Min(255, $back.B + 18))
    $b.Font = New-Object System.Drawing.Font("Segoe UI", $fontSize, [System.Drawing.FontStyle]::Bold)
    $b.Cursor = [System.Windows.Forms.Cursors]::Hand
    $parent.Controls.Add($b)
    return $b
}

function New-DarkTextBox($parent, [int]$x, [int]$y, [int]$w, [int]$h, [string]$value = "") {
    $t = New-Object System.Windows.Forms.TextBox
    $t.Location = New-Object System.Drawing.Point($x, $y)
    $t.Size = New-Object System.Drawing.Size($w, $h)
    $t.Text = $value
    $t.Font = New-Object System.Drawing.Font("Segoe UI", 10)
    $t.RightToLeft = [System.Windows.Forms.RightToLeft]::No
    $t.BackColor = [System.Drawing.Color]::FromArgb(19, 28, 45)
    $t.ForeColor = [System.Drawing.Color]::FromArgb(242, 246, 252)
    $t.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
    $t.Anchor = "Top,Left,Right"
    $parent.Controls.Add($t)
    return $t
}

# Header card
$header = New-Object System.Windows.Forms.Panel
$header.Location = New-Object System.Drawing.Point(28, 20)
$header.Size = New-Object System.Drawing.Size(1048, 104)
$header.BackColor = [System.Drawing.Color]::FromArgb(22, 34, 55)
$header.Anchor = "Top,Left,Right"
$form.Controls.Add($header)

$title = New-Object System.Windows.Forms.Label
$title.Text = "KICK STUDIO"
$title.Location = New-Object System.Drawing.Point(22, 12)
$title.Size = New-Object System.Drawing.Size(700, 42)
$title.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 23, [System.Drawing.FontStyle]::Bold)
$title.ForeColor = [System.Drawing.Color]::FromArgb(93, 226, 177)
$title.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
$title.RightToLeft = [System.Windows.Forms.RightToLeft]::No
$header.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "Live DVR capture  |  VOD downloads  |  Clip downloads"
$subtitle.Location = New-Object System.Drawing.Point(24, 58)
$subtitle.Size = New-Object System.Drawing.Size(760, 25)
$subtitle.ForeColor = [System.Drawing.Color]::FromArgb(174, 191, 216)
$subtitle.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
$header.Controls.Add($subtitle)

$versionLabel = New-Object System.Windows.Forms.Label
$versionLabel.Text = "WINDOWS SERVER  •  v2.6"
$versionLabel.Location = New-Object System.Drawing.Point(810, 34)
$versionLabel.Size = New-Object System.Drawing.Size(215, 30)
$versionLabel.ForeColor = [System.Drawing.Color]::FromArgb(119, 145, 178)
$versionLabel.Font = New-Object System.Drawing.Font("Segoe UI", 8, [System.Drawing.FontStyle]::Bold)
$versionLabel.TextAlign = [System.Drawing.ContentAlignment]::MiddleRight
$header.Controls.Add($versionLabel)

# Shared channel and output settings
Add-Label $form "KICK CHANNEL URL" 34 135 650 24 8 $true | Out-Null
$script:urlBox = New-DarkTextBox $form 34 160 650 34 "https://kick.com/"
Add-Label $form "SAVE LOCATION" 710 135 290 24 8 $true | Out-Null
$script:folderBox = New-DarkTextBox $form 710 160 290 34 $script:Downloads
$browse = Add-Button $form "Browse" 1010 160 66 34 ([System.Drawing.Color]::FromArgb(55, 76, 108)) 8
$browse.Anchor = "Top,Right"
$browse.Add_Click({
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.SelectedPath = $script:folderBox.Text
    if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $script:folderBox.Text = $dlg.SelectedPath }
})

# Shared output profile (applies to Live DVR, VOD, and Clip downloads)
Add-Label $form "OUTPUT PROFILE" 710 205 366 20 8 $true | Out-Null
$script:encodingBox = New-Object System.Windows.Forms.ComboBox
$script:encodingBox.Location = New-Object System.Drawing.Point(710, 226)
$script:encodingBox.Size = New-Object System.Drawing.Size(366, 30)
$script:encodingBox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
$script:encodingBox.BackColor = [System.Drawing.Color]::FromArgb(19, 28, 45)
$script:encodingBox.ForeColor = [System.Drawing.Color]::White
foreach ($profile in @("Original (copy)", "Balanced (720p)", "Compact (720p)", "Compact (480p)")) { [void]$script:encodingBox.Items.Add($profile) }
$script:encodingBox.SelectedIndex = 2
$form.Controls.Add($script:encodingBox)

# Main workspace tabs
$tabs = New-Object System.Windows.Forms.TabControl
$tabs.Location = New-Object System.Drawing.Point(28, 260)
$tabs.Size = New-Object System.Drawing.Size(1048, 320)
$tabs.Anchor = "Top,Left,Right"
$tabs.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
$tabs.DrawMode = [System.Windows.Forms.TabDrawMode]::Normal
$form.Controls.Add($tabs)

$liveTab = New-Object System.Windows.Forms.TabPage
$liveTab.Text = "LIVE DVR"
$liveTab.BackColor = [System.Drawing.Color]::FromArgb(15, 23, 38)
$vodTab = New-Object System.Windows.Forms.TabPage
$vodTab.Text = "VOD LIBRARY"
$vodTab.BackColor = [System.Drawing.Color]::FromArgb(15, 23, 38)
$clipTab = New-Object System.Windows.Forms.TabPage
$clipTab.Text = "CLIP LIBRARY"
$clipTab.BackColor = [System.Drawing.Color]::FromArgb(15, 23, 38)
[void]$tabs.TabPages.Add($liveTab)
[void]$tabs.TabPages.Add($vodTab)
[void]$tabs.TabPages.Add($clipTab)

# Live DVR tab
Add-Label $liveTab "STREAM QUALITY" 28 24 300 24 8 $true | Out-Null
$script:qualityBox = New-Object System.Windows.Forms.ComboBox
$script:qualityBox.Location = New-Object System.Drawing.Point(28, 52)
$script:qualityBox.Size = New-Object System.Drawing.Size(300, 32)
$script:qualityBox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
$script:qualityBox.BackColor = [System.Drawing.Color]::FromArgb(19, 28, 45)
$script:qualityBox.ForeColor = [System.Drawing.Color]::White
foreach ($q in @("best", "1080p60", "720p60", "720p30", "480p30", "360p30")) { [void]$script:qualityBox.Items.Add($q) }
$script:qualityBox.SelectedIndex = 2
$liveTab.Controls.Add($script:qualityBox)

$profileHint = Add-Label $liveTab "Output profiles reduce the saved MP4 size, not Kick network traffic. To reduce incoming data, choose a lower stream quality such as 480p or 360p." 28 100 940 36 8 $false
$profileHint.ForeColor = [System.Drawing.Color]::FromArgb(149, 171, 201)

$script:keepSourceCheck = New-Object System.Windows.Forms.CheckBox
$script:keepSourceCheck.Text = "Keep the temporary source file after MP4 is created"
$script:keepSourceCheck.Location = New-Object System.Drawing.Point(28, 142)
$script:keepSourceCheck.Size = New-Object System.Drawing.Size(570, 28)
$script:keepSourceCheck.ForeColor = [System.Drawing.Color]::FromArgb(180, 195, 218)
$script:keepSourceCheck.BackColor = $liveTab.BackColor
$script:keepSourceCheck.Checked = $false
$liveTab.Controls.Add($script:keepSourceCheck)

$script:startButton = Add-Button $liveTab "START LIVE DVR" 28 195 260 48 ([System.Drawing.Color]::FromArgb(21, 145, 103)) 10
$script:stopButton = Add-Button $liveTab "STOP TASK" 306 195 210 48 ([System.Drawing.Color]::FromArgb(164, 65, 77)) 10
$script:stopButton.Enabled = $false
$openFolder = Add-Button $liveTab "OPEN SAVE FOLDER" 534 195 250 48 ([System.Drawing.Color]::FromArgb(55, 76, 108)) 9
$openFolder.Add_Click({
    $p = $script:folderBox.Text.Trim()
    if (-not $p) { $p = $script:Downloads }
    New-Item -ItemType Directory -Force -Path $p | Out-Null
    Start-Process explorer.exe -ArgumentList (Quote-Arg $p)
})

$liveHint = Add-Label $liveTab "DVR catch-up may download earlier minutes quickly. This is historical backfill, not only the seconds elapsed since you clicked Start." 28 252 970 24 8 $false
$liveHint.ForeColor = [System.Drawing.Color]::FromArgb(231, 184, 91)

# VOD tab
$loadVodsButton = Add-Button $vodTab "LOAD CHANNEL VODS" 28 18 220 40 ([System.Drawing.Color]::FromArgb(55, 76, 108)) 9
$downloadVodButton = Add-Button $vodTab "DOWNLOAD SELECTED VOD" 266 18 260 40 ([System.Drawing.Color]::FromArgb(21, 145, 103)) 9
$script:vodListBox = New-Object System.Windows.Forms.ListBox
$script:vodListBox.Location = New-Object System.Drawing.Point(28, 72)
$script:vodListBox.Size = New-Object System.Drawing.Size(970, 188)
$script:vodListBox.Anchor = "Top,Left,Right,Bottom"
$script:vodListBox.BackColor = [System.Drawing.Color]::FromArgb(9, 15, 27)
$script:vodListBox.ForeColor = [System.Drawing.Color]::FromArgb(224, 234, 247)
$script:vodListBox.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$script:vodListBox.HorizontalScrollbar = $true
$script:vodListBox.DisplayMember = "DisplayName"
$vodTab.Controls.Add($script:vodListBox)
$vodHint = Add-Label $vodTab "Load the channel VOD list, select an item, and download it as MP4. Uses the shared output profile above." 28 270 970 22 8 $false
$vodHint.ForeColor = [System.Drawing.Color]::FromArgb(149, 171, 201)

# Clip tab
$loadClipsButton = Add-Button $clipTab "LOAD CHANNEL CLIPS" 28 18 220 40 ([System.Drawing.Color]::FromArgb(55, 76, 108)) 9
$downloadClipButton = Add-Button $clipTab "DOWNLOAD SELECTED CLIP" 266 18 270 40 ([System.Drawing.Color]::FromArgb(21, 145, 103)) 9
$script:clipListBox = New-Object System.Windows.Forms.ListBox
$script:clipListBox.Location = New-Object System.Drawing.Point(28, 72)
$script:clipListBox.Size = New-Object System.Drawing.Size(970, 188)
$script:clipListBox.Anchor = "Top,Left,Right,Bottom"
$script:clipListBox.BackColor = [System.Drawing.Color]::FromArgb(9, 15, 27)
$script:clipListBox.ForeColor = [System.Drawing.Color]::FromArgb(224, 234, 247)
$script:clipListBox.Font = New-Object System.Drawing.Font("Segoe UI", 9)
$script:clipListBox.HorizontalScrollbar = $true
$script:clipListBox.DisplayMember = "DisplayName"
$clipTab.Controls.Add($script:clipListBox)
$clipHint = Add-Label $clipTab "Load the channel clip list, select an item, and download it as MP4. Uses the shared output profile above." 28 270 970 22 8 $false
$clipHint.ForeColor = [System.Drawing.Color]::FromArgb(149, 171, 201)

# Shared status card
$panel = New-Object System.Windows.Forms.Panel
$panel.Location = New-Object System.Drawing.Point(28, 600)
$panel.Size = New-Object System.Drawing.Size(1048, 100)
$panel.BackColor = [System.Drawing.Color]::FromArgb(22, 34, 55)
$panel.Anchor = "Top,Left,Right"
$form.Controls.Add($panel)

$script:statusLabel = New-Object System.Windows.Forms.Label
$script:statusLabel.Text = "Ready. Enter a Kick channel URL and choose a task."
$script:statusLabel.Location = New-Object System.Drawing.Point(18, 10)
$script:statusLabel.Size = New-Object System.Drawing.Size(805, 25)
$script:statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(235, 184, 82)
$script:statusLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
$script:statusLabel.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
$panel.Controls.Add($script:statusLabel)
$script:globalStopButton = Add-Button $panel "STOP CURRENT TASK" 842 8 184 34 ([System.Drawing.Color]::FromArgb(164, 65, 77)) 8
$script:globalStopButton.Enabled = $false
$script:globalStopButton.Add_Click({ Stop-DVRRecording })

$script:sizeLabel = New-Object System.Windows.Forms.Label
$script:sizeLabel.Text = "File size: —  |  Media captured: —  |  Wall time: —  |  Speed: —"
$script:sizeLabel.Location = New-Object System.Drawing.Point(18, 40)
$script:sizeLabel.Size = New-Object System.Drawing.Size(1008, 22)
$script:sizeLabel.ForeColor = [System.Drawing.Color]::FromArgb(180, 194, 215)
$script:sizeLabel.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
$panel.Controls.Add($script:sizeLabel)

$script:fileLabel = New-Object System.Windows.Forms.Label
$script:fileLabel.Text = "Output: no active task"
$script:fileLabel.Location = New-Object System.Drawing.Point(18, 66)
$script:fileLabel.Size = New-Object System.Drawing.Size(1008, 20)
$script:fileLabel.ForeColor = [System.Drawing.Color]::FromArgb(145, 163, 190)
$script:fileLabel.Font = New-Object System.Drawing.Font("Segoe UI", 8)
$script:fileLabel.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
$panel.Controls.Add($script:fileLabel)

$script:qualityInfo = Add-Label $form "Ready for a new task." 30 710 1040 24 8 $false
$script:qualityInfo.ForeColor = [System.Drawing.Color]::FromArgb(155, 175, 202)
Add-Label $form "ACTIVITY LOG" 30 740 1040 22 8 $true | Out-Null
$script:logBox = New-Object System.Windows.Forms.TextBox
$script:logBox.Location = New-Object System.Drawing.Point(28, 765)
$script:logBox.Size = New-Object System.Drawing.Size(1048, 105)
$script:logBox.Anchor = "Top,Left,Right,Bottom"
$script:logBox.Multiline = $true
$script:logBox.ReadOnly = $true
$script:logBox.ScrollBars = [System.Windows.Forms.ScrollBars]::Vertical
$script:logBox.BackColor = [System.Drawing.Color]::FromArgb(6, 10, 19)
$script:logBox.ForeColor = [System.Drawing.Color]::FromArgb(195, 211, 232)
$script:logBox.Font = New-Object System.Drawing.Font("Consolas", 8.5)
$script:logBox.RightToLeft = [System.Windows.Forms.RightToLeft]::No
$form.Controls.Add($script:logBox)

# Task buttons
$script:startButton.Add_Click({
    if ($script:RecorderProcess -or $script:SetupJob) { return }
    $slug = Get-ChannelSlug $script:urlBox.Text
    if (-not $slug) {
        [System.Windows.Forms.MessageBox]::Show("Enter a valid channel URL, such as https://kick.com/channelname.", "Invalid channel URL") | Out-Null
        return
    }
    $folder = $script:folderBox.Text.Trim()
    if (-not $folder) { $folder = $script:Downloads }
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $script:PendingRequest = [pscustomobject]@{ Url = $script:urlBox.Text.Trim(); Folder = $folder; Quality = [string]$script:qualityBox.SelectedItem }
    $script:PendingAction = "StartLive"
    if (-not (Find-LocalTools)) { Start-FirstRunSetup; return }
    try { Invoke-PendingAction } catch { Show-ActionError "Live DVR could not start." $_.Exception.Message }
})

$script:stopButton.Add_Click({ Stop-DVRRecording })
$loadVodsButton.Add_Click({
    if ($script:RecorderProcess -or $script:SetupJob) { return }
    $script:PendingAction = "LoadVods"
    if (-not (Find-LocalTools)) { Start-FirstRunSetup; return }
    try { Invoke-PendingAction } catch { Show-ActionError "VOD library could not be loaded." $_.Exception.Message }
})
$loadClipsButton.Add_Click({
    if ($script:RecorderProcess -or $script:SetupJob) { return }
    $script:PendingAction = "LoadClips"
    if (-not (Find-LocalTools)) { Start-FirstRunSetup; return }
    try { Invoke-PendingAction } catch { Show-ActionError "Clip library could not be loaded." $_.Exception.Message }
})
$downloadVodButton.Add_Click({
    if ($script:RecorderProcess -or $script:SetupJob) { return }
    try { Start-MediaDownload "VOD" } catch { Show-ActionError "VOD download could not start." $_.Exception.Message }
})
$downloadClipButton.Add_Click({
    if ($script:RecorderProcess -or $script:SetupJob) { return }
    try { Start-MediaDownload "Clip" } catch { Show-ActionError "Clip download could not start." $_.Exception.Message }
})

$script:timer = New-Object System.Windows.Forms.Timer
$script:timer.Interval = 1000
$script:timer.Add_Tick({
    if ($script:SetupJob) {
        $job = $script:SetupJob
        if ($job.State -eq "Completed") {
            $null = Receive-Job -Job $job -ErrorAction SilentlyContinue
            Remove-Job -Job $job -Force
            $script:SetupJob = $null
            Find-LocalTools | Out-Null
            if ((Test-Path $script:ApiExe) -and $script:FfmpegExe) {
                Add-Log "Initialization completed."
                try { Invoke-PendingAction } catch { Show-ActionError "The requested task could not start." $_.Exception.Message }
            } else {
                $script:statusLabel.Text = "Initialization incomplete. Check Logs\setup.log."
                $script:statusLabel.ForeColor = [System.Drawing.Color]::Tomato
                Add-Log "One or more required executables were not created."
                $script:startButton.Enabled = $true
            }
        } elseif ($job.State -in @("Failed", "Stopped")) {
            $reason = ""
            try { $reason = [string]$job.ChildJobs[0].JobStateInfo.Reason } catch {}
            $null = Receive-Job -Job $job -ErrorAction SilentlyContinue
            Remove-Job -Job $job -Force
            $script:SetupJob = $null
            $script:statusLabel.Text = "Initialization failed."
            $script:statusLabel.ForeColor = [System.Drawing.Color]::Tomato
            Add-Log "Setup error: $reason"
            $setupLog = Join-Path $script:Logs "setup.log"
            if (Test-Path $setupLog) { foreach ($line in (Get-Content $setupLog -Tail 8)) { Add-Log $line } }
            [System.Windows.Forms.MessageBox]::Show("Initialization failed. Check Logs\setup.log.`r`n$reason", "Setup failed") | Out-Null
            $script:startButton.Enabled = $true
        }
    }

    if ($script:RecorderProcess) {
        try {
            $script:RecorderProcess.Refresh()
            if ($script:CurrentTs -and (Test-Path $script:CurrentTs)) {
                $f = Get-Item $script:CurrentTs
                $elapsed = (Get-Date) - $script:StartedAt
                $mediaTime = "—"
                $speedText = "—"
                if ($script:CurrentOutLog -and (Test-Path $script:CurrentOutLog)) {
                    $progressLines = @(Get-Content -Path $script:CurrentOutLog -Tail 100 -ErrorAction SilentlyContinue)
                    $progressText = $progressLines -join "`n"
                    $timeMatches = [regex]::Matches($progressText, '(?m)^out_time=(\d{2}:\d{2}:\d{2}(?:\.\d+)?)')
                    if ($timeMatches.Count -gt 0) { $mediaTime = $timeMatches[$timeMatches.Count - 1].Groups[1].Value }
                    $speedMatches = [regex]::Matches($progressText, '(?m)^speed=\s*([0-9.]+x)')
                    if ($speedMatches.Count -gt 0) { $speedText = $speedMatches[$speedMatches.Count - 1].Groups[1].Value }
                }
                if ($script:CurrentErrLog -and (Test-Path $script:CurrentErrLog)) {
                    $tail = @(Get-Content -Path $script:CurrentErrLog -Tail 8 -ErrorAction SilentlyContinue)
                    $joined = ($tail -join "`r`n")
                    if ($joined -and $joined -ne $script:LastLog) {
                        $script:LastLog = $joined
                        $script:logBox.Text = $joined
                        $script:logBox.SelectionStart = $script:logBox.TextLength
                        $script:logBox.ScrollToCaret()
                    }
                }
                $avgRate = "—"
                if ($mediaTime -match '^(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?$') {
                    $mediaSeconds = ([int]$Matches[1] * 3600) + ([int]$Matches[2] * 60) + [int]$Matches[3]
                    if ($Matches[4]) { $mediaSeconds += [double]::Parse(("0." + $Matches[4]), [Globalization.CultureInfo]::InvariantCulture) }
                    if ($mediaSeconds -gt 0) { $avgRate = ("{0:N1} Mbps" -f (($f.Length * 8.0) / $mediaSeconds / 1000000.0)) }
                }
                $script:sizeLabel.Text = ("File: {0:N1} MB  |  Media: {1}  |  Wall: {2:hh\:mm\:ss}  |  Speed: {3}  |  Avg: {4}" -f ($f.Length / 1MB), $mediaTime, $elapsed, $speedText, $avgRate)
            }
            if ($script:RecorderProcess.HasExited) {
                $code = $script:RecorderProcess.ExitCode
                Add-Log "FFmpeg process exited. Exit code: $code"
                Finalize-Recording
            }
        } catch { Add-Log "Error while checking FFmpeg status: $($_.Exception.Message)" }
    }

    if ($script:ApiProcess) {
        try {
            $script:ApiProcess.Refresh()
            if ($script:ApiProcess.HasExited) {
                Add-Log "The DVR server has stopped."
                $script:ApiProcess = $null
            }
        } catch {}
    }

    $setupLog = Join-Path $script:Logs "setup.log"
    if ($script:SetupJob -and (Test-Path $setupLog)) {
        $last = Get-Content $setupLog -Tail 1 -ErrorAction SilentlyContinue
        if ($last) { $script:statusLabel.Text = [string]$last }
    }
})

if (Find-LocalTools) {
    $script:statusLabel.Text = "DVR engine is ready. Enter a channel URL to begin."
    $script:statusLabel.ForeColor = [System.Drawing.Color]::FromArgb(87, 218, 157)
    Add-Log "Local runtime files detected."
} else {
    Add-Log "First run: required portable components will be downloaded and built when you start a task."
}

$form.Add_FormClosing({
    if ($script:RecorderProcess) {
        try {
            $script:RecorderProcess.Refresh()
            if (-not $script:RecorderProcess.HasExited) {
                $choice = [System.Windows.Forms.MessageBox]::Show(
                    "A task is still running. Exiting will stop it. Do you want to continue?",
                    "Task in progress", [System.Windows.Forms.MessageBoxButtons]::YesNo,
                    [System.Windows.Forms.MessageBoxIcon]::Warning
                )
                if ($choice -eq [System.Windows.Forms.DialogResult]::No) {
                    $_.Cancel = $true
                } else {
                    Stop-Process -Id $script:RecorderProcess.Id -Force -ErrorAction SilentlyContinue
                }
            }
        } catch {}
    }
    if ($script:SetupJob) {
        Stop-Job -Job $script:SetupJob -ErrorAction SilentlyContinue
        Remove-Job -Job $script:SetupJob -Force -ErrorAction SilentlyContinue
    }
    if ($script:ApiStartedByApp -and $script:ApiProcess) {
        try { Stop-Process -Id $script:ApiProcess.Id -Force -ErrorAction SilentlyContinue } catch {}
    }
})

[void]$form.ShowDialog()
