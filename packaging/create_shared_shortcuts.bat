@echo off
rem Keep this file UTF-8 without BOM and CRLF line endings: the PowerShell
rem block below is executed by reading this very file. Saving as ANSI or with
rem a BOM breaks the first line with no usable error message.
rem IMPORTANT: the cmd section above "# POWERSHELL-BEGIN" must stay ASCII-only.
rem cmd reads it with the OEM code page (CP950 here), and UTF-8 Chinese bytes
rem can decode into "&" or "|", which cmd then treats as a command separator.
setlocal

set "PSD_SOURCE_DIR=%~dp0"
set "PSD_BAT_FILE=%~f0"

powershell.exe -NoLogo -NoProfile -Command "$content = [IO.File]::ReadAllText($env:PSD_BAT_FILE, [Text.Encoding]::UTF8); $marker = '# POWERSHELL-BEGIN'; $start = $content.LastIndexOf($marker); if ($start -lt 0) { throw 'PowerShell section not found.' }; Invoke-Expression $content.Substring($start + $marker.Length)"

set "PSD_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %PSD_EXIT%

# POWERSHELL-BEGIN
$ErrorActionPreference = 'Stop'
$notNetworkMessage = '目前資料夾不是 SMB/UNC 網路路徑，也不在本機任何分享底下；請從網路分享、映射網路磁碟，或伺服器上已分享的資料夾內執行。'
$retryMessage = '請修復網路連線後重新執行 BAT。'

function Resolve-LocalShare([string] $localPath) {
    # 管理者直接在伺服器本機執行時，路徑是 C:\... 而非 UNC。
    # 取「Path 能對上且最長」的分享，組回 \\本機名稱\分享名\剩餘路徑。
    # ⚠️ 只認一般磁碟分享（Type 0）並排除 C$／D$／ADMIN$ 這類管理共用：
    # 管理共用一定存在且涵蓋整顆磁碟，若不排除，任何本機路徑都會被解成
    # \\本機\D$\...，做出一般使用者根本打不開的捷徑。
    try {
        $shares = @(Get-CimInstance -ClassName Win32_Share -ErrorAction Stop |
            Where-Object {
                $_.Path -and $_.Path -match '^[A-Za-z]:' -and
                $_.Type -eq 0 -and -not ([string] $_.Name).EndsWith('$')
            })
    } catch {
        return $null
    }
    $best = $null
    $bestLength = -1
    foreach ($share in $shares) {
        $sharePath = ([string] $share.Path).TrimEnd([char] 92)
        $isSame = $localPath.Equals($sharePath, [StringComparison]::OrdinalIgnoreCase)
        $isChild = $localPath.StartsWith($sharePath + [char] 92,
            [StringComparison]::OrdinalIgnoreCase)
        if (($isSame -or $isChild) -and $sharePath.Length -gt $bestLength) {
            $best = $share
            $bestLength = $sharePath.Length
        }
    }
    if ($null -eq $best) { return $null }
    $rest = $localPath.Substring($bestLength).TrimStart([char] 92)
    $unc = [string] ([char] 92) + [char] 92 + $env:COMPUTERNAME + [char] 92 + $best.Name
    if ($rest) { $unc = $unc + [char] 92 + $rest }
    return $unc
}

