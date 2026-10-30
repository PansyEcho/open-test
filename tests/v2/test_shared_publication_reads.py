"""共享目录批量读取的SQL预算、完整内容和员工可见范围回归；仅使用内存SQLite。"""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from opentest.domain.case_template_v4 import CaseTemplateGenerationV4
from opentest.domain.publication import PublicationRequest
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError, ScopeViolationError
from tests.v2.test_shared_publication import generation_payload, publication, seed_interface


def observe_queries(database, monkeypatch):
    """记录一次测试的真实SQL及绑定参数，返回可清空列表；不替代查询结果或可见性过滤。"""

    queries = []
    fetch_one, fetch_all = database.fetch_one, database.fetch_all

    def read_one(sql, parameters=()):
        """记录单行只读查询后交由原SQLite执行；保持原始异常和结果。"""

        queries.append((sql, parameters))
        return fetch_one(sql, parameters)

    def read_all(sql, parameters=()):
        """记录集合只读查询后交由原SQLite执行；保持原始异常和结果。"""

        queries.append((sql, parameters))
        return fetch_all(sql, parameters)

    # 统计真正触发的存储调用，不以预设Mock响应掩盖N+1或查询范围错误。
    monkeypatch.setattr(database, "fetch_one", read_one)
    monkeypatch.setattr(database, "fetch_all", read_all)
    return queries


@pytest.mark.parametrize("view", ["published", "mine"])
def test_interface_list_batches_exact_revisions_without_reducing_content(publication, monkeypatch, view):
    """67个接口只用三次SQL，保留完整固定正文及原响应，且不读取另一修订或其他员工草稿。"""

    service, database, scope = publication
    for identity in range(1, 68):
        seed_interface(database, identity, summary="完整接口知识\n" * 100)
        database.execute("UPDATE ot_baseline_interface SET current_interface_id=%s,current_contract_revision=1,"
                         "availability='AVAILABLE' WHERE baseline_interface_id=%s", (identity, identity))
    seed_interface(database, 68, owner="employee-b", summary="PRIVATE-OTHER-EMPLOYEE")
    database.execute("INSERT INTO ot_interface_contract_version SELECT interface_id,2,contract_json,"
                     "REPLACE(knowledge_json,'完整接口知识','PRIVATE-OTHER-REVISION'),author_user_id "
                     "FROM ot_interface_contract_version WHERE interface_id=1 AND revision=1")
    rows = service.store.list_items(scope, "interfaces", view)
    expected = [service._interface_view(row, view) for row in rows]
    queries = observe_queries(database, monkeypatch)

    # 与原单项投影逐字段比对，同时检查实际SQL只提交当前授权的成对引用。
    actual = service.list_interfaces(scope, view)
    assert actual == expected
    assert len(actual) == 67 and len(queries) == 3
    assert "COMPRESS(c.knowledge_json)" in queries[-1][0]
    assert list(zip(queries[-1][1][::2], queries[-1][1][1::2])) == [(identity, 1) for identity in range(1, 68)]
    assert "PRIVATE" not in json.dumps(actual, ensure_ascii=False)
    assert actual[0]["knowledge"]["bodies"]["node-order"] == "完整接口知识\n" * 100


def test_interface_list_preserves_building_and_missing_fixed_content(publication, monkeypatch):
    """未完成草稿和缺失固定材料仍保留原状态与空内容，不补用系统或共享的新版本。"""

    service, database, scope = publication
    seed_interface(database, 1)
    seed_interface(database, 2)
    database.execute("UPDATE ot_interface_draft SET interface_id=NULL,contract_revision=NULL,status='BUILDING' "
                     "WHERE baseline_interface_id=1")
    database.execute("UPDATE ot_interface_draft SET contract_revision=9 WHERE baseline_interface_id=2")
    expected = [service._interface_view(row, "mine") for row in service.store.list_items(scope, "interfaces", "mine")]
    queries = observe_queries(database, monkeypatch)

    # 缺失固定修订不得重新触发单项查询或回退其他内容。
    assert service.list_interfaces(scope, "mine") == expected
    assert len(queries) == 3
    assert queries[-1][1] == [2, 9]
    assert expected[0]["status"] == "BUILDING"
    assert all(item["knowledge"] is None and item["contract"] is None for item in expected)


