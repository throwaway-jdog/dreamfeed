"""
python -m dreamfeed follow    Who you follow on Chaturbate, live or not (the follow service): their
                              rooms, your recordings' posters and highlights, Saved's copies of what
                              you save, Chaturbate follows and unfollows tapped in dreamfeed.
python -m dreamfeed follow reddit-login [ADDRESS]
                              Sign Reddit in by hand (the Dashboard's Sign in with Reddit does it for you).

The rest of dreamfeed's code here is read by the web app (feed/: the live sites; live/:
Chaturbate; core/: sign-ins, the database, the minors rule).
"""
import sys


def main() -> None:
    cmd, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "follow":
        from .live.follow import main as follow
        follow(rest)
    else:
        sys.exit(__doc__)


main()
