# Security

Report vulnerabilities privately to the repository owner instead of filing a
public issue.

WorldState binds local development services to `127.0.0.1`. Local desktop
requests may write without a token; non-local write access requires
`WORLDSTATE_WRITE_TOKEN`. Do not expose the Research API to a network without
authentication and TLS.

API credentials belong in `.runtime/worldstate.env`, the operating-system
keyring or deployment secrets. Never commit cookies, provider tokens,
proprietary consensus files or local databases.
