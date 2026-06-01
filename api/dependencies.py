from fastapi import Request
from google.adk.runners import Runner


def get_runner(request: Request) -> Runner:
    return request.app.state.runner
