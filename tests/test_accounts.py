from fastapi.testclient import TestClient

from main import app


def test_administrator_manages_sqlite_accounts():
    client = TestClient(app)
    path = "/api/v1/accounts"
    admin = ("admin@dashboard", "123")
    viewer = ("viewer@dashboard", "123")
    data = {"email": "new@example.com", "role": "VIEW_ONLY", "password": "testing-123"}

    assert client.get(path, auth=viewer).status_code == 403
    assert client.post(path, json=data, auth=viewer).status_code == 403
    created = client.post(path, json=data, auth=admin)
    assert created.status_code == 201
    assert created.json() == {"email": data["email"], "role": "VIEW_ONLY"}
    assert client.get("/api/v1/session", auth=(data["email"], data["password"])).status_code == 200
    assert client.put(path + "/admin@dashboard", json={"email": admin[0], "role": "VIEW_ONLY"},
                      auth=admin).status_code == 409

    edited = {"email": "updated@example.com", "role": "INFRA_ADMIN"}
    assert client.put(path + "/new@example.com", json=edited, auth=admin).status_code == 200
    assert client.get("/api/v1/session", auth=(edited["email"], data["password"])).json()["role"] == "INFRA_ADMIN"
    assert client.get("/api/v1/session", auth=(data["email"], data["password"])).status_code == 401
    assert data["password"] not in client.get("/api/v1/audit-logs", auth=admin).text
