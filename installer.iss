[Setup]
AppName=SimpleDM
AppVersion=1.0
DefaultDirName={autopf}\SimpleDM
DefaultGroupName=SimpleDM
OutputDir=installer_out
OutputBaseFilename=SimpleDM-Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest

[Files]
Source: "dist\SimpleDM.exe"; DestDir: "{app}"
Source: "extension\*"; DestDir: "{app}\extension"; Flags: recursesubdirs

[Icons]
Name: "{group}\SimpleDM"; Filename: "{app}\SimpleDM.exe"
Name: "{autodesktop}\SimpleDM"; Filename: "{app}\SimpleDM.exe"

[Run]
Filename: "{app}\SimpleDM.exe"; Description: "Start SimpleDM"; Flags: nowait postinstall skipifsilent
