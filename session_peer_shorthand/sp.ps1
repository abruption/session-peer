# Dot-source in the current scope. Use -Remove to remove only our alias.
param([Alias('Remove')][switch] $SessionPeerSpRemove)

if ($MyInvocation.InvocationName -ne '.') {
    throw 'Dot-source sp.ps1 to change the current PowerShell scope.'
}
# Wildcard syntax forces enumeration rather than exact-name command discovery.
# -ListImported alone still permits exact-name misses to auto-import a module.
$SessionPeerSpExisting = @(Get-Command -Name '[s]p' -All -ListImported -ErrorAction SilentlyContinue)
$SessionPeerSpMarker = Get-Variable -Name SessionPeerSpOwned -Scope Local -ErrorAction SilentlyContinue
$SessionPeerSpVisibleAlias = Get-Alias -Name sp -ErrorAction SilentlyContinue
if ($SessionPeerSpVisibleAlias -and $SessionPeerSpMarker -and $SessionPeerSpMarker.Value -eq $true -and
    $SessionPeerSpVisibleAlias.Definition -eq 'session-peer') {
    if ($SessionPeerSpRemove) {
        Remove-Item -LiteralPath Alias:sp -ErrorAction Stop
        Remove-Variable -Name SessionPeerSpOwned -ErrorAction SilentlyContinue
    }
    return
}
if ($SessionPeerSpExisting.Count -gt 0) {
    throw 'sp already exists (PowerShell normally uses it for Set-ItemProperty). Nothing was changed.'
}
if ($SessionPeerSpRemove) {
    Remove-Variable -Name SessionPeerSpOwned -ErrorAction SilentlyContinue
    return
}
if (-not (Get-Command -Name '[s]ession-peer' -ListImported -ErrorAction SilentlyContinue)) {
    throw 'session-peer is unavailable; select its existing installation on PATH first.'
}
Set-Alias -Name sp -Value session-peer -Scope Local -ErrorAction Stop
$SessionPeerSpOwned = $true