def seed_shared_generation(database):
    """插入两项共享Case及同批一项本人草稿，返回严格Generation；私有正文用于检测同批泄漏。"""

    seed_interface(database, 1)
    payload = generation_payload()
    second_public = deepcopy(payload["variants"][0])
    second_public.update(variant_id="case-variant-v4-" + "c" * 20, ordinal=3,
                         request_values={"id": "public-order-two"})
    payload["variants"].append(second_public)
    payload["case_bindings"].append({"case_id": "case-public-two", "variant_id": second_public["variant_id"],
                                     "knowledge_dependencies": payload["case_bindings"][0]["knowledge_dependencies"]})
    generation = CaseTemplateGenerationV4.model_validate(payload)
    database.execute("INSERT INTO ot_case_generation VALUES(%s,'orders','baseline-one','employee-a',%s)",
                     (generation.generation_id, generation.model_dump_json()))
    # 仅两条稳定Case拥有共享指针，第三条只归员工A草稿，三条都引用同一不可变产物。
    for binding in generation.case_bindings:
        database.execute("INSERT INTO ot_case(case_id,baseline_interface_id) VALUES(%s,1)", (binding.case_id,))
        if binding.case_id == "case-private":
            database.execute("INSERT INTO ot_case_draft VALUES(%s,'employee-a',%s,%s,0,1,'READY',NULL)",
                             (binding.case_id, generation.generation_id, binding.variant_id))
        else:
            database.execute("UPDATE ot_case SET current_generation_id=%s,current_variant_id=%s,impact_status='CURRENT' "
                             "WHERE case_id=%s", (generation.generation_id, binding.variant_id, binding.case_id))
    return generation


def test_case_list_reads_and_parses_shared_generation_once_per_request(publication, monkeypatch):
    """同批两项Case只传输并解析一次Generation，保持逐Case原投影且不泄漏私有兄弟项或跨请求缓存。"""

    service, database, scope = publication
    generation = seed_shared_generation(database)
    other = scope.model_copy(update={"user_id": "employee-b"})
    expected = [service._case_view(row, "published") for row in service.store.list_items(other, "cases", "published")]
    queries = observe_queries(database, monkeypatch)
    original_validate = CaseTemplateGenerationV4.model_validate
    parsed_ids = []

    def validate_generation(cls, payload):
        """记录真实严格解析次数，继续运行原模型校验，不提供预构造产物。"""

        parsed_ids.append(payload["generation_id"])
        return original_validate(payload)

    monkeypatch.setattr(CaseTemplateGenerationV4, "model_validate", classmethod(validate_generation))
    # 第二次读取必须重新查询并校验当前指针，防止把请求内复用变成权限过期的跨请求缓存。
    for _ in range(2):
        queries.clear()
        actual = service.list_cases(other)
        assert actual == expected
        assert len(queries) == 3
        assert "COMPRESS(generation_json)" in queries[-1][0]
        assert queries[-1][1] == [generation.generation_id]
        assert "PRIVATE-SIBLING" not in "".join(item.model_dump_json() for item in actual)
        assert "private-template-values" not in "".join(item.model_dump_json() for item in actual)
    assert parsed_ids == [generation.generation_id] * 2


def test_case_list_preserves_mine_isolation_and_empty_query_budget(publication, monkeypatch):
    """mine只返回本人的单项草稿；他人空集合不读取任何Generation。"""

    service, database, scope = publication
    seed_shared_generation(database)
    expected = service.get_case(scope, "case-private", "mine")
    queries = observe_queries(database, monkeypatch)
    assert service.list_cases(scope, "mine") == [expected]
    assert len(queries) == 3
    # 另一员工不能凭同批共享Case取得此私有variant。
    queries.clear()
    assert service.list_cases(scope.model_copy(update={"user_id": "employee-b"}), "mine") == []
    assert len(queries) == 2


@pytest.mark.parametrize("corruption", ["missing", "system", "baseline", "variant"])
def test_case_list_keeps_missing_scope_and_binding_failures(publication, corruption):
    """批量读取遇到缺产物、错误系统/基准或变体绑定时仍明确失败，不跳过坏项假造正常目录。"""

    service, database, scope = publication
    generation = seed_shared_generation(database)
    if corruption == "missing":
        database.execute("DELETE FROM ot_case_generation WHERE generation_id=%s", (generation.generation_id,))
        error_type = KnowledgeNotFoundError
    elif corruption in {"system", "baseline"}:
        column = "system_id" if corruption == "system" else "baseline_id"
        database.execute(f"UPDATE ot_case_generation SET {column}='other' WHERE generation_id=%s", (generation.generation_id,))
        error_type = ScopeViolationError
    else:
        database.execute("UPDATE ot_case SET current_variant_id='missing-variant' WHERE case_id='case-public'")
        error_type = KnowledgeValidationError
    # 保留旧单项读取的错误类别，而不是把失败缓存为空目录。
    with pytest.raises(error_type):
        service.list_cases(scope)


