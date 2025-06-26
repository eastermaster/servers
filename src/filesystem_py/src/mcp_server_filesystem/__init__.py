from .server import serve


def main() -> None:
    """Entry point for the MCP filesystem server."""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="MCP filesystem server")
    parser.add_argument(
        "--dir",
        dest="dirs",
        action="append",
        required=True,
        help="Directory the server is allowed to access. May be specified multiple times.",
    )

    args = parser.parse_args()
    asyncio.run(serve(args.dirs))


if __name__ == "__main__":
    main()
