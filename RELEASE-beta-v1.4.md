# Xyra Core beta-v1.4

This build continues the push toward a more polished, safer and actually usable Xyra experience.

The focus of this version was on quality-of-life improvements, safer remote handling and getting the project ready for cleaner GitHub releases.

## Highlights

- Improved remote-first workflow
  - cleaner wording around server access
  - better separation between remote file access and future terminal features

- SSH profile system
  - save reusable server profiles
  - quick profile switching directly from the Remote menu
  - faster reconnects without typing everything again

- Secure credential handling
  - passwords are no longer stored as plain text
  - Windows Credential Manager / Keyring is preferred
  - DPAPI fallback remains available when needed
  - old profile secret entries are cleaned up when profile storage is rewritten
  - PuTTY is no longer launched with the SSH password in process arguments

- Safer local state storage
  - icon positions now use SQLite instead of a loose JSON file
  - remote/profile metadata is being moved out of plain config storage
  - GUI-only preferences are now separated more cleanly from sensitive app state
  - local runtime files, build outputs and web assets are ignored for GitHub publishing

- Quick Paths
  - new toolbar menu for fast navigation between recent remote folders
  - current folder can be saved as the launch/start folder
  - recent folder history is stored locally and kept out of Git

- Copy Path workflow
  - copy the current remote folder path from the empty-space context menu
  - copy file and folder paths directly from item context menus
  - copied paths use clean remote-style formatting like `/var/www/html`

- In-app image preview
  - image files can now open directly inside Xyra
  - fit-to-window behavior on open
  - zoom support with mouse wheel
  - optional external open still available

- Direct dashboard file actions
  - copy files and folders to another remote path
  - move files and folders directly from the item context menu
  - less need to jump out into shell tools for simple file management
  - copy and move now run in a background worker so the UI stays smoother during remote operations
  - configured SSH root is protected from accidental delete and move actions

- Archive workflow inside the dashboard
  - extract common archives directly from the item context menu
  - extract archives into a custom target path
  - create ZIP archives for files and folders without leaving Xyra
  - first extraction support includes .zip, .pk3, .iwd, .rar, .7z and common tar formats

- Properties and permissions
  - new Properties dialog for files and folders
  - shows path, type, size, modified date and permission info
  - chmod can now be applied directly inside Xyra with octal modes like 755 or 644

- Better large-folder handling
  - large directories no longer crush icons into tiny unreadable thumbnails
  - proper scrolling keeps the view usable

- UI and polish improvements
  - cleaner toolbar spacing
  - better button styling
  - improved server wording and status labels
  - more consistent visual language across the app

- Windows packaging prep
  - app resources and user data are now separated more cleanly for packaged builds
  - a repeatable PyInstaller setup is included for generating a Windows EXE build
  - Git attributes define consistent line endings and binary asset handling

## Notes

- This is still a beta build
- core remote browsing/editing workflow is already very usable
- more polish, previews and quality-of-life features are still planned

## Recommended Release Title

`Xyra Core beta-v1.4`

## Short Release Summary

Xyra Core beta-v1.4 improves daily remote work with Quick Paths, Copy Path actions, safer SSH handling, cleaner local state storage and GitHub-ready project hygiene.

---

Developed by Brejax
