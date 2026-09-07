"""验证DSF源码资源发现、状态语义与本地持久化脱敏边界。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from opentest.adapters.environment_config import LocalEnvironmentLoader
from opentest.adapters.resource_inventory import ResourceStateStore, SourceResourceDiscoverer
from opentest.application.foundation import OpenTestApplication
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import (
    ResourceBusinessEvidence,
    ResourceKind,
    ResourceProbeRequest,
    ResourceRole,
    ResourceStateRecord,
    ResourceStatus,
    SystemDefinition,
)


def _write_resource_fixture(source_root: Path) -> None:
    """创建覆盖booking.core四类资源声明方式的最小生产源码树。

    Args:
        source_root: 待创建Spring XML和Java源码的项目根目录。

    Side Effects:
        写入四个数据库、Redis、MQ publisher/consumer和Java Producer样例。
    """

    db_xml = source_root / "app/dal/src/main/resources/META-INF/spring/bookingcore-db-beans.xml"
    integration_xml = source_root / "app/integration/src/main/resources/META-INF/spring/bookingcore-integration-beans.xml"
    consumer_xml = source_root / "app/biz/src/main/resources/META-INF/spring/booingcore-biz-jms.xml"
    producer_java = source_root / "app/biz/src/main/java/example/RevokeMessageProducer.java"
    test_xml = source_root / "app/biz/src/test/resources/ignored.xml"
    for path in (db_xml, integration_xml, consumer_xml, producer_java, test_xml):
        path.parent.mkdir(parents=True, exist_ok=True)

    db_xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans">
  <bean id="bookingCoreDatasource" class="com.ly.dal.datasource.RoutableDataSource">
    <property name="env" value="${uniform.env}"/>
    <property name="projectId" value="${uniform.skyCode}"/>
    <property name="dbName" value="TETravelTrainSupplychainOrder"/>
  </bean>
  <bean id="bookingCoreTidbDatasource" class="com.ly.dal.datasource.RoutableDataSource">
    <property name="env" value="${uniform.env}"/>
    <property name="projectId" value="${uniform.skyCode}"/>
    <property name="dbName" value="TETravelTrainSupplychainOrder_tidb"/>
  </bean>
  <bean id="tempOrderDatasource" class="com.ly.dal.datasource.RoutableDataSource">
    <property name="env" value="${uniform.env}"/>
    <property name="projectId" value="${uniform.skyCode}"/>
    <property name="dbName" value="TETravelTrainScTempOrder"/>
  </bean>
  <bean id="bookingCoreTidbAnalyDatasource" class="com.ly.dal.datasource.RoutableDataSource">
    <property name="env" value="${uniform.env}"/>
    <property name="projectId" value="${uniform.skyCode}"/>
    <property name="dbName" value="TETravelTrainSupplychainOrder_tidb_analy"/>
  </bean>
</beans>
""",
        encoding="utf-8",
    )
    integration_xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans" xmlns:sof="http://schema.ly.com/schema/sof">
  <sof:publisher id="uniformEventPublisher" group="${mq.sample.group}" nameSrvAddress="${mq.nameSrvAddress}"/>
  <bean id="redisClient" class="com.ly.flight.chainsaas.refund.integration.tools.redis.RedisClient">
    <property name="groupName" value="${redis.groupName:do-not-persist-default}"/>
  </bean>
  <bean id="redissonProxy" class="com.ly.flight.chainsaas.refund.integration.lock.proxy.RedissonProxy">
    <property name="groupName" value="${redis.groupName:do-not-persist-default}"/>
  </bean>
