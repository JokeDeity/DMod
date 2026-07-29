<#
.SYNOPSIS
    BlueAway GUI - Deep Bluetooth Registry Cleaner & Obliterator
.DESCRIPTION
    Designed to run hidden/standalone or embedded as a subprogram from DMod.
#>

# Hide the PowerShell console window immediately upon execution
Add-Type -Name Window -Namespace Console -MemberDefinition '[DllImport("Kernel32.dll")] public static extern IntPtr GetConsoleWindow(); [DllImport("User32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);'
$consolePtr = [Console.Window]::GetConsoleWindow()
if ($consolePtr -ne [IntPtr]::Zero) { 
    [Console.Window]::ShowWindow($consolePtr, 0) | Out-Null 
}

# Ensure script runs as Administrator
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -ArgumentList "-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    Exit
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# --- Root Directory & Backup Setup ---
# Determine root directory dynamically (where BlueAway.ps1 or DMod.exe resides)
$RootDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$backupDir = Join-Path -Path $RootDir -ChildPath "BlueAway_Backups"

if (-not (Test-Path -Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

# Timestamped registry backup directly into the local backup folder
$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$RegBackupFile = Join-Path -Path $backupDir -ChildPath "Bluetooth_Devices_Backup_$Timestamp.reg"

reg export "HKLM\SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices" "$RegBackupFile" /y

# --- Registry & Cleanup Logic ---
$BthDevicesPath = "SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
$BthKeysPath    = "SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Keys"
$BthEnumPath    = "SYSTEM\CurrentControlSet\Enum\BTHENUM"

function Get-BluetoothDevices {
    $masterList = @{}
    $baseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Default)

    try {
        $DevicesKey = $baseKey.OpenSubKey($BthDevicesPath, [Microsoft.Win32.RegistryKeyPermissionCheck]::ReadSubTree, [System.Security.AccessControl.RegistryRights]::ReadKey)
        if ($DevicesKey) {
            foreach ($mac in $DevicesKey.GetSubKeyNames()) {
                $subKey = $DevicesKey.OpenSubKey($mac)
                $nameVal = $subKey.GetValue("Name")
                if (-not $nameVal) { $nameVal = $subKey.GetValue("LName") }
                
                $friendlyName = "Unknown Device ($mac)"
                if ($nameVal -is [byte[]]) {
                    $friendlyName = [System.Text.Encoding]::UTF8.GetString($nameVal).Trim([char]0)
                } elseif ($nameVal -is [string]) {
                    $friendlyName = $nameVal
                }

                $masterList[$mac] = [PSCustomObject]@{
                    Name       = $friendlyName
                    Mac        = $mac
                    DevPath    = "$BthDevicesPath\$mac"
                    KeyPath    = "$BthKeysPath"
                    EnumPaths  = @()
                }
                $subKey.Close()
            }
            $DevicesKey.Close()
        }
    } catch {}

    try {
        $EnumKey = $baseKey.OpenSubKey($BthEnumPath, [Microsoft.Win32.RegistryKeyPermissionCheck]::ReadSubTree, [System.Security.AccessControl.RegistryRights]::ReadKey)
        if ($EnumKey) {
            foreach ($subKeyName in $EnumKey.GetSubKeyNames()) {
                if ($subKeyName -like "DEV_*") {
                    $mac = $subKeyName.Substring(4, 12)
                    $deviceSubKey = $EnumKey.OpenSubKey($subKeyName)
                    if ($deviceSubKey) {
                        foreach ($instance in $deviceSubKey.GetSubKeyNames()) {
                            $fullInstancePath = "$BthEnumPath\$subKeyName\$instance"
                            if ($masterList.ContainsKey($mac)) {
                                $masterList[$mac].EnumPaths += $fullInstancePath
                            } else {
                                $masterList[$mac] = [PSCustomObject]@{
                                    Name       = "Orphaned Ghost Device ($mac)"
                                    Mac        = $mac
                                    DevPath    = $null
                                    KeyPath    = $null
                                    EnumPaths  = @($fullInstancePath)
                                }
                            }
                        }
                        $deviceSubKey.Close()
                    }
                }
            }
            $EnumKey.Close()
        }
    } catch {}

    return ,($masterList.Values | Where-Object { $_.Mac -match '^[0-9A-Fa-f]{12}$' })
}

# --- GUI Construction ---
$form = New-Object System.Windows.Forms.Form
$form.Text = "BlueAway - Deep Registry Bluetooth Device Remover"
$form.Size = New-Object System.Drawing.Size(710, 520)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(30, 30, 30)
$form.ForeColor = [System.Drawing.Color]::White

# Header Label
$lblTitle = New-Object System.Windows.Forms.Label
$lblTitle.Text = "BlueAway - Deep Registry Bluetooth Device Remover"
$lblTitle.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
$lblTitle.Location = New-Object System.Drawing.Point(15, 15)
$lblTitle.AutoSize = $true
$form.Controls.Add($lblTitle)

# ListView for Devices
$listView = New-Object System.Windows.Forms.ListView
$listView.View = [System.Windows.Forms.View]::Details
$listView.FullRowSelect = $true
$listView.GridLines = $true
$listView.BackColor = [System.Drawing.Color]::FromArgb(45, 45, 48)
$listView.ForeColor = [System.Drawing.Color]::White
$listView.Location = New-Object System.Drawing.Point(15, 50)
$listView.Size = New-Object System.Drawing.Size(665, 240)
$listView.Columns.Add("Device Name", 290) | Out-Null
$listView.Columns.Add("MAC Address", 170) | Out-Null
$listView.Columns.Add("Links Found", 180) | Out-Null
$form.Controls.Add($listView)

# Log/Status Textbox
$txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Multiline = $true
$txtLog.ScrollBars = "Vertical"
$txtLog.ReadOnly = $true
$txtLog.BackColor = [System.Drawing.Color]::FromArgb(20, 20, 20)
$txtLog.ForeColor = [System.Drawing.Color]::LightGreen
$txtLog.Location = New-Object System.Drawing.Point(15, 305)
$txtLog.Size = New-Object System.Drawing.Size(520, 140)
$form.Controls.Add($txtLog)

# Function to refresh list data inside GUI
function Refresh-DeviceList {
    $listView.Items.Clear()
    $global:currentDevices = Get-BluetoothDevices
    foreach ($dev in $global:currentDevices) {
        $item = New-Object System.Windows.Forms.ListViewItem($dev.Name)
        $item.SubItems.Add($dev.Mac) | Out-Null
        $item.SubItems.Add("$($dev.EnumPaths.Count) hardware link(s)") | Out-Null
        $listView.Items.Add($item) | Out-Null
    }
    $txtLog.AppendText("`r`n[+] Scanned registry. Found $($global:currentDevices.Count) devices.")
}

# Obliterate Button
$btnClean = New-Object System.Windows.Forms.Button
$btnClean.Text = "OBLITERATE"
$btnClean.BackColor = [System.Drawing.Color]::FromArgb(180, 40, 40)
$btnClean.ForeColor = [System.Drawing.Color]::White
$btnClean.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$btnClean.Location = New-Object System.Drawing.Point(550, 305)
$btnClean.Size = New-Object System.Drawing.Size(130, 38)
$form.Controls.Add($btnClean)

# Refresh Button
$btnRefresh = New-Object System.Windows.Forms.Button
$btnRefresh.Text = "Refresh List"
$btnRefresh.BackColor = [System.Drawing.Color]::FromArgb(50, 50, 50)
$btnRefresh.ForeColor = [System.Drawing.Color]::White
$btnRefresh.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$btnRefresh.Location = New-Object System.Drawing.Point(550, 350)
$btnRefresh.Size = New-Object System.Drawing.Size(130, 30)
$form.Controls.Add($btnRefresh)

# View Backups Button
$btnBackups = New-Object System.Windows.Forms.Button
$btnBackups.Text = "Manage Backups"
$btnBackups.BackColor = [System.Drawing.Color]::FromArgb(40, 110, 180)
$btnBackups.ForeColor = [System.Drawing.Color]::White
$btnBackups.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$btnBackups.Location = New-Object System.Drawing.Point(550, 390)
$btnBackups.Size = New-Object System.Drawing.Size(130, 30)
$form.Controls.Add($btnBackups)

# --- Backup Manager Form Function ---
function Show-BackupManager {
    $subForm = New-Object System.Windows.Forms.Form
    $subForm.Text = "BlueAway - Backup Manager"
    $subForm.Size = New-Object System.Drawing.Size(650, 400)
    $subForm.StartPosition = "CenterParent"
    $subForm.BackColor = [System.Drawing.Color]::FromArgb(30, 30, 30)
    $subForm.ForeColor = [System.Drawing.Color]::White

    $lblSub = New-Object System.Windows.Forms.Label
    $lblSub.Text = "Saved Backup Registry Files ($backupDir):"
    $lblSub.Location = New-Object System.Drawing.Point(15, 15)
    $lblSub.AutoSize = $true
    $subForm.Controls.Add($lblSub)

    $subList = New-Object System.Windows.Forms.ListView
    $subList.View = [System.Windows.Forms.View]::Details
    $subList.FullRowSelect = $true
    $subList.GridLines = $true
    $subList.BackColor = [System.Drawing.Color]::FromArgb(45, 45, 48)
    $subList.ForeColor = [System.Drawing.Color]::White
    $subList.Location = New-Object System.Drawing.Point(15, 45)
    $subList.Size = New-Object System.Drawing.Size(605, 230)
    $subList.Columns.Add("Backup File Name", 420) | Out-Null
    $subList.Columns.Add("Date Created", 160) | Out-Null
    $subForm.Controls.Add($subList)

    function Load-BackupItems {
        $subList.Items.Clear()
        if (Test-Path $backupDir) {
            $files = Get-ChildItem -Path $backupDir -Filter "*.reg"
            foreach ($file in $files) {
                $item = New-Object System.Windows.Forms.ListViewItem($file.Name)
                $item.SubItems.Add($file.CreationTime.ToString("yyyy-MM-dd HH:mm:ss")) | Out-Null
                $subList.Items.Add($item) | Out-Null
            }
        }
    }
    Load-BackupItems

    $btnOpenFolder = New-Object System.Windows.Forms.Button
    $btnOpenFolder.Text = "Open Folder"
    $btnOpenFolder.BackColor = [System.Drawing.Color]::FromArgb(50, 50, 50)
    $btnOpenFolder.ForeColor = [System.Drawing.Color]::White
    $btnOpenFolder.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $btnOpenFolder.Location = New-Object System.Drawing.Point(15, 290)
    $btnOpenFolder.Size = New-Object System.Drawing.Size(120, 35)
    $subForm.Controls.Add($btnOpenFolder)

    $btnRestore = New-Object System.Windows.Forms.Button
    $btnRestore.Text = "Restore Selected"
    $btnRestore.BackColor = [System.Drawing.Color]::FromArgb(40, 140, 60)
    $btnRestore.ForeColor = [System.Drawing.Color]::White
    $btnRestore.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $btnRestore.Location = New-Object System.Drawing.Point(365, 290)
    $btnRestore.Size = New-Object System.Drawing.Size(120, 35)
    $subForm.Controls.Add($btnRestore)

    $btnDeleteBackup = New-Object System.Windows.Forms.Button
    $btnDeleteBackup.Text = "Delete Backup"
    $btnDeleteBackup.BackColor = [System.Drawing.Color]::FromArgb(140, 40, 40)
    $btnDeleteBackup.ForeColor = [System.Drawing.Color]::White
    $btnDeleteBackup.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $btnDeleteBackup.Location = New-Object System.Drawing.Point(500, 290)
    $btnDeleteBackup.Size = New-Object System.Drawing.Size(120, 35)
    $subForm.Controls.Add($btnDeleteBackup)

    $btnOpenFolder.Add_Click({
        if (Test-Path $backupDir) { Start-Process $backupDir }
    })

    $btnRestore.Add_Click({
        if ($subList.SelectedItems.Count -eq 0) { return }
        $fileName = $subList.SelectedItems[0].Text
        $filePath = Join-Path $backupDir $fileName
        $confirm = [System.Windows.Forms.MessageBox]::Show("Merge registry settings from '$fileName' back into the system?", "Confirm Restore", [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question)
        if ($confirm -eq [System.Windows.Forms.DialogResult]::Yes) {
            & reg.exe import "$filePath"
            [System.Windows.Forms.MessageBox]::Show("Registry backup restored successfully.", "Restored", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
        }
    })

    $btnDeleteBackup.Add_Click({
        if ($subList.SelectedItems.Count -eq 0) { return }
        $fileName = $subList.SelectedItems[0].Text
        $filePath = Join-Path $backupDir $fileName
        Remove-Item $filePath -Force -ErrorAction SilentlyContinue
        Load-BackupItems
    })

    [void]$subForm.ShowDialog()
}

$btnBackups.Add_Click({
    Show-BackupManager
})

# --- Main Actions ---
$btnRefresh.Add_Click({
    Refresh-DeviceList
})

$btnClean.Add_Click({
    if ($listView.SelectedItems.Count -eq 0) {
        [System.Windows.Forms.MessageBox]::Show("Please select a device from the list first.", "No Selection", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)
        return
    }

    $selectedIndex = $listView.SelectedIndices[0]
    $target = $global:currentDevices[$selectedIndex]

    $confirm = [System.Windows.Forms.MessageBox]::Show("Are you sure you want to completely obliterate all traces of $($target.Name)?", "Confirm Obliteration", [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question)
    if ($confirm -eq [System.Windows.Forms.DialogResult]::Yes) {
        $txtLog.AppendText("`r`n[~] Purging $($target.Name)...")
        
        try {
            New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
            $safeName = $target.Name -replace '[\\/:*?"<>|]', '_'
            $backupFile = "$backupDir\$safeName`_($($target.Mac))_$(Get-Date -Format 'yyyyMMdd_HHmmss').reg"

            function Remove-RegKeyForce {
                param($path)
                if (-not $path) { return }
                $fullPath = "HKLM\$path"
                & reg.exe query "$fullPath" > $null 2>&1
                if ($LASTEXITCODE -ne 0) { return }
                & takeown.exe /f "$fullPath" /r /d y *>&1 | Out-Null
                & icacls.exe "$fullPath" /grant administrators:F /t *>&1 | Out-Null
                & reg.exe export "$fullPath" "$backupFile" /y *>&1 | Out-Null
                & reg.exe delete "$fullPath" /f *>&1 | Out-Null
            }

            if ($target.DevPath) { Remove-RegKeyForce $target.DevPath }

            try {
                $baseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Default)
                $keysRootPath = "SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Keys"
                $keysRootKey = $baseKey.OpenSubKey($keysRootPath, [Microsoft.Win32.RegistryKeyPermissionCheck]::ReadSubTree, [System.Security.AccessControl.RegistryRights]::ReadKey)
                if ($keysRootKey) {
                    foreach ($adapter in $keysRootKey.GetSubKeyNames()) {
                        Remove-RegKeyForce "$keysRootPath\$adapter\$($target.Mac)"
                    }
                    $keysRootKey.Close()
                }
            } catch {}

            foreach ($ep in $target.EnumPaths) {
                Remove-RegKeyForce $ep
            }

            $macUpper = $target.Mac.ToUpper()
            $macFormatted1 = "$($macUpper.Substring(0,2))-$($macUpper.Substring(2,2))-$($macUpper.Substring(4,2))-$($macUpper.Substring(6,2))-$($macUpper.Substring(8,2))-$($macUpper.Substring(10,2))"
            $macFormatted2 = "$($macUpper.Substring(0,2)):$($macUpper.Substring(2,2)):$($macUpper.Substring(4,2)):$($macUpper.Substring(6,2)):$($macUpper.Substring(8,2)):$($macUpper.Substring(10,2))"

            $allHivesToSweep = @(
                "SYSTEM\CurrentControlSet\Control\DeviceContainers",
                "SYSTEM\CurrentControlSet\Control\Bluetooth\AudioDevices",
                "SYSTEM\CurrentControlSet\Enum\ROOT\BLUETOOTHWDP",
                "SYSTEM\CurrentControlSet\Enum\BTH",
                "SOFTWARE\Microsoft\Windows\CurrentVersion\Bluetooth\DeviceSupport"
            )

            foreach ($hive in $allHivesToSweep) {
                try {
                    $searchKey = $baseKey.OpenSubKey($hive, [Microsoft.Win32.RegistryKeyPermissionCheck]::ReadSubTree, [System.Security.AccessControl.RegistryRights]::ReadKey)
                    if ($searchKey) {
                        foreach ($subName in $searchKey.GetSubKeyNames()) {
                            if ($subName -like "*$macUpper*" -or $subName -like "*$macFormatted1*" -or $subName -like "*$macFormatted2*") {
                                Remove-RegKeyForce "$hive\$subName"
                            } else {
                                $subInstance = $searchKey.OpenSubKey($subName)
                                if ($subInstance) {
                                    foreach ($nestedName in $subInstance.GetSubKeyNames()) {
                                        if ($nestedName -like "*$macUpper*" -or $nestedName -like "*$macFormatted1*" -or $nestedName -like "*$macFormatted2*") {
                                            Remove-RegKeyForce "$hive\$subName\$nestedName"
                                        }
                                    }
                                    $subInstance.Close()
                                }
                            }
                        }
                        $searchKey.Close()
                    }
                } catch {}
            }

            # --- STEP 2: Device Manager / Plug and Play PnP Cleanup ---
            $txtLog.AppendText("`r`n[~] Uninstalling Device Manager PnP nodes...")
            
            # Fetch PnP devices by MAC address match, formatted MAC match, or target device name
            $pnpDevices = Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { 
                ($_.InstanceId -like "*$macUpper*" -or 
                 $_.InstanceId -like "*$macFormatted1*" -or 
                 $_.InstanceId -like "*$macFormatted2*" -or 
                 ($target.Name -ne $null -and $_.FriendlyName -eq $target.Name))
            }
            
            foreach ($dev in $pnpDevices) {
                & pnputil.exe /remove-device "$($dev.InstanceId)" *>&1 | Out-Null
            }

            # Also sweep any orphaned disconnected Bluetooth/Audio PnP nodes
            $phantomBluetoothNodes = Get-PnpDevice -Class 'Bluetooth' -ErrorAction SilentlyContinue | 
                                     Where-Object { $_.Present -eq $false -and $_.InstanceId -like "*$macUpper*" }
            foreach ($node in $phantomBluetoothNodes) {
                & pnputil.exe /remove-device "$($node.InstanceId)" *>&1 | Out-Null
            }

            # Restart Bluetooth Service to apply changes
            $job = Start-Job -ScriptBlock { Stop-Service -Name bthserv -Force -ErrorAction SilentlyContinue }
            $null = Wait-Job $job -Timeout 3
            Remove-Job $job -Force
            Start-Service -Name bthserv -ErrorAction SilentlyContinue

            $txtLog.AppendText("`r`n[+] Success! Obliterated.")
            Refresh-DeviceList
        } catch {
            $txtLog.AppendText("`r`n[-] Error: $_")
        }
    }
})

$form.Add_Shown({
    Refresh-DeviceList
})

[void]$form.ShowDialog()