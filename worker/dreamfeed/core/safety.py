"""What dreamfeed leaves out: content about minors, and nothing else. By the words and tags alone
(no picture is looked at).

- minors(text): words that only mean minors (underage, child, loli, "16yo" ...), for everything:
  posts, titles, tags, subreddit names, rooms, searches. Adult-site words like "teen", "young",
  "petite" or "schoolgirl" aren't among them: on sites of real, verified adults they don't mean
  minors.
- Drawn work (e621, comics) also leaves out e621's own tags for minors (DRAWN_TAGS: young, cub
  ...), since a drawing has no verified age; drawn_words(text) checks a title the same way.
"""
import re

# Words that only mean minors, wherever they're read.
MINORS = re.compile(
    r"(?<![a-z0-9])(?:jailbait|loli|lolis|lolicon|shota|shotas|shotacon|underage|under ?age|under ?aged|minors?|"
    r"child|children|kids?|preteens?|pre ?teen|tweens?|toddlers?|infants?|"
    r"(?:1[0-7]|[1-9]) ?y(?:ears?)? ?o(?:ld)?|(?:1[0-7]|[1-9])yo)(?![a-z0-9])", re.I)

# e621's tags (and drawn work's words) for characters under 18.
DRAWN_TAGS = {"young", "cub", "child", "loli", "shota", "toddler", "baby", "infant", "teen", "adolescent", "underage",
              "young_human", "young_anthro", "young_feral"}


def minors(*texts) -> list[str]:
    """The minors-only words in the texts, lowercased and sorted; empty when there are none."""
    found = set()
    for t in texts:
        if t:
            found |= {m.group(0).lower() for m in MINORS.finditer(str(t).replace("_", " ").replace("-", " "))}
    return sorted(found)


def drawn_words(*texts) -> list[str]:
    """For drawn work's titles and tags: minors() plus DRAWN_TAGS as whole words."""
    t = " ".join(str(x) for x in texts if x).lower()
    words = set(re.findall(r"[a-z0-9_]+", t)) | set(re.findall(r"[a-z0-9]+", t))
    return sorted(set(minors(t)) | (words & DRAWN_TAGS))
