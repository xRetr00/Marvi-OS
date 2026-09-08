"""What the user has just put you right about, kept in front of you.

Measured, because the obvious explanation was wrong. Marvi told the user
goodnight four times in a row while they were saying it was morning, including
immediately after promising not to:

    user       No, you don't understand it's morning and I am going to sleep.
    assistant  Goodnight, Shereef. Sleep well.
    user       Why do you saying good night when I'm telling you it's morning?
    assistant  You're right, it's morning. I should not say good night at
               morning. I will keep that in mind.
    user       Just going to sleep.
    assistant  Goodnight, Shereef. Sleep well.

The first guess was prompt bloat -- the system prompt was 17,000 characters
against 290 of conversation, and the correction was 0.4% of what the model
read. Replaying that exact exchange against the real model says otherwise:

    said "good night" in 7 of 8   with the full 12,384-character prompt
    said "good night" in 7 of 8   with the prompt cut to 11,734
    said "good night" in 8 of 8   with no system prompt at all

Nothing in the instructions was causing it and nothing in the instructions
could stop it. What drives it is her own side of the conversation: three
earlier assistant turns say "Goodnight, Shereef", and the next one continues
the pattern. Taking those lines out of the history halves it on their own.

That is not something a rule can fix, because the model is not disobeying a
rule -- it is completing a sequence, and the sequence is the strongest signal
in the request. So the correction has to arrive as something other than one
more user line among forty:

    said "good night" in 1 of 8   with the correction restated as a system
                                  message immediately before the turn

Seven in eight to one in eight, same model, same conversation, same prompt.

## Why it expires

A correction is about a moment. "It's morning, not night" is worth carrying
for the next few turns and worth forgetting after that -- and a correction
that never expires becomes a second, unmanaged instruction block, which is the
thing this module exists to avoid adding to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: How the shape of being corrected reads, out loud.
#:
#: Deliberately narrow. A false positive costs one short system line on a turn
#: that did not need it; a false negative is the failure above, repeated. But
#: matching too loosely would put a note in front of every turn and become the
#: bloat this was measured against.
CORRECTING = re.compile(
    r"\b(why (do|are) you\b.*\?"          # "why do you keep saying that?"
    r"|i (just )?(told|said to) you\b"    # "I told you it's morning"
    r"|you keep (say|do|call)"            # "you keep saying goodnight"
    r"|stop (say|call|doing)"             # "stop saying that"
    r"|don'?t say\b"                      # "don't say good night"
    r"|that'?s not what i\b"              # "that's not what I meant"
    r"|you don'?t understand\b"           # "you don't understand, it's morning"
    r"|no,? i (said|meant)\b)",           # "no, I meant the other one"
    re.I,
)

#: How many turns a correction stays in front of her.
#:
#: Three. The failure repeated across two turns after the correction, and a
#: correction still being recited on the tenth turn is a worse assistant than
#: one that forgot -- it would read as being unable to let something go.
HELD_FOR_TURNS = 3


@dataclass
class Corrections:
    """The last thing the user put right, for the next few turns."""

    said: str = ""
    left: int = 0

    def heard(self, text: str) -> bool:
        """Take note if this turn is a correction. True when it was."""
        clean = " ".join((text or "").split())
        if not clean or not CORRECTING.search(clean):
            return False
        # Their words, not a paraphrase. A summary of a correction is one more
        # place for the meaning to go missing, and the sentence is short.
        self.said, self.left = clean[:200], HELD_FOR_TURNS
        return True

    def block(self) -> str:
        """The system line for this turn, or empty. Consumes one turn."""
        if self.left <= 0 or not self.said:
            return ""
        self.left -= 1
        held = self.said
        if self.left <= 0:
            self.said = ""
        return (
            "The user has just corrected you. They said: "
            f'"{held}" '
            "Take it as settled and do not repeat what they corrected."
        )

    def forget(self) -> None:
        self.said, self.left = "", 0
