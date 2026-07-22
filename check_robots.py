"""Check each shop's robots.txt for the listing path we intend to fetch."""

import urllib.parse
import urllib.robotparser

from ebikedeals.adapters import ADAPTERS
from ebikedeals.net import UA

for cls in ADAPTERS:
    url = cls.source_url
    parts = urllib.parse.urlsplit(url)
    robots = f"{parts.scheme}://{parts.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots)
    try:
        rp.read()
    except Exception as e:
        print(f"{cls.key:14s} robots.txt unreadable ({type(e).__name__})")
        continue
    allowed_ua = rp.can_fetch(UA, url)
    allowed_star = rp.can_fetch("*", url)
    delay = rp.crawl_delay("*")
    flag = "OK " if (allowed_ua and allowed_star) else "NO "
    print(f"{flag}{cls.key:14s} allow(*)={allowed_star!s:5s} crawl_delay={delay} {parts.path[:48]}")
