# Security Policy

Xyra handles SSH/SFTP connections and local server profile data, so security reports are taken seriously.

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 1.7.x | Yes |
| 1.6 | Security fixes only |
| older beta builds | No |

## Update Trust

Xyra update manifests are fetched only over HTTPS and must carry a valid Ed25519 signature for
the public key pinned in the application. The signature covers the release channel, version,
release-notes URL, installer URL, exact byte count and SHA-256. Downloads are staged separately and
are never executed until their signed size and hash match. The private manifest-signing key is kept
outside the repository in the release owner's Windows Credential Manager.

Authenticode signing is a separate Windows publisher-identity layer. Official public releases must
not claim to be Authenticode-signed unless the release manifest reports a valid trusted signature.

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

Xyra verifies SSH host keys before trusting a new server and stores accepted
keys in its private application-data directory. A changed key is rejected. If a
server is rebuilt legitimately, remove its old entry from Xyra's `known_hosts`
file only after verifying the replacement fingerprint with the provider.
