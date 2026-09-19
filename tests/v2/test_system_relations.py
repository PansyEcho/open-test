"""验证只读扫描关系、独立两层BFS和真实MQ扫描证据，不访问外部环境。"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.resource_inventory import SourceResourceDiscoverer
from opentest.adapters.source_analysis import GitSourceRepository, SourceScanArtifactStore
from opentest.application.candidate_operations import CandidateOperationCatalogService
from opentest.application.system_relations import SystemRelationService
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import (
    DsfClientProfile, DsfOperationDefinition, ScanCompleteness, ScanManifest, ScanPublicationOutcome,
    SourceBaseline, SourceReference, SystemDefinition, SystemDependencyBindingSubmission,
    SystemDependencyPurpose, SystemDependencyRole, SourceVersionPin,
)


def _publish(store: GitKnowledgeStore, manifest: ScanManifest) -> None:
    """发布测试扫描并同步注册版本，使关系服务消费真实持久存储。

    Args:
        store: 隔离注册存储。
        manifest: 当前系统完整扫描。
    Side Effects:
        仅写入测试临时目录的scan、baseline与latest。
    """

    artifacts = SourceScanArtifactStore(store.root)
    artifacts.write_manifest(manifest)
    store.update_source_baseline(manifest.system_id, manifest.baseline)
    artifacts.publish_latest(manifest.system_id, manifest.scan_id)


def _operation(provider_id: str, route: str) -> DsfOperationDefinition:
    """生成保留精确接口方法身份的DSF声明，路由可不同于注册ID。

    Args:
        provider_id: 发布或引用声明持有的提供方身份。
        route: 精确路由所绑定的业务系统名。
    Returns:
        可用于构造两端扫描的完整发布坐标。
    """

    return DsfOperationDefinition(
        operation_id=f"dsf:{route}:api:get", provider_system_id=provider_id,
        gs_name=f"dsf.route-{route}", service_name="api", version="1", action="get",
        source_refs=[SourceReference(path="src/main/java/Api.java", symbol=f"sample.{route.replace('-', '')}.Api#get", line=1)],
    )


def _graph(tmp_path: Path, edges: list[tuple[str, str]]) -> tuple[GitKnowledgeStore, dict[str, ScanManifest]]:
    """为有向调用边建立独立系统扫描，使用不同的注册和DSF路由身份。

    Args:
        tmp_path: 测试临时根目录。
        edges: 调用方到提供方的DSF关系。
    Returns:
        注册存储与已发布扫描，供后续漂移测试复用。
    Side Effects:
        创建隔离源码、注册定义及完整扫描。
    """

    store = GitKnowledgeStore(tmp_path / "knowledge")
    manifests: dict[str, ScanManifest] = {}
    for system_id in sorted({item for pair in edges for item in pair}):
        source = tmp_path / system_id
        source.mkdir()
        store.register_system(SystemDefinition(system_id=system_id, name=system_id, source_path=str(source)))
        baseline = SourceBaseline(source_path=str(source), commit=f"source-{system_id}")
        operations = [_operation(system_id, system_id)]
        # 本系统发布仅出现一次，重复调用引用会在关系聚合时去重。
        for caller, provider in edges:
            if caller == system_id:
                reference = _operation(f"route-{provider}", provider)
                reference.source_refs = [reference.source_refs[0].model_copy(update={"path": "src/main/resources/references.xml"})]
                operations.append(reference)
        manifest = ScanManifest(scan_id=f"scan-{system_id}", system_id=system_id, baseline=baseline, dsf_operations=operations)
        _publish(store, manifest)
        manifests[system_id] = manifest
    return store, manifests


def test_two_independent_bfs_never_reverse_at_shared_upstream(tmp_path: Path) -> None:
    """三层链、侧枝和重复边保持每方向两层边界，不沿共享上游反向展开。

    Args:
        tmp_path: 隔离系统图与扫描根目录。
    """

    # sideways仅能通过共享上游反向到达，应在两个独立方向中都保持不可见。
    edges = [("aaa", "bbb"), ("bbb", "ccc"), ("ccc", "refund"), ("refund", "ddd"), ("ddd", "eee"), ("eee", "fff"), ("ccc", "sideways"), ("ccc", "refund")]
    store, _ = _graph(tmp_path, edges)
    service = SystemRelationService(store, SourceScanArtifactStore(store.root))
    catalog = service.catalog("refund")

    assert {item.system_id: item.depth for item in catalog.upstream} == {"bbb": 2, "ccc": 1}
    assert {item.system_id: item.depth for item in catalog.downstream} == {"ddd": 1, "eee": 2}
    assert service.system_ids("refund") == ["refund", "bbb", "ccc", "ddd", "eee"]
    assert not catalog.gaps
    assert len(catalog.relations) == 4
    assert all(not Path(item.source_ref.path).is_absolute() for relation in catalog.relations for item in relation.evidence)


def test_cycles_and_shortcuts_keep_minimum_depth_and_exclude_self(tmp_path: Path) -> None:
    """环路、自环和长短重复路径不能把自身或第三层重新入队。

    Args:
        tmp_path: 隔离循环关系根目录。
    """

    # refund到beta同时存在一步和两步路径，gamma仍应保留为第二层。
    store, _ = _graph(tmp_path, [("refund", "alpha"), ("alpha", "beta"), ("refund", "beta"), ("beta", "refund"), ("beta", "gamma"), ("gamma", "delta"), ("refund", "refund")])
    catalog = SystemRelationService(store, SourceScanArtifactStore(store.root)).catalog("refund")

    assert {item.system_id: item.depth for item in catalog.downstream} == {"alpha": 1, "beta": 1, "gamma": 2}
    assert {item.system_id: item.depth for item in catalog.upstream} == {"alpha": 2, "beta": 1}
    assert all(relation.source_system_id != relation.target_system_id for relation in catalog.relations)


def test_discovery_shows_unregistered_downstream_once_without_unrelated_gaps(tmp_path: Path) -> None:
    """调用方引用即可展示下游，不把未接入或其他系统缺口变成错误卡。

    Args:
        tmp_path: 隔离扫描与系统注册目录。
    """

    store, manifests = _graph(tmp_path, [("refund", "booking"), ("outside", "remote")])
    caller = manifests["refund"]
    reference = caller.dsf_operations[1]
    caller.dsf_operations.append(reference.model_copy(update={"operation_id": "dsf:booking:api:cancel", "action": "cancel"}))
    _publish(store, caller)
    store.unregister_system("booking")
    service = SystemRelationService(store, SourceScanArtifactStore(store.root))
    catalog = service.discovery_catalog("refund")

    assert len(catalog.external_systems) == 1
    downstream = catalog.external_systems[0]
    assert downstream.gs_name == "dsf.route-booking"
    assert downstream.registered_system_id is None
    assert len(downstream.interfaces) == 2
    assert catalog.gaps == []
    # 展示发现与可读取的已注册系统范围独立，未接入系统不会进入Case执行集合。
    assert service.system_ids("refund") == ["refund"]


@pytest.mark.parametrize("change", ["version", "service_name", "symbol", "drift", "missing", "ambiguity"])
def test_dsf_requires_unique_current_exact_publication(tmp_path: Path, change: str) -> None:
    """坐标、接口身份、当前版本及发布唯一性均参与关系判断。

    Args:
        tmp_path: 隔离扫描存储。
        change: 要制造的不匹配或缺失证据。
    """

    # 起始引用与发布完全匹配，每个参数仅破坏一种关系前提。
    store, manifests = _graph(tmp_path, [("refund-real", "booking-real")])
    provider = manifests["booking-real"]
    if change in {"version", "service_name"}:
        provider.dsf_operations[0] = provider.dsf_operations[0].model_copy(update={change: "different"})
        _publish(store, provider)
    elif change == "symbol":
        provider.dsf_operations[0].source_refs[0].symbol = "wrong.Api#get"
        _publish(store, provider)
    elif change == "drift":
        store.update_source_baseline("booking-real", provider.baseline.model_copy(update={"commit": "new-source"}))
    elif change == "missing":
        SourceScanArtifactStore(store.root)._manifest_path("booking-real", provider.scan_id).unlink()
    else:
        # 相同路由由两个独立注册项目发布，不能按注册名称或列表顺序选一个。
        duplicate_source = tmp_path / "duplicate"
        duplicate_source.mkdir()
        store.register_system(SystemDefinition(system_id="duplicate", name="duplicate", source_path=str(duplicate_source)))
        duplicate = provider.model_copy(deep=True, update={"system_id": "duplicate", "scan_id": "scan-duplicate", "baseline": SourceBaseline(source_path=str(duplicate_source), commit="duplicate")})
        duplicate.dsf_operations[0].provider_system_id = "duplicate"
        _publish(store, duplicate)
    catalog = SystemRelationService(store, SourceScanArtifactStore(store.root)).catalog("refund-real")
    assert not catalog.downstream
    assert not catalog.relations
    assert any(gap.code.startswith("DSF_PROVIDER_") for gap in catalog.gaps)


def test_legacy_binding_is_readable_but_does_not_widen_discovery(tmp_path: Path) -> None:
    """历史关系不再参与范围或被修改，旧调用明确报退役且文件原样保留。

    Args:
        tmp_path: 隔离历史存储目录。
    """

    # 先通过旧存储接口构造历史文件，再验证业务服务不再采纳或改写它。
    store, _ = _graph(tmp_path, [("refund", "booking"), ("outside", "remote")])
    submission = SystemDependencyBindingSubmission(provider_system_id="outside", role=SystemDependencyRole.UPSTREAM, purposes=[SystemDependencyPurpose.SETUP])
    store.put_system_dependency_binding("refund", submission)
    catalog_service = CandidateOperationCatalogService(store, SourceScanArtifactStore(store.root))
    before = catalog_service.dependency_bindings("refund")
    relation_service = SystemRelationService(store, SourceScanArtifactStore(store.root))
    assert relation_service.system_ids("refund") == ["refund", "booking"]
    with pytest.raises(KnowledgeValidationError, match="retired"):
        catalog_service.put_dependency_binding("refund", submission)
    with pytest.raises(KnowledgeValidationError, match="retired"):
        catalog_service.delete_dependency_binding("refund", "outside")
    assert catalog_service.dependency_bindings("refund") == before


@pytest.mark.parametrize("change", ["partial", "pin", "unregistered"])
def test_unavailable_intermediate_never_uses_previous_relations(tmp_path: Path, change: str) -> None:
    """中间系统部分扫描、pin变化或移除后不能沿其历史证据到达第二层。

    Args:
        tmp_path: 隔离链路存储。
        change: 让中间系统证据失效的当前状态变化。
    """

    store, manifests = _graph(tmp_path, [("refund", "middle"), ("middle", "end")])
    manifest = manifests["middle"]
    if change == "partial":
        partial = manifest.model_copy(update={"completeness": ScanCompleteness.PARTIAL, "publication_outcome": ScanPublicationOutcome.PARTIAL_PROJECTION})
        # 模拟磁盘中不完整的latest内容，正常发布API本身已拒绝partial。
        SourceScanArtifactStore(store.root).write_manifest(partial)
    elif change == "pin":
        system = store.get_system("middle")
        commit = "f" * 40
        system.source_version = SourceVersionPin(selected_revision="new-release", commit=commit, managed_tag=f"opentest/baseline/{commit}")
        store.restore_system_definition(system)
    else:
        store.unregister_system("middle")
    catalog = SystemRelationService(store, SourceScanArtifactStore(store.root)).catalog("refund")
    assert not catalog.downstream
    assert any(gap.code in {"SOURCE_SCAN_INCOMPLETE", "SOURCE_SCAN_DRIFT", "DSF_PROVIDER_UNRESOLVED"} for gap in catalog.gaps)


def _mq_source(root: Path, role: str, config: dict[str, str]) -> None:
    """写入真实SOF bean、字段注入和send/consumer模式供生产scanner读取。

    Args:
        root: 生产源码树根目录。
        role: producer或consumer。
        config: 测试环境的非敏感配置值。
    Side Effects:
        写入测试源码和qa filter，不访问MQ服务。
    """

    xml = root / "src/main/resources/mq.xml"
    java = root / "src/main/java/Sender.java"
    xml.parent.mkdir(parents=True)
    java.parent.mkdir(parents=True)
    key = "out" if role == "producer" else "in"
    if role == "producer":
        # 与真实booking项目一致：Producer bean显式引用SOF publisher，Autowired名称匹配。
        body = '<bean id="producer" class="com.ly.sof.api.mq.producer.DefaultProducer"><property name="uniformEventPublisher" ref="uniformEventPublisher"/></bean><sof:publisher id="uniformEventPublisher" nameSrvAddress="${out.cluster}"/>'
        java.write_text('''import com.ly.sof.api.mq.producer.Producer;
class Sender {
    @Autowired private Producer producer;
    @Value("${out.topic}") private String topic;
    @Value("${out.tag}") private String tag;
    /** 按配置路由发送当前测试载荷，供源码扫描确认真实MQ调用。 */
    void send(Object payload) {
        // 发送实参引用配置字段，不能仅因类内存在Topic注解就声称存在该消息流。
        producer.send(topic, tag, payload);
    }
}
''', encoding="utf-8")
    else:
        body = '<sof:consumer id="listener" nameSrvAddress="${in.cluster}"><sof:listener ref="handler"/><sof:channels><sof:channel topic="${in.topic}"><sof:event eventCode="${in.tag}"/></sof:channel></sof:channels></sof:consumer>'
    xml.write_text('<beans xmlns="http://www.springframework.org/schema/beans" xmlns:sof="http://schema.ly.com/schema/sof">' + body + '</beans>', encoding="utf-8")
    (root / "filter.qa").write_text("\n".join(f"{key}.{name}={value}" for name, value in config.items()), encoding="utf-8")


def _mq_store(tmp_path: Path, consumer_config: dict[str, str]) -> tuple[GitKnowledgeStore, dict[str, ScanManifest]]:
    """执行真正资源扫描，冻结源码版本后建立MQ关系测试系统。

    Args:
        tmp_path: 隔离测试根目录。
        consumer_config: 消费者集群、Topic及标签条件。
    Returns:
        可交给实际关系服务的注册存储与生产scanner产物。
    Side Effects:
        只写入测试源码和scan，不调用远端服务。
    """

    store = GitKnowledgeStore(tmp_path / "knowledge")
    manifests: dict[str, ScanManifest] = {}
    for system_id, role, config in [("booking", "producer", {"cluster": "broker-b:9876;broker-a:9876", "topic": "billing-events", "tag": "READY"}), ("refund", "consumer", consumer_config)]:
        source = tmp_path / system_id
        _mq_source(source, role, config)
        store.register_system(SystemDefinition(system_id=system_id, name=system_id, source_path=str(source)))
        resources = SourceResourceDiscoverer().discover(system_id, source).resources
        baseline = GitSourceRepository().capture(source)
        manifest = ScanManifest(scan_id=f"scan-{system_id}", system_id=system_id, baseline=baseline, resources=resources, dsf_profile=DsfClientProfile(system_id=system_id, config_environment="qa"))
        _publish(store, manifest)
        manifests[system_id] = manifest
    return store, manifests


def test_real_mq_scanner_connects_injection_send_and_consumer(tmp_path: Path) -> None:
    """不同配置键但实际集群、Topic及消费标签匹配时形成真实方向关系。

    Args:
        tmp_path: 隔离源码、scanner与关系服务目录。
    """

    # 发送和消费配置键完全不同，只有解析后实际路由相同才可形成关系。
    store, manifests = _mq_store(tmp_path, {"cluster": "broker-a:9876;broker-b:9876", "topic": "billing-events", "tag": "READY || UPDATED"})
    producer = next(item for item in manifests["booking"].resources if item.logical_name == "Sender")
    assert producer.bean_id == "producer"
    assert producer.nameserver_config_key == "out.cluster"
    assert producer.topic_config_key == "out.topic"
    assert producer.tag_config_key == "out.tag"
    service = SystemRelationService(store, SourceScanArtifactStore(store.root))
    assert [(item.system_id, item.depth) for item in service.catalog("booking").downstream] == [("refund", 1)]
    catalog = service.catalog("refund")
    assert [(item.system_id, item.depth) for item in catalog.upstream] == [("booking", 1)]
    assert len(catalog.relations) == 1
    assert catalog.relations[0].relation_type == "MQ"
    assert not catalog.gaps
    assert "broker-a" not in catalog.model_dump_json()
    assert "billing-events" not in catalog.model_dump_json()


@pytest.mark.parametrize("change", ["cluster", "topic", "tag"])
def test_mq_actual_route_mismatch_never_creates_relation(tmp_path: Path, change: str) -> None:
    """相似配置名称不意味着相同运行路由，三类不匹配均排除关系。

    Args:
        tmp_path: 隔离MQ源码。
        change: 消费者要改变的实际路由部分。
    """

    # 每次只改变一项实际配置，确保任一不匹配都足以排除消息关系。
    config = {"cluster": "broker-a:9876;broker-b:9876", "topic": "billing-events", "tag": "READY"}
    config[change] = "unrelated"
    store, _ = _mq_store(tmp_path, config)
    catalog = SystemRelationService(store, SourceScanArtifactStore(store.root)).catalog("refund")
    assert not catalog.relations
    assert not catalog.upstream


@pytest.mark.parametrize("change", ["missing_injection", "wrong_bean", "missing_wrapper", "dynamic_tag", "multi_channel", "source_drift", "sql_filter", "literal_star", "rebound_publisher", "shadowed_producer", "duplicate_bean", "topic_reassigned", "same_keys_mismatch"])
def test_mq_unknown_routes_report_gaps_without_guessing(tmp_path: Path, change: str) -> None:
    """缺失注入、动态标签、多路或源码漂移明确报缺口；固定通配标签可证明。

    Args:
        tmp_path: 隔离MQ扫描。
        change: 受测的真实源码或配置变化。
    """

    config = {"cluster": "broker-a:9876;broker-b:9876", "topic": "billing-events", "tag": "READY"}
    store, manifests = _mq_store(tmp_path, config)
    producer_java = tmp_path / "booking/src/main/java/Sender.java"
    producer_xml = tmp_path / "booking/src/main/resources/mq.xml"
    consumer_xml = tmp_path / "refund/src/main/resources/mq.xml"
    if change == "missing_injection":
        producer_java.write_text(producer_java.read_text().replace("@Autowired ", ""))
    elif change == "wrong_bean":
        producer_java.write_text(producer_java.read_text().replace("@Autowired", '@Autowired @Qualifier("other")'))
    elif change == "missing_wrapper":
        producer_xml.write_text(producer_xml.read_text().replace('ref="uniformEventPublisher"', 'ref="missing"'))
    elif change == "dynamic_tag":
        producer_java.write_text(producer_java.read_text().replace("send(topic, tag,", "send(topic, event.getTag(),"))
    elif change == "rebound_publisher":
        producer_java.write_text(producer_java.read_text().replace("producer.send", "producer.setUniformEventPublisher(other); producer.send"))
    elif change == "shadowed_producer":
        producer_java.write_text(producer_java.read_text().replace("void send(Object payload)", "void send(Object payload, Producer producer)"))
    elif change == "duplicate_bean":
        producer_xml.write_text(producer_xml.read_text().replace("</beans>", '<bean id="producer" class="example.UnknownProducer"/></beans>'))
    elif change == "topic_reassigned":
        producer_java.write_text(producer_java.read_text().replace("producer.send", 'topic = "other"; producer.send'))
    elif change == "same_keys_mismatch":
        consumer_xml.write_text(consumer_xml.read_text().replace("${in.", "${out."))
        (tmp_path / "refund/filter.qa").write_text("out.cluster=other-broker:9876\nout.topic=billing-events\nout.tag=READY\n")
    elif change == "multi_channel":
        consumer_xml.write_text(consumer_xml.read_text().replace("</sof:channels>", '<sof:channel topic="${in.topic}"><sof:event eventCode="*"/></sof:channel></sof:channels>'))
    elif change == "sql_filter":
        (tmp_path / "refund/filter.qa").write_text("in.cluster=broker-a:9876;broker-b:9876\nin.topic=billing-events\nin.tag=amount > 1\n")
    elif change == "literal_star":
        producer_java.write_text(producer_java.read_text().replace("send(topic, tag,", 'send(topic, "*",'))
        consumer_xml.write_text(consumer_xml.read_text().replace("${in.tag}", "*"))
    else:
        (tmp_path / "booking/filter.qa").write_text("out.cluster=changed-after-scan\n")
    # 除漂移用例外都以修改后版本重新扫描，证明失败来自解析而非版本不一致。
    if change != "source_drift":
        for system_id, manifest in manifests.items():
            source = tmp_path / system_id
            manifest.resources = SourceResourceDiscoverer().discover(system_id, source).resources
            manifest.baseline = GitSourceRepository().capture(source)
            _publish(store, manifest)
    catalog = SystemRelationService(store, SourceScanArtifactStore(store.root)).catalog("refund")
    if change == "literal_star":
        assert len(catalog.relations) == 1
        assert not catalog.gaps
    elif change == "same_keys_mismatch":
        # 同一键名不参与匹配；配置完整且确实不同的路由应正常排除，而非解析失败。
        assert not catalog.relations
        assert not catalog.gaps
    else:
        assert not catalog.relations
        assert any(gap.code.startswith("MQ_") for gap in catalog.gaps)
