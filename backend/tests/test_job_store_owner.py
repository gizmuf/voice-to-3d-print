from __future__ import annotations

from services import job_store


class _Snapshot:
    def __init__(self, document_id: str, payload: dict | None) -> None:
        self.id = document_id
        self._payload = payload
        self.exists = payload is not None

    def to_dict(self) -> dict | None:
        return self._payload


class _Document:
    def __init__(self, document_id: str, documents: dict[str, dict]) -> None:
        self.document_id = document_id
        self.documents = documents

    def get(self) -> _Snapshot:
        return _Snapshot(self.document_id, self.documents.get(self.document_id))


class _Query:
    def __init__(self, documents: dict[str, dict]) -> None:
        self.documents = documents
        self.filters: list[tuple[str, str]] = []
        self.limit_value = 50

    def where(self, field: str, _operator: str, value: str):
        self.filters.append((field, value))
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, value: int):
        self.limit_value = value
        return self

    def stream(self):
        matches = []
        for document_id, payload in self.documents.items():
            if all(payload.get(field) == value for field, value in self.filters):
                matches.append(_Snapshot(document_id, payload))
        return matches[: self.limit_value]


class _Collection(_Query):
    def document(self, document_id: str) -> _Document:
        return _Document(document_id, self.documents)


class _Client:
    def __init__(self, documents: dict[str, dict]) -> None:
        self.documents = documents

    def collection(self, _name: str) -> _Collection:
        return _Collection(self.documents)


def test_job_reads_and_lists_are_owner_scoped(monkeypatch) -> None:
    documents = {
        "owned": {"job_id": "owned", "project_id": "project", "owner_id": "owner-one"},
        "foreign": {"job_id": "foreign", "project_id": "project", "owner_id": "owner-two"},
    }
    monkeypatch.setattr(job_store, "_get_firestore", lambda: _Client(documents))
    monkeypatch.setattr(job_store, "_current_owner", lambda: "owner-one")

    assert job_store.get_job("owned")["owner_id"] == "owner-one"
    assert job_store.get_job("foreign") is None
    assert [job["job_id"] for job in job_store.list_jobs_for_project("project")] == ["owned"]
