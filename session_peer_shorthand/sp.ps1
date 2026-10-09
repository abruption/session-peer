# Dot-source in the current scope. Use -Remove to remove only our alias.
param([Alias('Remove')][switch] $SessionPeerSpRemove)

if ($MyInvocation.InvocationName -ne '.') {
    throw 'Dot-source sp.ps1 to change the current PowerShell scope.'
}
# -ListImported alone still permits exact-name misses to auto-import a module.
# Disable autoload only during lookup, restoring the caller's local preference.
# Exact-name lookup still finds native executables and Windows .cmd launchers.
$SessionPeerSpPreference = Get-Variable -Name PSModuleAutoLoadingPreference -Scope Local -ErrorAction SilentlyContinue
$SessionPeerSpSavedPreference = if ($SessionPeerSpPreference) { $SessionPeerSpPreference.Value } else { $null }
try {
    Set-Variable -Name PSModuleAutoLoadingPreference -Value 'None' -Scope Local -ErrorAction Stop
    $SessionPeerSpExisting = @(Get-Command -Name sp -All -ListImported -ErrorAction SilentlyContinue)
    $SessionPeerSpCanonical = @(Get-Command -Name session-peer -ListImported -ErrorAction SilentlyContinue)
} finally {
    if ($SessionPeerSpPreference) {
        Set-Variable -Name PSModuleAutoLoadingPreference -Value $SessionPeerSpSavedPreference -Scope Local -ErrorAction Stop
    } else {
        Remove-Variable -Name PSModuleAutoLoadingPreference -Scope Local -ErrorAction SilentlyContinue
    }
}
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
if ($SessionPeerSpCanonical.Count -eq 0) {
    throw 'session-peer is unavailable; select its existing installation on PATH first.'
}
Set-Alias -Name sp -Value session-peer -Scope Local -ErrorAction Stop
$SessionPeerSpOwned = $true
