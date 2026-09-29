import logging
import time

from .app import create_app


def main():
    """Gemini 후처리 worker를 시작하고 미처리 이벤트를 주기적으로 확인한다."""
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    modal_worker = app.state.get_modal_worker()
    enrichment_worker = app.state.get_enrichment_worker()
    while True:
        worked = modal_worker.tick()
        worked = enrichment_worker.tick() or worked
        time.sleep(5 if worked else 10)


if __name__ == "__main__":
    main()
