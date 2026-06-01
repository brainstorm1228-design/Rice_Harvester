param(
    [string]$SourceRoot = $PSScriptRoot,
    [string]$OutputRoot = "C:\QA Security Project_Test",
    [ValidateSet("Submission", "Test", "None")]
    [string]$DriverSigningMode = "Submission",
    [string]$DriverEvCertificateThumbprint = "",
    [ValidateSet("Split", "Full", "Both")]
    [string]$InstallerMode = "Split",
    [switch]$SkipPipInstall,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$SourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)

$dotnet = Join-Path $env:ProgramFiles "dotnet\dotnet.exe"
$iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
$python = "python"

$agentProject = Join-Path $SourceRoot "Agent\Agent.csproj"
$controllerMain = Join-Path $SourceRoot "Controller\main.py"
$requirements = Join-Path $SourceRoot "Controller\requirements.txt"
$icon = Join-Path $SourceRoot "assets\icon.ico"
$makeIcon = Join-Path $SourceRoot "assets\make_icon.py"
$agentInstaller = Join-Path $SourceRoot "Agent\install_agent.ps1"
$agentInstallerBat = Join-Path $SourceRoot "Agent\Install_Agent.bat"
$driverSourceDir = Join-Path $SourceRoot "VhfDriver"
$hardwareSourceDir = Join-Path $SourceRoot "Hardware"

$agentOut = Join-Path $OutputRoot "Agent"
$controllerOut = Join-Path $OutputRoot "Controller"
$pyiWork = Join-Path $OutputRoot "_pyi_work"
$specOut = $OutputRoot
$driverPackageOut = Join-Path $agentOut "VhfDriver"
$installerOut = Join-Path $OutputRoot "Installer"

function Assert-PathExists([string]$Path, [string]$Label) {
    if (-not (Test-Path $Path)) {
        throw "$Label not found: $Path"
    }
}

Assert-PathExists $agentProject "Agent project"
Assert-PathExists $controllerMain "Controller entrypoint"
Assert-PathExists $requirements "Controller requirements"
Assert-PathExists $agentInstaller "Agent installer script"

New-Item -ItemType Directory -Force -Path $agentOut, $controllerOut, $pyiWork | Out-Null

