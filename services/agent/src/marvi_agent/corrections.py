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

Restating the correction as a system message helps only if it names the thing
to stop. Measured at 24 samples a variant, same conversation, same model:

    11/24  45%   nothing
    13/24  54%   the user's complaint quoted, and nothing else
     5/24  20%   an explicit instruction, "it is morning, do not say good night"
     2/24   8%   the complaint quoted *and her own last reply named*

Quoting the complaint alone is no better than doing nothing -- it says
somebody is unhappy without saying which words to drop. What works is putting
her own sentence in front of her and forbidding that sentence, because the
sentence is what she is copying.

The first version of this module did the thing that does not work. It was
written from a run of eight samples that read 7/8 against 1/8; twenty-four
samples put the same comparison at 13/24 against 11/24, which is noise. Small
samples on a sampling model are how a fix that does nothing gets shipped.

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
    r"(^\s*(no|nope|nah)\s*,"                  # "No, it's morning" -- the comma matters
    r"|^\s*(no|nope|nah)\s+(it|that|i|you|the|not|we)\b"
    r"|\bit'?s not\b"                     # "It's not night, it's morning"
    r"|\bthat'?s not\b"                   # "that's not what I said"
    r"|^\s*but\b.{0,40}$"                 # "But it's morning."
    r"|\bwhy (do|are) you\b"              # "why do you keep saying that"
    r"|\bi (just |keep )?(told|said to) you\b"
    r"|\byou keep (say|do|call|repeat)"   # "you keep saying goodnight"
    r"|\bstop (say|call|doing|repeat)"    # "stop saying that"
    r"|\bdon'?t say\b"                    # "don't say good night"
    r"|\byou don'?t understand\b"         # "you don't understand"
    r"|\bwrong\b"                         # "that's wrong"
    r"|\bno,? i (said|meant|am|was)\b)",  # "no, I meant the other one"
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
    #: What Marvi answered immediately before being corrected -- the sentence
    #: she is copying, and the one the note has to name.
    answered: str = ""
    left: int = 0
    #: The last reply she gave, normalised. See `repeating`.
    last: str = ""

    def heard(self, text: str, answered: str = "") -> bool:
        """Take note if this turn is a correction. True when it was.

        `answered` is her own last reply. Without it the note says somebody is
        unhappy without saying which words to drop, which measured no better
        than saying nothing at all.
        """
        clean = " ".join((text or "").split())
        if not clean or not CORRECTING.search(clean):
            return False
        # Their words, not a paraphrase. A summary of a correction is one more
        # place for the meaning to go missing, and the sentence is short.
        self.said = clean[:200]
        self.answered = " ".join((answered or "").split())[:200]
        self.left = HELD_FOR_TURNS
        return True

    def block(self) -> str:
        """The system line for this turn, or empty. Consumes one turn."""
        if self.left <= 0 or not self.said:
            return ""
        self.left -= 1
        complaint, mine = self.said, self.answered
        if self.left <= 0:
            self.said = self.answered = ""
        note = f'The user has just corrected you. They said: "{complaint}"'
        if mine:
            # The half that does the work. See the measurements above.
            note += f' You had said: "{mine}" -- do not say it again.'
        else:
            note += " Take it as settled and do not repeat what they corrected."
        return note

    #: Her own last reply, for noticing when she says it twice.
    #:
    #: The stronger of the two signals, and the one that needs nothing from
    #: the user. In a real session she said "Good morning, Shereef. I'm glad
    #: you're awake." verbatim twice in a row, and "Goodnight, Shereef." three
    #: times, while the user objected in four different phrasings -- none of
    #: which the first version of `CORRECTING` matched. Repetition is visible
    #: without parsing anybody's objection.
    def repeating(self, said: str) -> str:
        """Note her repeating herself, and remember this reply. Empty usually.

        Compared on the words rather than the characters, because "Goodnight,
        Shereef." and "Good night, Shereef" are the same reply twice as far as
        anyone listening is concerned.
        """
        # Letters and digits only, spacing dropped: "Goodnight, Shereef." and
        # "Good night, Shereef" are one reply said twice to anybody listening,
        # and she alternated between exactly those two spellings.
        now = "".join(re.findall(r"[a-z0-9]+", (said or "").lower()))
        if not now:
            return ""
        was, self.last = self.last, now
        if not was or was != now:
            return ""
        return (
            f'You have just said "{said.strip()[:160]}" twice in a row. '
            "Do not say it a third time -- answer what they actually asked, "
            "or say something new."
        )

    def forget(self) -> None:
        self.said = self.answered = self.last = ""
        self.left = 0
