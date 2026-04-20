# Security Policy

Xyra handles SSH/SFTP connections and local server profile data, so security reports are taken seriously.

## Supported Versions

| Version | Supported |
| ------- | --------- |
| beta-v1.4 | Yes |
| older beta builds | No |

## Reporting a Vulnerability

If you find a security issue, please do not open a public GitHub issue with sensitive details.

Instead, contact the maintainer privately:

- GitHub: @mambuzrrr

Please include:

- a short description of the issue
- affected version
- steps to reproduce if possible
- why it may be security relevant

## Scope

Security-relevant examples include:

- leaking SSH credentials
- unsafe local secret storage
- path traversal or access outside the configured SSH root
- unsafe remote file operations
- command execution issues
- packaging or release files exposing private data

## Notes

Xyra is currently beta software. Please avoid using it with highly sensitive production systems unless you understand the risks.
