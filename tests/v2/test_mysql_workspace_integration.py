"""按显式本地配置运行真实MySQL验收；探针身份独立且finally清理。"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import threading
import uuid

import pytest
import yaml

from opentest.adapters.mysql_metadata import MySqlMetadataStore
from opentest.adapters.mysql_knowledge import MySqlKnowledgeStore
from opentest.adapters.mysql_index import MySqlKnowledgeIndex
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.operation_execution_store import OperationExecutionStore
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.application.mysql_tasks import MySqlTaskManager
from opentest.application.metadata_migration import MetadataMigration
from opentest.application.system_relations import SystemRelationService
from opentest.domain.errors import ScopeViolationError
from opentest.domain.models import (
    KnowledgeNode, KnowledgeNodeKind, SystemDefinition, TaskRecord, TaskStatus,
    OperationCapability, OperationKind, OperationMutability, OperationExecutionRequest,
    ScanManifest, SourceBaseline, DsfOperationDefinition, SourceReference,
    utc_now,
)


@pytest.fixture
def workspace(tmp_path):
    """显式启用远端测试，为每次运行建立唯一命名空间并删除本次创建的记录。"""

    configuration_path = os.environ.get("OPENTEST_MYSQL_TEST_CONFIG")
    if not configuration_path:
        pytest.skip("explicit MySQL test configuration is required")
    configuration = yaml.safe_load(Path(configuration_path).read_text(encoding="utf-8"))
    identity = "mysql-test-" + uuid.uuid4().hex[:16]
    first = MySqlMetadataStore(configuration, identity + "-first")
    second = MySqlMetadataStore(configuration, identity + "-second")
    source = tmp_path / "source"
    source.mkdir()
    local = MySqlKnowledgeStore(tmp_path / "first", first)
    remote = MySqlKnowledgeStore(tmp_path / "second", second)
    local.register_system(SystemDefinition(system_id=identity, name="共享验收", source_path=str(source)))
    try:
        yield identity, local, remote
    finally:
        # 只删除测试唯一system_id下的探针，绝不清空共享表或接触业务数据。
        with first.transaction():
            for system_id in (identity, identity + "-provider"):
                first.execute("DELETE c FROM ot_interface_contract_version c JOIN ot_interface i ON i.interface_id=c.interface_id WHERE i.system_id=%s", (system_id,))
                first.execute("DELETE FROM ot_interface_relation WHERE consumer_system_id=%s OR provider_system_id=%s", (system_id, system_id))
                for table in ("ot_execution", "ot_workflow_record", "ot_knowledge_edge", "ot_knowledge_node", "ot_interface", "ot_scan", "ot_system"):
                    first.execute(f"DELETE FROM {table} WHERE system_id=%s", (system_id,))


def test_shared_knowledge_keeps_local_source_bindings_and_rolls_back(workspace):
    """另一工作台立即读取共享知识，但源码路径为空且失败事务不会发布半份正文。"""

    identity, local, remote = workspace
    node = KnowledgeNode(system_id=identity, node_id="rule:shared", kind=KnowledgeNodeKind.BUSINESS_RULE,
                         title="退票规则", summary="中文用途与术语")
    local.write_node(node, "第一次正文")
    assert remote.get_system(identity).source_path == ""
    assert remote.get_node(identity, node.node_id)[0] == node
    assert MySqlKnowledgeIndex(remote).search("退票", identity)[0]["node_id"] == node.node_id
    # 嵌套Store写必须属于外层事务；回滚后其他连接仍观察到旧正文。
    with pytest.raises(RuntimeError, match="rollback"):
        with local.system_transaction(identity):
            local.write_node(node, "不应发布的正文")
            raise RuntimeError("rollback")
    assert "第一次正文" in remote.get_node(identity, node.node_id)[2]
    assert not local.node_path(node).exists()


def test_foreign_workspace_task_is_read_only_and_not_orphaned(workspace, tmp_path):
    """相同PID空间也不允许他机恢复或续写任务，当前workspace的失效PID才可中断。"""

    identity, local, remote = workspace
    task = TaskRecord(task_id="task-" + uuid.uuid4().hex[:16], system_id=identity,
                      operation="probe", status=TaskStatus.RUNNING, trace_id="integration",
                      owner_pid=99999999, owner_workspace_id=local.metadata.workspace_id)
    local.metadata.put_workflow("task", task.task_id, task.model_dump(mode="json"))
    foreign = MySqlTaskManager(tmp_path / "foreign-tasks", remote.metadata)
    owner = None
    try:
        assert foreign.get(task.task_id).status == TaskStatus.RUNNING
        with pytest.raises(ScopeViolationError, match="another workspace"):
            foreign._write(foreign.get(task.task_id))
        owner = MySqlTaskManager(tmp_path / "owner-tasks", local.metadata)
        assert foreign.get(task.task_id).status == TaskStatus.INTERRUPTED
    finally:
        foreign.close()
        if owner:
            owner.close()


def test_task_creation_with_distinct_system_locks_does_not_deadlock(workspace, tmp_path):
    """两工作台各持自身系统行后同时建任务，不得再反向锁住整个系统目录。"""

    identity, local, remote = workspace
    provider = identity + "-provider"
    local.register_system(SystemDefinition(system_id=provider, name="任务并发提供方", source_path=str(tmp_path)))
    first = MySqlTaskManager(tmp_path / "lock-first", local.metadata)
    second = MySqlTaskManager(tmp_path / "lock-second", remote.metadata)
    barrier = threading.Barrier(2)

    def create_owned_task(store, manager, system_id):
        """持有原Data流程的系统事务后同步进入任务创建，返回实际持久任务身份。"""

        # barrier确保两个连接同时持有不同系统行，确定性覆盖旧目录锁的死锁顺序。
        with store.system_transaction(system_id):
            barrier.wait(timeout=10)
            task = TaskRecord(task_id="task-" + uuid.uuid4().hex[:16], system_id=system_id,
                              operation="data-execution", status=TaskStatus.WAITING_FOR_COMPLETION,
                              trace_id="lock-integration", ended_at=utc_now(), result={"request_id": "lock-test"})
            return manager.create_business_record(task).task_id

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(create_owned_task, local, first, identity),
                       executor.submit(create_owned_task, remote, second, provider)]
            task_ids = [future.result(timeout=20) for future in futures]
        assert len(set(task_ids)) == 2
        assert first.get(task_ids[0]).system_id == identity
        assert second.get(task_ids[1]).system_id == provider
    finally:
        first.close()
        second.close()


def test_global_operation_request_reserves_exactly_once_across_workspaces(workspace, tmp_path):
    """两个独立连接并发提交同一请求只产生一个执行ID，任何工作台都不得重复派发。"""

    identity, local, remote = workspace
    capability = OperationCapability(system_id=identity, operation_id="sample.Api#query", business_name="查询探针",
        kind=OperationKind.FACADE, mutability=OperationMutability.READ_ONLY, source_scan_id="scan-probe")
    request = OperationExecutionRequest(operation_id=capability.operation_id, request_id="probe-" + uuid.uuid4().hex,
                                        arguments={}, environment="qa")
    stores = [OperationExecutionStore(tmp_path / "operations-a", local.metadata),
              OperationExecutionStore(tmp_path / "operations-b", remote.metadata)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(store.create_or_get, identity, capability, request, "a" * 64) for store in stores]
        records = [future.result() for future in futures]
    assert records[0][0].execution_id == records[1][0].execution_id
    assert sum(created for _, created in records) == 1
    with pytest.raises(ScopeViolationError):
        stores[1].create_or_get("other-system", capability, request, "a" * 64)


def test_second_workspace_reuses_portable_scan_without_tool_download(workspace, tmp_path):
    """扫描缓存跨目录可复用，重复读取不下载大字段，读目录不下载执行工具。"""

    identity, local, remote = workspace
    source = local.get_system(identity).source_path
    scan_id = "scan-" + uuid.uuid4().hex
    artifacts = SourceScanArtifactStore(local.root, local.metadata)
    manifest = ScanManifest(system_id=identity, scan_id=scan_id, baseline=SourceBaseline(source_path=source, commit="a" * 40))
    artifacts.write_manifest(manifest)
    remote_artifacts = SourceScanArtifactStore(remote.root, remote.metadata)
    remote_artifacts.source_path_resolver = lambda system_id: remote.get_system(system_id).source_path
    received = remote_artifacts.read(identity, scan_id)
    assert received.baseline.source_path == ""
    assert received.baseline.commit == manifest.baseline.commit
    assert not (remote_artifacts.tool_root / identity / scan_id).exists()
    # 明确禁止第二次读传输压缩正文，而非仅比较最终内容相同。
    original_fetch = remote.metadata.fetch_one

    def fetch_without_blob(sql, parameters=()):
        """复用真实连接，只拒绝缓存命中后仍请求大型BLOB的实现。"""

        assert "manifest_gzip" not in sql
        return original_fetch(sql, parameters)

    remote.metadata.fetch_one = fetch_without_blob
    assert remote_artifacts.read(identity, scan_id) == received


def test_file_migration_is_repeatable_and_preserves_manual_body(workspace):
    """真实迁移可重复执行且正文不丢失，迁移过程不会覆盖来源Markdown。"""

    identity, shared, _ = workspace
    source = GitKnowledgeStore(shared.root)
    source.register_system(shared.get_system(identity))
    node = KnowledgeNode(system_id=identity, node_id="rule:migrate", kind=KnowledgeNodeKind.BUSINESS_RULE,
                         title="迁移规则", summary="保留人工段落")
    source.write_node(node, "程序段落")
    path = source.node_path(node)
    path.write_text(path.read_text(encoding="utf-8") + "\n人工确认的用途。\n", encoding="utf-8")
    original = path.read_bytes()
    # 两次读取同一来源只验证/复用相同聚合，不制造新版本或改写人工正文。
    first = MetadataMigration(source.root, shared.metadata).run()
    second = MetadataMigration(source.root, shared.metadata).run()
    assert first == second
    assert path.read_bytes() == original
    assert "人工确认的用途" in shared.get_node(identity, node.node_id)[2]


def test_concurrent_scan_publication_completes_both_directions(workspace, tmp_path):
    """A引用B与B注册扫描并发发布后关系双向可见，不遗漏后发布的一方。"""

    identity, local, remote = workspace
    provider_id = identity + "-provider"
    provider_source = tmp_path / "provider-source"
    provider_source.mkdir()
    remote.register_system(SystemDefinition(system_id=provider_id, name="provider", source_path=str(provider_source)))
    declaration = DsfOperationDefinition(operation_id=f"dsf:{provider_id}:api:query", provider_system_id=provider_id,
        gs_name=provider_id, service_name="api", version="1", action="query",
        source_refs=[SourceReference(path="Api.java", symbol="sample.Api#query", line=1)])

    def publish(store, system_id):
        """走真实准备、全目录行锁和latest提交顺序，线程只共享数据库。"""

        artifacts = SourceScanArtifactStore(store.root, store.metadata)
        manifest = ScanManifest(system_id=system_id, scan_id="scan-" + uuid.uuid4().hex,
            baseline=SourceBaseline(source_path=store.get_system(system_id).source_path, commit="a" * 40),
            dsf_operations=[declaration])
        relations = SystemRelationService(store, artifacts)
        artifacts.write_manifest(manifest)
        relations.prepare_interfaces(manifest, [])
        with store.metadata.transaction():
            relations.reconcile_published_scan(system_id, manifest.scan_id)
            artifacts.publish_latest(system_id, manifest.scan_id)
        return relations

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(publish, local, identity), pool.submit(publish, remote, provider_id)]
        consumer_relations, provider_relations = [item.result() for item in pending]
    assert consumer_relations.catalog(identity).interface_relations[0].target_system_id == provider_id
    assert provider_relations.catalog(provider_id).upstream[0].system_id == identity


def test_console_cache_observes_contract_and_draft_writes_from_other_workspace(workspace):
    """通过真实MySQL写契约、后补接口和草稿，另一进程的同一缓存目录必须立即更新。"""

    from opentest.adapters.operation_contract_store import OperationContractStore
    from opentest.application.console_read_cache import ConsoleReadCache
    from opentest.application.operation_input_knowledge import OperationInputKnowledgeBuilder
    from opentest.domain.models import KnowledgeGenerationWorkflowBatch

    identity, local, remote = workspace
    scan_id = "scan-" + uuid.uuid4().hex
    operation = OperationCapability(system_id=identity, operation_id="facade:sample.Api#query", business_name="缓存探针",
        kind=OperationKind.FACADE, mutability=OperationMutability.READ_ONLY, source_scan_id=scan_id)
    local.metadata.execute("INSERT INTO ot_interface(system_id,scan_id,operation_id,definition_json) VALUES(%s,%s,%s,%s)",
                           (identity, scan_id, operation.operation_id, "{}"))
    contracts = OperationContractStore(local.root / "contracts", local.metadata)
    remote_contracts = OperationContractStore(remote.root / "contracts", remote.metadata)
    cache = ConsoleReadCache(remote.metadata, remote.root)
    loads = []

    @cache.cached
    def directory():
        """读取与控制台相同的契约/草稿源，返回摘要并记录实际加载次数。"""

        loads.append(True)
        contract = remote_contracts.get_latest(identity, scan_id, operation.operation_id)
        return {"summary": contract.operation_summary if contract else "", "drafts": len(remote.list_draft_batches(identity)),
                "operations": len(remote_contracts.read_operations(identity, scan_id))}

    assert directory() == {"summary": "", "drafts": 0, "operations": 0}
    directory()
    assert len(loads) == 1
    # 经真实存储写路径发布补充后，版本推进必须与正文同提交。
    base = OperationInputKnowledgeBuilder().build(operation, None, scan_id)
    contracts.save(identity, base.model_copy(update={"operation_summary": "新增说明"}))
    assert directory()["summary"] == "新增说明"
    local.write_draft_batch(KnowledgeGenerationWorkflowBatch(batch_id="batch-" + uuid.uuid4().hex,
        system_id=identity, scan_id=scan_id, target_ids=[operation.operation_id], status="GENERATING"))
    assert directory()["drafts"] == 1
    contracts.register_operation(identity, scan_id, DsfOperationDefinition(operation_id="dsf:probe:api:query",
        provider_system_id="probe-provider", gs_name="group.probe", service_name="api", action="query", version="1",
        source_refs=[SourceReference(path="Api.java", symbol="sample.Api#query")]))
    assert directory()["operations"] == 1
    assert len(loads) == 4
    # 被回滚的补充不能改变可见版本，之前的正确缓存仍然命中。
    with pytest.raises(RuntimeError, match="rollback"):
        with local.metadata.transaction():
            contracts.save(identity, base.model_copy(update={"contract_revision": 1, "operation_summary": "不应可见"}))
            raise RuntimeError("rollback")
    assert directory()["summary"] == "新增说明"
    assert len(loads) == 4
