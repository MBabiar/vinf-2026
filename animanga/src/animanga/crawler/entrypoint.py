"""Console scripts: `uv run crawl [--start|--stop|--watch|--status|--run] [site ...]` and `watch`.

Without an option `crawl` starts the crawlers in the background (args.py). Sites: ann,
mangaupdates; none named = all.
"""

import sys

from animanga.crawler.args import parse_args


def main(argv: list[str] | None = None) -> None:
    """Run the `crawl` command: parse the arguments and call the chosen command.

    Parameters
    ----------
    argv : list[str] or None
        Arguments without the program name; ``None`` reads ``sys.argv``.
    """
    args = parse_args(argv)
    sys.exit(args.func(args))


def watch_main() -> None:
    """Run the `watch` command: the same as `crawl --watch`."""
    main(["--watch", *sys.argv[1:]])


if __name__ == "__main__":  # `crawl --start` runs each crawler as `python -m … --run <site>`
    main()
