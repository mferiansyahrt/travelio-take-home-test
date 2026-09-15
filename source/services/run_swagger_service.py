import argparse

import uvicorn

from config import settings

# Run from the `source/` directory:
#   python -m services.run_swagger_service -p 8000 -w 1


def get_args():
    parser = argparse.ArgumentParser(
        description="Run Travelio Message Classifier Service"
    )

    parser.add_argument(
        "-p", "--port",
        help="Port to listen on",
        type=int,
        default=8000
    )

    parser.add_argument(
        "-H", "--host",
        help="Host to bind to",
        default="0.0.0.0"
    )

    parser.add_argument(
        "-w", "--workers",
        help="Number of worker processes",
        type=int,
        default=1
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = get_args()
    # Request logs come from the service's structured middleware, so uvicorn's access log is disabled.
    uvicorn.run(
        "services.swagger_service:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=False,
        reload=False,
    )
