# Security

The full policy is in [`jev-router-copilot/SECURITY.md`](jev-router-copilot/SECURITY.md): what the router sends to
TypeSafe and when it does not, how the API key is read (environment variable, macOS Keychain or Windows Credential
Manager, never stored by the installer), that hooks run as you, and what the installer writes.

In short: with the router ON, the text of each prompt (first 6000 characters) goes to `https://api.typesafe.ai`
with your `TYPESAFE_API_KEY`. Slash and `!` commands, short follow-ups and secret-looking text stay local. Nothing
else leaves the machine.

## Reporting a vulnerability

Open a GitHub issue for anything that is not sensitive. For a report that should stay private, use GitHub's
"Report a vulnerability" form on this repository if it is enabled, or contact the maintainer through their GitHub
profile. Please do not include your API key or Copilot session files.
