# Authentication

*Last updated: 2026-09-16*

This guide documents how to authenticate with the Makimoto transcription API. 
For a full worked example (create an account, submit a recording, poll, read the transcript), see [Walkthrough](walkthrough.md).

## Authentication Model

Developers authenticate API requests with an API key created from the Makimoto dashboard.

```http
Authorization: Bearer <makimoto_api_key>
```

Set these environment variables for the examples:

```bash
export MAKIMOTO_API_URL="https://api.makimoto.ai"
export MAKIMOTO_API_KEY="<api-key-from-dashboard>"
```

Create the key from the developer/API section of the dashboard. Public API integrations should not call the underlying identity service directly; the dashboard handles sign-in and key management for you.

## Key Lifetime and Rotation

Unlike the short-lived session tokens used earlier in the beta, an API key doesn't expire on its own unless you set an expiry when creating it, and doesn't depend on staying signed in to the dashboard. It keeps working until you revoke it.

The raw key is shown once, at creation; afterwards the dashboard only shows a masked preview (`mkm_sk_...a1b2`). Store it somewhere you control, such as a secrets manager or an untracked `.env` file, as soon as it's created: a lost key can't be recovered, only revoked and replaced.

You can hold up to three active keys at a time, so you can bring a new one into use before revoking the old one rather than having a gap in access. Revoke a key from the dashboard as soon as it's no longer needed, for instance after it leaks or the service that used it is decommissioned.

Treat any `401` response from the API as "key missing, invalid, expired, or revoked" and issue a fresh one from the dashboard.

## Beta and Production Access

Access is API-key based for both beta and production use: create a key from the dashboard at [makimoto.ai](https://makimoto.ai) and send it the same way, as shown above.

For higher volume or a production support agreement, contact us at [contact@makimoto.ai](mailto:contact@makimoto.ai).

## References

- [OpenAI API authentication](https://platform.openai.com/docs/api-reference/authentication)
- [Anthropic API authentication](https://docs.anthropic.com/en/api/getting-started)
- [Deepgram API authentication](https://developers.deepgram.com/docs/authenticating)
