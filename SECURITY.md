# Security

Do not post API keys, developer account details, config-entry storage, or full
Home Assistant diagnostics in public issues. The diagnostics download redacts
the API token. Player tags stay visible because they are public API identifiers.
Revoke an exposed key in the [Clash Royale developer portal](https://developer.clashroyale.com)
and replace it in Home Assistant.

Report vulnerabilities privately through GitHub's **Security → Report a
vulnerability** feature when available, or contact the repository owner privately.
Do not use public issues for secret-bearing reports.

Only the latest release is maintained. The integration makes read-only requests
to Supercell's official API; no gameplay commands or account login are supported.