try {
    $sourceDirectory = ($env:PSD_SOURCE_DIR).TrimEnd([char] 92)
    if ([string]::IsNullOrWhiteSpace($sourceDirectory)) {
        throw '無法判斷 BAT 所在資料夾。'
    }

    if ($sourceDirectory.StartsWith('\\')) {
        $uncDirectory = $sourceDirectory
    } elseif ($sourceDirectory -match '^[A-Za-z]:\\') {
        $drive = $sourceDirectory.Substring(0, 2)
        $mappedDrives = (New-Object -ComObject WScript.Network).EnumNetworkDrives()
        $ProviderName = $null
        for ($index = 0; $index -lt $mappedDrives.Count(); $index += 2) {
            if ([string]::Equals([string] $mappedDrives.Item($index), $drive,
                    [StringComparison]::OrdinalIgnoreCase)) {
                $ProviderName = [string] $mappedDrives.Item($index + 1)
                break
            }
        }
        if ([string]::IsNullOrWhiteSpace($ProviderName) -or
                -not $ProviderName.StartsWith('\\')) {
            # 不是映射網路磁碟：可能是管理者直接在伺服器本機執行，
            # 改用 Win32_Share 反查該路徑是否落在某個分享底下。
            $uncDirectory = Resolve-LocalShare $sourceDirectory
            if ([string]::IsNullOrWhiteSpace($uncDirectory)) {
                throw $notNetworkMessage
            }
        } else {
            $uncDirectory = $ProviderName.TrimEnd([char] 92) +
                $sourceDirectory.Substring(2)
        }
    } else {
        throw $notNetworkMessage
    }

    $uncDirectory = $uncDirectory.TrimEnd([char] 92)
    if ($uncDirectory.Contains('%')) {
        throw '資料夾名稱不可包含 %，請移除後重新執行 BAT。'
    }
    if ($uncDirectory -notmatch '^\\\\[^\\]+\\[^\\]+') {
        throw 'BAT 必須放在 SMB 分享底下才能建立共用捷徑。'
    }
    # 放在分享根目錄（\\伺服器\分享）時沒有可用的上一層，捷徑就建在同一層；
    # 放在內層資料夾時維持既有行為：建在上一層，使用者不必進到內層。
    $atShareRoot = ($uncDirectory -notmatch '^\\\\[^\\]+\\[^\\]+\\.+$')

    $fullExe = Join-Path $uncDirectory 'Police-Document-Manager.exe'
    $entryExe = Join-Path $uncDirectory 'Police-Entry-Manager.exe'
    $database = Join-Path $uncDirectory 'dbfile.db'
    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($requiredPath in @($fullExe, $entryExe, $database)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            $missing.Add([IO.Path]::GetFileName($requiredPath))
        }
    }
    if ($missing.Count -gt 0) {
        throw ('找不到必要檔案：' + ($missing -join ', ') +
            '。請確認兩支 EXE、dbfile.db 和 BAT 都在同一個資料夾。')
    }

    if ($atShareRoot) {
        $parentDirectory = $uncDirectory
    } else {
        $parentDirectory = Split-Path -Parent $uncDirectory
    }
    if ([string]::IsNullOrWhiteSpace($parentDirectory) -or
            -not (Test-Path -LiteralPath $parentDirectory -PathType Container)) {
        throw '找不到要建立捷徑的資料夾。'
    }

    $fullDestination = Join-Path $parentDirectory '公文收發管理系統.lnk'
    $entryDestination = Join-Path $parentDirectory '公文快速登錄系統.lnk'
    if ((Test-Path -LiteralPath $fullDestination -PathType Container) -or
            ((Test-Path -LiteralPath $fullDestination) -and
            -not (Test-Path -LiteralPath $fullDestination -PathType Leaf))) {
        throw '公文收發管理系統.lnk 已被資料夾或其他非檔案項目占用，請先移除。'
    }
    if ((Test-Path -LiteralPath $entryDestination -PathType Container) -or
            ((Test-Path -LiteralPath $entryDestination) -and
            -not (Test-Path -LiteralPath $entryDestination -PathType Leaf))) {
        throw '公文快速登錄系統.lnk 已被資料夾或其他非檔案項目占用，請先移除。'
    }

    $shell = New-Object -ComObject WScript.Shell
    $fullShortcut = $shell.CreateShortcut($fullDestination)
    $fullShortcut.TargetPath = $fullExe
    $fullShortcut.WorkingDirectory = $uncDirectory
    $fullShortcut.IconLocation = $fullExe + ',0'
    $fullShortcut.Save()
    $entryShortcut = $shell.CreateShortcut($entryDestination)
    $entryShortcut.TargetPath = $entryExe
    $entryShortcut.WorkingDirectory = $uncDirectory
    $entryShortcut.IconLocation = $entryExe + ',0'
    $entryShortcut.Save()
    [Console]::WriteLine('捷徑建立完成：' + $parentDirectory)
    exit 0
} catch {
    $detail = $_.Exception.Message
    if ($_.Exception -is [System.UnauthorizedAccessException]) {
        $detail = '沒有寫入權限，無法在該資料夾建立捷徑；請改用對該分享有寫入權限的帳號執行。'
    }
    [Console]::Error.WriteLine('建立捷徑失敗：' + $detail + $retryMessage)
    exit 1
}
