from __future__ import annotations

from wsgiref.simple_server import make_server

from .config import Config
from .web import create_app


def main() -> None:
    config = Config.from_env()
    app = create_app(config)
    with make_server("0.0.0.0", config.port, app) as server:
        print(f"Movies We Missed listening on 0.0.0.0:{config.port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
