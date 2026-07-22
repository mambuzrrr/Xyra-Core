# Xyra Core 1.7.3

Xyra Core 1.7.3 focuses on desktop polish, independent server workspaces, smoother remote
navigation, stronger file insight and safer update and recovery tools.

This release note only covers the newest changes since Xyra Core 1.6.

## Highlights

- Refined visual system
  - replaces the former block-heavy shell with a quiet graphite workspace, warm off-whites and restrained champagne accents
  - adds a compact branded toolbar, clearer connection status and a lighter floating command dock
  - uses mauve for display tools and sage only for semantic remote/success states instead of repeating one accent everywhere
  - introduces a subtle warm desktop glow, dot grid and smoother icon hover feedback
  - redesigns the offline state, transfer overlays and adaptive toast motion for clearer feedback
  - collapses toolbar labels and search width automatically on smaller windows instead of clipping commands
  - refreshes the SSH connection dialog with stronger hierarchy and an obvious primary action
  - keeps existing custom backgrounds and icon-pack choices intact

- More compact desktop layout
  - desktop icons now use tighter grid spacing
  - dragging an icon between slots now opens a live target gap while surrounding items glide into their future positions
  - the final order is committed exactly where the icon is released
  - long names are measured to a maximum of two lines and middle-elided while preserving useful prefixes and suffixes
  - hovering a truncated label immediately reveals its complete file or folder name
  - the first row starts lower so toast messages no longer cover the top-left icon
  - icon drag ordering feels cleaner and no longer forces folders back in front after manual movement
  - inline rename now appears directly on the icon label instead of as a large overlay
  - typing while the desktop is focused now jumps to matching files and folders
  - mouse side buttons now navigate backward and forward through folder history

- Smarter uploads
  - drag-and-drop uploads now run in the background instead of freezing the dashboard
  - uploads show a real progress bar with percent updates
  - Xyra now asks before overwriting existing remote files or folders with the same name

- Better downloads
  - manual downloads now run in the background instead of blocking the dashboard
  - downloads show a real progress bar with percent updates
  - Xyra now asks before overwriting an existing local file

- Transfer Center and conflict handling
  - uploads and downloads now pass through a bounded background transfer queue
  - the Transfer Center shows status, progress, speed, ETA and destination for each job
  - queued or active jobs can be cancelled and failed jobs can be retried without restarting Xyra
  - file and folder conflicts use one consistent Xyra dialog instead of scattered system prompts
  - destructive replacements require an explicit decision and incompatible item types are not replaced silently

- Independent server workspaces
  - additional connections now open inside the existing Xyra window instead of launching another application window
  - the server bar appears only when more than one workspace is open
  - each tab keeps its own path, navigation history, selection and icon layout while switching
  - multiple tabs for the same VPS remain independent and receive clear numbered names when needed
  - every server tab has a compact themed close action
  - closing the active tab switches safely to the remaining session, while Disconnect collapses secondary sessions
  - closing Xyra cancels active transfers and closes the SSH/SFTP transport instead of restoring an unintended live session on the next start

- Smoother remote navigation
  - folder listings now load on background workers so remote latency no longer blocks the window
  - stale results from an older folder or server are discarded instead of overwriting the current view
  - search, desktop relayout, background scaling and window-size persistence are debounced to reduce resize and navigation jitter
  - loading and failure states stay inside Xyra and preserve the current usable folder whenever possible
  - startup geometry is clamped to the active desktop and centered when saved dimensions are missing or unusable

- Built-in Numix icon packs
  - bundled Numix icon packs are now available directly from `Display -> Change icon pack`
  - built-in packs are stored by stable pack keys instead of fragile local paths
  - selected built-in icon packs now persist correctly after restarting Xyra
  - the icon pack picker is more compact and keeps custom folder support

- Search navigation fix
  - opening a folder while the local search filter is active now clears the filter automatically
  - this prevents searched folders from incorrectly opening as empty

- Stronger Properties dialog
  - redesigned Properties with `General` and `Checksums` tabs
  - shows owner, group, UID/GID, symbolic permissions and octal mode
  - permissions can now be edited through R/W/X checkboxes plus Set UID, Set GID and Sticky bits
  - octal mode and checkbox state stay synchronized
  - permission presets and risk guidance make common modes easier to choose safely
  - recursive changes use separate file and folder modes, skip symbolic links and stop at a defensive item limit
  - Xyra verifies the resulting remote mode and reports partial failures instead of pretending the whole operation succeeded
  - checkbox styling is cleaner and uses a dedicated checkmark asset

