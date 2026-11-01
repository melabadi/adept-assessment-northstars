"""The release trigger: an Azure Function (Python, Flex Consumption) that Event Grid calls once for each build pushed to
the registry. This file only adapts the event and logs what happened; release_trigger.py decides.

  release_on_push   Event Grid trigger, called by the subscription release-on-push on the registry's system topic. For a
                    push of the API's repository to this registry, it starts one execution of the release job with the
                    image's digest. For any other event it starts nothing, and the invocation fails with every failed
                    check in its error, in the function's Invocations and in Application Insights.
"""
import json
import logging

import azure.functions as func

import release_trigger

app = func.FunctionApp()


@app.event_grid_trigger(arg_name="event")
def release_on_push(event: func.EventGridEvent) -> None:
    started = release_trigger.start_release(
        {"topic": event.topic, "eventType": event.event_type, "data": event.get_json()},
        release_trigger.Settings.from_environment(), release_trigger.Arm())
    # Event ids repeat when Event Grid delivers an event again; the release job then skips the repeat.
    logging.info("Started release execution %s for %s, tag %s, event %s", started.execution, started.image,
                 json.dumps(started.commit[:72]), json.dumps(str(event.id)[:72]))
