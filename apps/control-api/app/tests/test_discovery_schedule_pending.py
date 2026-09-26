"""R01：设备侧待确认周期发现计划的只读枚举。

行为用例挂在**独立 app** 上（`device_client`），与共享 app 的其他路由解耦；组织侧数据
仍通过既有入口创建。可达性由 `test_endpoint_is_wired_into_the_real_app` 单独证明——
它走共享的真实 app，是"接线已生效"的唯一证据（独立 app 天然证不了这件事）。
"""
import copy
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import session_scope
from app.discovery_scheduler import digest
from app.models import DiscoveryScheduleRecord
from app.routers.discovery_schedule_pending import router as pending_router
from app.tests.test_discovery_schedule_management import counts, management  # noqa: F401
from app.tests.test_discovery_scheduler import confirmed  # noqa: F401
from app.tests.test_initial_scan import catalog, initial_context  # noqa: F401

PATH = "/edge/v1/discovery-schedules"


@pytest.fixture(scope="module")
def device_client(client):
    """只挂载新 router 的独立应用；DB 由 session 级 client 夹具初始化。"""
    app = FastAPI()
    app.include_router(pending_router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def pending(request, client, tenant_a):
    path, body = request.getfixturevalue("management")
    _, headers, _ = request.getfixturevalue("initial_context")
    created = client.post(path, headers=tenant_a, json=body)
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "pending_confirmation"
    return path, headers, body


def create_pending(client, tenant_a, path, body):
    changed = copy.deepcopy(body)
    changed["intent"]["schedule_id"] = "eds-" + uuid.uuid4().hex
    created = client.post(path, headers=tenant_a, json=changed)
    assert created.status_code == 200, created.text
    return changed["intent"]["schedule_id"]


def test_pending_list_is_device_scoped_and_readonly(device_client, pending):
    path, headers, body = pending
    schedule_id = body["intent"]["schedule_id"]
    before = counts()
    response = device_client.get(PATH, headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["schema_version"] == "enterprise-discovery-schedule-pending-list/v1"
    assert result["integrity_failed"] == []
    assert [item["schedule_id"] for item in result["items"]] == [schedule_id]
    item = result["items"][0]
    assert item["status"] == "pending_confirmation" and item["revision"] == 0
    assert item["intent"] == body["intent"]
    assert item["intent_digest"] == digest(body["intent"])
    assert result["evaluated_at"].endswith("Z")
    # 只读：重复读取内容相同（时间戳除外），且不新增计划、任务、轮次或审计。
    assert counts() == before
    again = device_client.get(PATH, headers=headers).json()
    assert {k: v for k, v in again.items() if k != "evaluated_at"} == \
        {k: v for k, v in result.items() if k != "evaluated_at"}
    assert counts() == before
    # 枚举不等于授权：计划仍未生效。
    with session_scope() as session:
        assert session.get(DiscoveryScheduleRecord, schedule_id).status == "pending_confirmation"


def test_pending_list_excludes_active_schedules(request, device_client, pending):
    active = request.getfixturevalue("confirmed")
    path, headers, body = pending
    response = device_client.get(PATH, headers=headers)
    assert response.status_code == 200, response.text
    listed = {item["schedule_id"] for item in response.json()["items"]}
    assert body["intent"]["schedule_id"] in listed
    # 同设备的 active 计划属于既有按 ID 读取/tick 路径，不进待办列表。
    assert active["schedule_id"] not in listed


@pytest.mark.parametrize("fault", ["no_credentials", "bad_secret", "unknown_identity"])
def test_pending_list_denials(device_client, pending, fault):
    _, headers, _ = pending
    request_headers = dict(headers)
    if fault == "no_credentials":
        request_headers.pop("Authorization")
    elif fault == "bad_secret":
        request_headers["Authorization"] = "Bearer edge-" + "0" * 43
    else:
        request_headers["X-Edge-Identity"] = "synthetic-unknown-device"
    before = counts()
    response = device_client.get(PATH, headers=request_headers)
    assert response.status_code == 401
    assert counts() == before


def test_pending_list_reports_integrity_failure_without_projection(device_client, pending):
    _, headers, body = pending
    schedule_id = body["intent"]["schedule_id"]
    with session_scope() as session:
        session.get(DiscoveryScheduleRecord, schedule_id).installation_plan_digest = "f" * 64
    response = device_client.get(PATH, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    # 损坏行既不投影内容，也不被静默当作"没有待办"。
    assert result["items"] == []
    assert result["integrity_failed"] == [schedule_id]
    assert result["next_cursor"] is None


def test_pending_list_pagination_advances_past_integrity_failure(device_client, client, tenant_a, pending):
    path, headers, body = pending
    other_id = create_pending(client, tenant_a, path, body)
    first_id = body["intent"]["schedule_id"]
    first, second = sorted([first_id, other_id])
    with session_scope() as session:
        session.get(DiscoveryScheduleRecord, first).installation_plan_digest = "f" * 64
    page = device_client.get(PATH, headers=headers, params={"limit": 1}).json()
    assert page["items"] == [] and page["integrity_failed"] == [first]
    # 分页必须继续推进，否则一行损坏会让其后所有待办永久不可达。
    assert page["next_cursor"] == first
    rest = device_client.get(PATH, headers=headers,
                            params={"limit": 1, "cursor": page["next_cursor"]}).json()
    assert [item["schedule_id"] for item in rest["items"]] == [second]
    assert rest["integrity_failed"] == [] and rest["next_cursor"] is None


def test_endpoint_is_wired_into_the_real_app(client):
    """接线验证：走**共享的真实 app**，该路径必须存在。

    本文件其余用例挂在独立 app 上，只能证明 router 自身行为，**证不了它被 app.main
    注册**。这条断言缺设备身份时为 401/403 而非 404——404 就意味着接线掉了。
    """
    response = client.get(PATH)
    assert response.status_code != 404, "endpoint is not registered in app.main"
    # 命中真实 app 上的设备身份闸门（而非某个 404 兜底或别的 401）。
    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "missing_edge_credentials"
