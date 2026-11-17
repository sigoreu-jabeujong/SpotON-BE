[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ConfigPath,
    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$stage = 'configuration'
$exitCode = 1
$canWriteReport = $false
$report = [ordered]@{
    runner_rule_version = 'windows-log-pilot-v1'
    status = 'failed'
    error = 'configuration'
    mode = $(if ($Execute) { 'execute' } else { 'dry_run' })
    completed_at = $null
    credential_unavailable = $false
    retention_risk = $false
    job_invocation_attempted = $false
    effects_may_be_partial = $false
    job = $null
}

function Assert-LocalPath([string]$Value) {
    if ($Value -notmatch '^[A-Za-z]:\\' -or $Value.Substring(2) -match '[:~"\x00-\x1f]' -or
        [IO.Path]::GetFullPath($Value) -ine $Value) { throw 'path' }
    foreach ($segment in $Value.Substring(3).Split('\')) {
        if (-not $segment -or $segment.EndsWith('.') -or $segment.EndsWith(' ')) { throw 'path' }
    }
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($Value))
    if ($drive.DriveType -ne [IO.DriveType]::Fixed) { throw 'path' }
    $current = $Value
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -Force -LiteralPath $current
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'path' }
        }
        $current = [IO.Path]::GetDirectoryName($current)
    }
}

function Assert-PrivateAcl([string]$Value, [bool]$Root = $false) {
    Assert-LocalPath $Value
    $acl = Get-Acl -LiteralPath $Value
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid -or
        ($Root -and -not $acl.AreAccessRulesProtected)) { throw 'acl' }
    $userFound = $false
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -ne 'Allow' -or $rule.IdentityReference.Value -notin @($sid, 'S-1-5-18')) { throw 'acl' }
        if ($rule.IdentityReference.Value -eq $sid -and
            ($rule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -eq
            [Security.AccessControl.FileSystemRights]::FullControl) { $userFound = $true }
    }
    if (-not $userFound) { throw 'acl' }
}

