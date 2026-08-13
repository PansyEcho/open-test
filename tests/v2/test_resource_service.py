"""验证资源应用服务的公开投影、探测降级和业务就绪状态保护。"""

from __future__ import annotations

from pathlib import Path

import yaml

from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.resource_inventory import SourceResourceDiscoverer
from opentest.adapters.source_analysis import GitSourceRepository, SourceScanArtifactStore
from opentest.application.resources import ResourceInventoryService
from opentest.domain.models import (
    BusinessValidationState,
    ResourceConnectionState,
    ResourceBusinessEvidence,
    ResourceStateRecord,
    ResourceStatus,
    ScanManifest,
    SystemDefinition,
)


SYSTEM_ID = "travelsystem.java.dsf.supplychain.booking.core"
MYSQL_RESOURCE_ID = f"resource:{SYSTEM_ID}:mysql:database:bookingcoredatasource"
MQ_RESOURCE_ID = f"resource:{SYSTEM_ID}:mq:consumer:jobmessagelistener"
MQ_CLUSTER_ID = f"resource:{SYSTEM_ID}:mq:cluster:mq-namesrvaddress"


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
    artifacts = SourceScanArtifactStore(knowledge_root)
    baseline = GitSourceRepository().capture(source_root)
    discovery = SourceResourceDiscoverer().discover(SYSTEM_ID, source_root)
    manifest = ScanManifest(
        scan_id="scan-resource-service-fixture",
        system_id=SYSTEM_ID,
        baseline=baseline,
        resources=discovery.resources,
        resource_inventory_captured=True,
    )
    artifacts.write_manifest(manifest)
    store.update_source_baseline(SYSTEM_ID, baseline)
    artifacts.publish_latest(SYSTEM_ID, manifest.scan_id)

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
                        },
                        {
                            "operation_id": "resource.probe",
                            "resource_id": MQ_CLUSTER_ID,
                            "kind": "mq",
                            "title": "MQ只读路由检测",
                            "parameter_names": [],
                            "result_fields": [],
                            "evidence_level": "direct",
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
        artifacts=artifacts,
    )


def test_list_resources_keeps_discovered_state_without_catalog(tmp_path: Path) -> None:
    """操作目录缺失时页面仍应展示源码发现资源而不是返回空列表。"""

    service = _resource_service(tmp_path)
    resources = service.list_resources(SYSTEM_ID)

    assert {item["definition"]["resource_id"] for item in resources} == {MYSQL_RESOURCE_ID, MQ_CLUSTER_ID}
    assert {item["state"]["status"] for item in resources} == {"DISCOVERED"}
    assert all(item["state"]["operation_count"] == 0 for item in resources)
    mq_definition = next(item["definition"] for item in resources if item["definition"]["kind"] == "mq")
    assert mq_definition["legacy_resource_ids"] == [MQ_RESOURCE_ID]
    assert len(mq_definition["interactions"]) == 1


def test_probe_reports_missing_worker_for_database_and_mq_cluster(tmp_path: Path) -> None:
    """Worker缺失应让数据库和MQ集群稳定BLOCKED，不得用静态发现伪装连接。"""

    service = _resource_service(tmp_path, with_catalog=True)
    states = {item.resource_id: item for item in service.probe(SYSTEM_ID, "qa")}

    assert states[MYSQL_RESOURCE_ID].status == ResourceStatus.BLOCKED
    assert states[MYSQL_RESOURCE_ID].error_code == "QA_WORKER_MISSING"
    assert states[MQ_CLUSTER_ID].status == ResourceStatus.BLOCKED
    assert states[MQ_CLUSTER_ID].error_code == "QA_WORKER_MISSING"


def test_legacy_mq_id_resolves_for_probe_and_business_evidence(tmp_path: Path, monkeypatch) -> None:
    """旧MQ Consumer ID应在探测和证据发布时统一映射到NameServer集群。

    Args:
        tmp_path: Pytest提供的隔离目录。
        monkeypatch: 替换Worker执行以避免测试访问QA。
    """

    service = _resource_service(tmp_path, with_catalog=True)

    def successful_execute(*_args, **_kwargs) -> dict[str, object]:
        """模拟批准的MQ只读路由检测成功，不创建生产者或消费者。"""

        return {"status": "ok", "projection": {}}

    monkeypatch.setattr("opentest.application.resources.QaWorkerClient.execute", successful_execute)
    states = {item.resource_id: item for item in service.probe(SYSTEM_ID, "qa", [MQ_RESOURCE_ID])}
    assert states[MQ_CLUSTER_ID].status == ResourceStatus.CONNECTED

    evidence = ResourceBusinessEvidence(
        snapshot_id="snapshot-001",
        case_id="case-mq-effect",
        run_id="run-001",
        step_ids=["observe-mq-effect"],
        assertion_digest="b" * 64,
        direct_observation=False,
    )
    saved = service.mark_business_evidence(MQ_RESOURCE_ID, evidence, effect_only=True)
    assert saved.resource_id == MQ_CLUSTER_ID
    assert saved.status == ResourceStatus.EFFECT_ONLY


