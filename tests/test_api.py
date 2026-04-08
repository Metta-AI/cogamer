from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cogamer.auth import AuthenticatedUser

TEST_USER = AuthenticatedUser(id="user-test", email="test@example.com", name="Test", is_team_member=False)
TEAM_USER = AuthenticatedUser(id="user-team", email="team@softmax.com", name="Team", is_team_member=True)

AUTH = {"Authorization": "Bearer test-token"}
TEAM_AUTH = {"Authorization": "Bearer team-token"}


def _make_client(user):
    patchers = []

    p = patch("cogamer.api.app.validate_softmax_token", return_value=user)
    patchers.append(p)
    p.start()

    p = patch("cogamer.api.routes.get_db")
    patchers.append(p)
    mock_db_dep = p.start()

    p = patch("cogamer.api.routes.get_ecs")
    patchers.append(p)
    mock_ecs_dep = p.start()

    p = patch("cogamer.api.routes.get_secrets")
    patchers.append(p)
    mock_secrets_dep = p.start()

    mock_db = MagicMock()
    mock_ecs = MagicMock()
    mock_secrets = MagicMock()
    mock_db_dep.return_value = mock_db
    mock_ecs_dep.return_value = mock_ecs
    mock_secrets_dep.return_value = mock_secrets

    from cogamer.api.app import create_app

    app = create_app()
    tc = TestClient(app)

    return tc, mock_db, mock_ecs, mock_secrets, patchers


@pytest.fixture
def client():
    tc, mock_db, mock_ecs, mock_secrets, patchers = _make_client(TEST_USER)
    yield tc, mock_db, mock_ecs, mock_secrets
    for p in patchers:
        p.stop()


@pytest.fixture
def team_client():
    tc, mock_db, mock_ecs, mock_secrets, patchers = _make_client(TEAM_USER)
    yield tc, mock_db, mock_ecs, mock_secrets
    for p in patchers:
        p.stop()


def test_missing_auth_returns_401():
    with patch("cogamer.api.app.validate_softmax_token", return_value=None):
        from cogamer.api.app import create_app

        app = create_app()
        tc = TestClient(app)
        resp = tc.get("/cogamers")
        assert resp.status_code == 401


def test_create_cogamer(client):
    tc, mock_db, mock_ecs, mock_secrets = client
    mock_db.get_cogamer.return_value = None
    mock_ecs.run_task.return_value = "arn:aws:ecs:us-east-1:123:task/abc"
    with (
        patch("cogamer.api.routes._get_image_info", return_value={}),
        patch("cogamer.api.routes._get_github_app_creds", return_value=("123", "fake-pem")),
        patch("cogamer.api.routes.create_repo_with_deploy_key", return_value=("softmax-agents/alpha", "fake-key")),
    ):
        resp = tc.post("/cogamers", json={"name": "alpha"}, headers=AUTH)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "alpha"
    assert data["owner"] == "user-test"
    assert data["token"].startswith("cgm_")
    assert data["codebase"] == "git@github.com:softmax-agents/alpha.git"


def test_create_cogamer_already_exists(client):
    tc, mock_db, _, _ = client
    from cogamer.models import CogamerState

    mock_db.get_cogamer.return_value = CogamerState(name="alpha", codebase="x", owner="user-test")
    resp = tc.post("/cogamers", json={"name": "alpha"}, headers=AUTH)
    assert resp.status_code == 409


def test_list_cogents(client):
    tc, mock_db, _, _ = client
    from cogamer.models import CogamerState

    mock_db.list_cogamers.return_value = [CogamerState(name="alpha", codebase="x", owner="user-test")]
    resp = tc.get("/cogamers", headers=AUTH)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_filters_by_owner(client):
    tc, mock_db, _, _ = client
    from cogamer.models import CogamerState

    mock_db.list_cogamers.return_value = [
        CogamerState(name="mine", codebase="x", owner="user-test"),
        CogamerState(name="theirs", codebase="x", owner="other-user"),
    ]
    resp = tc.get("/cogamers", headers=AUTH)
    names = [c["name"] for c in resp.json()]
    assert names == ["mine"]


def test_list_all_for_team_member(team_client):
    tc, mock_db, _, _ = team_client
    from cogamer.models import CogamerState

    mock_db.list_cogamers.return_value = [
        CogamerState(name="mine", codebase="x", owner="user-team"),
        CogamerState(name="theirs", codebase="x", owner="other-user"),
    ]
    resp = tc.get("/cogamers?all=true", headers=TEAM_AUTH)
    assert len(resp.json()) == 2