</beans>
""",
        encoding="utf-8",
    )
    consumer_xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans" xmlns:sof="http://schema.ly.com/schema/sof">
  <sof:consumer id="jobMessageListener" group="${mq.job.group}" nameSrvAddress="${mq.nameSrvAddress}">
    <sof:listener ref="jobListener"/>
    <sof:channels><sof:channel topic="${mq.job.topic}"><sof:event eventCode="*"/></sof:channel></sof:channels>
  </sof:consumer>
  <sof:consumer id="serviceFeeChangeListenerConsumer" group="${mq.servicefee.change.group}">
    <sof:listener ref="serviceFeeChangeListener"/>
    <sof:channels><sof:channel topic="${mq.servicefee.change.topic}">
      <sof:event eventCode="${mq.servicefee.change.tag}"/>
    </sof:channel></sof:channels>
  </sof:consumer>
</beans>
""",
        encoding="utf-8",
    )
    producer_java.write_text(
        """package example;
import org.springframework.beans.factory.annotation.Value;
import com.ly.sof.api.mq.producer.Producer;

public class RevokeMessageProducer {
    private Producer producer;
    @Value("${train.supply.chain.revoke.topic:runtime-default-topic}")
    private String revokeTopic;

    public void publish(Object payload) {
        producer.send(revokeTopic, "*", payload);
    }
}
""",
        encoding="utf-8",
    )
    test_xml.write_text(
        """<beans xmlns="http://www.springframework.org/schema/beans">
<bean id="testDatasource" class="com.ly.dal.datasource.RoutableDataSource">
<property name="dbName" value="MustNotBeDiscovered"/></bean></beans>
""",
        encoding="utf-8",
    )


def _business_evidence(direct_observation: bool = True) -> ResourceBusinessEvidence:
    """构造满足Snapshot绑定要求的测试业务证据。

    Args:
        direct_observation: 是否直接观察到资源交互结果。

    Returns:
        绑定固定Snapshot、Case和Run的领域证据。
    """

    return ResourceBusinessEvidence(
        snapshot_id="snapshot-001",
        case_id="case-create-order",
        run_id="run-001",
        step_ids=["observe-order"],
        assertion_digest="a" * 64,
        direct_observation=direct_observation,
    )


def test_discovers_booking_core_resource_shapes_with_source_evidence(tmp_path: Path) -> None:
    """扫描器应发现四个逻辑DB、Redis Group及MQ生产消费配置键。"""

    source_root = tmp_path / "booking-core"
    _write_resource_fixture(source_root)

    discovery = SourceResourceDiscoverer().discover("train-booking-core", source_root)
    databases = [resource for resource in discovery.resources if resource.role == ResourceRole.DATABASE]
    assert len(databases) == 4
    assert {resource.kind for resource in databases} == {ResourceKind.MYSQL, ResourceKind.TIDB}
    assert {resource.database_name for resource in databases} == {
        "TETravelTrainSupplychainOrder",
        "TETravelTrainSupplychainOrder_tidb",
        "TETravelTrainScTempOrder",
        "TETravelTrainSupplychainOrder_tidb_analy",
    }
    assert {resource.database_project_config_key for resource in databases} == {"uniform.skyCode"}
    assert {resource.database_environment_config_key for resource in databases} == {"uniform.env"}

    redis = next(resource for resource in discovery.resources if resource.kind == ResourceKind.REDIS)
    assert redis.logical_name == "redis.groupName"
    assert redis.config_keys == ["redis.groupName"]
    assert {reference.symbol for reference in redis.source_refs} == {"redisClient", "redissonProxy"}
    assert redis.legacy_resource_ids == [
        "resource:train-booking-core:redis:cache:redisclient",
        "resource:train-booking-core:redis:cache:redissonproxy",
    ]
    assert "do-not-persist-default" not in redis.model_dump_json()

    consumers = [resource for resource in discovery.resources if resource.role == ResourceRole.CONSUMER]
    assert len(consumers) == 2
    job_consumer = next(resource for resource in consumers if resource.logical_name == "jobMessageListener")
    assert job_consumer.listener_ref == "jobListener"
    assert job_consumer.config_keys == ["mq.job.group", "mq.job.topic", "mq.nameSrvAddress"]
    assert job_consumer.nameserver_config_key == "mq.nameSrvAddress"
    assert job_consumer.topic_config_key == "mq.job.topic"
    assert job_consumer.group_config_key == "mq.job.group"
    tagged_consumer = next(
        resource for resource in consumers if resource.logical_name == "serviceFeeChangeListenerConsumer"
    )
    assert tagged_consumer.tag_config_key == "mq.servicefee.change.tag"

    producers = [resource for resource in discovery.resources if resource.role == ResourceRole.PRODUCER]
    producer_keys = {key for resource in producers for key in resource.config_keys}
    assert {"mq.sample.group", "mq.nameSrvAddress", "train.supply.chain.revoke.topic"} <= producer_keys
    assert "runtime-default-topic" not in discovery.model_dump_json()

    # 所有证据都必须保持源码根相对路径并给出可导航的一基行号。
    assert all(not Path(reference.path).is_absolute() for resource in discovery.resources for reference in resource.source_refs)
    assert all(reference.line and reference.line > 0 for resource in discovery.resources for reference in resource.source_refs)
    assert all("src/test" not in reference.path for resource in discovery.resources for reference in resource.source_refs)