def test_public_operation_projection_excludes_private_execution_fields(tmp_path: Path) -> None:
    """API可见操作目录不得返回SQL、Redis Key模板或连接实现。"""

    service = _resource_service(tmp_path, with_catalog=True)
    operations = service.list_operations(SYSTEM_ID)
    serialized = [operation.model_dump(mode="json") for operation in operations]

    assert operations[0].operation_id == "order.primary_detail"
    assert "statement" not in serialized[0]
    assert "redis_key_template" not in serialized[0]
    assert "secret" not in str(serialized)


def test_current_resources_exclude_orphan_state_and_history_lists_it_separately(tmp_path: Path) -> None:
    """旧源码资源状态不得混入当前主表，只能进入脱敏历史区。

    Args:
        tmp_path: Pytest提供的隔离源码和资源状态目录。
    """

    service = _resource_service(tmp_path)
    orphan_id = f"resource:{SYSTEM_ID}:mysql:database:removeddatasource"
    service.state_store.save(
        ResourceStateRecord(
            resource_id=orphan_id,
            system_id=SYSTEM_ID,
            status=ResourceStatus.BLOCKED,
            error_code="UNKNOWN_RESOURCE",
            safe_summary="历史资源已不在当前源码中",
        )
    )

    current_ids = {item["definition"]["resource_id"] for item in service.list_resources(SYSTEM_ID)}
    history = service.list_resource_history(SYSTEM_ID)

    assert orphan_id not in current_ids
    assert history == [
        {
            "resource_id": orphan_id,
            "status": "BLOCKED",
            "error_code": "UNKNOWN_RESOURCE",
            "safe_summary": "历史资源已不在当前源码中",
            "updated_at": history[0]["updated_at"],
        }
    ]


def test_resource_projection_stays_bound_to_latest_successful_scan(tmp_path: Path) -> None:
    """未重新扫描的源码改动不得直接改变资源主表。

    Args:
        tmp_path: Pytest提供的隔离源码和扫描Manifest目录。
    """

    service = _resource_service(tmp_path)
    before = {item["definition"]["resource_id"] for item in service.list_resources(SYSTEM_ID)}
    resource_path = tmp_path / "source/app/biz/src/main/resources/META-INF/spring/resources.xml"
    resource_path.write_text(
        resource_path.read_text(encoding="utf-8").replace(
            "</beans>",
            '<bean id="unscannedDatasource" class="com.ly.dal.datasource.RoutableDataSource">'
            '<property name="dbName" value="MustWaitForSuccessfulScan"/></bean></beans>',
        ),
        encoding="utf-8",
    )

    after = {item["definition"]["resource_id"] for item in service.list_resources(SYSTEM_ID)}

    assert after == before


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


def test_failed_probe_preserves_ready_business_evidence(
    tmp_path: Path,
) -> None:
    """临时连接失败只能更新连接维度，不能抹掉历史业务验证证据。

    Args:
        tmp_path: Pytest提供的隔离资源状态目录。
    """

    service = _resource_service(tmp_path, with_catalog=True)
    evidence = ResourceBusinessEvidence(
        snapshot_id="snapshot-001",
        case_id="case-create-order",
        run_id="run-001",
        step_ids=["observe-order"],
        assertion_digest="c" * 64,
    )
    service.state_store.save(
        ResourceStateRecord(
            resource_id=MYSQL_RESOURCE_ID,
            system_id=SYSTEM_ID,
            status=ResourceStatus.READY,
            business_evidence=evidence,
        )
    )

    # 缺失Worker稳定触发连接失败，验证失败不会修改Snapshot业务证据。
    states = {item.resource_id: item for item in service.probe(SYSTEM_ID, "qa", [MYSQL_RESOURCE_ID])}
    state = states[MYSQL_RESOURCE_ID]
    public_state = next(
        item["state"]
        for item in service.list_resources(SYSTEM_ID)
        if item["definition"]["resource_id"] == MYSQL_RESOURCE_ID
    )

    assert state.status == ResourceStatus.READY
    assert state.connection_state == ResourceConnectionState.FAILED
    assert state.business_validation_state == BusinessValidationState.VERIFIED
    assert state.business_evidence == evidence
    assert public_state["connection_state"] == "FAILED"
    assert public_state["business_validation_state"] == "VERIFIED"
