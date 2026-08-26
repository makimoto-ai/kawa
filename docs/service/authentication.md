# Authentication

This guide documents how to authenticate with the Makimoto transcription API. 
For a full worked example (create an account, submit a recording, poll, read the transcript), see [Walkthrough](walkthrough.md).

## Authentication Model

Developers authenticate API requests with a token generated from the Makimoto dashboard.

```http
Authorization: Bearer <makimoto_api_token>
```

Set these environment variables for the examples:

```bash
export MAKIMOTO_API_URL="https://api.makimoto.ai"
export MAKIMOTO_API_TOKEN="<token-from-dashboard>"
```

Generate the token from the dashboard. Currently, public API integrations should not call the underlying identity service directly; the dashboard handles sign-in and token generation for you.

## Token Lifetime and Refresh

The dashboard token is short-lived. While you are signed in, the dashboard keeps your token current, so for interactive and test usage you can copy the latest token whenever you need one.

A token you have copied elsewhere (an environment variable, a script, a Postman variable) is a snapshot: it does not renew itself and stops working once it expires. When that happens, copy a fresh token from the dashboard. Treat any `401` response from the API as "token missing, expired, or revoked" and regenerate.

## Beta and Production Access

During the beta, access is token-based: retrieve a token from the dashboard at [makimoto.ai](https://makimoto.ai) and send it as a bearer token, as shown above.

This suits development, testing, and the playground.

For production use, contact us at [contact@makimoto.ai](mailto:contact@makimoto.ai) for persistent credentials (such as an API key or other service authentication) and higher volume limits.

## References

- [OpenAI API authentication](https://platform.openai.com/docs/api-reference/authentication)
- [Anthropic API authentication](https://docs.anthropic.com/en/api/getting-started)
- [Deepgram API authentication](https://developers.deepgram.com/docs/authenticating)
