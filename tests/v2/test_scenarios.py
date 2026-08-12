"""验证覆盖驱动Case、pairwise组合和自然语言场景编译。"""

from __future__ import annotations

from pathlib import Path

from opentest.adapters.case_store import GitCaseStore
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.application.scenarios import CREATE_ORDER_ENTRY, PairwiseVariantSelector, ScenarioGenerationService
from opentest.domain.models import (
    KnowledgeConfirmation,
    KnowledgeNode,
    KnowledgeNodeKind,
    KnowledgeQuestion,
    KnowledgeStatus,
    EntryPoint,
    NaturalLanguageScenarioRequest,
    ScanManifest,
    ScenarioGenerationBatch,
    ScenarioGenerationRequest,
    SourceBaseline,
    SystemDefinition,
)


def _scenario_service(tmp_path: Path) -> tuple[ScenarioGenerationService, GitCaseStore]:
    """创建包含createOrder关键知识节点的单系统场景服务。"""

    source = tmp_path / "source"
    source.mkdir()
    store = GitKnowledgeStore(tmp_path / "knowledge")
    baseline = SourceBaseline(source_path=str(source), commit="scenario-test", dirty=False)
    store.register_system(
        SystemDefinition(
            system_id="train-booking-core",
            name="火车票预订",
            source_path=str(source),
            baseline=baseline,
        )
    )
    node_specs = [
        (CREATE_ORDER_ENTRY, KnowledgeNodeKind.FACADE, "创建订单"),
        ("rule:create-order:adult-required", KnowledgeNodeKind.BUSINESS_RULE, "订单至少包含成人"),
        ("rule:create-order:direct-accept", KnowledgeNodeKind.BUSINESS_RULE, "港铁直接收单"),
        ("rule:create-order:hk-payment-verify", KnowledgeNodeKind.BUSINESS_RULE, "港币逐乘客校验"),
        ("rule:create-order:hk-plan-price", KnowledgeNodeKind.BUSINESS_RULE, "港币计划价"),
        ("state-machine:OrderStateEnum", KnowledgeNodeKind.STATE_MACHINE, "订单状态机"),
    ]
    for node_id, kind, title in node_specs:
        node = KnowledgeNode(
            node_id=node_id,
            system_id="train-booking-core",
            kind=kind,
            title=title,
            summary=title,
            status=KnowledgeStatus.CODE_VERIFIED,
            confidence=1,
        )
        store.write_node(node, f"## 业务结论\n\n{title}")
    case_store = GitCaseStore(store)
    artifacts = SourceScanArtifactStore(store.root)
    scan_id, tool_root = artifacts.allocate("train-booking-core", baseline)
    tool_root.mkdir(parents=True)
    entry = EntryPoint(
        entry_id="facade:test.TradeFacade#createOrder",
        system_id="train-booking-core",
        kind=KnowledgeNodeKind.FACADE,
        display_name="TradeFacade#createOrder",
        source_id="test.TradeFacade#createOrder",
        source_path=str(source / "TradeFacade.java"),
        tool_id="facade.trade.create_order",
        metadata={
            "required_fields": ["traceId", "bookInfo", "passengers", "contactInfo"],
            "request_template": _request_template(),
        },
    )
    artifacts.write_manifest(
        ScanManifest(
            scan_id=scan_id,
            system_id="train-booking-core",
            baseline=baseline,
            entries=[entry],
            tool_root=str(tool_root),
        )
    )
    artifacts.publish_latest("train-booking-core", scan_id)
    return ScenarioGenerationService(store, case_store, artifacts=artifacts), case_store


def _request_template() -> dict[str, object]:
    """返回与真实scriptgen createOrder入口一致的最小DTO形状。"""

    return {
        "traceId": "",
        "bookInfo": {
            "trainNo": "",
            "serialId": "",
            "electronicSerialId": "",
            "trainDate": "",
            "fromCityName": "",
            "toCityName": "",
            "startTime": "",
            "occupySeat": 0,
            "distributeMerchantType": 0,
            "connectType": 0,
            "userPayType": 0,
        },
        "passengers": [{"type": 0, "seatClass": 0, "foreignTicketPrice": 0}],
        "contactInfo": {"name": "", "phone": "", "email": "", "otherPhone": ""},
        "extend": {"inquire": False, "merchantId": "", "ticketMachineId": ""},
    }