def test_batch_reads_fail_closed_on_corrupt_compressed_content(publication):
    """压缩传输损坏直接报错，不把无法还原的知识正文当作无知识。"""

    service, database, scope = publication
    seed_interface(database, 1)

    def corrupt_compression(payload):
        """在隔离数据库内模拟损坏传输；不影响生产压缩器或凭据。"""

        return b"invalid compressed JSON"

    # 运行真实批量SQL和生产解码器，确认错误不会触发原文回退或吞掉正文。
    database.connection.create_function("COMPRESS", 1, corrupt_compression)
    with pytest.raises(KnowledgeValidationError, match="compressed metadata JSON is invalid"):
        service.list_interfaces(scope, "mine")


@pytest.mark.parametrize("view", ["published", "mine"])
def test_interface_summaries_skip_knowledge_bodies_and_keep_visibility(publication, monkeypatch, view):
    """列表摘要保持完整列表的身份可见范围，额外返回索引计数且不下载契约或知识正文。"""

    service, database, scope = publication
    for identity in range(1, 4):
        seed_interface(database, identity, summary=f"接口{identity}用途")
        database.execute("UPDATE ot_baseline_interface SET current_interface_id=%s,current_contract_revision=1,"
                         "availability='AVAILABLE' WHERE baseline_interface_id=%s", (identity, identity))
    seed_interface(database, 4, owner="employee-b", summary="PRIVATE-OTHER-EMPLOYEE")
    full = service.list_interfaces(scope, view)
    queries = observe_queries(database, monkeypatch)

    summaries = service.list_interface_summaries(scope, view)
    # 身份、状态和修订逐项一致；新增Case计数独立验收，不能误视作完整详情字段。
    assert [{key: value for key, value in item.items() if key not in {"operation_summary", "has_knowledge", "case_count"}} for item in summaries] == [
        {key: value for key, value in item.items() if key not in {"contract", "knowledge"}} for item in full]
    assert all(item["case_count"] == 0 for item in summaries)
    assert [item["operation_summary"] for item in summaries] == [item["contract"]["operation_summary"] for item in full]
    assert all(item["has_knowledge"] for item in summaries)
    assert len(queries) == 3 and "knowledge_json IS NOT NULL" in queries[-1][0]
    assert "COMPRESS(c.knowledge_json)" not in queries[-1][0]
    assert "COMPRESS(c.contract_json)" not in queries[-1][0]
    assert "PRIVATE" not in json.dumps(summaries, ensure_ascii=False)


def test_interface_detail_uses_list_visibility(publication):
    """单项详情只返回当前视图可见的接口，他人草稿与未发布接口按不存在处理。"""

    service, database, scope = publication
    seed_interface(database, 1)
    seed_interface(database, 2, owner="employee-b")
    # 未发布接口只能以本人草稿读取，共享视图不能凭稳定身份看到。
    with pytest.raises(KnowledgeNotFoundError):
        service.get_interface(scope, 1, "published")
    assert service.get_interface(scope, 1, "mine")["knowledge"]["bodies"]["node-order"] == "订单查询"
    with pytest.raises(KnowledgeNotFoundError):
        service.get_interface(scope, 2, "mine")
    database.execute("UPDATE ot_baseline_interface SET current_interface_id=1,current_contract_revision=1,"
                     "availability='AVAILABLE' WHERE baseline_interface_id=1")
    assert service.get_interface(scope, 1, "published") == service.list_interfaces(scope, "published")[0]


def test_contract_only_interface_preserves_visibility_and_detail(publication):
    """没有legacy正文的独立契约仍可显示用途与详情；本人未发布内容保持员工隔离。"""

    service, database, scope = publication
    seed_interface(database, 1)
    database.execute("UPDATE ot_interface_contract_version SET knowledge_json=NULL WHERE interface_id=1")
    # 列表只传用途及身份，正文缺省不改变mine/shared边界，也不回退另一次扫描。
    mine = service.list_interface_summaries(scope, "mine")
    assert len(mine) == 1 and mine[0]["operation_summary"] == "订单查询" and not mine[0]["has_knowledge"]
    assert service.get_interface(scope, 1, "mine")["knowledge"] is None
    assert service.operation_contract(scope, "query-1", "mine")["operation_contract"]["source_scan_id"] == "scan-1"
    other = scope.model_copy(update={"user_id": "employee-b"})
    with pytest.raises(KnowledgeNotFoundError):
        service.get_interface(other, 1, "mine")
    with pytest.raises(KnowledgeNotFoundError):
        service.get_interface(other, 1, "published")
    service.publish(scope, "interfaces", PublicationRequest(request_id="publish-contract-only-read", scope="all"))
    published = service.get_interface(other, 1, "published")
    assert published["knowledge"] is None and published["contract"]["target_id"] == "query-1"
