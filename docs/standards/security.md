# Security standards

## Untrusted input
Treat all user input and stored data as untrusted. Render text with `textContent` or framework escaping, never by building HTML strings. Validate lengths and types before saving.

## Secrets
Never hard-code API keys, tokens or passwords. Never read or write `.env` files. Configuration that needs secrets must read them from the environment at runtime.

## Authentication changes
Changes to login, sessions or OAuth are high-risk: keep the existing flow working, never log credentials or tokens, and use the provider's official endpoints and state/PKCE parameters.

## Dependencies and commands
Do not add dependencies or scripts that download and execute code. Do not add `postinstall` scripts.