def _qa_template() -> dict[str, object]:
    """返回不含真实身份的完整QA场景输入模板。"""

    return {
        "train_no": "QA-G100",
        "train_date": "2026-09-01",
        "departure_station": "QA-HKH",
        "arrival_station": "QA-XRL",
        "start_time": "2026-09-01 10:00:00",
        "seat_class": 2,
        "contact_info": {"name": "QA_CONTACT", "phone": "00000000000", "email": "", "otherPhone": ""},
        "create_order_extend": {"inquire": False, "merchantId": "QA", "ticketMachineId": ""},
        "adult_passenger": {"name": "QA_ADULT", "idType": 1, "idCard": "QA-ADULT-ID"},
        "child_passenger": {"name": "QA_CHILD", "idType": 1, "idCard": "QA-CHILD-ID"},
        "adult_passenger_type": 1,
        "child_passenger_type": 2,
        "default_distribute_merchant_type": 1,
        "hk_distribute_merchant_type": 9,
        "default_user_pay_type": 1,
        "hk_user_pay_type": 2,
        "occupy_type_default": 0,
        "occupy_type_normal": 1,
        "connect_type": 0,
        "foreign_ticket_price": "100.00",
        "hk_quote_status": "valid",
    }


def test_pairwise_selector_covers_pairs_without_cartesian_explosion() -> None:
    """选择器应覆盖所有可达值对且明显少于完整笛卡尔积。"""

    dimensions = {
        "payment": ["CNY", "HKD"],
        "passenger": ["adult", "adult_child", "child"],
        "route": ["normal", "mtr"],
        "occupy": ["ticketing", "occupying"],
    }
    selector = PairwiseVariantSelector()
    selected = selector.select(dimensions, lambda _: True)

    assert len(selected) < 2 * 3 * 2 * 2
    for left_index, left_name in enumerate(dimensions):
        for right_name in list(dimensions)[left_index + 1 :]:
            expected_pairs = {(left, right) for left in dimensions[left_name] for right in dimensions[right_name]}
            actual_pairs = {(item[left_name], item[right_name]) for item in selected}
            assert actual_pairs == expected_pairs


def test_regression_generation_persists_targets_and_stable_variants(tmp_path: Path) -> None:
    """全量生成应保存知识覆盖目标并在重复运行时保持变体身份稳定。"""

    service, case_store = _scenario_service(tmp_path)
    request = ScenarioGenerationRequest(system_id="train-booking-core", entry_node_id=CREATE_ORDER_ENTRY)
    first = service.generate(request)
    second = service.generate(request)

    assert len(first.coverage_targets) == 5
    assert len(first.variants) < 72
    assert [item.variant_id for item in first.variants] == [item.variant_id for item in second.variants]
    assert case_store.list_coverage_targets("train-booking-core")
    persisted = case_store.list_variants("train-booking-core", "scenario:create-order:main-flow")
    assert {item.variant_id for item in persisted} == {item.variant_id for item in first.variants}
    assert any(item.expected_outcome == "no_adult" for item in first.variants)
    assert any(item.expected_outcome == "oracle_required" for item in first.variants)
    assert any(item.lifecycle == "blocked" for item in first.variants)
    for variant in first.variants:
        request_payload = variant.inputs["request"]
        assert set(request_payload) == {"traceId", "bookInfo", "passengers", "contactInfo", "extend"}
        assert "quoteResult" not in request_payload
        assert "routeType" not in request_payload
        if variant.expected_outcome == "no_adult":
            assert variant.cleanup_steps == []
            assert variant.coverage_target_ids == ["coverage:create-order:adult-required"]
        if variant.inputs["dimensions"]["payment_type"] == "HK_PAYMENT":
            expected_quote = variant.inputs["dimensions"]["quote_result"]
            assert variant.replay["data_preconditions"]["hk_quote_status"]["expected"] == expected_quote
        else:
            assert variant.replay["data_preconditions"] == {}


def test_natural_language_reports_missing_qa_conditions_without_guessing(tmp_path: Path) -> None:
    """没有QA模板时应返回明确缺失项且不生成伪造订单输入。"""

    service, _ = _scenario_service(tmp_path)
    compilation = service.compile_natural_language(
        NaturalLanguageScenarioRequest(
            system_id="train-booking-core",
            text="创建2个港币支付的订单，要求多乘客，包含儿童和成人",
        )
    )

    assert compilation.status == "needs_input"
    assert compilation.variants == []
    missing_keys = {item.key for item in compilation.missing_conditions}
    assert {"train_no", "contact_info", "adult_passenger", "child_passenger", "foreign_ticket_price"} <= missing_keys
    constraints = {item.field: item.value for item in compilation.constraints}
    assert constraints["order_count"] == 2
    assert constraints["payment_type"] == "HK_PAYMENT"
    assert constraints["passenger_count"] == 2


