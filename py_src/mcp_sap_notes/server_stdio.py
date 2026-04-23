from __future__ import annotations

import logging

from dotenv import load_dotenv

from .config import load_config
from .server_core import build_mcp_server


def main() -> None:
    load_dotenv()

    config = load_config(http_mode=False)
    logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO))

    mcp = build_mcp_server(config)
    mcp.run()


if __name__ == "__main__":
    main()