@pytest.mark.parametrize(
    ("bean_class", "property_name"),
    [
        ("example.RedissionProxy", "groupName"),
        ("example.CacheClientHA", "cacheName"),
    ],
)
def test_discovers_supported_legacy_redis_initializers(
    tmp_path: Path,
    bean_class: str,
    property_name: str,
) -> None:
    """历史拼写和显式CacheClientHA仍应按配置键形成一个Redis逻辑资源。

    Args:
        tmp_path: Pytest提供的隔离源码目录。
        bean_class: 当前兼容样例使用的受支持初始化类型。
        property_name: 该初始化类型声明逻辑Redis身份的property。

    Side Effects:
        写入一个最小生产XML并执行纯本地静态资源发现。
    """

    source_root = tmp_path / "refund-core"
    xml_path = source_root / "app/integration/src/main/resources/META-INF/spring/redis.xml"
    xml_path.parent.mkdir(parents=True)
    xml_path.write_text(
        f'<beans><bean id="legacyRedis" class="{bean_class}">'
        f'<property name="{property_name}" value="${{redis.legacy}}"/>'
        '</bean></beans>',
        encoding="utf-8",
    )

    discovery = SourceResourceDiscoverer().discover("refund-core", source_root)

    assert len(discovery.resources) == 1
    assert discovery.resources[0].kind == ResourceKind.REDIS
    assert discovery.resources[0].logical_name == "redis.legacy"

@pytest.mark.parametrize("status", list(ResourceStatus))
def test_all_resource_statuses_round_trip(status: ResourceStatus, tmp_path: Path) -> None:
    """六种资源状态均应按领域语义完成脱敏持久化往返。"""

    evidence = None
    if status == ResourceStatus.READY:
        evidence = _business_evidence()
    elif status == ResourceStatus.EFFECT_ONLY:
        evidence = _business_evidence(direct_observation=False)
    error_code = "RESOURCE_UNREACHABLE" if status == ResourceStatus.BLOCKED else ""
    record = ResourceStateRecord(
        resource_id="resource:train-booking-core:mysql:database:orders",
        system_id="train-booking-core",
        status=status,
        error_code=error_code,
        safe_summary="状态可安全展示",
        business_evidence=evidence,
    )

    store = ResourceStateStore(tmp_path / "state")
    saved = store.save(record)
    loaded = store.load(record.system_id, record.resource_id)
    assert loaded == saved
    assert loaded.status == status


def test_readiness_requires_snapshot_case_evidence() -> None:
    """CONNECTED不得冒充READY，效果证据也必须明确没有直接观察MQ轨迹。"""

    with pytest.raises(ValidationError, match="snapshot-bound business evidence"):
        ResourceStateRecord(
            resource_id="resource:train-booking-core:mysql:database:orders",
            system_id="train-booking-core",
            status=ResourceStatus.READY,
        )
    with pytest.raises(ValidationError, match="direct_observation=false"):
        ResourceStateRecord(
            resource_id="resource:train-booking-core:mq:consumer:orders",
            system_id="train-booking-core",
            status=ResourceStatus.EFFECT_ONLY,
            business_evidence=_business_evidence(),
        )


