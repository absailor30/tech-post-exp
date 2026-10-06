"""Hold a scheduled run until its exact target time (UTC, HH:MM).

GitHub's cron can start a run anywhere from minutes to ~7 hours late. So the workflows fire
EARLY and this gate sleeps until the target, making the post land on time. A run that
starts after the target (or any manual dispatch) goes straight through.
"""
import datetime
import os
import sys
import time

MAX_WAIT = 5 * 3600     # never sleep longer than this; earlier means the cron fired absurdly early


def main():
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        print("not a scheduled run: no wait")
        return
    hh, mm = (int(x) for x in sys.argv[1].split(":"))
    now = datetime.datetime.now(datetime.timezone.utc)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    wait = (target - now).total_seconds()
    if wait <= 0:
        print(f"already past {sys.argv[1]} UTC ({-wait / 60:.0f} min late): going now")
        return
    if wait > MAX_WAIT:
        print(f"{wait / 3600:.1f}h to target is more than the cap: going now")
        return
    print(f"waiting {wait / 60:.0f} min for {sys.argv[1]} UTC")
    time.sleep(wait)


if __name__ == "__main__":
    main()
