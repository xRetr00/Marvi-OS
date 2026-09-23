"""Local providers: the user's own hardware.

Ollama, LM Studio, llama.cpp and vLLM all serve an OpenAI-compatible chat
completions API, so they are one profile shape with different default ports
rather than four plugins.

These matter more than their size suggests for a local-first product. They are
the only providers that keep working with the network down, the only ones with
no privacy question at all, and the only ones that cost nothing — which makes
them the right default for auxiliary work like classification and extraction.

None of them do prompt caching in the provider sense: the server keeps its own
KV cache across requests with the same prefix, but there is nothing to ask for
in the request, so `CachePolicy` stays `none`. That is not a gap; a local token
is free either way.
"""

from __future__ import annotations

from .base import CachePolicy, LimitPolicy, ProviderProfile, ReasoningPolicy, register

_NO_LIMITS = LimitPolicy(style="none", note="Local hardware; nothing metered.")

ollama = register(
    ProviderProfile(
        name="ollama",
        aliases=("local", "ollama-local"),
        display_name="Ollama",
        description="Local models served by Ollama.",
        signup_url="https://ollama.com/download",
        access_path="local",
        auth_type="none",
        api_mode="chat_completions",
        base_url_env="MARVI_OLLAMA_URL",
        default_base_url="http://localhost:11434/v1",
        default_model_env="MARVI_OLLAMA_MODEL",
        default_model="qwen3:8b",
        default_aux_model="qwen3:4b",
        cache=CachePolicy(style="none"),
        reasoning=ReasoningPolicy(style="effort", levels=("off", "on", "low", "medium", "high")),
        limits=_NO_LIMITS,
        supports_vision=False,
        default_max_tokens=2048,
    )
)

lm_studio = register(
    ProviderProfile(
        name="lmstudio",
        aliases=("lm-studio", "lm_studio"),
        display_name="LM Studio",
        description="Local models served by LM Studio.",
        signup_url="https://lmstudio.ai/",
        access_path="local",
        auth_type="none",
        api_mode="chat_completions",
        base_url_env="MARVI_LMSTUDIO_URL",
        default_base_url="http://localhost:1234/v1",
        default_model_env="MARVI_LMSTUDIO_MODEL",
        default_model="",
        cache=CachePolicy(style="none"),
        reasoning=ReasoningPolicy(style="effort", levels=("off", "on", "low", "medium", "high")),
        limits=_NO_LIMITS,
        default_max_tokens=2048,
    )
)

llama_cpp = register(
    ProviderProfile(
        name="llamacpp",
        aliases=("llama.cpp", "llama-cpp", "local-openai"),
        display_name="llama.cpp",
        description="Local GGUF models served by llama-server.",
        signup_url="https://github.com/ggml-org/llama.cpp",
        access_path="local",
        auth_type="none",
        api_mode="chat_completions",
        base_url_env="MARVI_LOCAL_OPENAI_URL",
        default_base_url="http://127.0.0.1:8080/v1",
        default_model_env="MARVI_LOCAL_OPENAI_MODEL",
        default_model="",
        cache=CachePolicy(style="none"),
        reasoning=ReasoningPolicy(
            style="effort",
            levels=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
        ),
        supports_tools=True,
        limits=_NO_LIMITS,
        default_max_tokens=2048,
    )
)

vllm = register(
    ProviderProfile(
        name="vllm",
        aliases=("v-llm",),
        display_name="vLLM",
        description="Local models served by vLLM.",
        signup_url="https://github.com/vllm-project/vllm",
        access_path="local",
        auth_type="none",
        api_mode="chat_completions",
        base_url_env="MARVI_VLLM_URL",
        default_base_url="http://127.0.0.1:8000/v1",
        default_model_env="MARVI_VLLM_MODEL",
        default_model="",
        cache=CachePolicy(style="none"),
        reasoning=ReasoningPolicy(style="effort", levels=("none", "low", "medium", "high")),
        limits=_NO_LIMITS,
        default_max_tokens=2048,
    )
)