def test_state_store_redacts_connections_credentials_and_sdk_exceptions(tmp_path: Path) -> None:
    """资源状态文件不得出现Host、账号、密码、Token、URI或SDK原始异常类名。"""

    unsafe_values = [
        "jdbc:mysql://qa-db.internal:3306/orders",
        "qa-db.internal:3306",
        "10.20.30.40:6379",
        "booking_user",
        "p@ssword-value",
        "token-value",
        "com.mysql.cj.jdbc.exceptions.CommunicationsException",
    ]
    unsafe_summary = (
        "jdbcUrl=jdbc:mysql://qa-db.internal:3306/orders host=qa-db.internal:3306 "
        "username=booking_user password=p@ssword-value token=token-value "
        "com.mysql.cj.jdbc.exceptions.CommunicationsException at example.Client.connect(Client.java:12)"
    )
    record = ResourceStateRecord(
        resource_id="resource:train-booking-core:mysql:database:orders",
        system_id="train-booking-core",
        status=ResourceStatus.BLOCKED,
        error_code="RESOURCE_UNREACHABLE",
        safe_summary=unsafe_summary,
    )

    store = ResourceStateStore(tmp_path / "state")
    saved = store.save(record)
    disk_text = (tmp_path / "state/train-booking-core/resources.json").read_text(encoding="utf-8")
    assert all(value not in disk_text for value in unsafe_values)
    assert saved.error_code == "RESOURCE_UNREACHABLE"
    assert "***" in saved.safe_summary
    assert "<redacted-error>" in saved.safe_summary


def test_state_store_rejects_unsafe_ids_and_corrupt_files(tmp_path: Path) -> None:
    """状态存储应拒绝路径逃逸标识，并把手工损坏文件报告为领域校验错误。"""

    store = ResourceStateStore(tmp_path / "state")
    with pytest.raises(KnowledgeValidationError, match="system_id"):
        store.list("../outside")
    with pytest.raises(KnowledgeValidationError, match="resource_id"):
        store.load("train-booking-core", "../../secret")

    state_path = tmp_path / "state/train-booking-core/resources.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"schema_version": 1, "system_id": "wrong", "resources": []}), encoding="utf-8")
    with pytest.raises(KnowledgeValidationError, match="invalid resource state file"):
        store.list("train-booking-core")


def test_environment_loader_resolves_only_explicit_unique_alias(tmp_path: Path) -> None:
    """环境选择只能命中规范ID或当前系统唯一声明的显式别名。

    Args:
        tmp_path: Pytest提供的隔离本地环境目录。

    Side Effects:
        写入两份不含真实凭据的本地环境YAML。
    """

    environment_root = tmp_path / "environments"
    system_root = environment_root / "train-booking-core"
    system_root.mkdir(parents=True)
    qa_path = system_root / "qa.yaml"
    qa_path.write_text(
        "system_id: train-booking-core\nenvironment: qa\naliases: [QA1]\nvalues: {region: qa-east}\n",
        encoding="utf-8",
    )
    qa_path.chmod(0o600)
    uat_path = system_root / "uat.yaml"
    uat_path.write_text(
        "system_id: train-booking-core\nenvironment: uat\naliases: [PRE]\n",
        encoding="utf-8",
    )
    uat_path.chmod(0o600)
    loader = LocalEnvironmentLoader(environment_root)

    catalog = loader.list_catalog("train-booking-core")
    resolved = loader.resolve("train-booking-core", "QA1")

    assert [(item.environment, item.aliases) for item in catalog] == [
        ("qa", ["QA1"]),
        ("uat", ["PRE"]),
    ]
    assert resolved.environment == "qa"
    assert resolved.aliases == ["QA1"]
    with pytest.raises(KnowledgeValidationError, match="not configured"):
        loader.resolve("train-booking-core", "qa1")