function New-DefaultInnoScript([string]$ScriptPath) {
    $escapedOutputRoot = $OutputRoot.Replace("\", "\\")
    $escapedInstallerOut = $installerOut.Replace("\", "\\")
    $content = @"
[Setup]
AppId={{6D392E9E-040D-46E2-AFC7-RICEHARVESTER}}
AppName=Rice Harvester
AppVersion=1.0.0
AppPublisher=Rice Harvester
DefaultDirName={autopf}\Rice Harvester
DefaultGroupName=Rice Harvester
OutputDir=$escapedInstallerOut
OutputBaseFilename=Rice_Harvester_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "$escapedOutputRoot\\Controller\\Rice_Harvester.exe"; DestDir: "{app}\\Controller"; Flags: ignoreversion
Source: "$escapedOutputRoot\\Agent\\*"; DestDir: "{app}\\Agent"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "$escapedOutputRoot\\Hardware\\*"; DestDir: "{app}\\Hardware"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{group}\\Rice Harvester Controller"; Filename: "{app}\\Controller\\Rice_Harvester.exe"
Name: "{autodesktop}\\Rice Harvester Controller"; Filename: "{app}\\Controller\\Rice_Harvester.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"
"@
    New-Item -ItemType Directory -Force -Path (Split-Path $ScriptPath -Parent) | Out-Null
    Set-Content -Path $ScriptPath -Value $content -Encoding UTF8
}

function New-SelfExtractingInstaller {
    $buildDir = Join-Path $OutputRoot "_installer_build"
    $payloadDir = Join-Path $buildDir "payload"
    $payloadZip = Join-Path $buildDir "payload.zip"
    $projectDir = Join-Path $buildDir "src"
    $publishDir = Join-Path $buildDir "publish"

    if (Test-Path $buildDir) {
        Remove-Item -LiteralPath $buildDir -Force -Recurse
    }
    New-Item -ItemType Directory -Force -Path $payloadDir, $projectDir, $publishDir, $installerOut | Out-Null

    Copy-Item -Path $agentOut -Destination (Join-Path $payloadDir "Agent") -Recurse -Force
    Copy-Item -Path $controllerOut -Destination (Join-Path $payloadDir "Controller") -Recurse -Force
    $hardwareOut = Join-Path $OutputRoot "Hardware"
    if (Test-Path $hardwareOut) {
        Copy-Item -Path $hardwareOut -Destination (Join-Path $payloadDir "Hardware") -Recurse -Force
    }
    $readme = Join-Path $SourceRoot "README.md"
    if (Test-Path $readme) {
        Copy-Item -Force $readme (Join-Path $payloadDir "README.md")
    }

    Compress-Archive -Path (Join-Path $payloadDir "*") -DestinationPath $payloadZip -Force

    $csproj = @'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0-windows</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <AssemblyName>Rice_Harvester_Setup</AssemblyName>
  </PropertyGroup>
  <ItemGroup>
    <EmbeddedResource Include="payload.zip" LogicalName="payload.zip" />
  </ItemGroup>
</Project>
'@
    Set-Content -Path (Join-Path $projectDir "RiceHarvesterSetup.csproj") -Value $csproj -Encoding UTF8
    Copy-Item -Force $payloadZip (Join-Path $projectDir "payload.zip")

    $program = @'
using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;

internal static class Program
{
    static string ArgValue(string[] args, string name, string fallback)
    {
        string prefix = name + "=";
        string? value = args.FirstOrDefault(a => a.StartsWith(prefix, StringComparison.OrdinalIgnoreCase));
        return value is null ? fallback : value.Substring(prefix.Length).Trim('"');
    }

    static void ExtractPayload(string installDir)
    {
        using Stream? payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip");
        if (payload is null) throw new InvalidOperationException("Embedded payload.zip was not found.");
        using var archive = new ZipArchive(payload, ZipArchiveMode.Read);
        string root = Path.GetFullPath(installDir);
        Directory.CreateDirectory(root);
        foreach (ZipArchiveEntry entry in archive.Entries)
        {
            string destination = Path.GetFullPath(Path.Combine(root, entry.FullName));
            if (!destination.StartsWith(root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(destination, root, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("Blocked unsafe archive path: " + entry.FullName);
            }
            if (string.IsNullOrEmpty(entry.Name))
            {
                Directory.CreateDirectory(destination);
                continue;
            }
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            entry.ExtractToFile(destination, overwrite: true);
        }
    }

    static void CreateShortcut(string shortcutPath, string targetPath, string workingDirectory)
    {
        try
        {
            Type? shellType = Type.GetTypeFromProgID("WScript.Shell");
            if (shellType is null) return;
            dynamic shell = Activator.CreateInstance(shellType)!;
            dynamic shortcut = shell.CreateShortcut(shortcutPath);
            shortcut.TargetPath = targetPath;
            shortcut.WorkingDirectory = workingDirectory;
            shortcut.Description = "Rice Harvester Controller";
            shortcut.Save();
        }
        catch
        {
            // Shortcut creation is best-effort; installation files are still valid without it.
        }
    }

    static int Main(string[] args)
    {
        try
        {
            string defaultDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs",
                "Rice Harvester");
            string installDir = ArgValue(args, "/D", defaultDir);
            bool noShortcuts = args.Any(a => string.Equals(a, "/NoShortcuts", StringComparison.OrdinalIgnoreCase));
            ExtractPayload(installDir);

            string controller = Path.Combine(installDir, "Controller", "Rice_Harvester.exe");
            string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            string startMenu = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.Programs),
                "Rice Harvester");
            if (!noShortcuts)
            {
                Directory.CreateDirectory(startMenu);
                if (File.Exists(controller))
                {
                    CreateShortcut(Path.Combine(desktop, "Rice Harvester Controller.lnk"), controller, Path.GetDirectoryName(controller)!);
                    CreateShortcut(Path.Combine(startMenu, "Rice Harvester Controller.lnk"), controller, Path.GetDirectoryName(controller)!);
                }
            }

            string uninstall = Path.Combine(installDir, "Uninstall_Rice_Harvester.cmd");
            File.WriteAllText(uninstall,
                "@echo off\r\n" +
                "echo Removing Rice Harvester...\r\n" +
                "timeout /t 2 /nobreak >nul\r\n" +
                "cd /d %TEMP%\r\n" +
                $"rmdir /s /q \"{installDir}\"\r\n");

            Console.WriteLine("Rice Harvester installed successfully.");
            Console.WriteLine(installDir);
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("Install failed: " + ex.Message);
            return 1;
        }
    }
}
'@
    Set-Content -Path (Join-Path $projectDir "Program.cs") -Value $program -Encoding UTF8

    & $dotnet publish (Join-Path $projectDir "RiceHarvesterSetup.csproj") `
        --configuration Release `
        --runtime win-x64 `
        --self-contained true `
        -p:PublishSingleFile=true `
        -p:IncludeNativeLibrariesForSelfExtract=true `
        -p:DebugType=None `
        -p:DebugSymbols=false `
        --output $publishDir `
        -v minimal
    if ($LASTEXITCODE -ne 0) { throw "Fallback installer build failed." }

    Copy-Item -Force (Join-Path $publishDir "Rice_Harvester_Setup.exe") (Join-Path $installerOut "Rice_Harvester_Setup.exe")
}

function New-DefaultSplitInnoScripts {
    $escapedOutputRoot = $OutputRoot.Replace("\", "\\")
    $escapedInstallerOut = $installerOut.Replace("\", "\\")
    New-Item -ItemType Directory -Force -Path $installerOut | Out-Null

    $controllerScript = Join-Path $OutputRoot "installer_controller.iss"
    $controllerContent = @"
[Setup]
AppId={{D41285AB-6D43-4768-A99E-2E2B98B9A101}}
AppName=Rice Harvester Controller
AppVersion=1.0.0
AppPublisher=Rice Harvester
DefaultDirName={autopf}\Rice Harvester
DefaultGroupName=Rice Harvester
OutputDir=$escapedInstallerOut
OutputBaseFilename=Rice_Harvester_Controller_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "$escapedOutputRoot\\Controller\\Rice_Harvester.exe"; DestDir: "{app}\\Controller"; Flags: ignoreversion
Source: "$($SourceRoot.Replace("\", "\\"))\\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\\Rice Harvester Controller"; Filename: "{app}\\Controller\\Rice_Harvester.exe"
Name: "{autodesktop}\\Rice Harvester Controller"; Filename: "{app}\\Controller\\Rice_Harvester.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"
"@
    Set-Content -Path $controllerScript -Value $controllerContent -Encoding UTF8

    $agentScript = Join-Path $OutputRoot "installer_agent.iss"
    $agentContent = @"
[Setup]
AppId={{1CFE499A-79BB-4891-A44E-7E0B2195D402}}
AppName=Rice Harvester Agent
AppVersion=1.0.0
AppPublisher=Rice Harvester
DefaultDirName={autopf}\Rice Harvester
DefaultGroupName=Rice Harvester
OutputDir=$escapedInstallerOut
OutputBaseFilename=Rice_Harvester_Agent_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "$escapedOutputRoot\\Agent\\*"; DestDir: "{app}\\Agent"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "$escapedOutputRoot\\Hardware\\*"; DestDir: "{app}\\Hardware"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "$($SourceRoot.Replace("\", "\\"))\\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\\Agent 폴더 열기"; Filename: "{app}\\Agent"
Name: "{group}\\Agent 설치 스크립트"; Filename: "{app}\\Agent\\Install_Agent.bat"; Flags: skipifdoesntexist
"@
    Set-Content -Path $agentScript -Value $agentContent -Encoding UTF8

    return @($controllerScript, $agentScript)
}

function New-SelfExtractorPackage(
    [string]$PackageName,
    [string]$AssemblyName,
    [string]$OutputFileName,
    [switch]$IncludeController,
    [switch]$IncludeAgent,
    [switch]$IncludeHardware
) {
    $buildDir = Join-Path $OutputRoot "_installer_build_$PackageName"
    $payloadDir = Join-Path $buildDir "payload"
    $payloadZip = Join-Path $buildDir "payload.zip"
    $projectDir = Join-Path $buildDir "src"
    $publishDir = Join-Path $buildDir "publish"

    if (Test-Path $buildDir) {
        Remove-Item -LiteralPath $buildDir -Force -Recurse
    }
    New-Item -ItemType Directory -Force -Path $payloadDir, $projectDir, $publishDir, $installerOut | Out-Null

    if ($IncludeController) {
        Copy-Item -Path $controllerOut -Destination (Join-Path $payloadDir "Controller") -Recurse -Force
    }
    if ($IncludeAgent) {
        Copy-Item -Path $agentOut -Destination (Join-Path $payloadDir "Agent") -Recurse -Force
    }
    if ($IncludeHardware) {
        $hardwareOut = Join-Path $OutputRoot "Hardware"
        if (Test-Path $hardwareOut) {
            Copy-Item -Path $hardwareOut -Destination (Join-Path $payloadDir "Hardware") -Recurse -Force
        }
    }
    $readme = Join-Path $SourceRoot "README.md"
    if (Test-Path $readme) {
        Copy-Item -Force $readme (Join-Path $payloadDir "README.md")
    }

    Compress-Archive -Path (Join-Path $payloadDir "*") -DestinationPath $payloadZip -Force

    $csproj = @"
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>WinExe</OutputType>
    <TargetFramework>net8.0-windows</TargetFramework>
    <UseWindowsForms>true</UseWindowsForms>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <AssemblyName>$AssemblyName</AssemblyName>
  </PropertyGroup>
  <ItemGroup>
    <EmbeddedResource Include="payload.zip" LogicalName="payload.zip" />
  </ItemGroup>
</Project>
"@
    Set-Content -Path (Join-Path $projectDir "RiceHarvesterSetup.csproj") -Value $csproj -Encoding UTF8
    Copy-Item -Force $payloadZip (Join-Path $projectDir "payload.zip")

    $displayName = if ($IncludeController -and -not $IncludeAgent) { "Rice Harvester Controller" } elseif ($IncludeAgent -and -not $IncludeController) { "Rice Harvester Agent" } else { "Rice Harvester" }
    $program = @'
using System;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Windows.Forms;

internal static class Program
{
    const string DisplayName = "__DISPLAY_NAME__";
    const bool HasController = __HAS_CONTROLLER__;

    static string ArgValue(string[] args, string name, string fallback)
    {
        string prefix = name + "=";
        string? value = args.FirstOrDefault(a => a.StartsWith(prefix, StringComparison.OrdinalIgnoreCase));
        return value is null ? fallback : value.Substring(prefix.Length).Trim('"');
    }

    static void ExtractPayload(string installDir)
    {
        using Stream? payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip");
        if (payload is null) throw new InvalidOperationException("Embedded payload.zip was not found.");
        using var archive = new ZipArchive(payload, ZipArchiveMode.Read);
        string root = Path.GetFullPath(installDir);
        Directory.CreateDirectory(root);
        foreach (ZipArchiveEntry entry in archive.Entries)
        {
            string destination = Path.GetFullPath(Path.Combine(root, entry.FullName));
            if (!destination.StartsWith(root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(destination, root, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("Blocked unsafe archive path: " + entry.FullName);
            }
            if (string.IsNullOrEmpty(entry.Name))
            {
                Directory.CreateDirectory(destination);
                continue;
            }
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            entry.ExtractToFile(destination, overwrite: true);
        }
    }

    static string DefaultInstallDir()
    {
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs",
            "Rice Harvester");
    }

    static void CreateShortcut(string shortcutPath, string targetPath, string workingDirectory)
    {
        try
        {
            Type? shellType = Type.GetTypeFromProgID("WScript.Shell");
            if (shellType is null) return;
            dynamic shell = Activator.CreateInstance(shellType)!;
            dynamic shortcut = shell.CreateShortcut(shortcutPath);
            shortcut.TargetPath = targetPath;
            shortcut.WorkingDirectory = workingDirectory;
            shortcut.Description = "Rice Harvester Controller";
            shortcut.Save();
        }
        catch
        {
            // Shortcut creation is best-effort; installation files are still valid without it.
        }
    }

    static void InstallTo(string installDir, bool noShortcuts)
    {
        ExtractPayload(installDir);

        string controller = Path.Combine(installDir, "Controller", "Rice_Harvester.exe");
        if (!noShortcuts && File.Exists(controller))
        {
            string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            string startMenu = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.Programs),
                "Rice Harvester");
            Directory.CreateDirectory(startMenu);
            CreateShortcut(Path.Combine(desktop, "Rice Harvester Controller.lnk"), controller, Path.GetDirectoryName(controller)!);
            CreateShortcut(Path.Combine(startMenu, "Rice Harvester Controller.lnk"), controller, Path.GetDirectoryName(controller)!);
        }

        string uninstall = Path.Combine(installDir, "Uninstall_Rice_Harvester.cmd");
        File.WriteAllText(uninstall,
            "@echo off\r\n" +
            "echo Removing Rice Harvester...\r\n" +
            "timeout /t 2 /nobreak >nul\r\n" +
            "cd /d %TEMP%\r\n" +
            $"rmdir /s /q \"{installDir}\"\r\n");
    }

    static int RunQuiet(string[] args)
    {
        try
        {
            string installDir = ArgValue(args, "/D", DefaultInstallDir());
            bool noShortcuts = args.Any(a => string.Equals(a, "/NoShortcuts", StringComparison.OrdinalIgnoreCase));
            InstallTo(installDir, noShortcuts);
            return 0;
        }
        catch
        {
            return 1;
        }
    }

    static int RunWizard(string[] args)
    {
        int exitCode = 1;
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);

        using Form form = new Form
        {
            Text = DisplayName + " \uC124\uCE58",
            StartPosition = FormStartPosition.CenterScreen,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            MaximizeBox = false,
            MinimizeBox = false,
            ClientSize = new Size(560, 280),
            BackColor = Color.FromArgb(248, 250, 252),
            Font = new Font("Segoe UI", 9F)
        };

        Label title = new Label
        {
            Text = DisplayName,
            AutoSize = false,
            Location = new Point(24, 20),
            Size = new Size(500, 32),
            Font = new Font("Segoe UI", 16F, FontStyle.Bold),
            ForeColor = Color.FromArgb(21, 32, 45)
        };
        Label subtitle = new Label
        {
            Text = "\uC124\uCE58 \uC704\uCE58\uB97C \uC120\uD0DD\uD55C \uB4A4 \uC124\uCE58\uB97C \uC9C4\uD589\uD558\uC138\uC694.",
            AutoSize = false,
            Location = new Point(26, 56),
            Size = new Size(500, 24),
            ForeColor = Color.FromArgb(92, 109, 128)
        };
        Label pathLabel = new Label
        {
            Text = "\uC124\uCE58 \uACBD\uB85C",
            Location = new Point(26, 100),
            AutoSize = true,
            ForeColor = Color.FromArgb(21, 32, 45)
        };
        TextBox pathBox = new TextBox
        {
            Location = new Point(26, 124),
            Size = new Size(410, 28),
            Text = ArgValue(args, "/D", DefaultInstallDir())
        };
        Button browse = new Button
        {
            Text = "\uCC3E\uC544\uBCF4\uAE30",
            Location = new Point(446, 122),
            Size = new Size(88, 30)
        };
        CheckBox shortcuts = new CheckBox
        {
            Text = "Controller \uBC14\uB85C\uAC00\uAE30 \uC0DD\uC131",
            Location = new Point(26, 164),
            Size = new Size(260, 24),
            Checked = HasController && !args.Any(a => string.Equals(a, "/NoShortcuts", StringComparison.OrdinalIgnoreCase)),
            Visible = HasController
        };
        Label status = new Label
        {
            Text = "",
            Location = new Point(26, 204),
            Size = new Size(360, 24),
            ForeColor = Color.FromArgb(92, 109, 128)
        };
        Button cancel = new Button
        {
            Text = "\uCDE8\uC18C",
            Location = new Point(342, 226),
            Size = new Size(90, 32),
            DialogResult = DialogResult.Cancel
        };
        Button install = new Button
        {
            Text = "\uC124\uCE58",
            Location = new Point(444, 226),
            Size = new Size(90, 32),
            BackColor = Color.FromArgb(47, 115, 218),
            ForeColor = Color.White,
            FlatStyle = FlatStyle.Flat
        };
        install.FlatAppearance.BorderSize = 0;

        browse.Click += (_, _) =>
        {
            using FolderBrowserDialog dialog = new FolderBrowserDialog
            {
                Description = "\uC124\uCE58\uD560 \uD3F4\uB354\uB97C \uC120\uD0DD\uD558\uC138\uC694.",
                SelectedPath = pathBox.Text
            };
            if (dialog.ShowDialog(form) == DialogResult.OK)
            {
                pathBox.Text = dialog.SelectedPath;
            }
        };

        install.Click += (_, _) =>
        {
            try
            {
                string installDir = pathBox.Text.Trim();
                if (string.IsNullOrWhiteSpace(installDir))
                {
                    MessageBox.Show(form, "\uC124\uCE58 \uACBD\uB85C\uB97C \uC785\uB825\uD558\uC138\uC694.", DisplayName, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }
                install.Enabled = false;
                browse.Enabled = false;
                cancel.Enabled = false;
                status.Text = "\uC124\uCE58 \uC911...";
                form.Refresh();
                InstallTo(installDir, noShortcuts: HasController && !shortcuts.Checked);
                status.Text = "\uC124\uCE58 \uC644\uB8CC";
                MessageBox.Show(form, "\uC124\uCE58\uAC00 \uC644\uB8CC\uB418\uC5C8\uC2B5\uB2C8\uB2E4.", DisplayName, MessageBoxButtons.OK, MessageBoxIcon.Information);
                exitCode = 0;
                form.Close();
            }
            catch (Exception ex)
            {
                install.Enabled = true;
                browse.Enabled = true;
                cancel.Enabled = true;
                status.Text = "\uC124\uCE58 \uC2E4\uD328";
                MessageBox.Show(form, ex.Message, DisplayName + " \uC124\uCE58 \uC2E4\uD328", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        };

        form.CancelButton = cancel;
        form.Controls.AddRange(new Control[] { title, subtitle, pathLabel, pathBox, browse, shortcuts, status, cancel, install });
        Application.Run(form);
        return exitCode;
    }

    [STAThread]
    static int Main(string[] args)
    {
        if (args.Any(a =>
            string.Equals(a, "/Quiet", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(a, "/Silent", StringComparison.OrdinalIgnoreCase)))
        {
            return RunQuiet(args);
        }
        return RunWizard(args);
    }
}
'@
    $program = $program.Replace("__DISPLAY_NAME__", $displayName)
    $program = $program.Replace("__HAS_CONTROLLER__", ($(if ($IncludeController) { "true" } else { "false" })))
    Set-Content -Path (Join-Path $projectDir "Program.cs") -Value $program -Encoding UTF8

    & $dotnet publish (Join-Path $projectDir "RiceHarvesterSetup.csproj") `
        --configuration Release `
        --runtime win-x64 `
        --self-contained true `
        -p:PublishSingleFile=true `
        -p:IncludeNativeLibrariesForSelfExtract=true `
        -p:DebugType=None `
        -p:DebugSymbols=false `
        --output $publishDir `
        -v minimal
    if ($LASTEXITCODE -ne 0) { throw "$PackageName installer build failed." }

    Copy-Item -Force (Join-Path $publishDir "$AssemblyName.exe") (Join-Path $installerOut $OutputFileName)
}

function New-SplitSelfExtractingInstallers {
    New-Item -ItemType Directory -Force -Path $installerOut | Out-Null
    Remove-Item -LiteralPath (Join-Path $installerOut "Rice_Harvester_Controller_Setup.exe") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $installerOut "Rice_Harvester_Agent_Setup.exe") -Force -ErrorAction SilentlyContinue

    New-SelfExtractorPackage `
        -PackageName "Controller" `
        -AssemblyName "Rice_Harvester_Controller_Setup" `
        -OutputFileName "Rice_Harvester_Controller_Setup.exe" `
        -IncludeController

    New-SelfExtractorPackage `
        -PackageName "Agent" `
        -AssemblyName "Rice_Harvester_Agent_Setup" `
        -OutputFileName "Rice_Harvester_Agent_Setup.exe" `
        -IncludeAgent `
        -IncludeHardware
}

Write-Host "=== Rice_Harvester build ==="
Write-Host "Source: $SourceRoot"
Write-Host "Output: $OutputRoot"
Write-Host ""

if (-not (Test-Path $icon)) {
    if (Test-Path $makeIcon) {
        Write-Host "[1/4] Generating icon..."
        & $python $makeIcon
        if ($LASTEXITCODE -ne 0) { throw "Icon generation failed." }
    } else {
        Write-Warning "Icon file is missing and make_icon.py was not found."
    }
} else {
    Write-Host "[1/4] Icon ready."
}

Write-Host "[2/4] Publishing Agent..."
& $dotnet publish $agentProject `
    --configuration Release `
    --runtime win-x64 `
    --self-contained true `
    -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    --output $agentOut `
    -v minimal
if ($LASTEXITCODE -ne 0) { throw "Agent publish failed." }

Write-Host "      Packaging Agent installer and VHF driver files..."
Copy-Item -Force $agentInstaller (Join-Path $agentOut "install_agent.ps1")
if (Test-Path $agentInstallerBat) {
    Copy-Item -Force $agentInstallerBat (Join-Path $agentOut "Install_Agent.bat")
}
New-Item -ItemType Directory -Force -Path $driverPackageOut | Out-Null
Get-ChildItem -Path $driverPackageOut -Force | Remove-Item -Force -Recurse

$driverBuildScript = Join-Path $driverSourceDir "build_driver.ps1"
if (Test-Path $driverBuildScript) {
    try {
        $driverBuildArgs = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $driverBuildScript,
            "-SourceRoot", $SourceRoot,
            "-SigningMode", $DriverSigningMode
        )
        if ($DriverEvCertificateThumbprint) {
            $driverBuildArgs += @("-EvCertificateThumbprint", $DriverEvCertificateThumbprint)
        }
        powershell.exe @driverBuildArgs
    } catch {
        Write-Warning "VhfDriver.sys build failed. Existing driver artifact will be used if available. $($_.Exception.Message)"
    }
}

