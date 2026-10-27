"""Command line arguments of `crawl`: one option per command, then the sites.

Each command option stores its function from commands.py in ``func``; without an option `crawl`
starts the crawlers (``--start``).
"""

import argparse
import functools

from animanga.crawler import commands
from animanga.crawler.sites import SITES


def build_parser() -> argparse.ArgumentParser:
    """Build the parser of the `crawl` command.

    Returns
    -------
    argparse.ArgumentParser
        Options ``--start`` (default), ``--stop``, ``--watch``, ``--status``, ``--run`` (one of
        them) and the sites (default: all).
    """
    parser = argparse.ArgumentParser(
        prog="crawl", description="Crawl ANN and MangaUpdates. Without an option: start them."
    )
    parser.add_argument(
        "sites", nargs="*", choices=sorted(SITES), metavar="site", help="default: all"
    )

    # one option per command; each stores its function in args.func (only one may be given)
    group = parser.add_mutually_exclusive_group()
    command = functools.partial(group.add_argument, dest="func", action="store_const")
    command("--start", const=commands.start, help="(default) start in background, restart running")
    command("--stop", const=commands.stop, help="stop cleanly and wait until it exits")
    command("--watch", const=commands.watch, help="follow errors, stops and progress (Ctrl+C)")
    command("--status", const=commands.status, help="statistics from the logs (no network)")
    command("--run", const=commands.run, help="crawl one site in the foreground")

    parser.set_defaults(func=commands.start)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line of `crawl`.

    Parameters
    ----------
    argv : list[str] or None
        Arguments without the program name; ``None`` reads ``sys.argv``.

    Returns
    -------
    argparse.Namespace
        ``func`` (the command) and ``sites`` (all sites if none was named).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.func is commands.run and len(args.sites) != 1:
        parser.error("--run needs exactly one site")

    args.sites = args.sites or list(SITES)
    return args