def test_natural_language_builds_two_independent_hkd_adult_child_variants(tmp_path: Path) -> None:
    """完整QA模板应把目标语句编译为两个独立、可重放的港币成人儿童订单。"""

    service, _ = _scenario_service(tmp_path)
    compilation = service.compile_natural_language(
        NaturalLanguageScenarioRequest(
            system_id="train-booking-core",
            text="创建2个港币支付的订单，要求多乘客，包含儿童和成人",
            template_inputs=_qa_template(),
        )
    )

    assert compilation.status == "ready"
    assert len(compilation.variants) == 2
    assert len({item.variant_id for item in compilation.variants}) == 2
    assert len({item.inputs["request"]["bookInfo"]["serialId"] for item in compilation.variants}) == 2
    for variant in compilation.variants:
        request_payload = variant.inputs["request"]
        assert set(request_payload) == {"traceId", "bookInfo", "passengers", "contactInfo", "extend"}
        passengers = request_payload["passengers"]
        assert {item["type"] for item in passengers} == {1, 2}
        assert all(item["foreignTicketPrice"] == "100.00" for item in passengers)
        assert variant.replay["template_digest"]
        assert variant.replay["data_preconditions"]["hk_quote_status"]["expected"] == "valid"

    # 深拷贝确保修改一个订单输入不会污染另一个独立变体。
    compilation.variants[0].inputs["request"]["passengers"][0]["name"] = "CHANGED"
    assert compilation.variants[1].inputs["request"]["passengers"][0]["name"] == "QA_ADULT"


def test_regeneration_preserves_user_edited_variant(tmp_path: Path) -> None:
    """自动重生成不得覆盖用户已编辑变体的输入和重放说明。"""

    service, case_store = _scenario_service(tmp_path)
    request = ScenarioGenerationRequest(system_id="train-booking-core", entry_node_id=CREATE_ORDER_ENTRY)
    first = service.generate(request)
    original = first.variants[0]
    edited = original.model_copy(
        update={"lifecycle": "user_edited", "replay": {**original.replay, "manual_note": "保留人工数据约束"}}
    )
    case_store.write_variant(edited)

    service.generate(request)
    persisted = case_store.get_variant("train-booking-core", original.variant_id)
    assert persisted.lifecycle == "user_edited"
    assert persisted.replay["manual_note"] == "保留人工数据约束"


def test_incremental_generation_merges_unaffected_targets_and_manual_variant(tmp_path: Path) -> None:
    """增量更新一个知识目标时必须保留其余覆盖目标及人工变体。"""

    service, case_store = _scenario_service(tmp_path)
    full_request = ScenarioGenerationRequest(system_id="train-booking-core", entry_node_id=CREATE_ORDER_ENTRY)
    first = service.generate(full_request)
    manual = first.variants[0].model_copy(
        update={"lifecycle": "user_edited", "replay": {**first.variants[0].replay, "manual_note": "保留"}}
    )
    case_store.write_variant(manual)

    incremental = service.generate(
        ScenarioGenerationRequest(
            system_id="train-booking-core",
            entry_node_id=CREATE_ORDER_ENTRY,
            mode="incremental",
            changed_node_ids=["rule:create-order:adult-required"],
        )
    )

    assert [item.target_id for item in incremental.coverage_targets] == ["coverage:create-order:adult-required"]
    assert len(case_store.list_coverage_targets("train-booking-core")) == 5
    persisted = case_store.get_variant("train-booking-core", manual.variant_id)
    assert persisted.lifecycle == "user_edited"
    assert persisted.replay["manual_note"] == "保留"


