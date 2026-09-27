import logging
import time

from .app import create_app


def main():
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    worker = app.state.get_enrichment_worker()
    while True:
        worked = worker.tick()
        time.sleep(5 if worked else 10)


if __name__ == "__main__":
    main()
