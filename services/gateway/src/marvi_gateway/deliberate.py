"""LLM deliberation for the mind.

**The second element of the returned tuple is the sentence Marvi may say, or
empty. It is never a reason.**

That distinction is load-bearing and it was got wrong. The three paths that
give up -- the provider failed, the provider is cooling down, the model wrote
something `_parse` could not read -- used to return `verdict.detail`, which is
the *feed label* for the policy ceiling: "worth saying out loud". `mind.tick`
reads the same field as the phrasing when it is non-empty, so on those paths
Marvi said the label:

    02:07:25  model_resting  speak  llm 38ms   -> "worth saying out loud"

38ms is the tell: no model answered. In the logs that is event 15928, where
deliberation failed in 0.68ms with "No provider is available; all are
unconfigured or cooling down", and TTS then generated 1.68s of audio. 16 of 65
deliberations across the retained logs took one of those three paths, so a
quarter of everything Marvi deliberated about could speak its own ceiling
label out loud.

Empty means "no opinion", which `mind.tick` already handles: the feed falls
back to `verdict.detail` and the spoken line falls back to the template in
`voicing`.

The policy decides how loud an event is *allowed* to be. This decides whether
it is worth saying at all, and what the one sentence should be. Those are
different questions, and keeping them apart is what stops a model from talking
itself into interrupting someone.

Three constraints, enforced here rather than trusted to the prompt:

* the model may only make a decision quieter. `mind.tick` discards any louder
  suggestion, and this module never returns a surface above the one it was
  given;
* every call has a hard token and time budget, and reports its cost so the
  daily budget in `REAL-AGENCY.md` actually binds;
* event content arrives inside its untrusted envelope. The model is told to
  treat it as information, and the prompt says so before the content appears.

No provider is named here. The call goes through `ProviderClient`, which
resolves whatever is configured, falls over to the next one, and reports tokens
in a single shape — so the budget binds the same whether the mind is thinking on
a local model or a subscription plan.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from . import auxiliary
from .cognition import MIND_TOOLS, CognitionHarness
from .identity import IdentityFiles
from .policy import must_be_said
from .providers import ProviderCallError, ProviderClient, configured_profiles
from .tools import ToolRegistry
from .untrusted import wrap_external

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 120

#: The stance used when the persona files are missing or say nothing.
#:
#: Deliberately the forward one. An install with no persona files should
#: behave like the shipped default, and the shipped default acts first.
FALLBACK_STANCE = (
    "Judge whether this is worth their attention now, and often it is. If you "
    "would mention it to someone sitting beside them, say it."
)

def system_prompt(root: Path | None = None) -> str:
    """The job, plus the chosen persona's stance on speaking up.

    Read per call rather than captured at import: the persona is a setting the
    user changes from the picker, and a module constant would hold whichever
    one happened to be chosen when the Gateway started.

    The job itself is `prompts/mind-deliberation.md`. It was a constant in this
    module, which is how "Silence is the normal, correct answer" stayed in
    force for months while the persona files said the opposite -- nobody
    looking at personas had any reason to open `deliberate.py`.
    """
    from . import personas, prompts

    return prompts.text(
        "mind-deliberation", STANCE=personas.for_mind(root) or FALLBACK_STANCE
    )


class Deliberator:
    """Turns an event plus a policy verdict into a quieter, phrased decision."""

    def __init__(
        self,
        client: ProviderClient | None = None,
        preferred: str | None = None,
        identity: IdentityFiles | None = None,
        tools: ToolRegistry | None = None,
        harness: CognitionHarness | None = None,
    ) -> None:
        self.client = client or ProviderClient()
        # In character, unlike the other background jobs: this one writes
        # the sentence Marvi actually says, so how she sounds is the output.
        self.harness = harness or CognitionHarness(
            self.client, identity=identity, tools=tools, in_character=True
        )
        # Thinking in the background is exactly the work that should run on a
        # free local model when one is there.
        self.preferred = preferred or os.environ.get("MARVI_MIND_PROVIDER", "").strip() or None
        self.last_provider = ""
        self.last_model = ""

    def available(self) -> bool:
        return bool(self.client.candidates(self.preferred))

    def _prompt(self, event: dict[str, Any], verdict: Any) -> str:
        envelope = wrap_external(
            str(event.get("source", "unknown")),
            {"summary": event.get("summary"), "payload": event.get("payload")},
        ).text
        # The model was never told that some of these are not its call.
        #
        # A welcome, an arrival, a feed going silent -- `policy.MUST_BE_SAID`
        # -- get spoken whatever it answers, and it was being asked "is this
        # worth interrupting for?" with no hint of that. It answered the way
        # the prompt taught it to, `false`, and the override then spoke its
        # reason for declining:
        #
        #     00:19:01  FC 26 started  speak  "not worth interrupting"
        #
        # So the request says which gate is already open. It is a better
        # question, and the answer is a sentence rather than an argument.
        settled = (
            "ALREADY DECIDED: this will be said. Write the sentence.\n"
            if must_be_said(event)
            else ""
        )
        return (
            f"{settled}"
            f"The policy allows at most: {verdict.surface} (rule: {verdict.rule}).\n"
            f"Event kind: {event.get('source')}:{event.get('kind')}\n"
            f"Trusted: {event.get('trusted')}\n\n"
            f"{envelope}"
        )

    def __call__(self, event: dict[str, Any], verdict: Any) -> tuple[str, str, int]:
        """Return (surface, detail, billable tokens).

        Falls back to the deterministic verdict on any failure, so a dead
        provider makes the mind quieter rather than broken.
        """
        route = auxiliary.fallback_overrides("mind")
        if self.preferred and "preferred" not in route:
            route["preferred"] = self.preferred
        self.last_provider = ""
        self.last_model = ""
        started = time.perf_counter()
        logger.info(
            "mind deliberation started",
            extra={
                "marvi_event_id": event.get("id", ""),
                "marvi_source": str(event.get("source", "unknown")),
                "marvi_kind": str(event.get("kind", "unknown")),
                "marvi_route": "auxiliary/mind",
                "marvi_preferred": route.get("preferred", "auto"),
                "marvi_model": route.get("model", "provider-aux-default"),
                "marvi_surface_ceiling": verdict.surface,
            },
        )
        try:
            completion = self.harness.ask(
                role="mind",
                task=system_prompt(),
                user=self._prompt(event, verdict),
                max_tokens=MAX_OUTPUT_TOKENS,
                allowed_tools=MIND_TOOLS,
                preferred=route.get("preferred"),
            )
        except ProviderCallError as exc:
            logger.warning(
                "mind deliberation failed; using deterministic verdict",
                extra={
                    "marvi_event_id": event.get("id", ""),
                    "marvi_route": "auxiliary/mind",
                    "marvi_latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "marvi_error": str(exc)[:240],
                },
            )
            return verdict.surface, "", 0

        # Cached prefix tokens are excluded: the budget should see the saving.
        self.last_provider = completion.provider
        self.last_model = completion.model
        tokens = completion.usage.billable
        decision = _parse(completion.text)
        logger.info(
            "mind deliberation completed",
            extra={
                "marvi_event_id": event.get("id", ""),
                "marvi_route": "auxiliary/mind",
                "marvi_provider": completion.provider,
                "marvi_model": completion.model,
                "marvi_latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "marvi_billable_tokens": tokens,
                "marvi_valid_output": decision is not None,
            },
        )
        if decision is None:
            # Empty, not `verdict.detail`. See the contract note above `ask`.
            return verdict.surface, "", tokens
        worth_it, sentence = decision
        if not worth_it:
            # The model may always choose quiet; that is the whole point.
            # Not "not worth interrupting".
            #
            # It was the commonest line on the Decisions page and it reads as a
            # verdict on the user rather than on the moment -- and it was
            # sometimes spoken aloud, because an override kept the model's
            # reason for declining and handed it to the voice. Silence is the
            # ordinary answer here; it does not need a dismissive name.
            return "silent", "nothing that needed saying", tokens
        return verdict.surface, sentence[:300], tokens


def _parse(content: str) -> tuple[bool, str] | None:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except ValueError:
        return None
    if not isinstance(parsed, dict) or "worth_it" not in parsed:
        return None
    return bool(parsed["worth_it"]), str(parsed.get("say", "")).strip()


def deliberator_from_env(
    client: ProviderClient | None = None,
    identity: IdentityFiles | None = None,
    tools: ToolRegistry | None = None,
    harness: CognitionHarness | None = None,
) -> Deliberator | None:
    """None when no provider is configured, which keeps the mind deterministic."""
    if not configured_profiles():
        return None
    return Deliberator(client=client, identity=identity, tools=tools, harness=harness)
