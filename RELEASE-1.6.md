# Xyra Core 1.6

Xyra Core 1.6 is focused on cleanup, navigation comfort and getting the project closer to a normal release instead of another beta-only drop.

This release note intentionally only covers the newest changes since the previous GitHub release text, so older features are not listed twice.

## Highlights

- Cleaner project structure
  - internal Python modules are now grouped under the `xyra/` package
  - `Dashboard.py` stays in the repository root as the simple app entry point
  - resource and local data paths still resolve from the project root, so existing saved profiles and state keep working

- Security documentation
  - added `SECURITY.md` for responsible reporting guidance
  - documents security-relevant areas like SSH credentials, local secret storage, path traversal and remote file actions

- Favorite folders
  - remote folders can be pinned as favorites
  - favorite folders are available from the `Quick Paths` menu
  - current folders and folder items can be added or removed from the context menus

- Faster path navigation
  - the taskbar path area opens a breadcrumb menu
  - parent folders can be opened directly from the path menu
  - the same menu also supports copying the current path, setting the launch folder and toggling favorites

- Desktop taskbar
  - added a first Xyra taskbar at the bottom of the dashboard
  - includes a start-style Xyra menu, current path, quick search, server health, fullscreen toggle and clock
  - desktop icons now keep extra bottom spacing so they do not sit behind the taskbar

- Desktop-style selection
  - single-click now selects desktop icons
  - selected icons get a clearer modern highlight state
  - supports `Ctrl+A`, `Esc`, `Enter`, `F2`, `Delete` and `Shift+Delete` for common desktop keyboard flow

- Server health snapshot
  - added a read-only `Server Health` view in the `Remote` menu
  - shows host, user, disk usage, load, memory, uptime and system information
  - includes a copyable raw report for quick troubleshooting

- Remote file search
  - search the server from the current folder by filename
  - choose a max folder depth before searching
  - a searching overlay is shown while the remote scan runs in the background
  - long searches can be cancelled directly from the overlay
  - path switching is blocked while a server search is running, so results stay tied to the folder that started the search
  - result hover and selection styling has been cleaned up
  - results can be opened by jumping to their parent folder or copied as paths

- Safer deletes
  - normal delete actions now move files and folders into `.xyra-trash`
  - permanent delete is still available as a separate explicit context-menu action
  - items already inside `.xyra-trash` must be deleted permanently

- Fullscreen workflow
  - `F11` toggles true fullscreen mode
  - `Esc` exits fullscreen before falling back to normal navigation behavior
  - returning from fullscreen preserves the previous maximized/normal window state

- Code editor polish
  - text editing now uses a darker programming-focused interface
  - added line numbers and current-line highlighting
  - the header now shows file name, remote path and saved/unsaved state
  - the status bar shows language, cursor position, character count and the save shortcut
  - the first server save per edited file creates a remote backup in `.xyra-backups`

- Display and icon customization
  - default icons now live under `assets/icons`
  - archive files such as `.zip`, `.pk3`, `.iwd`, `.rar` and `.7z` use a dedicated archive icon
  - custom icon packs can be selected from the `Display` menu
  - icon packs can override folder, file, image and archive icons while Xyra keeps desktop icons scaled consistently

- Windows release polish
  - added a PyInstaller manifest for a more native Windows build
  - added Windows version metadata for the generated `Xyra.exe`
  - the release executable now uses the new Xyra icon

- SSH profile reliability
  - saved quick-server profiles now require both host and username
  - incomplete legacy profiles are ignored instead of appearing as broken quick servers
  - connecting with a named profile keeps that profile available in `Quick servers`

## Notes

- This release is no longer marked as a beta release.
- Existing local profile and state data should continue to load from the project root.

## Recommended Release Title

`Xyra Core 1.6`

## Short Release Summary

Xyra Core 1.6 cleans up the project structure and adds a first desktop taskbar, favorite folders, breadcrumb path navigation, remote search, server health checks, safer file handling and a more polished Windows release build.
