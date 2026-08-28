"""Putting the names back into a transcript that lost them.

The recogniser gets ordinary English right and proper nouns wrong. Measured on
this machine, both Parakeet models, Marvi's own voice reading the sentences:

    NeuDocs  -> "new docs"      Marvi   -> "Marvey" / "Marvy"
    Shereef  -> "Sheriff"       Düzce   -> "DUS" / "Doz"

Neither model has these words. Nothing about the audio was unclear; the
vocabulary simply does not contain them, and `onnx-asr` exposes no hook to put
them there before decoding.

What Marvi does have is a list of exactly these words -- the entities in her
memory graph, named by the dreamer from what she has been told. So they go back
afterwards. It is the cheap end of contextual biasing: worse than biasing the
decoder, and available, which that is not.

## Why the first letter has to match

A wrong correction is worse than a miss -- "the ducks" becoming "NeuDocs" reads
as the assistant hallucinating -- so the bar was measured rather than picked.
On the real failures and a set of ordinary sentences, similarity alone is only
just separable: the worst thing that must be corrected scores 0.55
("morvey" against "Marvi") and the worst thing that must not scores 0.53
("the ducks" against "NeuDocs"). Two hundredths is not a margin.

Requiring the first letter to match opens it up. A recogniser mangles the
middle and end of an unfamiliar name and rarely its opening consonant, while
the false matches are false precisely because they begin elsewhere. With that
gate the false matches drop away and the real ones stay: see `CLOSE_ENOUGH`
for where the line ended up and what it deliberately gives up.
"""

from __future__ import annotations

import difflib
import logging
import re

log = logging.getLogger("marvi.voice")

#: Measured, not chosen, and set where it stops inventing rather than where it
#: catches the most.
#:
#: The real failures score 0.67 to 0.86 -- "new docs" against NeuDocs is 0.86,
#: "sheriff" against Shereef 0.71. The worst false match that survives the
#: first-letter gate is "new features" against "NeuRetro Labs" at 0.52, and one
#: real failure sits between them: "morvey" against "Marvi" at 0.545.
#:
#: 0.60 leaves "morvey" uncorrected. That is the right way round. A miss leaves
#: the transcript as it was heard, which is where it started; a false match
#: writes a product name into a sentence about features, and reads as the
#: assistant making things up.
CLOSE_ENOUGH = 0.60

#: Words the recogniser produces correctly and often, which happen to look like
#: something in a personal vocabulary. Correcting one of these turns a working
#: sentence into a wrong one.
LEAVE_ALONE = frozenset(
    ["a", "about", "all", "and", "any", "are", "as", "at", "be", "been", "but", "by", "can", "did", "do", "does", "for", "from", "had", "has", "have", "he", "her", "here", "him", "his", "how", "i", "if", "in", "is", "it", "its", "just", "like", "make", "makes", "me", "more", "most", "much", "my", "new", "no", "not", "now", "of", "on", "one", "only", "or", "other", "our", "out", "over", "said", "same", "say", "see", "she", "so", "some", "than", "that", "the", "their", "them", "then", "there", "these", "they", "thing", "think", "this", "time", "to", "too", "under", "up", "us", "use", "very", "want", "was", "way", "we", "were", "what", "when", "where", "which", "who", "why", "will", "with", "work", "would", "you", "your"]
)

#: How many heard words one name may span. "new docs" is two; nothing useful
#: is more, and each extra one multiplies the comparisons on a path with no
#: time to spare.
MAX_SPAN = 2


def _key(text: str) -> str:
    """A word reduced to what a recogniser is likely to preserve."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def correct(text: str, names: list[str]) -> str:
    """Put known names back into a transcript. Unchanged when unsure.

    Never raises: a correction pass that fails leaves the transcript as it was
    heard, which is where it started.
    """
    if not text.strip() or not names:
        return text
    try:
        return _correct(text, names)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("could not correct the transcript: %s", exc)
        return text


def _best(heard: str, keyed: list[tuple[str, str]]) -> str:
    """The name this text was probably meant to be, or empty.

    Empty for text that is already one of the names: it is right, and replacing
    it with itself would only risk changing its capitalisation.
    """
    key = _key(heard)
    if len(key) < 3:
        return ""
    best, score = "", 0.0
    for name, name_key in keyed:
        if key == name_key:
            return ""
        if key[0] != name_key[0]:
            continue
        # Comparable lengths. Without this, a two-word span that *contains* a
        # correct name scores well on the shared prefix alone -- "Shereef
        # builds" against "Shereef" is 0.70 -- and the correction eats the word
        # after the name.
        if min(len(key), len(name_key)) / max(len(key), len(name_key)) < 0.7:
            continue
        ratio = difflib.SequenceMatcher(None, key, name_key).ratio()
        if ratio >= CLOSE_ENOUGH and ratio > score:
            best, score = name, ratio
    return best


def _correct(text: str, names: list[str]) -> str:
    keyed = [(name, _key(name)) for name in names if len(_key(name)) >= 3]
    # Separators kept, so the sentence is rebuilt exactly as it was apart from
    # what changed.
    parts = re.findall(r"\w+|\W+", text)
    words = [index for index, part in enumerate(parts) if part[0].isalnum()]

    at = 0
    while at < len(words):
        # Longest span first: "new docs" has to beat "new" alone, or the second
        # half of the name is left stranded in the sentence.
        for span in range(min(MAX_SPAN, len(words) - at), 0, -1):
            chosen = words[at : at + span]
            heard = "".join(parts[position] for position in range(chosen[0], chosen[-1] + 1))
            # One ordinary word, spelled correctly, is not a mistake to fix.
            if span == 1 and _key(heard) in LEAVE_ALONE:
                continue
            name = _best(heard, keyed)
            if not name:
                continue
            parts[chosen[0]] = name
            for position in range(chosen[0] + 1, chosen[-1] + 1):
                parts[position] = ""
            log.info("stt: %r heard as a name; corrected to %r", heard, name)
            at += span
            break
        else:
            at += 1
    return "".join(parts)
