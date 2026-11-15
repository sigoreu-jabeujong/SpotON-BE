import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from etl.operation_logs import archive, job


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell/ACL integration")
def test_windows_runner_private_process_contract(tmp_path):
    folder = tmp_path
    repo = Path(__file__).resolve().parents[2]
    PS = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
    PY = sys.executable
    GIT = shutil.which("git")
    assert GIT is not None
    setup = """\
    param([Parameter(Mandatory=$true)][string]$Root)
    $ErrorActionPreference='Stop'
    if (Test-Path -LiteralPath $Root) { throw 'exists' }
    [void][IO.Directory]::CreateDirectory($Root)
    $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl=[Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($allowed in @($sid,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
        $rule=[Security.AccessControl.FileSystemAccessRule]::new(
            $allowed,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Root -AclObject $acl
    Write-Output '{"private_root_created":true}'
    """
    (folder / "private-root.ps1").write_text(setup, encoding="utf-8")
    root = folder / ("native-" + uuid4().hex)
    checks = []

    def psfile(path, *args, env=None):
        return subprocess.run(
            [PS, "-NoProfile", "-NonInteractive", "-File", str(path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=40,
        )

    def command(args, cwd):
        r = subprocess.run(args, cwd=cwd, capture_output=True, timeout=30)
        assert r.returncode == 0, "fixture_command"
        return r.stdout.decode().strip()

    r = psfile(folder / "private-root.ps1", "-Root", str(root))
    assert r.returncode == 0, "acl_setup"
    runtime = root / "runtime"
    runtime.mkdir()
    command([GIT, "init", "--quiet"], runtime)
    command([GIT, "config", "user.name", "Private verification"], runtime)
    command([GIT, "config", "user.email", "private@example.invalid"], runtime)
    for sub in ["etl", "etl/operation_logs"]:
        (runtime / sub).mkdir(exist_ok=True)
        (runtime / sub / "__init__.py").write_text("")
    (runtime / "uv.lock").write_bytes((repo / "uv.lock").read_bytes())
    (runtime / ".gitignore").write_text("__pycache__/\n")
    (runtime / ".gitattributes").write_text("* text=auto eol=lf\n")
    data = root / "events.sqlite3"
    state = root / "job.sqlite3"
    archive.initialize(data, execute=True)
    now = datetime.now(UTC)
    owner, service = "tea-" + "a" * 20, "srv-" + "b" * 20
    job.initialize(
        data, state, owner, service, (now - timedelta(minutes=20)).isoformat(), now, execute=True
    )
    runner = root / "run.ps1"
    runner.write_bytes((repo / "ops/windows/run-operation-log-job.ps1").read_bytes())
    config = dict(
        rule_version="windows-log-pilot-v1",
        root=str(root),
        runtime=str(runtime),
        python=PY,
        git=GIT,
        source_commit="0" * 40,
        lock_sha256=hashlib.sha256((runtime / "uv.lock").read_bytes()).hexdigest(),
        runner_sha256=hashlib.sha256(runner.read_bytes()).hexdigest(),
        owner_id=owner,
        service_id=service,
    )
    config_path = root / "config.json"
    payload = dataclasses.asdict(job.Result())
    canary = "rnd_TEST_ONLY_PRIVATE_CANARY"

    def install(extra="", changes=None, code=None):
        value = dict(payload)
        value.update(changes or {})
        source = (
            "import json,os,sys\nv="
            + repr(value)
            + '\nv["mode"]="execute" if "--execute" in sys.argv else "dry_run"\n'
            'if os.environ.get("RENDER_API_KEY")=='
            + repr(canary)
            + ': v["unexpected_secret"]=True\n'
            + extra
            + "\nprint(json.dumps(v))\n"
            + ("sys.exit(" + str(code) + ")\n" if code is not None else "")
        )
        (runtime / "etl/operation_logs/job.py").write_text(source, encoding="utf-8")
        command([GIT, "add", "."], runtime)
        command(
            [GIT, "commit", "--quiet", "--allow-empty", "-m", "private native fixture"], runtime
        )
        config["source_commit"] = command([GIT, "rev-parse", "HEAD"], runtime)
        config_path.write_text(json.dumps(config), encoding="utf-8")

    def run(name, *, execute=False, error=None, env=None):
        r = psfile(
            runner, "-ConfigPath", str(config_path), *(["-Execute"] if execute else []), env=env
        )
        assert canary not in r.stdout + r.stderr, "raw_canary"
        assert not r.stderr, "stderr_leak"
        try:
            result = json.loads(r.stdout)
        except Exception:
            raise AssertionError("runner_json_" + name) from None
        assert result["error"] == error, "unexpected_" + name + "_" + str(result["error"])
        assert r.returncode == (0 if result["status"] == "ok" else 1), "exit_mapping"
        checks.append(name)
        return result

    install()
    env = dict(os.environ, RENDER_API_KEY=canary)
    before = {p: p.read_bytes() for p in [data, state]}
    run("preview_parent_key_not_inherited", env=env)
    assert (
        before == {p: p.read_bytes() for p in before} and not (root / "latest-result.json").exists()
    )
    checks.append("preview_files_unchanged")
    install("sys.stderr.write(" + repr(canary) + ")")
    run("stderr_not_forwarded")
    install(changes={"status": "failed", "error": canary}, code=1)
    run("unknown_error_redacted", error="job_failed")
    for name, changes in [
        ("unknown_property", {"raw": canary}),
        ("negative_count", {"inserted": -1}),
        ("boolean_count", {"inserted": True}),
        ("wrong_boolean", {"checkpoint_committed": 1}),
        ("raw_time", {"cursor_before": canary}),
    ]:
        install(changes=changes)
        run(name, error="output")
    install('sys.stderr.write("x"*100000)')
    run("stderr_bounded", error="output_oversize")
    install("print(" + repr(canary) + ")")
    run("multiline_stdout_rejected", error="output")
    install(changes={"status": "failed", "error": "configuration"}, code=0)
    run("exit_status_mismatch", error="output")
    install(changes={"mode": "execute"})
    original = config_path.read_bytes()
    config_path.write_text(json.dumps(dict(config, extra=canary)))
    run("extra_config_rejected", error="configuration")
    config_path.write_bytes(original)
    original_runner = runner.read_bytes()
    runner.write_bytes(original_runner + b"\n")
    run("runner_hash_rejected", error="configuration")
    runner.write_bytes(original_runner)
    acl_script = folder / "test-acl.ps1"
    acl_script.write_text(
        """param([string]$Target,[switch]$Grant)
$ErrorActionPreference='Stop'
$acl=Get-Acl -LiteralPath $Target
$world=[Security.Principal.SecurityIdentifier]::new('S-1-1-0')
$rule=[Security.AccessControl.FileSystemAccessRule]::new($world,'Read','Allow')
if ($Grant) { $acl.AddAccessRule($rule) } else { $acl.RemoveAccessRuleAll($rule) }
Set-Acl -LiteralPath $Target -AclObject $acl
""",
        encoding="utf-8",
    )
    assert psfile(acl_script, "-Target", str(config_path), "-Grant").returncode == 0
    run("broad_file_acl_rejected", error="configuration")
    assert psfile(acl_script, "-Target", str(config_path)).returncode == 0
    command([GIT, "update-index", "--assume-unchanged", "etl/operation_logs/job.py"], runtime)
    with (runtime / "etl/operation_logs/job.py").open("a") as f:
        f.write("\n# changed\n")
    run("assume_unchanged_rejected", error="source")
    command([GIT, "update-index", "--no-assume-unchanged", "etl/operation_logs/job.py"], runtime)
    install(changes={"status": "failed", "error": "configuration"}, code=1)
    result = run(
        "missing_dpapi_parent_key_not_inherited",
        execute=True,
        error="credential_unavailable",
        env=env,
    )
    assert result["credential_unavailable"] and result["job"]["error"] == "configuration"
    assert result["job_invocation_attempted"] and result["effects_may_be_partial"]
    latest = json.loads((root / "latest-result.json").read_text())
    assert latest == result
    checks.append("latest_safe_atomic_result")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process tree integration")
def test_windows_timeout_terminates_the_real_venv_interpreter(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    script = (repo / "ops/windows/run-operation-log-job.ps1").read_text(encoding="utf-8")
    helper = re.search(r"(?s)Add-Type -TypeDefinition @'\r?\n(.*?)\r?\n'@", script)
    assert helper is not None
    test_script = tmp_path / "timeout.ps1"
    test_script.write_text(
        "param([string]$Python,[string]$Folder)\n"
        "$ErrorActionPreference='Stop'\nAdd-Type -TypeDefinition @'\n"
        + helper[1]
        + "\n'@\n"
        + """$source="import os,pathlib,time;"
$source+="pathlib.Path('actual-python.pid').write_text(str(os.getpid()));time.sleep(60)"
$arguments='-E -s -B -c "'+$source+'"'
$timedOut=$false
try { [void][SpotONBoundedChild]::Run($Python,$arguments,$Folder,$null,3000) }
catch { $timedOut=($_.Exception.InnerException -is [TimeoutException]) }
$childRuntimePid=[int][IO.File]::ReadAllText((Join-Path $Folder 'actual-python.pid'))
$gone=$false
try {
    $childProcess=[Diagnostics.Process]::GetProcessById($childRuntimePid)
    $gone=$childProcess.HasExited
}
catch [ArgumentException] { $gone=$true }
[pscustomobject]@{timed_out=$timedOut;actual_interpreter_gone=$gone} | ConvertTo-Json -Compress
""",
        encoding="utf-8",
    )
    powershell = str(
        Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(test_script),
            "-Python",
            sys.executable,
            "-Folder",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=40,
    )
    assert result.returncode == 0 and not result.stderr
    assert json.loads(result.stdout) == {"timed_out": True, "actual_interpreter_gone": True}
