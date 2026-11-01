"""One JSON record per run: what the run did so far, and what a person or the timer decided.

In Azure the records are blobs (runs/<run id>.json) in the Function app's storage account, which has no public network
access and no shared keys: the Function app reaches it through a private endpoint, with its managed identity. Each
blob's metadata holds the run's state, so the timer finds the runs that wait for a person with one list call.

Saving is optimistic: save() only succeeds if nobody saved the record since it was loaded (the blob's ETag), and
raises Conflict otherwise. A step and a cancel can't overwrite each other.

States, in order: queued → drafting → evaluating → awaiting_review → publishing → published. A run can also end as
rejected (the person closed the review Issue), timed_out (no decision within 2 hours), cancelled (runs.py cancel), or
failed (with an error code and message in the record).
"""
from __future__ import annotations

import copy
import json
import threading

ACTIVE = ("queued", "drafting", "evaluating", "awaiting_review", "publishing")
FINISHED = ("published", "rejected", "timed_out", "cancelled", "failed")


class Conflict(Exception):
    """Someone saved the record after it was loaded."""


class NotFound(KeyError):
    """No run with this id."""


class MemoryStore:
    """The store the tests use: the same contract as BlobStore, in a dictionary."""

    def __init__(self):
        self.records: dict[str, tuple[str, int]] = {}
        self.lock = threading.Lock()

    def create(self, record: dict) -> str:
        with self.lock:
            if record["id"] in self.records:
                raise Conflict(record["id"])
            self.records[record["id"]] = (json.dumps(record), 1)
            return "1"

    def load(self, run_id: str) -> tuple[dict, str]:
        with self.lock:
            if run_id not in self.records:
                raise NotFound(run_id)
            text, version = self.records[run_id]
            return json.loads(text), str(version)

    def save(self, record: dict, etag: str) -> str:
        with self.lock:
            _, version = self.records[record["id"]]
            if str(version) != etag:
                raise Conflict(record["id"])
            self.records[record["id"]] = (json.dumps(record), version + 1)
            return str(version + 1)

    def list(self) -> list[dict]:
        with self.lock:
            records = [json.loads(text) for text, _ in self.records.values()]
        return [{"id": r["id"], "state": r["state"], "created": r["created"], "updated": r.get("updated", r["created"])}
                for r in records]

    def peek(self, run_id: str) -> dict:
        """Test helper: the record as saved."""
        return copy.deepcopy(self.load(run_id)[0])


class BlobStore:
    """Run records as blobs in one container, with the run's state in the blob's metadata."""

    def __init__(self, container_client):
        self.container = container_client

    @staticmethod
    def name(run_id: str) -> str:
        return f"{run_id}.json"

    @staticmethod
    def metadata(record: dict) -> dict[str, str]:
        return {"state": record["state"], "created": record["created"], "updated": record.get("updated", record["created"])}

    def create(self, record: dict) -> str:
        from azure.core.exceptions import ResourceExistsError

        try:
            result = self.container.get_blob_client(self.name(record["id"])).upload_blob(
                json.dumps(record), overwrite=False, metadata=self.metadata(record))
        except ResourceExistsError as error:
            raise Conflict(record["id"]) from error
        return result["etag"]

    def load(self, run_id: str) -> tuple[dict, str]:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            download = self.container.get_blob_client(self.name(run_id)).download_blob()
        except ResourceNotFoundError as error:
            raise NotFound(run_id) from error
        return json.loads(download.readall()), download.properties.etag

    def save(self, record: dict, etag: str) -> str:
        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceModifiedError

        try:
            result = self.container.get_blob_client(self.name(record["id"])).upload_blob(
                json.dumps(record), overwrite=True, metadata=self.metadata(record), etag=etag,
                match_condition=MatchConditions.IfNotModified)
        except ResourceModifiedError as error:
            raise Conflict(record["id"]) from error
        return result["etag"]

    def list(self) -> list[dict]:
        runs = []
        for blob in self.container.list_blobs(include=["metadata"]):
            meta = blob.metadata or {}
            if blob.name.endswith(".json") and meta.get("state"):
                created = meta.get("created", "")
                runs.append({"id": blob.name[:-5], "state": meta["state"], "created": created,
                             "updated": meta.get("updated") or created})
        return runs
