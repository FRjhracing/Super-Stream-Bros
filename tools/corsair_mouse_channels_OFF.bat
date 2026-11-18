@echo off
rem Turns OFF the 4 Corsair mouse HID channels that make every Dolphin start wait ~40 s.
rem Pointer, buttons and keyboard keep working; iCUE can't control the mouse (lighting, DPI) until turned back on.
rem Corsair mouse = VID_1B1C PID_1B3E; channels MI_00 COL02/COL03/COL04 + MI_01. See VODCUTTER_PROJECT_NOTES.md.
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" & exit /b)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d = @(Get-PnpDevice -PresentOnly | ? { $_.InstanceId -match '^HID.VID_1B1C&PID_1B3E&(MI_00&COL0[234]|MI_01)' }); if ($d.Count -eq 0) { 'Corsair mouse not found (unplugged?)' } else { $d | Disable-PnpDevice -Confirm:$false; Get-PnpDevice | ? { $_.InstanceId -match '^HID.VID_1B1C&PID_1B3E&(MI_00&COL0[234]|MI_01)' } | ft Status,FriendlyName,InstanceId -auto }"
pause