def test_get_cogent(client):
    tc, mock_db, mock_ecs, _ = client
    from cogamer.models import CogamerState

    mock_db.get_cogamer.return_value = CogamerState(
        name="alpha",
        codebase="x",
        owner="user-test",
        ecs_task_arn="arn:task/abc",
    )
    mock_ecs.describe_task.return_value = {"task_arn": "arn:task/abc", "status": "RUNNING", "ip": "10.0.1.5"}
    resp = tc.get("/cogamers/alpha", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["name"] == "alpha"


def test_get_cogent_not_found(client):
    tc, mock_db, _, _ = client
    mock_db.get_cogamer.return_value = None
    resp = tc.get("/cogamers/nope", headers=AUTH)
    assert resp.status_code == 404


def test_owner_cannot_access_other_cogent(client):
    tc, mock_db, _, _ = client
    from cogamer.models import CogamerState

    mock_db.get_cogamer.return_value = CogamerState(name="alpha", codebase="x", owner="other-user")
    resp = tc.get("/cogamers/alpha", headers=AUTH)
    assert resp.status_code == 403


def test_team_member_can_access_any_cogent(team_client):
    tc, mock_db, mock_ecs, _ = team_client
    from cogamer.models import CogamerState

    mock_db.get_cogamer.return_value = CogamerState(
        name="alpha",
        codebase="x",
        owner="other-user",
        ecs_task_arn="arn:task/abc",
    )
    mock_ecs.describe_task.return_value = {"task_arn": "arn:task/abc", "status": "RUNNING", "ip": "10.0.1.5"}
    resp = tc.get("/cogamers/alpha", headers=TEAM_AUTH)
    assert resp.status_code == 200


def test_stop_cogent(client):
    tc, mock_db, mock_ecs, _ = client
    from cogamer.models import CogamerState

    mock_db.get_cogamer.return_value = CogamerState(
        name="alpha",
        codebase="x",
        owner="user-test",
        ecs_task_arn="arn:task/abc",
    )
    resp = tc.delete("/cogamers/alpha", headers=AUTH)
    assert resp.status_code == 200
    mock_ecs.stop_task.assert_called_once()


def test_send_message(client):
    tc, mock_db, _, _ = client
    from cogamer.models import CogamerState

    mock_db.get_cogamer.return_value = CogamerState(name="alpha", codebase="x", owner="user-test")
    resp = tc.post("/cogamers/alpha/send", json={"message": "fix the bug"}, headers=AUTH)
    assert resp.status_code == 200
    assert "channel_id" in resp.json()
    mock_db.put_message.assert_called_once()


def test_recv_messages(client):
    tc, mock_db, _, _ = client
    from cogamer.models import CogamerState, Message

    mock_db.get_cogamer.return_value = CogamerState(name="alpha", codebase="x", owner="user-test")
    mock_db.get_messages.return_value = [Message(channel_id="ch-abc", sender="cogamer", body="done")]
    resp = tc.get("/cogamers/alpha/recv/ch-abc", headers=AUTH)
    assert resp.status_code == 200
    assert len(resp.json()["messages"]) == 1


def test_set_config(client):
    tc, mock_db, _, _ = client
    from cogamer.models import CogamerState

    mock_db.get_cogamer.return_value = CogamerState(name="alpha", codebase="x", owner="user-test")
    resp = tc.put("/cogamers/alpha/config", json={"config": {"key": "value"}}, headers=AUTH)
    assert resp.status_code == 200
    mock_db.update_cogamer.assert_called_once()


def test_set_secrets(client):
    tc, mock_db, _, mock_secrets = client
    from cogamer.models import CogamerState

    mock_db.get_cogamer.return_value = CogamerState(name="alpha", codebase="x", owner="user-test")
    resp = tc.put("/cogamers/alpha/secrets", json={"secrets": {"API_KEY": "abc"}}, headers=AUTH)
    assert resp.status_code == 200
    mock_secrets.set_secrets.assert_called_once()


def test_token_excluded_from_get(client):
    tc, mock_db, mock_ecs, _ = client
    from cogamer.models import CogamerState

    mock_db.get_cogamer.return_value = CogamerState(
        name="alpha",
        codebase="x",
        owner="user-test",
        token="cgm_secret123",
    )
    mock_ecs.describe_task.return_value = {"task_arn": "arn:task/abc", "status": "RUNNING", "ip": "10.0.1.5"}
    resp = tc.get("/cogamers/alpha", headers=AUTH)
    assert resp.status_code == 200
    assert "token" not in resp.json()


def test_token_excluded_from_list(client):
    tc, mock_db, _, _ = client
    from cogamer.models import CogamerState

    mock_db.list_cogamers.return_value = [
        CogamerState(name="alpha", codebase="x", owner="user-test", token="cgm_secret123"),
    ]
    resp = tc.get("/cogamers", headers=AUTH)
    assert resp.status_code == 200
    assert "token" not in resp.json()[0]


def test_get_cogamer_token_endpoint(client):
    tc, mock_db, _, _ = client
    from cogamer.models import CogamerState

    mock_db.get_cogamer.return_value = CogamerState(
        name="alpha",
        codebase="x",
        owner="user-test",
        token="cgm_secret123",
    )
    resp = tc.get("/cogamers/alpha/token", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["token"] == "cgm_secret123"


def test_get_cogamer_token_forbidden_for_non_owner(client):
    tc, mock_db, _, _ = client
    from cogamer.models import CogamerState

    mock_db.get_cogamer.return_value = CogamerState(
        name="alpha",
        codebase="x",
        owner="other-user",
        token="cgm_secret123",
    )
    resp = tc.get("/cogamers/alpha/token", headers=AUTH)
    assert resp.status_code == 403


def test_cogamer_token_auth_own_endpoints():
    """A cogamer token can access its own endpoints."""
    from cogamer.auth import AuthenticatedCogamer

    cogamer_caller = AuthenticatedCogamer(cogamer_name="alpha")
    patchers = []

    p = patch("cogamer.api.app.validate_softmax_token", return_value=None)
    patchers.append(p)
    p.start()

    p = patch("cogamer.api.app._resolve_cogamer_token", return_value=cogamer_caller)
    patchers.append(p)
    p.start()

    p = patch("cogamer.api.routes.get_db")
    patchers.append(p)
    mock_db_dep = p.start()

    p = patch("cogamer.api.routes.get_ecs")
    patchers.append(p)
    p.start()

    p = patch("cogamer.api.routes.get_secrets")
    patchers.append(p)
    p.start()

    mock_db = MagicMock()
    mock_db_dep.return_value = mock_db

    from cogamer.api.app import create_app
    from cogamer.models import CogamerState

    app = create_app()
    tc = TestClient(app)

    mock_db.get_cogamer.return_value = CogamerState(
        name="alpha",
        codebase="x",
        owner="user-test",
        token="cgm_abc123",
    )

    cgm_auth = {"Authorization": "Bearer cgm_abc123"}
    resp = tc.post("/cogamers/alpha/heartbeat", json={"status": "running"}, headers=cgm_auth)
    assert resp.status_code == 200

    for p in patchers:
        p.stop()


def test_cogamer_token_cannot_access_other_cogamer():
    """A cogamer token cannot access a different cogamer."""
    from cogamer.auth import AuthenticatedCogamer

    cogamer_caller = AuthenticatedCogamer(cogamer_name="alpha")
    patchers = []

    p = patch("cogamer.api.app.validate_softmax_token", return_value=None)
    patchers.append(p)
    p.start()

    p = patch("cogamer.api.app._resolve_cogamer_token", return_value=cogamer_caller)
    patchers.append(p)
    p.start()

    p = patch("cogamer.api.routes.get_db")
    patchers.append(p)
    mock_db_dep = p.start()

    p = patch("cogamer.api.routes.get_ecs")
    patchers.append(p)
    p.start()

    p = patch("cogamer.api.routes.get_secrets")
    patchers.append(p)
    p.start()

    mock_db = MagicMock()
    mock_db_dep.return_value = mock_db

    from cogamer.api.app import create_app
    from cogamer.models import CogamerState

    app = create_app()
    tc = TestClient(app)

    mock_db.get_cogamer.return_value = CogamerState(
        name="beta",
        codebase="x",
        owner="user-test",
        token="cgm_beta456",
    )

    cgm_auth = {"Authorization": "Bearer cgm_abc123"}
    resp = tc.post("/cogamers/beta/heartbeat", json={"status": "running"}, headers=cgm_auth)
    assert resp.status_code == 403

    for p in patchers:
        p.stop()


def test_cogent_token_cannot_create(client):
    """Cogent tokens cannot call user-only endpoints like create."""
    from cogamer.auth import AuthenticatedCogamer

    cogamer_caller = AuthenticatedCogamer(cogamer_name="alpha")
    patchers = []

    p = patch("cogamer.api.app.validate_softmax_token", return_value=None)
    patchers.append(p)
    p.start()

    p = patch("cogamer.api.app._resolve_cogamer_token", return_value=cogamer_caller)
    patchers.append(p)
    p.start()

    p = patch("cogamer.api.routes.get_db")
    patchers.append(p)
    p.start()

    p = patch("cogamer.api.routes.get_ecs")
    patchers.append(p)
    p.start()

    p = patch("cogamer.api.routes.get_secrets")
    patchers.append(p)
    p.start()

    from cogamer.api.app import create_app

    app = create_app()
    tc = TestClient(app)

    cgm_auth = {"Authorization": "Bearer cgm_abc123"}
    resp = tc.post("/cogamers", json={"name": "new"}, headers=cgm_auth)
    assert resp.status_code == 403

    for p in patchers:
        p.stop()