def test_incremental_generation_replaces_affected_scenario_coverage(tmp_path: Path) -> None:
    """增量批次不再覆盖受影响目标时应移除旧关系，同时保留无关目标。"""

    service, case_store = _scenario_service(tmp_path)
    full = service.generate(
        ScenarioGenerationRequest(system_id="train-booking-core", entry_node_id=CREATE_ORDER_ENTRY)
    )
    affected_id = "coverage:create-order:adult-required"
    affected_target = next(item for item in full.coverage_targets if item.target_id == affected_id)
    updated_scenario = full.scenarios[0].model_copy(update={"coverage_target_ids": []})
    updated_variants = [
        item.model_copy(update={"coverage_target_ids": sorted(set(item.coverage_target_ids) - {affected_id})})
        for item in full.variants
    ]
    case_store.write_batch(
        ScenarioGenerationBatch(
            batch_id="batch:remove-affected-coverage",
            system_id="train-booking-core",
            entry_node_id=CREATE_ORDER_ENTRY,
            coverage_targets=[affected_target],
            scenarios=[updated_scenario],
            variants=updated_variants,
        ),
        mode="incremental",
    )

    persisted = case_store.list_scenarios("train-booking-core")[0]
    assert affected_id not in persisted.coverage_target_ids
    assert "coverage:create-order:hk-verify" in persisted.coverage_target_ids


def test_quote_decision_rejects_negated_success_phrase_as_ambiguous(tmp_path: Path) -> None:
    """包含“继续通过”的否定回答不得被误判为可执行成功口径。"""

    service, _ = _scenario_service(tmp_path)
    question = KnowledgeQuestion(
        question_id="question:create-order:hk-quote-missing",
        system_id="train-booking-core",
        title="报价缺失如何处理",
        detail="确认缺少港币报价时创建订单的预期结果",
    )
    service.knowledge_store.write_questions("train-booking-core", [question])
    service.knowledge_store.answer_question(
        "train-booking-core",
        KnowledgeConfirmation(
            question_id=question.question_id,
            answer="我认为不应该继续通过",
        ),
    )

    assert service._quote_missing_decision("train-booking-core") == "needs_confirmation"


def test_natural_language_rejects_negated_or_unconsumed_requirements(tmp_path: Path) -> None:
    """否定乘客条件和未支持座位偏好不得被静默编译为ready。"""

    service, _ = _scenario_service(tmp_path)
    compilation = service.compile_natural_language(
        NaturalLanguageScenarioRequest(
            system_id="train-booking-core",
            text="创建2个港币订单，要求靠窗，不要儿童，包含成人",
            template_inputs=_qa_template(),
        )
    )

    assert compilation.status == "needs_input"
    constraints = {item.field: item for item in compilation.constraints}
    assert constraints["child_count"].operator == "eq"
    assert constraints["child_count"].value == 0
    assert "unsupported_requirements" in {item.key for item in compilation.missing_conditions}


def test_natural_language_respects_adult_only_passenger_mix(tmp_path: Path) -> None:
    """只要求成人时编译器应生成单成人DTO，不能静默追加儿童。"""

    service, _ = _scenario_service(tmp_path)
    template = _qa_template()
    for key in ("child_passenger", "child_passenger_type", "hk_distribute_merchant_type", "hk_user_pay_type"):
        template.pop(key)
    compilation = service.compile_natural_language(
        NaturalLanguageScenarioRequest(
            system_id="train-booking-core",
            text="创建1个人民币订单，包含成人",
            template_inputs=template,
        )
    )

    assert compilation.status == "ready"
    passengers = compilation.variants[0].inputs["request"]["passengers"]
    assert len(passengers) == 1
    assert passengers[0]["type"] == template["adult_passenger_type"]
    assert compilation.variants[0].coverage_target_ids == ["coverage:create-order:adult-required"]
    assert compilation.variants[0].replay["data_preconditions"] == {}


def test_case_file_names_remain_distinct_for_lossy_slug_collision(tmp_path: Path) -> None:
    """只在标点上不同的稳定ID必须写入不同文件且都能独立读取。"""

    service, case_store = _scenario_service(tmp_path)
    batch = service.generate(
        ScenarioGenerationRequest(system_id="train-booking-core", entry_node_id=CREATE_ORDER_ENTRY)
    )
    first = batch.variants[0].model_copy(update={"variant_id": "variant:a:b"})
    second = batch.variants[0].model_copy(update={"variant_id": "variant:a-b"})
    case_store.write_variant(first)
    case_store.write_variant(second)

    assert case_store.get_variant("train-booking-core", first.variant_id).variant_id == first.variant_id
    assert case_store.get_variant("train-booking-core", second.variant_id).variant_id == second.variant_id
    variant_root = case_store.knowledge_store.system_root("train-booking-core") / "cases" / "variants"
    assert len([path for path in variant_root.glob("variant-a-b-*.yaml")]) == 2
