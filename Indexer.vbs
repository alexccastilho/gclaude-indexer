' GClaude Indexer - entry point for the desktop shortcut (explicit user
' request: version 1.0, no longer an MVP - no console window flashing
' when opening the system.
'
' If the virtual environment already exists on this machine, starts
' everything (Indexer.bat, which in turn already uses pythonw.exe for the
' server) with no window shown. The first time, when the installer still
' needs to run (it can take a while and can fail), leaves the window
' visible -- running the installer hidden would mean the user never sees
' an error or gets to dismiss the .bat file's error pause.
'
' Phase 15, task 3: forwards the optional "--cpu-sensor" flag to the .bat,
' which is what the second desktop shortcut ("GClaude Indexer (CPU sensor)")
' passes. Recognised by name and re-emitted as a literal, never
' concatenated from what came in: this string ends up on a command line, and
' an allow-list of exactly one known flag is the cheapest way to be sure
' nothing else can ever get there. Anything else on the command line is
' ignored, and ignoring it opens the system normally -- the same thing that
' happens with no arguments at all.
Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

ScriptFolder = objFSO.GetParentFolderName(WScript.ScriptFullName)
BatPath = ScriptFolder & "\Indexer.bat"
VenvPythonPath = objShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\GClaudeIndexer\venv\Scripts\python.exe"

ExtraArgument = ""
If WScript.Arguments.Count > 0 Then
    If LCase(WScript.Arguments(0)) = "--cpu-sensor" Then
        ExtraArgument = " --cpu-sensor"
    End If
End If

CommandLine = """" & BatPath & """" & ExtraArgument

If objFSO.FileExists(VenvPythonPath) Then
    objShell.Run CommandLine, 0, False
Else
    objShell.Run CommandLine, 1, False
End If