def test_environment_loader_rejects_ambiguous_alias_without_guessing(tmp_path: Path) -> None:
    """同一系统多个环境声明相同别名时必须要求用户确认规范环境。

    Args:
        tmp_path: Pytest提供的隔离本地环境目录。

    Side Effects:
        写入两份故意使用相同别名的本地环境YAML。
    """

    system_root = tmp_path / "environments/train-booking-core"
    system_root.mkdir(parents=True)
    for environment in ("qa", "uat"):
        path = system_root / f"{environment}.yaml"
        path.write_text(
            "system_id: train-booking-core\n"
            f"environment: {environment}\n"
            "aliases: [QA1]\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
    loader = LocalEnvironmentLoader(tmp_path / "environments")

    with pytest.raises(KnowledgeValidationError, match="ambiguous"):
        loader.resolve("train-booking-core", "QA1")


def test_resource_probe_requires_environment_and_resolves_canonical_or_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """资源探测必须显式选择环境，并在建任务前把唯一alias解析为canonical ID。

    Args:
        tmp_path: Pytest提供的隔离知识、源码和本地环境目录。
        monkeypatch: 将任务提交和资源探测替换为同步离线记录器。

    Returns:
        None；缺环境被模型拒绝，canonical和显式alias均只向资源服务传递``qa``时通过。

    Side Effects:
        写入一份无凭据环境YAML和临时任务目录；不会启动Worker或访问QA。
    """

    with pytest.raises(ValidationError, match="environment"):
        ResourceProbeRequest(system_id="train-booking-core")

    source_root = tmp_path / "source"
    source_root.mkdir()
    application = OpenTestApplication(tmp_path / "knowledge")
    application.store.register_system(
        SystemDefinition(
            system_id="train-booking-core",
            name="火车票预订",
            source_path=str(source_root),
        )
    )
    environment_path = (
        application.knowledge_root
        / ".opentest/environments/train-booking-core/qa.yaml"
    )
    environment_path.parent.mkdir(parents=True)
    environment_path.write_text(
        "system_id: train-booking-core\nenvironment: qa\naliases: [QA1]\n",
        encoding="utf-8",
    )
    environment_path.chmod(0o600)
    observed_environments: list[str] = []
    submitted_jobs: list[dict[str, object]] = []
    submitted_task = object()

    def probe_without_worker(
        system_id: str,
        environment: str,
        resource_ids: list[str],
    ) -> list[ResourceStateRecord]:
        """记录资源服务收到的规范环境并返回空安全状态集。

        Args:
            system_id: 探测所属注册系统。
            environment: Foundation已经解析的规范环境。
            resource_ids: 用户选择的可选资源范围。

        Returns:
            空状态集，避免离线测试启动真实Worker。
        """

        assert system_id == "train-booking-core"
        assert resource_ids == []
        observed_environments.append(environment)
        return []

    def submit_inline(
        operation: str,
        system_id: str,
        job,
        exclusive: bool = False,
    ):
        """同步执行资源任务闭包以观察其参数而不启动线程池工作流。

        Args:
            operation: Foundation声明的任务类型。
            system_id: 任务归属系统。
            job: 已冻结canonical环境的资源探测闭包。
            exclusive: 是否要求排他任务门禁。

        Returns:
            用于确认两次提交均返回原任务管理器结果的测试哨兵。

        Side Effects:
            当前测试线程内执行闭包并保存其安全摘要。
        """

        assert operation == "resource-probe"
        assert system_id == "train-booking-core"
        assert exclusive is True
        submitted_jobs.append(job())
        return submitted_task

    monkeypatch.setattr(application.resources, "probe", probe_without_worker)
    monkeypatch.setattr(application.tasks, "submit", submit_inline)
    try:
        alias_task = application.submit_resource_probe(
            ResourceProbeRequest(system_id="train-booking-core", environment="QA1")
        )
        canonical_task = application.submit_resource_probe(
            ResourceProbeRequest(system_id="train-booking-core", environment="qa")
        )
        with pytest.raises(KnowledgeValidationError, match="not configured"):
            application.submit_resource_probe(
                ResourceProbeRequest(system_id="train-booking-core", environment="QA2")
            )

        assert alias_task is submitted_task
        assert canonical_task is submitted_task
        assert observed_environments == ["qa", "qa"]
        assert submitted_jobs == [
            {"resource_count": 0, "states": []},
            {"resource_count": 0, "states": []},
        ]
    finally:
        application.close()
