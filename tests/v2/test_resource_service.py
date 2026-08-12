"""验证资源应用服务的公开投影、探测降级和业务就绪状态保护。"""

from __future__ import annotations

from pathlib import Path

import yaml

from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.application.resources import ResourceInventoryService
from opentest.domain.models import (
    ResourceBusinessEvidence,
    ResourceStateRecord,
    ResourceStatus,
    SystemDefinition,
)


SYSTEM_ID = "train-booking-core"
MYSQL_RESOURCE_ID = "resource:train-booking-core:mysql:database:bookingcoredatasource"
MQ_RESOURCE_ID = "resource:train-booking-core:mq:consumer:jobmessagelistener"


def _write_resource_source(source_root: Path) -> None:
    """创建包含主库和MQ消费者的最小Spring生产资源。

    Args:
        source_root: 已创建的测试源码根目录。

    Side Effects:
        写入数据源和MQ消费者XML供真实发现器扫描。
    """

    resource_path = source_root / "app/biz/src/main/resources/META-INF/spring/resources.xml"
    resource_path.parent.mkdir(parents=True)
    resource_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans" xmlns:sof="http://schema.ly.com/schema/sof">
  <bean id="bookingCoreDatasource" class="com.ly.dal.datasource.RoutableDataSource">
    <property name="dbName" value="TETravelTrainSupplychainOrder"/>
  </bean>
  <sof:consumer id="jobMessageListener" group="${mq.job.group}">
    <sof:listener ref="jobListener"/>
    <sof:channels><sof:channel topic="${mq.job.topic}"/></sof:channels>
  </sof:consumer>
</beans>
""",
        encoding="utf-8",
    )


def _resource_service(tmp_path: Path, with_catalog: bool = False) -> ResourceInventoryService:
    """构造使用固定QA应用身份的资源服务，不创建本地连接配置。

    Args:
        tmp_path: Pytest提供的隔离临时目录。
        with_catalog: 是否写入包含私有执行字段的固定操作目录。

    Returns:
        使用不存在Worker Jar的资源应用服务。

    Side Effects:
        创建知识仓库，并按需写入操作目录。
    """

    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_resource_source(source_root)
    knowledge_root = tmp_path / "knowledge"
    store = GitKnowledgeStore(knowledge_root)
    store.register_system(SystemDefinition(system_id=SYSTEM_ID, name="火车票预订", source_path=str(source_root)))

    if with_catalog:
        catalog_path = store.system_root(SYSTEM_ID) / "oracles/catalog.yaml"
        catalog_path.parent.mkdir(parents=True)
        catalog_path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "system_id": SYSTEM_ID,
                    "operations": [
                        {
                            "operation_id": "order.primary_detail",
                            "resource_id": MYSQL_RESOURCE_ID,
                            "kind": "mysql",
                            "title": "订单主表详情",
                            "parameter_names": ["order_serial_no"],
                            "result_fields": ["order_serial_no", "status"],
                            "evidence_level": "direct",
                            "statement": "SELECT secret FROM table",
                            "redis_key_template": "must-not-leak:{order_serial_no}",
                        }
                    ],
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    return ResourceInventoryService(
        store,
        worker_jar=tmp_path / "missing-worker.jar",
    )


def test_list_resources_keeps_discovered_state_without_catalog(tmp_path: Path) -> None:
    """操作目录缺失时页面仍应展示源码发现资源而不是返回空列表。"""

    service = _resource_service(tmp_path)
    resources = service.list_resources(SYSTEM_ID)

    assert {item["definition"]["resource_id"] for item in resources} == {MYSQL_RESOURCE_ID, MQ_RESOURCE_ID}
    assert {item["state"]["status"] for item in resources} == {"DISCOVERED"}
    assert all(item["state"]["operation_count"] == 0 for item in resources)


def test_probe_reports_missing_worker_and_keeps_mq_discovered(tmp_path: Path) -> None:
    """Worker缺失应产生稳定BLOCKED，MQ不得用静态发现伪装CONNECTED。"""

    service = _resource_service(tmp_path, with_catalog=True)
    states = {item.resource_id: item for item in service.probe(SYSTEM_ID, "qa")}

    assert states[MYSQL_RESOURCE_ID].status == ResourceStatus.BLOCKED
    assert states[MYSQL_RESOURCE_ID].error_code == "QA_WORKER_MISSING"
    assert states[MQ_RESOURCE_ID].status == ResourceStatus.DISCOVERED
    assert "MQ" in states[MQ_RESOURCE_ID].safe_summary


def test_public_operation_projection_excludes_private_execution_fields(tmp_path: Path) -> None:
    """API可见操作目录不得返回SQL、Redis Key模板或连接实现。"""

    service = _resource_service(tmp_path, with_catalog=True)
    operations = service.list_operations(SYSTEM_ID)
    serialized = [operation.model_dump(mode="json") for operation in operations]

    assert operations[0].operation_id == "order.primary_detail"
    assert "statement" not in serialized[0]
    assert "redis_key_template" not in serialized[0]
    assert "secret" not in str(serialized)


def test_successful_probe_does_not_downgrade_ready_business_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """连接复测成功只能刷新耗时，不能覆盖已绑定Snapshot的READY证据。

    Args:
        tmp_path: Pytest提供的隔离临时目录。
        monkeypatch: 用于替换Worker进程调用的Pytest夹具。
    """

    service = _resource_service(tmp_path, with_catalog=True)
    evidence = ResourceBusinessEvidence(
        snapshot_id="snapshot-001",
        case_id="case-create-order",
        run_id="run-001",
        step_ids=["observe-order"],
        assertion_digest="a" * 64,
    )
    service.state_store.save(
        ResourceStateRecord(
            resource_id=MYSQL_RESOURCE_ID,
            system_id=SYSTEM_ID,
            status=ResourceStatus.READY,
            business_evidence=evidence,
        )
    )

    # 测试只验证状态机，不启动真实QA Worker或读取任何连接配置。
    def successful_execute(*_args, **_kwargs) -> dict[str, object]:
        """模拟固定resource.probe操作成功并返回空白名单投影。"""

        return {"status": "ok", "projection": {}}

    monkeypatch.setattr("opentest.application.resources.QaWorkerClient.execute", successful_execute)
    states = {item.resource_id: item for item in service.probe(SYSTEM_ID, "qa", [MYSQL_RESOURCE_ID])}
    state = states[MYSQL_RESOURCE_ID]

    assert state.status == ResourceStatus.READY
    assert state.business_evidence == evidence
