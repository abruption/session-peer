"""Opt-in aliases in isolated shells; no live sessions or user profile writes."""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "session_peer_shorthand"


class ShorthandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="session-peer-sp-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ, HOME=str(self.directory), USERPROFILE=str(self.directory),
                        SESSION_PEER_NO_UPDATE_NOTICE="1", PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.fixture = self.directory / "capture.py"
        self.fixture.write_text(
            "import json,sys\nprint(json.dumps({'args':sys.argv[1:],'stdin':sys.stdin.buffer.read().decode('utf-8')}))\n"
            "sys.exit(7 if '--fail' in sys.argv else 0)\n", encoding="utf-8")
        self.canonical(self.fixture)

    def canonical(self, program):
        if os.name == "nt":
            (self.bin / "session-peer.cmd").write_text(
                '@"' + sys.executable + '" "' + str(program) + '" %*\r\n', encoding="utf-8")
        else:
            command = self.bin / "session-peer"
            command.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " +
                               shlex.quote(str(program)) + ' "$@"\n', encoding="utf-8")
            command.chmod(0o700)

    def shells(self):
        return [name for name in ("bash", "zsh") if shutil.which(name)]

    def run_shell(self, shell, text, input_text=""):
        script = self.directory / (shell + "-test.sh")
        script.write_text("set -u\n" + ("shopt -s expand_aliases\n" if shell == "bash" else "") + text,
                          encoding="utf-8")
        return subprocess.run([shell, "--noprofile", "--norc", str(script)] if shell == "bash" else
                              [shell, "-f", str(script)], env=self.env, input=input_text,
                              capture_output=True, text=True, timeout=15)

    @property
    def source(self):
        return "source " + shlex.quote(str(ASSETS / "sp.sh"))

    @property
    def remove_source(self):
        return "source " + shlex.quote(str(ASSETS / "sp-remove.sh"))

    @unittest.skipIf(os.name == "nt", "POSIX shell contracts")
    def test_alias_preserves_argv_stdin_exit_and_option_separator(self):
        for shell in self.shells():
            with self.subTest(shell=shell):
                result = self.run_shell(shell, self.source + "\nsp send --message='--값 $;`literal`' -- 'space value' 雪 --fail\nexit $?\n",
                                        "stdin 값\n")
                self.assertEqual(result.returncode, 7, result.stderr)
                self.assertEqual(json.loads(result.stdout), {"args": ["send", "--message=--값 $;`literal`", "--", "space value", "雪", "--fail"], "stdin": "stdin 값\n"})

    @unittest.skipIf(os.name == "nt", "POSIX shell contracts")
    def test_actual_cli_equivalence(self):
        self.canonical(ROOT / "session_peer.py")
        for shell in self.shells():
            for args in ("--version", "--help", "list --agent claude --json",
                         "send --to missing-target-for-isolated-test --dry-run -m 'hello 雪' --json", "--invalid-option"):
                with self.subTest(shell=shell, args=args):
                    expected = self.run_shell(shell, "session-peer " + args + "\n")
                    actual = self.run_shell(shell, self.source + "\nsp " + args + "\n")
                    self.assertEqual((actual.returncode, actual.stdout, actual.stderr),
                                     (expected.returncode, expected.stdout, expected.stderr))

    @unittest.skipIf(os.name == "nt", "POSIX shell contracts")
    def test_collision_refuses_alias_function_and_executable(self):
        for shell in self.shells():
            for kind in ("alias", "function", "executable"):
                with self.subTest(shell=shell, kind=kind):
                    prefix = "alias sp='unrelated-command'\n" if kind == "alias" else "sp() { printf unrelated; }\n"
                    if kind == "executable":
                        prefix = ""
                        executable = self.bin / "sp"
                        executable.write_text("#!/bin/sh\nprintf unrelated\n", encoding="utf-8")
                        executable.chmod(0o700)
                    result = self.run_shell(shell, prefix + self.source + "\nactivation_status=$?\ntype sp\nexit $activation_status\n")
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("already exists", result.stderr)
                    self.assertIn("sp", result.stdout)
                    if kind == "executable":
                        executable.unlink()

    @unittest.skipIf(os.name == "nt", "POSIX shell contracts")
    def test_repeated_activation_owned_removal_update_and_uninstall(self):
        for shell in self.shells():
            result = self.run_shell(shell, self.source + "\n" + self.source + "\n" +
                                    self.remove_source + "\n" + self.remove_source + "\n" +
                                    "command -v sp && exit 9\n" + self.source + "\nsp before-update\n")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["args"], ["before-update"])
            # Re-selecting an installation on PATH changes the canonical command,
            # not a separately pinned runtime or generated launcher.
            updated = self.directory / "updated.py"
            updated.write_text("print('updated implementation')\n", encoding="utf-8")
            script = (self.source + "\nPATH=" + shlex.quote(str(self.directory / "new-bin")) + ":$PATH\n"
                      "sp --version\n" + self.remove_source + "\n")
            new_bin = self.directory / "new-bin"
            new_bin.mkdir(exist_ok=True)
            launcher = new_bin / "session-peer"
            launcher.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(updated)) + "\n", encoding="utf-8")
            launcher.chmod(0o700)
            result = self.run_shell(shell, script)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "updated implementation")

    @unittest.skipIf(os.name == "nt", "POSIX shell contracts")
    def test_changed_alias_is_never_removed_and_missing_runtime_refused(self):
        for shell in self.shells():
            result = self.run_shell(shell, self.source + "\nalias sp='other'\n" + self.remove_source + "\nactivation_status=$?\nalias sp\nexit $activation_status\n")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("other", result.stdout)
            result = self.run_shell(shell, "PATH=/nonexistent\n" + self.source + "\n")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("unavailable", result.stderr)

    @unittest.skipIf(os.name == "nt", "POSIX shell contracts")
    def test_execution_refused_and_caller_arguments_do_not_change_activation(self):
        for shell in self.shells():
            result = subprocess.run([shell, str(ASSETS / "sp.sh")], env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Source", result.stderr)
            result = self.run_shell(shell, "set -- --remove 'caller argument'\n" + self.source + "\n" + self.source + "\nsp preserved\n" + self.remove_source + "\n")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["args"], ["preserved"])

    def test_asset_locator_is_read_only_and_constrained(self):
        for shell, filename in (("bash", "sp.sh"), ("powershell", "sp.ps1")):
            result = subprocess.run([sys.executable, "-m", "session_peer_shorthand", shell], cwd=ROOT,
                                    env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()), ASSETS / filename)
        result = subprocess.run([sys.executable, "-m", "session_peer_shorthand", "cmd"], cwd=ROOT,
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    @unittest.skipUnless(os.name == "nt" or shutil.which("pwsh"), "PowerShell not installed")
    def test_powershell_contract(self):
        shell = shutil.which("powershell") if os.name == "nt" else shutil.which("pwsh")
        if not shell:
            self.skipTest("PowerShell unavailable")
        script = self.directory / "contract.ps1"
        asset = str(ASSETS / "sp.ps1").replace("'", "''")
        fixture = str(self.fixture).replace("'", "''")
        python = sys.executable.replace("'", "''")
        # This removal is fixture-only in a child process: the activator never
        # removes PowerShell's default ReadOnly/AllScope sp=Set-ItemProperty.
        script.write_text("""$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $OutputEncoding
$asset = '__ASSET__'
function Require($condition, $description) { if (-not $condition) { throw $description } }
Set-Alias -Name sp -Value Set-ItemProperty -Option ReadOnly,AllScope -Force -Scope Global
$refused = $false
try { . $asset } catch { $refused = $true }
Require $refused 'default alias was not refused'
Require ((Get-Alias sp).Definition -eq 'Set-ItemProperty') 'default alias changed'
Remove-Item Alias:sp -Force
function session-peer { $input | & '__PYTHON__' '__FIXTURE__' @args }
Set-StrictMode -Version 2.0
. $asset
. $asset
$expected = session-peer send '--message=값 $;`literal`' '--' 'space value' '雪' --fail | ConvertFrom-Json
$result = sp send '--message=값 $;`literal`' '--' 'space value' '雪' --fail | ConvertFrom-Json
Require ($LASTEXITCODE -eq 7) 'native exit code changed'
Require ($result.args.Count -eq 6) 'argument count changed'
Require ($result.args[1] -eq '--message=값 $;`literal`') 'argument changed'
Require (($result | ConvertTo-Json -Compress) -eq ($expected | ConvertTo-Json -Compress)) 'alias changed native argument input'
$result = 'stdin α' | sp input | ConvertFrom-Json
Require ($result.stdin.Trim() -eq 'stdin α') 'pipeline stdin changed'
function session-peer { 'updated implementation'; $global:LASTEXITCODE = 0 }
Require ((sp --version) -eq 'updated implementation') 'canonical selection not followed after update'
. $asset -Remove
. $asset -Remove
Require (-not (Get-Alias -Name sp -ErrorAction SilentlyContinue)) 'owned alias not removed'
. $asset
function sp { 'hidden command appeared after activation' }
. $asset -Remove
Require (-not (Get-Alias -Name sp -ErrorAction SilentlyContinue)) 'hidden function prevented owned alias removal'
Require ((Get-Command -Name sp).CommandType -eq 'Function') 'hidden function was deleted'
Remove-Item Function:sp
Require (-not (Get-Command sp -ListImported -ErrorAction SilentlyContinue)) 'owned alias not removed'
function sp { 'unrelated' }
$refused = $false
try { . $asset } catch { $refused = $true }
Require $refused 'function collision not refused'
Remove-Item Function:sp
. $asset
Set-Alias -Name sp -Value Get-Item
$refused = $false
try { . $asset -Remove } catch { $refused = $true }
Require $refused 'changed alias removed'
Require ((Get-Alias sp).Definition -eq 'Get-Item') 'changed alias overwritten'
Remove-Item Alias:sp
Remove-Item Function:session-peer
Remove-Item '__CANONICAL__'
$refused = $false
try { . $asset } catch { $refused = $true }
Require $refused 'missing canonical command not refused'
exit 0
""".replace("__ASSET__", asset).replace("__PYTHON__", python).replace("__FIXTURE__", fixture)
            .replace("__CANONICAL__", str(self.bin / ("session-peer.cmd" if os.name == "nt" else "session-peer")).replace("'", "''")), encoding="utf-8-sig")
        result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                env=self.env, input="", capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(os.name == "nt" or shutil.which("pwsh"), "PowerShell not installed")
    def test_powershell_collision_lookup_never_autoloads_modules(self):
        shell = shutil.which("powershell") if os.name == "nt" else shutil.which("pwsh")
        if not shell:
            self.skipTest("PowerShell unavailable")
        modules = self.directory / "modules"
        module = modules / "SpLookupProbe"
        module.mkdir(parents=True)
        marker = self.directory / "autoloaded"
        module.joinpath("SpLookupProbe.psm1").write_text(
            "[IO.File]::WriteAllText('" + str(marker).replace("'", "''") + "', 'loaded')\n"
            "function sp { 'unimported' }; function session-peer { 'unimported' }\n"
            "Export-ModuleMember -Function sp,session-peer\n", encoding="utf-8-sig")
        module.joinpath("SpLookupProbe.psd1").write_text(
            "@{RootModule='SpLookupProbe.psm1';ModuleVersion='1.0.0';"
            "GUID='01900000-0000-7000-8000-000000000001';FunctionsToExport=@('sp','session-peer')}\n",
            encoding="utf-8-sig")
        script = self.directory / "autoload-lookup.ps1"
        script.write_text("""$ErrorActionPreference = 'Stop'
Remove-Item Alias:sp -Force -ErrorAction SilentlyContinue
$env:PSModulePath = '__MODULES__' + [IO.Path]::PathSeparator + $env:PSModulePath
$asset = '__ASSET__'
. $asset
if (Test-Path '__MARKER__') { throw 'sp lookup auto-imported a module' }
. $asset -Remove
Remove-Item '__CANONICAL__'
$refused = $false
try { . $asset } catch { $refused = $true }
if (-not $refused) { throw 'missing canonical command accepted' }
if (Test-Path '__MARKER__') { throw 'canonical lookup auto-imported a module' }
# Verify the test module really can be discovered by an ordinary exact lookup.
Get-Command -Name sp | Out-Null
if (-not (Test-Path '__MARKER__')) { throw 'autoload fixture was ineffective' }
exit 0
""".replace("__MODULES__", str(modules).replace("'", "''"))
            .replace("__ASSET__", str(ASSETS / "sp.ps1").replace("'", "''"))
            .replace("__MARKER__", str(marker).replace("'", "''"))
            .replace("__CANONICAL__", str(self.bin / ("session-peer.cmd" if os.name == "nt" else "session-peer")).replace("'", "''")), encoding="utf-8-sig")
        result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                env=self.env, input="", capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(os.name == "nt" or shutil.which("pwsh"), "PowerShell not installed")
    def test_powershell_actual_cli_equivalence(self):
        shell = shutil.which("powershell") if os.name == "nt" else shutil.which("pwsh")
        if not shell:
            self.skipTest("PowerShell unavailable")
        script = self.directory / "native-equivalence.ps1"
        script.write_text("""$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $OutputEncoding
Remove-Item Alias:sp -Force -ErrorAction SilentlyContinue
function session-peer { & '__PYTHON__' '__CLI__' @args }
. '__ASSET__'
$cases = @(
    @('--version'), @('--help'), @('list', '--agent', 'claude', '--json'),
    @('send', '--to', 'missing-target-for-isolated-test', '--dry-run', '-m', 'hello 雪', '--json'),
    @('send', '--to', 'missing-target-for-isolated-test', '--dry-run', '--json', '--', '-leading 雪'),
    @('--invalid-option')
)
foreach ($arguments in $cases) {
    $ErrorActionPreference = 'Continue'
    $expected = (& session-peer @arguments 2>$null | Out-String)
    $expectedExit = $LASTEXITCODE
    $actual = (& sp @arguments 2>$null | Out-String)
    $actualExit = $LASTEXITCODE
    if ($actual -ne $expected -or $actualExit -ne $expectedExit) { throw 'canonical output or exit mismatch' }
}
exit 0
""".replace("__PYTHON__", sys.executable.replace("'", "''"))
            .replace("__CLI__", str(ROOT / "session_peer.py").replace("'", "''"))
            .replace("__ASSET__", str(ASSETS / "sp.ps1").replace("'", "''")), encoding="utf-8-sig")
        result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                env=self.env, input="", capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
