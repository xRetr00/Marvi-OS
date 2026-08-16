"""Prove a provider works against its real endpoint.

Unit tests check request shaping against recorded payloads. That catches a
wrong field name; it cannot catch a vendor who renamed one, moved an endpoint,
or reports usage differently than their documentation says. This makes one small
real call and checks what actually comes back.

    uv run --project services/gateway python scripts/verify_provider.py openai
    uv run --project services/gateway python scripts/verify_provider.py --all

**This spends money** on metered providers and consumes plan quota on
subscriptions. It is a script you run deliberately, not part of the test suite,
which is why it lives here rather than in `tests/`.

Deliberately minimal: about 30 input tokens and at most 16 output. The point is
proving the wire format, not the model.
"""

from __future__ import annotations

import argparse
import sys

from marvi_gateway.providers import (
    ProviderCallError,
    ProviderClient,
    all_profiles,
    configured_profiles,
    get,
)

PROMPT = [
    {"role": "system", "content": "You reply with exactly one word."},
    {"role": "user", "content": "Say the word: ready"},
]


def check(client: ProviderClient, name: str) -> bool:
    profile = get(name)
    print(f"\n{profile.label()}  ({profile.access_path}, {profile.api_mode})")
    print(f"  endpoint  {profile.endpoint()}")
    print(f"  model     {profile.model_for()}")

    if not profile.configured():
        print("  SKIPPED   not configured")
        return True

    try:
        completion = client.call(PROMPT, provider=profile, max_tokens=16)
    except ProviderCallError as exc:
        print(f"  FAILED    {exc}")
        return False

    usage = completion.usage
    print(f"  reply     {completion.text.strip()[:60]!r}")
    print(
        f"  usage     {usage.input} in / {usage.output} out"
        f" / {usage.cached_input} cached / {usage.billable} billable"
    )

    problems = []
    if not completion.text.strip():
        problems.append("empty reply — read_text does not match this response shape")
    if usage.total == 0:
        # Without this the token budget is silently blind on this provider.
        problems.append("no usage reported — read_usage does not match this shape")
    if usage.cached_input > usage.input:
        problems.append("cached input exceeds total input — the shapes disagree")
    for problem in problems:
        print(f"  PROBLEM   {problem}")
    if not problems:
        print("  OK")
    return not problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", nargs="*", help="provider names; default is all configured")
    parser.add_argument("--all", action="store_true", help="include unconfigured providers")
    args = parser.parse_args()

    if args.provider:
        names = args.provider
    elif args.all:
        names = [p.name for p in all_profiles()]
    else:
        names = [p.name for p in configured_profiles()]

    if not names:
        print("No provider is configured. Connect one in the Marvi control center.")
        return 1

    print(f"Calling {len(names)} provider(s) for real. This costs tokens.")
    client = ProviderClient()
    results = {name: check(client, name) for name in names}

    failed = [name for name, ok in results.items() if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} verified")
    if failed:
        print(f"failed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
