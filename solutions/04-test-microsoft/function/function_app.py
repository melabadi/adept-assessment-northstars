"""Azure Functions app of the Test · Microsoft solution (Python 3.12, Flex Consumption, inside the solution's VNet).

Two functions, both thin: the decisions live in reporter/ and have unit tests (test_reporter.py).
  test_run_ended  POST /api/test-run-ended. The action group calls it, with a function key, when Azure Load Testing's
                  notification rule reports that a run ended. It checks the run and queues its report (flow.accept),
                  then answers at once.
  report_run      Queue trigger on test-runs: one report step (flow.step). Waits for the verdict and the telemetry by
                  queueing the next step with a delay, then opens, comments on, or closes the test's GitHub Issue.
Nothing here logs a token, a key, or a request body.
"""
import json
import logging
from datetime import datetime, timezone

import azure.functions as func

from reporter import flow, services

# The Azure SDKs log every HTTP request, with its headers, and every token they get, at INFO. Keep the function's log to
# its own decisions (the reporter logger).
logging.getLogger("azure").setLevel(logging.WARNING)

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
# infra/reporting.bicep creates this queue and passes its name to the function as QUEUE_NAME.
QUEUE = "test-runs"


@app.route(route="test-run-ended", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def test_run_ended(req: func.HttpRequest) -> func.HttpResponse:
    answer = flow.accept(req.get_body(), services.connect(github=False), flow.Settings.from_env(),
                         datetime.now(timezone.utc))
    return func.HttpResponse(json.dumps({"message": answer.message}), status_code=answer.status,
                             mimetype="application/json")


@app.queue_trigger(arg_name="message", queue_name=QUEUE, connection="AzureWebJobsStorage")
def report_run(message: func.QueueMessage) -> None:
    flow.step(message.get_body(), services.connect(), flow.Settings.from_env(), datetime.now(timezone.utc))
