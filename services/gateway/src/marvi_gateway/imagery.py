"""Making a picture, when somebody asks for one.

The model call is the easy half. The half that kept this unbuilt was that a
generated image had nowhere to go: Chat renders images from attachment rows,
and a tool handler does not know which conversation it is running in. That is
solved in `chat._keep_produced` -- a tool hands back
`{"produced": {name, media_type, data}}` and the dispatcher, which does know
the thread, turns it into an attachment. This module is the first user of that
contract, and a chart or an export will be the next.

**The OpenAI images shape, and nothing else.** `POST {base}/images/generations`
is what OpenAI, OpenRouter's image models and most compatible gateways answer;
an Anthropic-style provider has no image endpoint at all and is told so by
name rather than left to fail somewhere deeper. Local generation is not here:
a diffusion model beside the resident voice models does not fit in 12 GB, and
pretending otherwise would be a feature that swaps for ten minutes and dies.

Privacy mode and local-only both refuse this, because it is a cloud call.
"""

from __future__ import annotations

import base64
from typing import Any

from .logs import get_logger

log = get_logger("gateway")

#: What the tool asks for when nobody says. Square, because most requests are
#: "draw me X" rather than a layout.
DEFAULT_SIZE = "1024x1024"

SIZES = ("256x256", "512x512", "1024x1024", "1024x1536", "1536x1024", "auto")

#: How long to wait. Image models are slow and a voice turn is not waiting on
#: this -- the tool returns, the picture lands in the conversation.
TIMEOUT = 120.0


class ImageUnavailableError(Exception):
    """No configured provider can generate an image."""


def _provider(client: Any) -> Any:
    """The first configured provider that answers the images endpoint."""
    from .providers.client import local_only

    if local_only():
        raise ImageUnavailableError(
            "image generation is a cloud call, and local-only mode is on"
        )
    for profile in client.candidates():
        # `chat_completions` is the OpenAI-shaped family; `responses` is
        # OpenAI's own newer API, which serves the same images endpoint.
        if profile.api_mode in ("chat_completions", "responses") and profile.api_key():
            return profile
    raise ImageUnavailableError(
        "no connected provider offers image generation. Connect OpenAI or "
        "OpenRouter in Settings > Providers."
    )


def generate(client: Any, prompt: str, size: str = DEFAULT_SIZE, model: str = "") -> dict[str, Any]:
    """One picture, as PNG bytes and the model that drew it."""
    profile = _provider(client)
    wanted = size if size in SIZES else DEFAULT_SIZE
    chosen = model or profile.image_model()
    body = {"model": chosen, "prompt": prompt, "size": wanted, "n": 1}
    http = client._client()
    response = http.post(
        f"{profile.base_url()}/images/generations",
        json=body,
        headers=profile.headers(client.key_index(profile.name)),
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise ImageUnavailableError(
            f"{profile.name} refused the image ({response.status_code}): "
            f"{response.text[:200]}"
        )
    payload = response.json()
    rows = payload.get("data") or []
    if not rows or not isinstance(rows[0], dict):
        raise ImageUnavailableError(f"{profile.name} returned no image")
    encoded = rows[0].get("b64_json")
    if not encoded:
        # Some gateways answer with a URL instead of bytes. Fetching it is a
        # second request to a host the provider chose, so it is done through
        # the same client and nothing else is followed.
        url = str(rows[0].get("url") or "")
        if not url:
            raise ImageUnavailableError(f"{profile.name} returned neither image data nor a URL")
        fetched = http.get(url, timeout=TIMEOUT)
        if fetched.status_code != 200:
            raise ImageUnavailableError(f"the image could not be fetched ({fetched.status_code})")
        data = fetched.content
    else:
        data = base64.b64decode(encoded)
    log.info(
        "generated an image",
        extra={"marvi_provider": profile.name, "marvi_model": chosen, "marvi_bytes": str(len(data))},
    )
    return {"data": data, "provider": profile.name, "model": chosen, "size": wanted}


def register_image_tools(registry: Any, client: Any) -> None:
    from .tools import ToolSpec

    def image_generate(prompt: str, size: str = DEFAULT_SIZE) -> dict[str, Any]:
        asked = " ".join((prompt or "").split())
        if not asked:
            return {"error": "say what the picture should be of"}
        try:
            made = generate(client, asked, size)
        except ImageUnavailableError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # a provider that failed is not a broken tool
            return {"error": f"the image could not be generated: {str(exc)[:200]}"}
        stem = "-".join(asked.lower().split()[:5]) or "image"
        return {
            "made": True,
            "provider": made["provider"],
            "model": made["model"],
            "size": made["size"],
            # The contract: the dispatcher puts this in the conversation.
            "produced": {
                "name": f"{stem[:60]}.png",
                "media_type": "image/png",
                "data": base64.b64encode(made["data"]).decode("ascii"),
            },
        }

    registry.register(
        ToolSpec(
            name="image_generate",
            description="Draw a picture from a description.",
            arguments={"prompt": str},
            optional={"size": str},
            # It costs money and reaches a provider, but it creates nothing
            # outside this machine and cannot be un-drawn; confirmation on
            # every doodle is friction without a decision behind it.
            sensitive=False,
            handler=image_generate,
            describes={
                "prompt": "What the picture should show, in a sentence or two. Describe the "
                "subject, the setting and the style; the model sees nothing else.",
                "size": f"One of {', '.join(SIZES)}. Default {DEFAULT_SIZE}.",
            },
        )
    )
