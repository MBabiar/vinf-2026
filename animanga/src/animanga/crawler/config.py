"""All crawl settings in one place (K2a: headers, timeouts, sleeps). Same for every site."""

from animanga import ROOT

PRODUCT = "VI2026-student-crawler"
USER_AGENT = f"{PRODUCT}/0.1 (FIIT STU course project; xbabiar@stuba.sk; +https://vi2026.ui.sav.sk)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en",
    "Accept-Encoding": "gzip, deflate",  # ~5x less transfer (Cowboy Bebop: 96 kB instead of 545 kB)
}

CONNECT_TIMEOUT = 10.0  # s
READ_TIMEOUT = 30.0  # s; normal pages answer in ~1-1.5 s
MAX_PAGE_BYTES = 10 * 1024 * 1024  # ANN pages are at most ~0.6 MB, MangaUpdates ~0.2-0.3 MB

# s between the end of one response and the next request, never below robots Crawl-delay (ANN 2).
# User's pacing (29 Sep): 3-5 s, plus 30 s every 5 minutes and 60 s every hour of running
# These are defaults; a site module may override MIN_DELAY / JITTER (ANN: 2 s + 0-2 s since 18 Oct;
# MangaUpdates: 1 s + 0-0.2 s)
MIN_DELAY = 3.0
JITTER = 2.0  # s, random extra on top of the delay
SHORT_BREAK = (300, 30)  # every 300 s of running, pause 30 s
LONG_BREAK = (3600, 60)  # every 3600 s of running, pause 60 s

# The crawl never stops on errors (user, 30 Sep). Page errors (500, 502, 504, read timeout) and
# refusals (403, 429, 503, bot challenge) of one ID (user, 16 Oct; before: 5 min x 5 tries, ~25 min
# per bad page): try again after QUICK_RETRY_WAIT (or a longer Retry-After); if it fails again,
# request a page that worked (health check). Site answers -> the ID is failed (problems/<site>.md,
# rechecked once at the end of the run) and the crawl goes on. Site down -> wait RETRY_WAIT, try
# the ID again, check again: the ID is never failed while the site is down. Our network down
# (ConnectionError): wait OFFLINE_WAIT and retry without limit.
QUICK_RETRY_WAIT = 30  # s
RETRY_WAIT = 300  # s
OFFLINE_WAIT = 30  # s; our network down (ConnectionError): check again sooner (user, 2 Oct)
MAX_ATTEMPTS = 2  # counted tries of one URL before the health check decides
MAX_HOPS = 3  # redirects followed for one ID (MangaUpdates: series.html?id=N -> /series/...)

PROBLEMS_DIR = ROOT.parent / "local_docs" / "problems"  # problems/<site>.md, not in git
