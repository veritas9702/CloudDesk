[CmdletBinding(SupportsShouldProcess)]
param()
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
if (-not (Test-Path -LiteralPath (Join-Path $root 'cloudtool\__init__.py'))) { throw 'Project marker missing' }
if (-not (Test-Path -LiteralPath (Join-Path $root 'app\CloudDesk\CloudDesk.exe'))) { throw 'Current app is missing. Build the latest app before cleaning.' }
if (Get-Process -Name CloudDesk -ErrorAction SilentlyContinue) { throw 'Close CloudDesk before cleanup.' }
$names = @('dist','dist-v0.2','dist-v0.3','dist-v0.4','dist-v0.5','dist-v0.6','dist-v0.7','dist-v0.8','dist-v0.9','dist-v0.9-chrome','dist-v0.10','dist-v0.10.1','dist-v0.10.2','dist-v0.10.3','build','.build','__pycache__','cloudtool\__pycache__','tests\__pycache__','tools\__pycache__')
$targets = @()
foreach ($name in $names) {
    $target = [IO.Path]::GetFullPath((Join-Path $root $name))
    if (-not $target.StartsWith($root + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Path is outside project' }
    if (-not (Test-Path -LiteralPath $target)) { continue }
    $item = Get-Item -LiteralPath $target -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing link: $target" }
    if (Get-ChildItem -LiteralPath $target -Recurse -Force -Attributes ReparsePoint) { throw "Refusing folder with links: $target" }
    $targets += $target
}
$freed = 0L
foreach ($target in $targets) {
    $size = (Get-ChildItem -LiteralPath $target -Recurse -File -Force | Measure-Object -Property Length -Sum).Sum
    if ($PSCmdlet.ShouldProcess($target,'Delete obsolete build/cache')) {
        Remove-Item -LiteralPath $target -Recurse -Force
        $freed += $size
    }
}
Write-Host ('Deleted {0:N1} MB. Current app, source, .venv and local user data are preserved.' -f ($freed / 1MB))
