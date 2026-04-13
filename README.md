# Xyra

Xyra is a desktop-style Linux/VPS dashboard built with Python and PyQt6.

It connects to your server over SSH/SFTP and gives you a more visual way to browse folders, manage files, edit text content and open remote assets locally without relying on clunky old workflows.

This release is the current **beta-v1.2** build.

## Features

- SSH / SFTP based workflow
- Desktop-style remote file browser
- Text file editing
- Drag & drop upload
- Local opening for external files like images
- Saved icon positions and UI state
- Secure local secret storage for SSH passwords
  - Windows Credential Manager / Keyring first
  - DPAPI fallback

## Why This Exists

Xyra is meant to feel more modern, visual and comfortable than a plain server file list.

It is especially useful if you spend a lot of time on Linux servers, webroots, dumps, configs or project folders and want something that feels a bit more like a desktop environment.

## Current State

This build is already very usable, but it is still a beta.

That means:

- the core SSH file workflow is working
- the UI is already polished enough for daily use
- there is still room for more cleanup and extra features

## Stack

- Python
- PyQt6
- Paramiko
- QtAwesome
- Keyring

## Run

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Start the app:

```bash
python Dashboard.py
```

## Main Files

- `Dashboard.py` - main window and startup
- `editor.py` - text editor window
- `ssh_backend.py` - SSH/SFTP backend
- `ui_components.py` - dialogs and UI helpers
- `storage_utils.py` - config and icon position storage
- `secret_storage.py` - password protection helpers
- `path_utils.py` - path and formatting helpers
- `app_constants.py` - app metadata and constants

## Notes

- Passwords are no longer stored as plain text in `config.json`
- The app currently focuses on SSH/SFTP file management
- More terminal-oriented features can be added later

## Author

Developed by **Rico (Brejax)**