foreach ($file in @("VhfDriver.inf", "install.ps1")) {
    $src = Join-Path $driverSourceDir $file
    if (Test-Path $src) {
        Copy-Item -Force $src (Join-Path $driverPackageOut $file)
    }
}

$driverCandidates = @(
    (Join-Path $OutputRoot "VhfDriver\VhfDriver.sys"),
    (Join-Path $SourceRoot "Build\VhfDriver\VhfDriver.sys"),
    (Join-Path $driverSourceDir "VhfDriver.sys")
)
$catCandidates = @(
    (Join-Path $OutputRoot "VhfDriver\VhfDriver.cat"),
    (Join-Path $SourceRoot "Build\VhfDriver\VhfDriver.cat"),
    (Join-Path $driverSourceDir "VhfDriver.cat")
)
$certCandidates = @(
    (Join-Path $OutputRoot "VhfDriver\VhfDriver.cer"),
    (Join-Path $SourceRoot "Build\VhfDriver\VhfDriver.cer"),
    (Join-Path $driverSourceDir "VhfDriver.cer")
)
$devconCandidates = @(
    (Join-Path $OutputRoot "VhfDriver\devcon.exe"),
    (Join-Path $SourceRoot "Build\VhfDriver\devcon.exe"),
    (Join-Path $driverSourceDir "devcon.exe")
)

