"""Domain values and errors; independent of Qt, HTTP and persistence."""
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field

class Cancelled(Exception):
    pass


class ApiError(Exception):
    def __init__(self, message, status=0, uncertain=False):
        super().__init__(message)
        self.status = status
        self.uncertain = uncertain


def fingerprint(token):
    return hashlib.sha256(token.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

@dataclass(frozen=True)
class Action:
    target: str
    method: str
    path: str
    body: object = None
    before: object = None
    guard_path: str = ""
    summary: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    guard_kind: str = "resource"


@dataclass
class Plan:
    owner: str
    actions: list[Action]
    created: float = field(default_factory=time.time)
    batch: str = field(default_factory=lambda: uuid.uuid4().hex)