function Quote-Argument([string]$Value) {
    if ($Value -match '["\x00\r\n]' -or $Value.EndsWith('\')) { throw 'argument' }
    return '"' + $Value + '"'
}

try {
    Assert-LocalPath $ConfigPath
    if ((Get-Item -LiteralPath $ConfigPath).Length -gt 16384) { throw 'configuration' }
    $config = [IO.File]::ReadAllText($ConfigPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
    $fields = @('rule_version', 'root', 'runtime', 'python', 'git', 'source_commit',
        'lock_sha256', 'runner_sha256', 'owner_id', 'service_id')
    if (@(Compare-Object $fields @($config.PSObject.Properties.Name)).Count) { throw 'configuration' }
    foreach ($field in $fields) { if ($config.$field -isnot [string]) { throw 'configuration' } }
    if ($config.rule_version -ne $report.runner_rule_version -or
        $config.source_commit -cnotmatch '^[0-9a-f]{40}$' -or
        $config.lock_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        $config.runner_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        $config.owner_id -cnotmatch '^(tea|usr)-[a-z0-9]{10,40}$' -or
        $config.service_id -cnotmatch '^srv-[a-z0-9]{10,40}$') { throw 'configuration' }
    $root = $config.root
    if ($ConfigPath -ine (Join-Path $root 'config.json') -or
        $config.runtime -ine (Join-Path $root 'runtime') -or
        $PSCommandPath -ine (Join-Path $root 'run.ps1')) { throw 'configuration' }
    Assert-PrivateAcl $root $true
    foreach ($path in @($ConfigPath, $PSCommandPath, (Join-Path $root 'events.sqlite3'), (Join-Path $root 'job.sqlite3'))) {
        Assert-PrivateAcl $path
        if ((Get-Item -LiteralPath $path).PSIsContainer) { throw 'configuration' }
    }
    foreach ($path in @($config.python, $config.git, $config.runtime)) { Assert-LocalPath $path }
    $credential = Join-Path $root 'render-key.dpapi'
    if (Test-Path -LiteralPath $credential) { Assert-PrivateAcl $credential }
    if (-not [IO.File]::Exists($config.python) -or -not [IO.File]::Exists($config.git) -or
        -not [IO.Directory]::Exists($config.runtime) -or
        (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $config.runner_sha256 -or
        (Get-FileHash -LiteralPath (Join-Path $config.runtime 'uv.lock') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $config.lock_sha256) { throw 'configuration' }

    # C# drains both pipes without a PowerShell event runspace or unbounded buffers.
    Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading.Tasks;
public sealed class SpotONChildResult {
    public string Output;
    public int ExitCode;
    public bool Oversize;
}
public static class SpotONBoundedChild {
    public static void CommitReport(string temporary, string destination) {
        if (File.Exists(destination)) File.Replace(temporary, destination, null);
        else File.Move(temporary, destination);
    }
    private sealed class Capture {
        public StringBuilder Text = new StringBuilder();
        public bool Oversize;
    }
    private static void Drain(StreamReader reader, Capture capture, bool keep) {
        char[] block = new char[1024];
        int length, bytes = 0;
        while ((length = reader.Read(block, 0, block.Length)) > 0) {
            int count = Encoding.UTF8.GetByteCount(block, 0, length);
            if (bytes > 65536 - count) { capture.Oversize = true; continue; }
            bytes += count;
            if (keep) capture.Text.Append(block, 0, length);
        }
    }
    private static void KillTree(Process process) {
        string path = Path.Combine(Environment.GetEnvironmentVariable("SystemRoot"), "System32", "taskkill.exe");
        ProcessStartInfo info = new ProcessStartInfo(path, "/PID " + process.Id + " /T /F");
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        info.EnvironmentVariables.Remove("RENDER_API_KEY");
        using (Process killer = Process.Start(info)) {
            Capture output = new Capture(), error = new Capture();
            Task outTask = Task.Run(() => Drain(killer.StandardOutput, output, false));
            Task errTask = Task.Run(() => Drain(killer.StandardError, error, false));
            if (!killer.WaitForExit(30000)) { killer.Kill(); throw new TimeoutException(); }
            if (!Task.WaitAll(new [] {outTask, errTask}, 5000) || killer.ExitCode != 0)
                throw new TimeoutException();
        }
    }
    public static SpotONChildResult Run(string exe, string arguments, string cwd, string key, int timeoutMs) {
        if (timeoutMs < 1 || timeoutMs > 540000) throw new ArgumentOutOfRangeException("timeoutMs");
        ProcessStartInfo info = new ProcessStartInfo(exe, arguments);
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.WorkingDirectory = cwd;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        info.StandardOutputEncoding = Encoding.UTF8;
        info.StandardErrorEncoding = Encoding.UTF8;
        info.EnvironmentVariables.Clear();
        foreach (string name in new [] {"SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "PATH", "COMSPEC"}) {
            string value = Environment.GetEnvironmentVariable(name);
            if (value != null) info.EnvironmentVariables[name] = value;
        }
        info.EnvironmentVariables["GIT_CONFIG_NOSYSTEM"] = "1";
        info.EnvironmentVariables["GIT_CONFIG_GLOBAL"] = "NUL";
        if (key != null) info.EnvironmentVariables["RENDER_API_KEY"] = key;
        using (Process process = new Process()) {
            process.StartInfo = info;
            process.Start();
            info.EnvironmentVariables.Remove("RENDER_API_KEY");
            Capture output = new Capture(), error = new Capture();
            Task outTask = Task.Run(() => Drain(process.StandardOutput, output, true));
            Task errTask = Task.Run(() => Drain(process.StandardError, error, false));
            if (!process.WaitForExit(timeoutMs)) {
                KillTree(process);
                if (!process.WaitForExit(5000)) throw new TimeoutException();
                Task.WaitAll(new [] {outTask, errTask}, 5000);
                throw new TimeoutException();
            }
            if (!Task.WaitAll(new [] {outTask, errTask}, 5000)) throw new TimeoutException();
            return new SpotONChildResult {Output = output.Text.ToString(), ExitCode = process.ExitCode,
                Oversize = output.Oversize || error.Oversize};
        }
    }
}
'@
    $stage = 'source'
    $gitArgs = @('-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=NUL', '--no-optional-locks', '-C', $config.runtime)
    foreach ($check in @(
        @{Args = @('rev-parse', 'HEAD'); Kind = 'head'},
        @{Args = @('status', '--porcelain', '--untracked-files=all'); Kind = 'status'},
        @{Args = @('ls-files', '-v'); Kind = 'flags'}
    )) {
        $arguments = (@($gitArgs + $check.Args) | ForEach-Object { Quote-Argument $_ }) -join ' '
        $checked = [SpotONBoundedChild]::Run($config.git, $arguments, $config.runtime, $null, 10000)
        if ($checked.ExitCode -ne 0 -or $checked.Oversize) { throw 'source' }
        if ($check.Kind -eq 'head' -and $checked.Output.Trim() -cne $config.source_commit) { throw 'source' }
        if ($check.Kind -eq 'status' -and $checked.Output.Trim()) { throw 'source' }
        if ($check.Kind -eq 'flags') {
            foreach ($line in ($checked.Output.TrimEnd() -split '\r?\n')) {
                if ($line -cnotmatch '^H ') { throw 'source' }
            }
        }
    }
    $canWriteReport = $true
    $key = $null
    if ($Execute) {
        $stage = 'credential'
        $plain = $null
        try {
            Assert-PrivateAcl $credential
            if ((Get-Item -LiteralPath $credential).Length -gt 16384) { throw 'credential' }
            Add-Type -AssemblyName System.Security
            $entropy = [Text.Encoding]::UTF8.GetBytes('SpotON-Render-log-pilot-v1')
            $plain = [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($credential), $entropy,
                [Security.Cryptography.DataProtectionScope]::CurrentUser)
            $key = [Text.Encoding]::UTF8.GetString($plain)
            if ($key -cnotmatch '^[\x21-\x7e]{10,1024}\z') { throw 'credential' }
        } catch {
            $report.credential_unavailable = $true
            $key = ''
        } finally {
            if ($null -ne $plain) { [Array]::Clear($plain, 0, $plain.Length) }
        }
    }
    $stage = 'child'
    $jobArgs = @('-E', '-s', '-B', '-m', 'etl.operation_logs.job', 'run', '--db', (Join-Path $root 'events.sqlite3'),
        '--state', (Join-Path $root 'job.sqlite3'), '--owner-id', $config.owner_id, '--service-id', $config.service_id)
    if ($Execute) { $jobArgs += '--execute' }
    $report.job_invocation_attempted = $true
    try {
        $child = [SpotONBoundedChild]::Run($config.python, (($jobArgs | ForEach-Object { Quote-Argument $_ }) -join ' '), $config.runtime, $key, 540000)
    } finally { $key = $null }
    $stage = 'output'
    if ($child.Oversize) { $stage = 'output_oversize'; throw 'output' }
    $line = $child.Output.TrimEnd("`r", "`n")
    if ($line.Length -eq 0 -or $line -match '[\r\n]') { throw 'output' }
    $job = $line | ConvertFrom-Json
    $counts = @('created', 'would_create', 'planned_windows', 'successful_windows', 'collector_invocations',
        'inserted', 'duplicate', 'api_rows', 'rejected_messages', 'prune_deleted', 'prune_would_delete')
    $nullableCounts = @('lag_seconds_after', 'remaining_windows')
    $booleans = @('coverage_verified', 'prune_completed', 'checkpoint_committed', 'effects_may_be_partial')
    $times = @('failed_window_start', 'cursor_before', 'last_confirmed_until', 'proposed_until')
    $allFields = $counts + $nullableCounts + $booleans + $times + @('status', 'error', 'phase', 'job_rule_version', 'mode')
    if (@(Compare-Object $allFields @($job.PSObject.Properties.Name)).Count) { throw 'output' }
    foreach ($name in ($counts + $nullableCounts)) {
        $value = $job.$name
        if ($null -eq $value -and $name -in $nullableCounts) { continue }
        if (($value -isnot [int] -and $value -isnot [long]) -or $value -lt 0) { throw 'output' }
    }
    foreach ($name in $booleans) { if ($job.$name -isnot [bool]) { throw 'output' } }
    foreach ($name in $times) {
        if ($null -ne $job.$name -and ($job.$name -isnot [string] -or
            $job.$name -cnotmatch '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{9}Z\z')) { throw 'output' }
    }
    if ($job.status -cnotin @('ok', 'failed', 'interrupted') -or
        $job.phase -cnotin @('state', 'validation', 'prune', 'collect', 'checkpoint', 'completed', 'preview') -or
        $job.job_rule_version -cne 'render-log-job-v1' -or $job.mode -cne $report.mode -or
        $job.coverage_verified -ne $false -or $child.ExitCode -notin @(0, 1, 2, 130) -or
        (($child.ExitCode -eq 0) -ne ($job.status -ceq 'ok')) -or
        (($child.ExitCode -eq 130) -ne ($job.status -ceq 'interrupted'))) { throw 'output' }
    $knownErrors = @('arguments', 'configuration', 'api_network', 'api_rate_limit', 'api_auth', 'api_http',
        'state_busy', 'state_journal_present', 'state_file', 'state_ownership', 'state_contents', 'state_changed',
        'binding_mismatch', 'archive_busy', 'archive_links', 'database_busy', 'database', 'ownership',
        'checkpoint_expired', 'clock_behind_checkpoint', 'collector_window', 'collector_contract',
        'operation_failed', 'interrupted')
    if ($null -ne $job.error -and $job.error -cnotin $knownErrors) { $job.error = 'job_failed' }
    if ($job.status -ceq 'ok' -and $null -ne $job.error) { throw 'output' }
    $report.job = $job
    $report.retention_risk = ($null -ne $job.lag_seconds_after -and $job.lag_seconds_after -gt 6 * 86400)
    $report.status = $job.status
    $report.error = $job.error
    $exitCode = $child.ExitCode
    if ($report.credential_unavailable) {
        $report.status = 'failed'; $report.error = 'credential_unavailable'; $exitCode = 1
    }
} catch {
    $report.status = 'failed'
    $report.error = $(if ($_.Exception -is [TimeoutException] -or $_.Exception.InnerException -is [TimeoutException]) { 'child_timeout' } else { $stage })
    $exitCode = 1
} finally {
    $report.completed_at = [DateTime]::UtcNow.ToString('o')
    $report.effects_may_be_partial = ($Execute -and $report.job_invocation_attempted -and $report.status -ne 'ok')
    if ($Execute -and $canWriteReport) {
        $tempPath = Join-Path $root ('result-' + [Guid]::NewGuid().ToString('N') + '.tmp')
        try {
            $stream = [IO.File]::Open($tempPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try {
                $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($report | ConvertTo-Json -Depth 5 -Compress))
                $stream.Write($bytes, 0, $bytes.Length)
                $stream.Flush($true)
            } finally { $stream.Dispose() }
            $latest = Join-Path $root 'latest-result.json'
            Assert-LocalPath $latest
            [SpotONBoundedChild]::CommitReport($tempPath, $latest)
        } catch {
            $report.status = 'failed'; $report.error = 'report_write'; $exitCode = 1
            $report.effects_may_be_partial = [bool]($Execute -and $report.job_invocation_attempted)
        } finally {
            try { if ([IO.File]::Exists($tempPath)) { [IO.File]::Delete($tempPath) } } catch { }
        }
    }
}
$report | ConvertTo-Json -Depth 5 -Compress
exit $exitCode