$driverSys = $driverCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($driverSys) {
    Copy-Item -Force $driverSys (Join-Path $driverPackageOut "VhfDriver.sys")
} else {
    Write-Warning "VhfDriver.sys was not found. Build the VHF driver before installing Agent hardware HID support."
}

$driverCat = $catCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($driverCat) {
    Copy-Item -Force $driverCat (Join-Path $driverPackageOut "VhfDriver.cat")
}

$driverCert = $certCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($driverCert) {
    Copy-Item -Force $driverCert (Join-Path $driverPackageOut "VhfDriver.cer")
}

$devcon = $devconCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($devcon) {
    Copy-Item -Force $devcon (Join-Path $driverPackageOut "devcon.exe")
}

if (Test-Path $hardwareSourceDir) {
    $hardwareOut = Join-Path $OutputRoot "Hardware"
    if (Test-Path $hardwareOut) {
        Remove-Item -LiteralPath $hardwareOut -Force -Recurse
    }
    Copy-Item -Path $hardwareSourceDir -Destination $hardwareOut -Recurse -Force
}

Write-Host "[3/4] Building Controller..."
if (-not $SkipPipInstall) {
    & $python -m pip install -r $requirements --quiet
    if ($LASTEXITCODE -ne 0) { throw "Controller dependency install failed." }
}

