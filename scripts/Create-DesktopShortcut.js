// Windows Script Host JScript. No installation or policy/settings changes.
(function () {
    try {
        if (WScript.Arguments.length > 1) {
            throw new Error("Expected at most one ProjectRoot argument.");
        }
        var files = new ActiveXObject("Scripting.FileSystemObject");
        var requestedRoot = WScript.Arguments.length === 1 ? WScript.Arguments(0) :
            files.GetParentFolderName(files.GetParentFolderName(WScript.ScriptFullName));
        var root = files.GetFolder(files.GetAbsolutePathName(requestedRoot)).Path;
        var target = files.BuildPath(root, "Launch.bat");
        var legacyTarget = files.BuildPath(root, "Launch.cmd");
        var icon = files.BuildPath(root, "static\\agent-workbench.ico");
        if (!files.FileExists(target)) {
            throw new Error("Launch.bat was not found in ProjectRoot.");
        }
        if (!files.FileExists(icon)) {
            throw new Error("static\\agent-workbench.ico was not found in ProjectRoot.");
        }
        var shell = new ActiveXObject("WScript.Shell");
        var desktop = shell.SpecialFolders("Desktop");
        if (!desktop || !files.FolderExists(desktop)) {
            throw new Error("The Windows desktop folder could not be located.");
        }
        var destination = files.BuildPath(desktop, "Agent Workbench.lnk");
        var existed = files.FileExists(destination);
        var shortcut = shell.CreateShortcut(destination);
        if (existed) {
            var existingTarget = String(shortcut.TargetPath).toLowerCase();
            if (existingTarget !== target.toLowerCase() && existingTarget !== legacyTarget.toLowerCase()) {
                throw new Error("A different Agent Workbench.lnk already exists on the desktop. It has not been changed.");
            }
            // Keep legacy CMD targets and all user launch customizations.
            shortcut.IconLocation = icon + ",0";
            shortcut.Save();
            WScript.Echo("Desktop shortcut icon updated; launch settings preserved: " + destination);
        } else {
            shortcut.TargetPath = target;
            shortcut.WorkingDirectory = root;
            shortcut.Description = "Start Agent Workbench on this computer";
            shortcut.IconLocation = icon + ",0";
            shortcut.WindowStyle = 1;
            shortcut.Save();
            WScript.Echo("Desktop shortcut created: " + destination);
        }
        WScript.Quit(0);
    } catch (error) {
        WScript.Echo("Shortcut creation failed: " + (error.message || error.description || "Windows could not create the shortcut."));
        WScript.Quit(1);
    }
}());