- Smarter Linux links
  - symbolic links such as `/lib`, `/lib64` and `/sbin` are resolved to their actual file or directory type
  - every double-click revalidates the current remote type before deciding how to open it
  - broken, inaccessible or out-of-root links stay in the current folder and report a friendly error directly in Xyra
  - background preview and external-open failures now use Xyra notifications instead of console-only messages

- Xyra Editor workspace
  - replaces the former editor card with a compact Notepad++-inspired menu, toolbar, document tab and segmented status bar
  - adds syntax highlighting for common server, web, config and programming formats
  - includes inline Find/Replace, next/previous search, Replace All and Go to Line
  - adds Undo/Redo, line duplication/deletion, case conversion, word wrap and zoom controls
  - shows cursor position, selection length, document statistics, EOL mode, UTF-8, language, insert mode and zoom
  - preserves the source document's LF or CRLF line endings when saving back to the server
  - opens additional remote text files as real tabs in the existing editor window
  - focuses an already-open path instead of duplicating or replacing its in-memory buffer
  - focuses existing tabs before any server download, so unsaved buffers remain reachable during connection trouble
  - keeps path, language, line endings, syntax state, zoom and unsaved state independently per tab
  - protects every dirty tab with Save, Discard and Cancel when a tab or the editor window is closed

- File checksums
  - file Properties now calculate `MD5`, `SHA1` and `SHA256`
  - checksum calculation runs in the background so the dialog stays responsive
  - checksum output is copy-friendly for comparing uploads, archives and server files

- Animated backgrounds
  - `.gif` backgrounds now animate instead of rendering as a static first frame
  - normal image backgrounds continue to work as before

- Trash Manager
  - added a Trash Manager from the Xyra start menu and `Remote` menu
  - new trash entries store metadata for reliable restore to the original path
  - trash items can be restored, permanently deleted or cleared all at once
  - older trash entries without metadata are still listed best-effort

- Sensitive File Guard
  - warns before opening, downloading or deleting likely sensitive files and folders
  - covers common secrets such as `.env`, SSH keys, certificates, token configs and credential files
  - helps avoid accidental exposure or removal of server credentials

- Discord Rich Presence
  - Xyra can now show Discord activity while the dashboard is open
  - uses the configured Xyra Discord app ID and bundled image keys
  - presence updates when connecting and disconnecting
  - keeps remote host, user and workspace details private
  - adds a "Get Xyra on GitHub" activity button
  - Discord integration is optional, so Xyra still starts normally without Discord running

- Authenticated application updates
  - adds manual and optional startup update checks with separate Stable and Preview channels
  - update metadata must arrive over HTTPS and carry a valid Ed25519 signature from the key pinned in Xyra
  - the signed payload fixes the release channel, version, release-notes URL, installer URL, byte count and SHA-256
  - downloads run in the background with progress and are staged outside the application directory
  - Xyra rejects redirects away from HTTPS, oversized downloads, incomplete files and checksum mismatches
  - only a fully downloaded and verified Windows installer can be launched

- Reproducible Windows release tooling
  - adds a pinned x64 PyInstaller build, Inno Setup installer and a single release build command
  - application metadata, executable resources and installer versions are validated against each other
  - generated release manifests record exact size, SHA-256 and Authenticode state
  - optional Authenticode signing requires an explicit certificate and RFC 3161 timestamp, then verifies every produced signature
  - update-manifest signing reads the private Ed25519 key from Windows Credential Manager instead of the repository
  - build products, local tests and release artifacts remain outside the public source commit

- Security hardening
  - unknown SSH host keys now require explicit SHA-256 fingerprint verification
  - accepted host keys are persisted and changed keys are rejected
  - remote root boundaries now reject parent traversal and symbolic-link escapes
  - potentially executable remote files are no longer launched directly
  - archive paths are validated before extraction and oversized listings are blocked
  - built-in editor reads and remote command output now have defensive size limits
  - connections and transfers are shut down explicitly during application exit
  - authenticated update metadata and exact installer hashes prevent an update server or mirror from silently substituting a different executable
  - runtime dependencies are pinned and Paramiko is updated to 5.0.0

## Notes

- New trash restore behavior is most reliable for items deleted with Xyra Core 1.7.3 or newer.
- The release remains focused on Windows 64-bit builds.

## Recommended Release Title

`Xyra Core 1.7.3`

## Short Release Summary

Xyra Core 1.7.3 introduces a refined desktop shell, independent in-window VPS workspaces,
responsive background navigation, a managed Transfer Center, the Notepad++-inspired editor,
richer Properties and permissions, recovery and sensitive-file guards, and an authenticated
update and Windows release pipeline.
