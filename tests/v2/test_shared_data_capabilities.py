"""使用真实本地存储、任务、编译器与Operation边界验收共享数据链路。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.adapters.case_template_v4_store import (
    CaseGenerationExecutionStoreV4, CaseTemplateGenerationStoreV4, CaseTemplateHandoffStoreV4,
)
from opentest.adapters.data_capability_store import DataCapabilityStore
from opentest.adapters.environment_config import LocalEnvironmentLoader, LocalSystemSettingsStore
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.operation_execution_store import OperationExecutionStore
from opentest.adapters.source_analysis import GitSourceRepository, SourceScanArtifactStore
from opentest.application.case_template_executor_v4 import CaseTemplateExecutorV4
from opentest.application.case_template_v4 import CaseTemplateV4RuntimeServices, CaseTemplateV4Service
from opentest.application.data_capabilities import DataCapabilityService
from opentest.application.dsf_operations import DsfOperationService
from opentest.application.operations import LocalQaOperationProvider, OperationExecutionService
from opentest.application.tasks import LocalTaskManager
from opentest.domain.case_template_v4 import (
    CaseGenerationExecutionRequestV4, CaseTemplateGenerationV4, CaseTemplateHandoffV4,
    CaseTemplateSubmission, CaseVariantV4, SharedDataSource,
)
from opentest.domain.data_capabilities import DataCapabilityDefinition, DataCapabilityPrepareRequest, DataExecutionRequest
from opentest.domain.errors import KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import (
    OperationCapability, OperationInputKnowledgeContract, OperationKind, OperationMutability,
    DsfOperationDefinition, DsfOperationMutability, SourceReference,
    ScanManifest, SystemDefinition, SystemDependencyBindingSubmission, SystemDependencyRole,
)

PROVIDER = 'ifightchainsaas.java.account.supplement.core'
CONSUMER = 'ifightchainsaas.java.refund.core'
FACADE = 'facade:com.ly.flight.chainsaas.account.supplement.core.facade.ReportFacade#'
TARGET = 'facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#billSupplement'
FIXTURE = Path(__file__).parents[1] / 'fixtures/data-capabilities/refund-supplement-report.json'


@pytest.fixture
def shared_scope(tmp_path: Path):
    """组装无知识节点的两个系统，只有远程业务调用使用有状态替身。

    Args:
        tmp_path: pytest隔离根。
    Yields:
        真实服务与可控制的模拟QA状态；测试结束关闭线程池。
    """

    store = GitKnowledgeStore(tmp_path / 'knowledge')
    store.initialize()
    artifacts = SourceScanArtifactStore(store.root)
    for system in (PROVIDER, CONSUMER):
        root = tmp_path / system
        root.mkdir()
        (root / 'ReportFacade.java').write_text('interface ReportFacade {\n void queryReportByUniqueKey();\n}\n')
        store.register_system(SystemDefinition(system_id=system, name=system, source_path=str(root)))
        manifest = ScanManifest(system_id=system, scan_id='scan-source-a', baseline=GitSourceRepository().capture(root),
            dsf_operations=[DsfOperationDefinition(operation_id='dsf:report.query', provider_system_id=PROVIDER,
                gs_name='dsf.supplement', service_name='report', version='1', action='query',
                mutability=DsfOperationMutability.READ_ONLY,
                source_refs=[SourceReference(path='ReportFacade.java', symbol='example.ReportFacade#query', line=1)])])
        artifacts.write_manifest(manifest)
        artifacts.publish_latest(system, manifest.scan_id)
        store.update_source_baseline(system, manifest.baseline)
    inputs = {'type':'object','properties':{'ownerId':{'type':'string'},'ticketNo':{'type':'string'}},
              'required':['ownerId','ticketNo'],'additionalProperties':False}
    report = {'type':'object','properties':{'id':{'type':'integer'},'ownerId':{'type':'string'},
              'ticketNo':{'type':'string'},'ext':{'type':'string'},'isSaveDb':{'type':'boolean'}},'additionalProperties':False}
    output = {'type':'object','properties':{'report':report},'additionalProperties':False}
    capabilities = [OperationCapability(
        operation_id=FACADE+name, system_id=PROVIDER, business_name=name, kind=OperationKind.FACADE,
        mutability=mutability, input_schema=inputs, source_scan_id='scan-source-a', executable=True,
        publication_output_schema={'type':'object','properties':{'output':output}},
    ) for name, mutability in [('queryReportByUniqueKey',OperationMutability.READ_ONLY),('saveReport',OperationMutability.WRITE)]]
    capabilities.append(OperationCapability(operation_id=TARGET, system_id=CONSUMER, business_name='退票补单',
        kind=OperationKind.FACADE, mutability=OperationMutability.WRITE, source_scan_id='scan-source-a', executable=True,
        input_schema={'type':'object','properties':{'id':{'type':'integer'}},'required':['id'],'additionalProperties':False}))
    # 跨项目范围由双方扫描坐标证明，完整链路不创建任何人工关系或授权文件。
    catalog = Mock(store=store)
    catalog.derive.side_effect = lambda system, scan, include_registered=False, resolved_operations=None: [item for item in capabilities if item.system_id == system]
    provider = Mock()
    state = {'report': {'id':101,'ownerId':'unit-owner','ticketNo':'unit-ticket','ext':'{"transactionType":3}','isSaveDb':False},
             'calls': [], 'wrong_create':False, 'target_status':'PROCESSING'}

    def invoke(capability, request):
        """模拟固定QA系统接口，保留调用顺序与真实参数供断言。

        Args:
            capability: 服务端固定操作。
            request: 实际环境和参数。
        Returns:
            不访问任何真实QA的确定响应。
        """

        state['calls'].append((capability.operation_id, request.arguments, request.environment))
        if capability.operation_id == FACADE+'saveReport':
            state['report'] = {'id':102,'ownerId':'wrong-owner' if state['wrong_create'] else request.arguments['ownerId'],
                               'ticketNo':request.arguments['ticketNo'],'ext':'{"transactionType":3}','isSaveDb':False}
            return {'success': True}
        if capability.operation_id == TARGET:
            return {'success': True, 'supplementStatus': state['target_status'], 'supplementId':request.arguments['id']}
        return {'report':deepcopy(state['report'])}

    provider.execute_facade.side_effect = invoke
    operations = OperationExecutionService(catalog, Mock(), OperationExecutionStore(tmp_path / 'operations'), Mock(), provider)
    tasks = LocalTaskManager(tmp_path / 'tasks')
    cases = CaseTemplateV4Service(store, artifacts, CaseTemplateGenerationStoreV4(store),
        CaseTemplateHandoffStoreV4(store.root), CaseTemplateV4RuntimeServices(catalog, operations, lambda _: {'env':'qa'}, tasks))
    service = DataCapabilityService(store, artifacts, cases, tasks)
    cases.data_capabilities = service
    yield SimpleNamespace(service=service, cases=cases, store=store, tasks=tasks, state=state, capabilities=capabilities, provider=provider)
    tasks._executor.shutdown(wait=True)


def _publish(scope: SimpleNamespace, request_id: str = 'unit-prepare-one'):
    """经真实任务源码读取、草稿校验与发布工具保存一个共享版本。

    Args:
        scope: 当前真实服务范围。
        request_id: 新任务幂等身份。
    Returns:
        已发布共享版本。
    """

    task = scope.service.prepare(PROVIDER, DataCapabilityPrepareRequest(goal='准备退票补单分销报表',request_id=request_id, execution_mode='generate_only'))
    scope.service.call_agent_tool(task.task_id,'read_source',{'source_system_id':PROVIDER,'path':'ReportFacade.java'})
    definition = json.loads(FIXTURE.read_text())
    response = scope.service.call_agent_tool(task.task_id,'save_data_draft',{'expected_revision':0,'definition':definition})
    assert response['validation_issues'] == []
    scope.service.call_agent_tool(task.task_id,'publish_data_capability',{'expected_revision':1})
    return scope.service.get_version(PROVIDER, definition['capability_id'], 1 if request_id == 'unit-prepare-one' else 2)


def _request(request_id: str = 'unit-execution-one', allow_writes: bool = False) -> DataExecutionRequest:
    """构造只有运行时存在的用户条件，不把任何报表ID写入定义。

    Args:
        request_id: 本次执行幂等身份。
        allow_writes: 用户本次明确授予的创建权限。
    Returns:
        固定版本和consumer环境的执行请求。
    """

    return DataExecutionRequest(version=1, owner_system_id=PROVIDER, environment_id='qa',
                                inputs={'owner_id':'unit-owner','ticket_no':'unit-ticket'},
                                request_id=request_id, allow_writes=allow_writes)


def test_publish_reuse_and_execution_replay(shared_scope: SimpleNamespace) -> None:
    """同一数据定义供独立自然语言任务复用；响应重试不重复执行。

    Args:
        shared_scope: 双系统实际服务和模拟QA。
    """

    version = _publish(shared_scope)
    assert not shared_scope.state['calls']  # 生成只产出定义，任何QA必须显式执行。
    execution = shared_scope.service.execute(CONSUMER,version.capability_id,_request())
    assert execution.status == 'COMPLETED', execution.error
    assert execution.outputs['report_id'] == 101
    assert execution.step_results[0].environment_id == 'qa'
    assert execution.step_results[0].source_scan_id == 'scan-source-a'
    assert all(check.passed for check in execution.checks)
    replay = shared_scope.service.execute(CONSUMER,version.capability_id,_request())
    assert replay.execution_id == execution.execution_id
    assert len(shared_scope.state['calls']) == 1
    with pytest.raises(KnowledgeValidationError,match='不同数据执行参数'):
        shared_scope.service.execute(CONSUMER,version.capability_id,_request().model_copy(update={'inputs':{'owner_id':'other'}}))
    assert shared_scope.store.list_nodes(PROVIDER) == []


def test_legacy_shared_version_executes_only_its_frozen_calls_without_rewriting_asset(shared_scope: SimpleNamespace, monkeypatch) -> None:
    """旧独立数据版本无选择字段时恢复固定调用，执行成功且不读取新契约或改写资产。

    Args:
        shared_scope: 真实数据发布、执行服务及状态化QA替身。
        monkeypatch: 记录实际交给执行器的范围并禁止额外契约分析。
    """

    version = _publish(shared_scope)
    path = shared_scope.store.system_root(PROVIDER) / 'data-capabilities' / version.capability_id / '1.json'
    legacy = json.loads(path.read_text())
    for scope in legacy['source_scopes']:
        for key in ('selected_operation_ids', 'selection_reasons', 'contract_revisions'):
            scope.pop(key, None)
    # 模拟升级前已发布资产的真实JSON形状，不通过新版本构造流程掩盖兼容边界。
    path.write_text(json.dumps(legacy, ensure_ascii=False))
    frozen_bytes = path.read_bytes()
    shared_scope.capabilities.append(shared_scope.capabilities[0].model_copy(update={'operation_id': FACADE + 'unrelated'}))
    selected_scopes = Mock(wraps=shared_scope.cases._runtime_capabilities)
    monkeypatch.setattr(shared_scope.cases, '_runtime_capabilities', selected_scopes)
    monkeypatch.setattr(shared_scope.cases.operation_contracts, 'get_contract', Mock(side_effect=AssertionError('已发布版本不可读取新契约')))
    shared_scope.cases.runtime.operation_catalog.derive.reset_mock()
    execution = shared_scope.service.execute(CONSUMER, version.capability_id, _request('legacy-shared-execution'))
    assert execution.status == 'COMPLETED', execution.error
    assert execution.outputs['report_id'] == 101
    assert [call[0] for call in shared_scope.state['calls']] == [FACADE + 'queryReportByUniqueKey']
    for call in selected_scopes.call_args_list:
        scope = next(item for item in call.args[0].source_scopes if item.source_system_id == PROVIDER)
        assert set(scope.selected_operation_ids) == {FACADE + 'queryReportByUniqueKey', FACADE + 'saveReport'}
        assert scope.source_scan_id == 'scan-source-a'
    assert all(call.args[1] == 'scan-source-a' for call in shared_scope.cases.runtime.operation_catalog.derive.call_args_list)
    assert path.read_bytes() == frozen_bytes
    assert shared_scope.service.records.get(PROVIDER, version.capability_id, 1).source_scopes[0].selected_operation_ids == []


@pytest.mark.parametrize('allow_writes,wrong_create,expected',[(False,False,'FAILED'),(True,False,'COMPLETED'),(True,True,'FAILED')])
def test_no_match_creates_only_when_authorized_and_rechecks(shared_scope: SimpleNamespace, allow_writes: bool,
                                                           wrong_create: bool, expected: str) -> None:
    """查询无匹配时需本次写权限；创建成功返回也必须重新验证所属主体。

    Args:
        shared_scope: 实际服务范围。
        allow_writes: 本次是否授权创建。
        wrong_create: 模拟saveReport复用错误所属的已有记录。
        expected: 完整验证后的业务状态。
    """

    version = _publish(shared_scope)
    shared_scope.state.update(report=None, wrong_create=wrong_create)
    execution = shared_scope.service.execute(CONSUMER,version.capability_id,_request(allow_writes=allow_writes))
    assert execution.status == expected, execution.error
    calls = [item[0] for item in shared_scope.state['calls']]
    assert calls == ([FACADE+'queryReportByUniqueKey',FACADE+'saveReport',FACADE+'queryReportByUniqueKey']
                     if allow_writes else [FACADE+'queryReportByUniqueKey'])
    if expected == 'FAILED':
        assert execution.outputs == {}
        assert execution.failure_kind == 'DATA_PREPARATION_FAILED'


def test_input_conditions_cannot_be_treated_as_observed_facts(shared_scope: SimpleNamespace) -> None:
    """缺少用户条件比较和仅输入自证的定义不能发布。

    Args:
        shared_scope: 实际服务范围。
    """

    task = shared_scope.service.prepare(PROVIDER,DataCapabilityPrepareRequest(goal='验证输入事实边界'))
    shared_scope.service.call_agent_tool(task.task_id,'read_source',{'source_system_id':PROVIDER,'path':'ReportFacade.java'})
    definition = json.loads(FIXTURE.read_text())
    predicate = definition['verify_steps'][0]['predicates'][0]
    predicate['left'] = predicate['right']
    response = shared_scope.service.call_agent_tool(task.task_id,'save_data_draft',{'expected_revision':0,'definition':definition})
    assert 'CHECK_REQUIRES_OBSERVATION' in {issue['code'] for issue in response['validation_issues']}
    with pytest.raises(KnowledgeValidationError,match='校验未通过'):
        shared_scope.service.call_agent_tool(task.task_id,'publish_data_capability',{'expected_revision':1})
    with pytest.raises(ScopeViolationError):
        shared_scope.service.call_agent_tool(task.task_id,'execute_data_capability',{})
    assert not shared_scope.state['calls']


def _generation(version, ordinal: int = 1) -> CaseTemplateGenerationV4:
    """把所选共享版本完整内嵌进既有Generation，不新增基线资产。

    Args:
        version: 已发布共享定义。
        ordinal: 独立Case身份序号。
    Returns:
        目标补单仅接受动态report_id、预期固定为PROCESSING的Generation。
    """

    source = SharedDataSource(owner_system_id=version.owner_system_id,capability_id=version.capability_id,version=version.version)
    template = {'template_id':'refund_supplement','title':'分销报表退票补单','coverage_kind':'business',
                'data_calls':[{'call_id':'report_data','function_name':version.capability_id,
                               'arguments':{'owner_id':{'kind':'literal','value':'unit-owner'},'ticket_no':{'kind':'literal','value':'unit-ticket'}}}],
                'request_bindings':[{'field':'id','source':{'kind':'data_output','call_id':'report_data','output_name':'report_id'}}],
                'combination':'each','oracles':[{'oracle_id':'supplement_response','channel':'response','assertions':[
                    {'actual_path':'supplementStatus','operator':'eq','expected':{'kind':'literal','value':'PROCESSING'}},
                    {'actual_path':'supplementId','operator':'eq','expected':{'kind':'request_field','path':'id'}}]}],
                'evidence':version.evidence}
    submission = CaseTemplateSubmission(data_functions=[version.as_function(source)],case_templates=[template],unresolved=[])
    template = submission.case_templates[0]
    return CaseTemplateGenerationV4(generation_id='case-template-generation-'+f'{ordinal:020x}',system_id=CONSUMER,
        operation_id=TARGET,source_scan_id='scan-source-a',coverage_id='coverage:supplement',runtime_registry_version='runtime-functions/v1',
        value_registry_version='value-functions/v1',status='READY',input_contract=OperationInputKnowledgeContract(
            target_id=TARGET,source_scan_id='scan-source-a',status='READY',request_schema={'type':'object','properties':{'id':{'type':'integer'}}},fields=[{'path':'id','field_name':'id','schema':{'type':'integer'},'business_identity':True}]),
        submission=submission,variants=[CaseVariantV4(variant_id='case-variant-v4-'+f'{ordinal:020x}',template_id=template.template_id,ordinal=1,
            parameter_values={},request_values={},data_calls=template.data_calls,oracles=template.oracles)])


def test_two_cases_and_natural_task_share_version_without_baseline_change(shared_scope: SimpleNamespace) -> None:
    """两个Case与自然任务共用方法；发布v2及新代码行为不会改变G1预期和数据步骤。

    Args:
        shared_scope: 双系统服务与可改变行为的QA替身。
    """

    version = _publish(shared_scope)
    first, second = _generation(version), _generation(version,2)
    frozen = first.model_dump(mode='json')
    newer = _publish(shared_scope,'unit-prepare-two')
    assert newer.version == 2
    handoff = SimpleNamespace(task_id='case-validation-task',system_id=CONSUMER, source_scopes=version.source_scopes)
    registry = shared_scope.service._registry(handoff)
    executor = CaseTemplateExecutorV4(shared_scope.cases.runtime.operation_service,consumer_system_id=CONSUMER,
                                      capabilities=shared_scope.capabilities,data_store=shared_scope.service.records)
    for index,generation in enumerate([first,second],1):
        execution = executor.execute('case-generation-execution-'+f'{index:020x}',generation,registry)
        assert execution[0].status == 'COMPLETED', execution[0].error
        assert execution[0].data_execution_ids
        assert execution[0].operations[-1].actual_request == {'id':101}
        assert all(item.phase != 'CLEANUP' for item in execution[0].operations)
    natural = shared_scope.service.execute(CONSUMER,version.capability_id,_request())
    assert natural.capability_version == 1 and natural.outputs['report_id'] == 101
    shared_scope.state['target_status'] = 'CHANGED'
    difference = executor.execute('case-generation-execution-'+'3'*20,first,registry)[0]
    assert difference.failure_kind == 'BEHAVIOR_DIFF'
    assert first.model_dump(mode='json') == frozen
    # 同一个G1持有完整版本1定义，版本2发布不会影响其数据准备或固定预期。
    assert first.submission.data_functions[0].shared_source.version == 1
    shared_scope.state['report']['ownerId'] = 'another-owner'
    before = len(shared_scope.state['calls'])
    blocked = executor.execute('case-generation-execution-'+'4'*20,first,registry)[0]
    assert blocked.failure_kind == 'DATA_PREPARATION_FAILED'
    assert all(call[0] != TARGET for call in shared_scope.state['calls'][before:])


def test_same_fixed_generation_runs_twice_with_shared_data_request_index(shared_scope: SimpleNamespace, tmp_path: Path) -> None:
    """同一固定Case的两次回归拥有各自数据请求，真实唯一索引不能阻断第二次执行。"""

    from tests.v2.test_mysql_metadata import shared_workspace_pair

    version = _publish(shared_scope)
    generation = _generation(version)
    frozen = generation.model_dump(mode='json')
    handoff = SimpleNamespace(task_id='case-validation-task', system_id=CONSUMER, source_scopes=version.source_scopes)
    registry = shared_scope.service._registry(handoff)
    shared, _ = shared_workspace_pair(tmp_path)
    data_store = DataCapabilityStore(shared)
    executor = CaseTemplateExecutorV4(shared_scope.cases.runtime.operation_service, consumer_system_id=CONSUMER,
                                     capabilities=shared_scope.capabilities, data_store=data_store)
    execution_ids = []
    # 两次使用相同Generation与Variant；只有本次执行身份变化，SQL约束仍为生产唯一索引。
    for ordinal in (1, 2):
        outcome = executor.execute('case-generation-execution-' + f'{ordinal:020x}', generation, registry)[0]
        assert outcome.status == 'COMPLETED', outcome.error
        execution_ids.extend(outcome.data_execution_ids)
    records = [data_store.get_execution(CONSUMER, identity) for identity in execution_ids]
    assert len({record.request_id for record in records}) == 2
    assert all(record.outputs['report_id'] == 101 for record in records)
    assert generation.model_dump(mode='json') == frozen


def test_missing_provider_profile_preserves_case_failure_report_and_baseline(
    shared_scope: SimpleNamespace, tmp_path: Path,
) -> None:
    """补单QA配置缺失形成可读持久报告，保留原编译阻塞且不改写G1。

    Args:
        shared_scope: 已接入双系统、真实共享定义和Case存储。
        tmp_path: Profile与执行历史使用的隔离目录。
    Returns:
        None；实际Executor保存环境失败、零业务派发且原Generation不变时通过。
    """

    version = _publish(shared_scope)
    generation = _generation(version)
    generation.handoff_id = 'case-template-handoff-' + 'b' * 20
    generation.status = 'PARTIAL'
    generation.variants.append(generation.variants[0].model_copy(update={
        'variant_id': 'case-variant-v4-' + 'b' * 20, 'ordinal': 2,
        'blocked_reason': '编译时未确认金额约束',
    }))
    handoff = CaseTemplateHandoffV4(
        handoff_id=generation.handoff_id, system_id=CONSUMER, entry_id=TARGET,
        source_scan_id=generation.source_scan_id, status='PARTIAL',
        source_scopes=[*shared_scope.cases._source_scopes(CONSUMER, 'scan-source-a', TARGET),
                       *version.source_scopes], generation_id=generation.generation_id,
    )
    shared_scope.cases.handoffs.write(handoff)
    shared_scope.cases.generations.write(generation)
    generation_path = shared_scope.store.system_root(CONSUMER) / 'cases/v4/generations' / f'{generation.generation_id}.json'
    frozen_generation = generation_path.read_bytes()

    # 只配置退票QA；补单虽已注册并存在固定操作，其运行配置缺口仍须在任何调用前发现。
    settings = LocalSystemSettingsStore(tmp_path / 'environments')
    settings.write(CONSUMER, '', resource_config_environment='test', environment='qa')
    dsf_worker = Mock()
    dsf = DsfOperationService(shared_scope.store, shared_scope.cases.artifacts, Mock(), Mock(), dsf_worker)
    operations = shared_scope.cases.runtime.operation_service
    operations.provider = LocalQaOperationProvider(dsf, shared_scope.cases.artifacts, LocalEnvironmentLoader(settings.environment_root))
    executions = CaseGenerationExecutionStoreV4(tmp_path / 'case-executions')
    cases = CaseTemplateV4Service(
        shared_scope.store, shared_scope.cases.artifacts, shared_scope.cases.generations,
        shared_scope.cases.handoffs, CaseTemplateV4RuntimeServices(
            shared_scope.cases.runtime.operation_catalog, operations,
            shared_scope.cases.runtime.environment_provider, shared_scope.tasks, executions,
        ),
    )
    cases.data_capabilities = shared_scope.service
    completed = cases.execute_generation(CONSUMER, generation.generation_id, CaseGenerationExecutionRequestV4(environment_id='qa'))

    # 从执行历史重新读取，确保不是只返回内存错误或把缺口缩成异常类型。
    persisted = executions.get(CONSUMER, completed.execution_id)
    assert persisted.status == 'FAILED'
    assert len(persisted.variant_results) == 2
    failed, blocked = persisted.variant_results
    assert failed.status == 'FAILED'
    assert failed.failure_kind == 'ENVIRONMENT_DEPENDENCY'
    assert f'{PROVIDER}: qa' in failed.error
    assert not failed.operations and not failed.data_execution_ids
    assert blocked.status == 'BLOCKED'
    assert blocked.error == '编译时未确认金额约束'
    assert blocked.failure_kind == ''
    assert not blocked.operations
    dsf_worker.execute.assert_not_called()
    shared_scope.provider.execute_facade.assert_not_called()
    assert shared_scope.state['calls'] == []
    assert generation_path.read_bytes() == frozen_generation


def test_shared_definition_can_compile_in_case_and_cannot_be_forged(shared_scope: SimpleNamespace) -> None:
    """Case编译接受已验证共享方法的用户条件，但拒绝伪造来源标签或更改步骤。

    Args:
        shared_scope: 使用真实存储和编译器的服务。
    """

    from opentest.domain.case_template_v4 import CaseTemplateCompilationInput
    version = _publish(shared_scope)
    generation = _generation(version)
    handoff = CaseTemplateHandoffV4(handoff_id='case-template-handoff-' + 'd' * 20,
        system_id=CONSUMER, entry_id=TARGET, source_scan_id='scan-source-a', status='WAITING_FOR_AGENT',
        source_scopes=shared_scope.cases._source_scopes(CONSUMER, 'scan-source-a', TARGET))
    # Case选择共享版本后只导入函数实际调用的精确接口，不再默认开放provider全目录。
    handoff = shared_scope.service.select_case_function_scopes(handoff, generation.submission)
    provider_scope = next(scope for scope in handoff.source_scopes if scope.source_system_id == PROVIDER)
    assert set(provider_scope.selected_operation_ids) == {FACADE + 'queryReportByUniqueKey', FACADE + 'saveReport'}
    ranges = shared_scope.service.validate_case_functions(handoff,generation.submission,{})
    assert ranges[PROVIDER]['ReportFacade.java'] == [(2,2)]
    registry = shared_scope.service._registry(handoff)
    compilation = CaseTemplateCompilationInput(submission=generation.submission,input_contract=generation.input_contract,
        target_output_schema={'type':'object','properties':{'supplementStatus':{'type':'string'},'supplementId':{'type':'integer'}}},
        runtime_registry=registry,value_registry=shared_scope.cases.registries.value_registry(),allowed_system_ids={PROVIDER,CONSUMER})
    variants, issues = shared_scope.cases.compiler.compile(compilation)
    assert issues == []
    assert len(variants) == 1
    changed = generation.submission.model_copy(deep=True)
    changed.data_functions[0].verify_steps[-1].predicates[0].right.value = True
    with pytest.raises(KnowledgeValidationError,match='内嵌共享定义'):
        shared_scope.service.validate_case_functions(handoff,changed,{})


def test_legacy_generation_recovers_only_frozen_runtime_and_observer_references(shared_scope: SimpleNamespace) -> None:
    """旧Generation空选择列表按固定DSL恢复数据和观察接口，不改资产或开放其他接口。

    Args:
        shared_scope: 两个系统的固定扫描及真实Case目录服务。
    """

    from opentest.domain.case_template_v4 import CaseOracle
    version = _publish(shared_scope)
    generation = _generation(version)
    observer_id, unrelated_id = FACADE + 'observeReport', FACADE + 'unrelated'
    shared_scope.capabilities.extend(shared_scope.capabilities[0].model_copy(update={'operation_id': identity})
                                     for identity in (observer_id, unrelated_id))
    oracle = CaseOracle(oracle_id='observed_report', channel='operation', function_id=observer_id,
        assertions=[{'actual_path':'report.id','operator':'eq','expected':{'kind':'literal','value':101}}])
    generation.submission.case_templates[0].oracles.append(oracle)
    generation.variants[0].oracles.append(oracle)
    generation.source_scopes = [scope.model_copy(update={'selected_operation_ids': [], 'selection_reasons': {}, 'contract_revisions': {}})
        for scope in [*shared_scope.cases._source_scopes(CONSUMER, 'scan-source-a', TARGET), *version.source_scopes]]
    handoff = CaseTemplateHandoffV4(handoff_id='case-template-handoff-' + 'e' * 20,
        system_id=CONSUMER, entry_id=TARGET, source_scan_id='scan-source-a', status='COMPLETED',
        source_scopes=generation.source_scopes, generation_id=generation.generation_id)
    frozen_generation = generation.model_dump(mode='json')
    frozen_handoff = handoff.model_dump(mode='json')
    registry = shared_scope.cases._runtime_registry_for_execution(handoff, generation)
    function_ids = {function.function_id for function in registry.functions}
    assert {FACADE + 'queryReportByUniqueKey', FACADE + 'saveReport', observer_id} <= function_ids
    assert unrelated_id not in function_ids
    assert generation.model_dump(mode='json') == frozen_generation
    assert handoff.model_dump(mode='json') == frozen_handoff


def test_data_new_provider_requires_explicit_unmet_input_and_keeps_selected_scope(shared_scope: SimpleNamespace, monkeypatch) -> None:
    """数据任务逐跳追溯需明确缺口和用途，只增加当前选中接口。

    Args:
        shared_scope: 注册的consumer/provider服务。
        monkeypatch: 隔离关系解析，验证工具入参和冻结行为。
    """

    from opentest.application.system_relations import SystemRelationService
    task = shared_scope.service.prepare(CONSUMER, DataCapabilityPrepareRequest(goal='准备补单输入', operation_id=TARGET))
    selected = shared_scope.capabilities[0]
    received_systems = []
    def resolve(scopes, operation_id):
        """记录选择发生时的冻结来源，并返回已确认的精确provider接口。"""

        received_systems.append({scope.source_system_id for scope in scopes})
        return selected
    resolver = Mock(side_effect=resolve)
    monkeypatch.setattr(SystemRelationService, 'resolve_from_scopes', resolver)
    arguments = {'source_system_id': PROVIDER, 'operation_id': selected.operation_id}
    with pytest.raises(KnowledgeValidationError, match='unmet_input_path和purpose'):
        shared_scope.service.call_agent_tool(task.task_id, 'read_contract', arguments)
    resolver.assert_not_called()
    response = shared_scope.service.call_agent_tool(task.task_id, 'read_contract', {
        **arguments, 'unmet_input_path': 'request.id', 'purpose': '查询并验证当前票对应报表'})
    handoff = shared_scope.service.records.get_handoff(task.task_id)
    provider_scope = next(scope for scope in handoff.source_scopes if scope.source_system_id == PROVIDER)
    assert provider_scope.selected_operation_ids == [selected.operation_id]
    assert provider_scope.source_scan_id == 'scan-source-a'
    assert provider_scope.contract_revisions[selected.operation_id] == response['contract']['contract_revision']
    assert received_systems == [{CONSUMER}]


def test_interrupted_data_execution_is_not_replayed(shared_scope: SimpleNamespace) -> None:
    """进程已中断的运行保留步骤并报告未知完成状态，同request重试不造数。

    Args:
        shared_scope: 具有真实任务所有权和执行存储的服务。
    """

    from opentest.domain.models import TaskStatus, utc_now
    version = _publish(shared_scope)
    execution = shared_scope.service.execute(CONSUMER,version.capability_id,_request())
    # 模拟退出发生在远端完成后、本地终态写入前的边界，不重新发起接口调用。
    shared_scope.service.records.save_execution(execution.model_copy(update={'status':'RUNNING','completed_at':None}))
    task = shared_scope.tasks.get(execution.task_id)
    shared_scope.tasks.save_business_record(task.model_copy(update={'status':TaskStatus.INTERRUPTED,'ended_at':utc_now()}))
    recovered = shared_scope.service.execute(CONSUMER,version.capability_id,_request())
    assert recovered.status == 'FAILED'
    assert recovered.failure_kind == 'ENVIRONMENT_DEPENDENCY'
    assert recovered.step_results == execution.step_results
    assert len(shared_scope.state['calls']) == 1


@pytest.mark.parametrize('encoded,expected_kind', [('{"supplementId":101}',''),('{"supplementId":999}','BEHAVIOR_DIFF'),('not-json','OBSERVATION_FAILED')])
def test_fixed_json_observation_checks_supplement_relation(shared_scope: SimpleNamespace, encoded: str, expected_kind: str) -> None:
    """固定Oracle解析实际ext关联；关联变化与观察格式损坏分开报告。

    Args:
        shared_scope: 使用真实执行器的服务。
        encoded: 远端观察实际返回的JSON字符串。
        expected_kind: 预期报告分类；空值表示通过。
    """

    from opentest.domain.case_template_v4 import CaseTemplateCompilationInput, CaseOracle
    version = _publish(shared_scope)
    generation = _generation(version)
    oracle = CaseOracle(oracle_id='report_relationship',channel='response',
        json_decode_fields={'ext':{'type':'object','properties':{'supplementId':{'type':'integer'}},'required':['supplementId']}},
        assertions=[{'actual_path':'ext.supplementId','operator':'eq','expected':{'kind':'request_field','path':'id'}}])
    generation.submission.case_templates[0].oracles = [oracle]
    generation.variants[0].oracles = [oracle]
    registry = shared_scope.service._registry(SimpleNamespace(task_id='case-validation-task',system_id=CONSUMER,source_scopes=version.source_scopes))
    compilation = CaseTemplateCompilationInput(submission=generation.submission,input_contract=generation.input_contract,
        target_output_schema={'type':'object','properties':{'ext':{'type':'string'}}},runtime_registry=registry,
        value_registry=shared_scope.cases.registries.value_registry(),allowed_system_ids={PROVIDER,CONSUMER})
    assert shared_scope.cases.compiler.compile(compilation)[1] == []
    operation_service = shared_scope.cases.runtime.operation_service
    # 测试范围直接保存Provider引用，避免将实现细节作为观察目标。
    current_invoke = shared_scope.provider.execute_facade.side_effect
    def observe(capability, request):
        """保持准备查询返回，仅为目标响应提供当前试验的ext字符串。

        Args:
            capability: 固定Operation。
            request: 实际调用参数。
        Returns:
            目标返回ext，其余保留原模拟接口结果。
        """

        response = current_invoke(capability, request)
        return {**response,'ext':encoded} if capability.operation_id == TARGET else response
    shared_scope.provider.execute_facade.side_effect = observe
    executor = CaseTemplateExecutorV4(operation_service,consumer_system_id=CONSUMER,
        capabilities=shared_scope.capabilities,data_store=shared_scope.service.records)
    outcome = executor.execute('case-generation-execution-'+'7'*20,generation,registry)[0]
    assert outcome.failure_kind == expected_kind
    assert outcome.operations[-1].actual_response['ext'] == encoded


def test_case_inline_function_cannot_drop_identity_conditions(shared_scope: SimpleNamespace) -> None:
    """移除共享来源并删掉主体/票号验证不能绕过相同编译约束。

    Args:
        shared_scope: 真实共享服务和Case编译器。
    """

    from opentest.domain.case_template_v4 import CaseTemplateCompilationInput
    version = _publish(shared_scope)
    generation = _generation(version)
    function = generation.submission.data_functions[0]
    function.shared_source = None
    function.verify_steps = [function.verify_steps[-1]]
    handoff = SimpleNamespace(task_id='case-validation-task',system_id=CONSUMER,source_scopes=version.source_scopes)
    compilation = CaseTemplateCompilationInput(submission=generation.submission,input_contract=generation.input_contract,
        target_output_schema={'type':'object','properties':{'supplementStatus':{'type':'string'},'supplementId':{'type':'integer'}}},
        runtime_registry=shared_scope.service._registry(handoff),value_registry=shared_scope.cases.registries.value_registry(),
        allowed_system_ids={PROVIDER,CONSUMER})
    variants, issues = shared_scope.cases.compiler.compile(compilation)
    assert {'owner_id','ticket_no'} <= {issue.field for issue in issues if issue.code == 'INPUT_CONDITION_UNVERIFIED'}
    assert not variants


@pytest.mark.parametrize('condition_name', ['owner_id', 'ticket_no'])
def test_empty_filter_cannot_replace_identity_assertion(
    shared_scope: SimpleNamespace, condition_name: str,
) -> None:
    """空集合不会执行过滤谓词，不能用它代替主体或票号的必经断言。

    Args:
        shared_scope: 真实共享服务和Case编译器，QA响应仅由本地替身提供。
        condition_name: 被移入空集合过滤步骤、因而没有实际验证的用户条件。
    Returns:
        None；编译阻塞缺失的输入条件且未派发任何QA调用时通过。
    """

    from opentest.domain.case_template_v4 import CaseTemplateCompilationInput, DataFunctionStep

    version = _publish(shared_scope)
    generation = _generation(version)
    function = generation.submission.data_functions[0]
    function.shared_source = None
    identity = function.verify_steps[0]
    skipped_predicate = next(predicate for predicate in identity.predicates if predicate.right.name == condition_name)
    # 保留另一个身份断言，将待验证条件放入永远不遍历元素的过滤步骤。
    remaining_identity = identity.model_copy(update={
        'predicates': [predicate for predicate in identity.predicates if predicate.right.name != condition_name],
    })
    shared_scope.state['report']['ext'] = '[]'
    function.verify_steps = [
        remaining_identity,
        DataFunctionStep(step_id='decode_empty_list', operation='json_decode',
            input_source={'kind':'step_output','step_id':'report_query','path':'report.ext'},
            output_schema={'type':'array','items':{'type':'object'},'maxItems':0}),
        DataFunctionStep(step_id='filter_identity', operation='filter',
            input_source={'kind':'step_output','step_id':'decode_empty_list'}, predicates=[skipped_predicate]),
        function.verify_steps[-1],
    ]
    handoff = SimpleNamespace(task_id='case-validation-task',system_id=CONSUMER,source_scopes=version.source_scopes)
    compilation = CaseTemplateCompilationInput(submission=generation.submission,input_contract=generation.input_contract,
        target_output_schema={'type':'object','properties':{'supplementStatus':{'type':'string'},'supplementId':{'type':'integer'}}},
        runtime_registry=shared_scope.service._registry(handoff),value_registry=shared_scope.cases.registries.value_registry(),
        allowed_system_ids={PROVIDER,CONSUMER})

    # 必须在编译阶段拒绝，不能让合法的报表输出绕过被空过滤跳过的条件检查。
    variants, issues = shared_scope.cases.compiler.compile(compilation)
    assert [(issue.code, issue.field) for issue in issues] == [('INPUT_CONDITION_UNVERIFIED', condition_name)]
    assert not variants
    assert shared_scope.state['calls'] == []


def test_same_operation_id_in_two_systems_is_rejected(shared_scope: SimpleNamespace) -> None:
    """同名Facade同时属于consumer/provider时，固定方法不能因目录顺序改绑。

    Args:
        shared_scope: 双系统绑定与真实目录服务。
    """

    shared_scope.capabilities.append(shared_scope.capabilities[0].model_copy(update={'system_id':CONSUMER}))
    # 明确选中两边的同名接口，不能以默认开放整个关联系统的旧行为制造歧义。
    scopes = [*shared_scope.cases._source_scopes(CONSUMER, 'scan-source-a', FACADE + 'queryReportByUniqueKey'),
              *shared_scope.cases._source_scopes(PROVIDER, 'scan-source-a', FACADE + 'queryReportByUniqueKey')]
    handoff = SimpleNamespace(task_id='case-validation-task',system_id=CONSUMER,source_scopes=scopes)
    with pytest.raises(KnowledgeValidationError,match='多个所属系统'):
        shared_scope.service._registry(handoff)


@pytest.mark.parametrize('source', [{'kind':'literal','value':None}, {'kind':'function_input','name':'owner_id'},
                                    {'kind':'step_output','step_id':'create_report','path':'report'}])
def test_match_source_must_be_an_actual_query_result(shared_scope: SimpleNamespace, source: dict) -> None:
    """只有实际查询结果能触发创建；调用者条件、常量或写结果都不得冒充未找到。

    Args:
        shared_scope: 已发布版本及真实执行器。
        source: 非法匹配来源。
    """

    from pydantic import ValidationError
    from opentest.domain.case_template_v4 import DslValueSource
    from opentest.domain.data_capabilities import DataExecution
    definition = json.loads(FIXTURE.read_text())
    definition['match_source'] = source
    with pytest.raises(ValidationError,match='match_source'):
        DataCapabilityDefinition.model_validate(definition)
    version = _publish(shared_scope)
    function = version.as_function().model_copy(update={'match_source':DslValueSource.model_validate(source)})
    executor = CaseTemplateExecutorV4(shared_scope.cases.runtime.operation_service,consumer_system_id=CONSUMER,
                                     capabilities=shared_scope.capabilities,data_store=shared_scope.service.records)
    execution = DataExecution(execution_id='data-execution-'+'9'*20,system_id=CONSUMER,
        capability_id=version.capability_id,capability_version=1,environment_id='qa',inputs=_request().inputs,allow_writes=True)
    outcome = executor.execute_data(execution,function,shared_scope.service._registry(SimpleNamespace(task_id='case-validation-task',system_id=CONSUMER,source_scopes=version.source_scopes)))
    assert outcome.failure_kind == 'DATA_PREPARATION_FAILED'
    assert shared_scope.state['calls'] == []


def test_default_draft_trial_is_required_and_replayed_once(shared_scope: SimpleNamespace, monkeypatch) -> None:
    """默认方法必须真实试跑；摘要目录下重试仍返回完整证据且不重复调用。

    Args:
        shared_scope: 实际服务、存储及可跟踪调用的测试Provider。
        monkeypatch: 将列表读取替换为MySQL使用的小型执行摘要形状。
    """

    from opentest.domain.data_capabilities import DataDraftExecutionRequest

    task = shared_scope.service.prepare(PROVIDER, DataCapabilityPrepareRequest(
        goal='实际准备并验证补单报表', request_id='draft-trial-prepare'))
    shared_scope.service.call_agent_tool(task.task_id, 'read_source', {'source_system_id': PROVIDER, 'path': 'ReportFacade.java'})
    definition = json.loads(FIXTURE.read_text())
    shared_scope.service.call_agent_tool(task.task_id, 'save_data_draft', {'expected_revision': 0, 'definition': definition})
    with pytest.raises(KnowledgeValidationError, match='试跑'):
        shared_scope.service.call_agent_tool(task.task_id, 'publish_data_capability', {'expected_revision': 1})
    # 没有现成报表时执行创建，再使用原查询回查；幂等重试返回第一次执行。
    shared_scope.state['report'] = None
    request = DataDraftExecutionRequest(expected_revision=1, function_name=definition['capability_id'],
        inputs={'owner_id': 'unit-owner', 'ticket_no': 'unit-ticket'}, request_id='draft-trial-request')
    trial = shared_scope.service.execute_draft(task.task_id, request)
    assert trial.status == 'COMPLETED'
    assert len([item for item in shared_scope.state['calls'] if item[0] == FACADE + 'saveReport']) == 1
    business_calls = list(shared_scope.state['calls'])
    list_executions = shared_scope.service.records.list_executions
    def summaries(system_id):
        """读取指定系统执行后省略大证据，复现共享MySQL列表的真实返回边界。"""

        executions = list_executions(system_id)
        return [item.model_copy(update={'outputs': {}, 'step_results': [], 'checks': []}) for item in executions]
    monkeypatch.setattr(shared_scope.service.records, 'list_executions', summaries)
    replay = shared_scope.service.execute_draft(task.task_id, request)
    assert replay.execution_id == trial.execution_id
    assert replay.outputs == trial.outputs and replay.outputs
    assert replay.step_results == trial.step_results and replay.step_results
    assert replay.checks == trial.checks and replay.checks
    assert shared_scope.state['calls'] == business_calls
    assert len([item for item in shared_scope.state['calls'] if item[0] == FACADE + 'saveReport']) == 1
    shared_scope.service.call_agent_tool(task.task_id, 'publish_data_capability', {'expected_revision': 1})
    assert shared_scope.service.get_version(PROVIDER, definition['capability_id'], 1).source_scopes
    # 崩溃发生在远端已完成、本地终态未保存时，草稿试跑也沿独立运行任务恢复为未知失败。
    from opentest.domain.models import TaskStatus, utc_now
    shared_scope.service.records.save_execution(trial.model_copy(update={'status': 'RUNNING', 'completed_at': None}))
    execution_task = shared_scope.tasks.get(trial.task_id)
    shared_scope.tasks.save_business_record(execution_task.model_copy(update={'status': TaskStatus.INTERRUPTED, 'ended_at': utc_now()}))
    recovered = shared_scope.service.execute_draft(task.task_id, request)
    assert recovered.status == 'FAILED'
    assert recovered.step_results == trial.step_results
    assert shared_scope.state['calls'] == business_calls
    assert len([item for item in shared_scope.state['calls'] if item[0] == FACADE + 'saveReport']) == 1


def test_contract_supplement_records_rejection_and_adoption_in_task(shared_scope: SimpleNamespace) -> None:
    """契约补充被拒绝时任务保存原因且不再接受提交；成功补充记录采纳并完成同一任务。"""

    from opentest.domain.models import TaskStatus

    operation_id = FACADE + 'queryReportByUniqueKey'
    contract = OperationInputKnowledgeContract(contract_version='operation-contract/v2', target_id=operation_id,
        request_type='Request', source_scan_id='scan-source-a', status='READY',
        request_schema={'type': 'object', 'properties': {}, 'additionalProperties': False}, fields=[])
    contracts = Mock()
    contracts.get_contract.return_value = contract
    contracts.supplement.side_effect = KnowledgeValidationError('补充Schema不属于受支持的确定结构')
    shared_scope.cases.operation_contracts = contracts
    supplement = {'fields': [{'path': 'ownerId', 'description': '归属方', 'evidence_refs': [
        {'path': 'ReportFacade.java', 'symbol': 'example.ReportFacade#query', 'line': 1}]}]}

    rejected = shared_scope.service.prepare(PROVIDER, DataCapabilityPrepareRequest(
        goal='补充ownerId', operation_id=operation_id, kind='contract', request_id='contract-reject'))
    with pytest.raises(KnowledgeValidationError, match='不属于受支持'):
        shared_scope.service.call_agent_tool(rejected.task_id, 'supplement_contract', {'expected_revision': 0, 'supplement': supplement})
    record = shared_scope.tasks.get(rejected.task_id)
    assert record.status == TaskStatus.FAILED
    assert record.result['contract_completion']['adoption'] == 'rejected'
    assert record.result['contract_completion']['reason'] == '补充Schema不属于受支持的确定结构'
    # 再次提交不得重复调用契约服务，且提示保留首次拒绝根因。
    with pytest.raises(KnowledgeValidationError, match='原因：补充Schema不属于受支持的确定结构'):
        shared_scope.service.call_agent_tool(rejected.task_id, 'supplement_contract', {'expected_revision': 0, 'supplement': supplement})
    assert contracts.supplement.call_count == 1

    contracts.supplement.side_effect = None
    contracts.supplement.return_value = contract.model_copy(update={'contract_revision': 1})
    accepted = shared_scope.service.prepare(PROVIDER, DataCapabilityPrepareRequest(
        goal='补充ownerId', operation_id=operation_id, kind='contract', request_id='contract-accept'))
    shared_scope.service.call_agent_tool(accepted.task_id, 'supplement_contract', {'expected_revision': 0, 'supplement': supplement})
    record = shared_scope.tasks.get(accepted.task_id)
    assert record.status == TaskStatus.COMPLETED
    assert record.result['contract_completion']['adoption'] == 'accepted'
    assert record.result['contract_completion']['reason'] == ''


def test_generate_only_draft_cannot_access_business_provider(shared_scope: SimpleNamespace) -> None:
    """明确禁止执行时，直接试跑入口也必须在访问业务Provider前拒绝。"""

    from opentest.domain.data_capabilities import DataDraftExecutionRequest

    task = shared_scope.service.prepare(PROVIDER, DataCapabilityPrepareRequest(
        goal='只生成方法', request_id='draft-no-execute-prepare', execution_mode='generate_only'))
    with pytest.raises(KnowledgeValidationError, match='禁止'):
        shared_scope.service.execute_draft(task.task_id, DataDraftExecutionRequest(
            expected_revision=0, function_name='refund_supplement_report', request_id='draft-no-execute-request'))
    assert shared_scope.state['calls'] == []
