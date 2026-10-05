Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Set the working directory to the script's folder
WshShell.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)

' Launch dmod.py via PowerShell completely hidden (window style 0)
WshShell.Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""python dmod.py""", 0, False