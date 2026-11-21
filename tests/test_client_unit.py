"""Unit tests that need no Argon stack."""

import json

from argon_agents import ArgonClient


class _Response:
    def __init__(self, body: dict, status: int = 201):
        self.status_code = status
        self.content = json.dumps(body).encode()
        self.text = self.content.decode()
        self._body = body

    def json(self):
        return self._body


def _client(reply: dict):
    sent = []
    client = ArgonClient("http://argon.test")

    def request(method, url, json=None, timeout=None):
        sent.append((method, url, json))
        return _Response(reply)

    client._session.request = request
    return client, sent


REPLY = {
    "branch": "sb", "connection_string": "mongodb://u:p@h/argon_br_1?authSource=argon_br_1",
    "expires_at": "2026-11-21T00:00:00Z", "forked_from": "main",
    "indexes": 2, "index_notes": ["index at_1 on orders was built without its TTL expiry"],
}


def test_credential_is_sent_only_when_asked():
    client, sent = _client(REPLY)
    client.create_sandbox("p")
    client.create_sandbox("p", credential=True)
    assert "credential" not in sent[0][2]
    assert sent[1][2]["credential"] is True


def test_sandbox_carries_index_report():
    client, _ = _client(REPLY)
    sandbox = client.create_sandbox("p")
    assert sandbox.indexes == 2
    assert sandbox.index_notes == REPLY["index_notes"]
    assert sandbox.database_name == "argon_br_1"


def test_older_engines_report_no_indexes():
    client, _ = _client({k: v for k, v in REPLY.items() if not k.startswith("index")})
    sandbox = client.sandbox_from_pin("p", "pin")
    assert sandbox.indexes == 0
    assert sandbox.index_notes == []
