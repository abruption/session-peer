# Dot-source in the current scope. Use -Remove to remove only our alias.
param([Alias('Remove')][switch] $SessionPeerSpRemove)

if ($MyInvocation.InvocationName -ne '.') {
    throw 'Dot-source sp.ps1 to change the current PowerShell scope.'
}
# -ListImported alone still permits exact-name misses to auto-import a module.
# Disable autoload only in a child lookup scope, preserving caller preferences.
# Exact-name lookup still finds native executables and Windows .cmd launchers.
$SessionPeerSpExisting = @(& {
    $PSModuleAutoLoadingPreference = 'None'
    Get-Command -Name sp -All -ListImported -ErrorAction SilentlyContinue
})
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
$SessionPeerSpCanonical = @(& {
    $PSModuleAutoLoadingPreference = 'None'
    Get-Command -Name session-peer -ListImported -ErrorAction SilentlyContinue
})
if ($SessionPeerSpCanonical.Count -eq 0) {
    throw 'session-peer is unavailable; select its existing installation on PATH first.'
}
Set-Alias -Name sp -Value session-peer -Scope Local -ErrorAction Stop
$SessionPeerSpOwned = $true
