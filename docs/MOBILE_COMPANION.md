# uneXpected Phone companion

This is an additive, same-origin installable PWA served at `/mobile/` by the existing uneXpected AI Studio gateway.

## Included

- Mobile chat that uses the existing authenticated `POST /orchestrate` endpoint.
- One-turn dictation and a voice-chat loop using browser speech recognition and speech synthesis, with English, French and Arabic language choices.
- Local projects, tasks, notes, chat history and an improvement proposal queue.
- Export/import workspace backup; the gateway bearer token is not exported.
- 40 v7.1 workflow profile references plus the two v7.1 workflow skill references. These are guidance/catalog references, not separate running agents.
- Optional per-request context sharing. It is off by default. Approved improvement ideas are sent only as planning context.
- Offline shell caching only. `/health`, `/orchestrate` and `/test-provider` are never cached.

## Install on Android

1. Open `https://unexpected-ai-studio.onrender.com/mobile/` in Chrome after deployment.
2. Use the browser menu and choose **Install app** or **Add to Home screen**.
3. Open Settings in the app and paste the existing `UNEXPECTED_ACCESS_TOKEN` value from your private Render environment. It is stored only in the current tab session; do not share it in chat.
4. Choose a workflow profile and AI route. OpenAI is the default route; selecting both may use additional provider credits.

Microphone and speech output depend on the browser and device language packs. Voice recognition may use the browser vendor's service and is not guaranteed to work offline. Offline mode supports local commands and stored workspace data, not general LLM inference.

## Security and boundary

The gateway retains its existing bearer authentication, rate limiting, request size limits and provider routing. The PWA calls the gateway same-origin; no permissive CORS policy or unauthenticated AI endpoint is added. No API provider call is made by the installation itself. A configured provider is not described as verified until a real, successful request is recorded.

Improvement proposals are stored locally. Approval in the app authorizes only planning context; it does not authorize code writes, protected instruction changes, commits, merges or deployments.