$pyinstallerArgs = @(
    "-m", "PyInstaller", $controllerMain,
    "--onefile",
    "--windowed",
    "--name", "Rice_Harvester",
    "--distpath", $controllerOut,
    "--workpath", $pyiWork,
    "--specpath", $specOut,
    "--noconfirm"
)

if (Test-Path $icon) {
    $pyinstallerArgs += @("--icon", $icon, "--add-data", "$icon;assets")
}

& $python $pyinstallerArgs
if ($LASTEXITCODE -ne 0) { throw "Controller build failed." }

Write-Host "[4/4] Installer step..."
if (-not $SkipInstaller -and (Test-Path $iscc)) {
    New-Item -ItemType Directory -Force -Path $installerOut | Out-Null
    if ($InstallerMode -in @("Full", "Both")) {
        $installerScript = Join-Path $OutputRoot "installer.iss"
        New-DefaultInnoScript $installerScript
        & $iscc $installerScript
        if ($LASTEXITCODE -ne 0) { throw "Installer build failed: $installerScript" }
    }
    if ($InstallerMode -in @("Split", "Both")) {
        foreach ($installerScript in (New-DefaultSplitInnoScripts)) {
            & $iscc $installerScript
            if ($LASTEXITCODE -ne 0) { throw "Installer build failed: $installerScript" }
        }
    }
} elseif (-not $SkipInstaller) {
    Write-Warning "Inno Setup was not found. Building .NET self-extracting installer(s) instead."
    if ($InstallerMode -in @("Full", "Both")) {
        New-SelfExtractingInstaller
    }
    if ($InstallerMode -in @("Split", "Both")) {
        if ($InstallerMode -eq "Split") {
            Remove-Item -LiteralPath (Join-Path $installerOut "Rice_Harvester_Setup.exe") -Force -ErrorAction SilentlyContinue
        }
        New-SplitSelfExtractingInstallers
    }
} else {
    Write-Host "Installer skipped."
}

Write-Host ""
Write-Host "=== Build complete ==="
Write-Host "Agent:      $(Join-Path $agentOut 'Rice_Harvester_Agent.exe')"
Write-Host "Controller: $(Join-Path $controllerOut 'Rice_Harvester.exe')"
if (Test-Path (Join-Path $installerOut "Rice_Harvester_Setup.exe")) {
    Write-Host "Full Installer:       $(Join-Path $installerOut 'Rice_Harvester_Setup.exe')"
}
if (Test-Path (Join-Path $installerOut "Rice_Harvester_Controller_Setup.exe")) {
    Write-Host "Controller Installer: $(Join-Path $installerOut 'Rice_Harvester_Controller_Setup.exe')"
}
if (Test-Path (Join-Path $installerOut "Rice_Harvester_Agent_Setup.exe")) {
    Write-Host "Agent Installer:      $(Join-Path $installerOut 'Rice_Harvester_Agent_Setup.exe')"
}
