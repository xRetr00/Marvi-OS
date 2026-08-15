# Upstream provenance

Structure and dependency selection derive from LiveKit's official Python agent
starter at commit `ddc18eb8519cbfdb17d56c679f363a6507f600ec`.

Cloud inference, ai-coustics, hosted STT/TTS, console UX, and Docker deployment
were intentionally removed because Marvi OS is native-Windows, local-media, and
has no user-facing CLI. The OpenCode Go adapter follows LiveKit's documented
custom OpenAI-compatible endpoint pattern.
