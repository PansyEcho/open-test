"""Case工作台的精确授权、分组分页、单项业务结论和固定回执统计回归。"""

from copy import deepcopy
from types import SimpleNamespace
import json
import re

import pytest
from pydantic import ValidationError

from opentest.adapters.mysql_metadata import pack_json
from opentest.application.shared_case_execution import execution_request_projection
from opentest.domain.case_results import case_result_outcome
from opentest.domain.errors import KnowledgeNotFoundError, KnowledgeValidationError
from opentest.domain.publication import CaseExecutionQuery, CaseExecutionReceiptQuery, CaseListQuery
from opentest.domain.shared_workspace import CaseSelection
from tests.v2.test_shared_publication import publication, seed_interface, seed_published_case


def install_case_query_sqlite(database):
    """沿用内存SQL夹具执行分组查询，仅把MySQL JSON_TABLE语法转为SQLite json_each。

    数据库仍执行真实授权JOIN、CTE、窗口、COUNT和LIMIT；真实MySQL语法另由HTTP验收覆盖。
    """

    if getattr(database, "case_query_sqlite_installed", False):
        return
    original = database._sql

    def translate(sql):
        """转换驱动及JSON表函数语法，保留所有生产过滤、排序、分页与分组表达式。"""

        fields = {}

        def table(match):
            """将一个固定Generation数组展开为json_each，并记录原列的JSON路径。"""

            path, columns, alias = match.groups()
            for name, field_path in re.findall(r"(\w+)\s+(?:VARCHAR\(\d+\)|INT|JSON)\s+PATH\s+'([^']+)'", columns):
                fields[alias + "." + name] = f"JSON_EXTRACT({alias}.value,'{field_path}')"
            return f"json_each(g.generation_json,'{path.removesuffix('[*]')}') {alias}"

        # 列引用替换前先处理SQL表函数；没有改变授权条件或提前裁剪测试记录。
        sql = re.sub(r"JSON_TABLE\(g\.generation_json,'([^']+)'\s+COLUMNS\((.*?)\)\)\s+(v|template|b)\b",
                     table, sql, flags=re.S)
        sql = re.sub(r"JSON_TABLE\(JSON_KEYS\(p\.parameter_values\),'\$\[\*\]' COLUMNS\(parameter_name VARCHAR\(240\) PATH '\$'\)\) k",
                     "json_each(JSON_KEYS(p.parameter_values)) k", sql)
        sql = sql.replace("k.parameter_name", "k.value")
        for name, expression in fields.items():
            sql = re.sub(r"\b" + re.escape(name) + r"\b", expression, sql)
        sql = re.sub(r"CONVERT\((.*?) USING utf8mb4\)", r"\1", sql, flags=re.S)
        return original(sql)

    def concatenate(*parts):
        """实现SQLite注册的SQL CONCAT变参回调；该签名由表函数测试协议规定。"""

        return None if any(part is None for part in parts) else "".join(str(part) for part in parts)

    def contains_path(document, mode, path):
        """校验本查询生成的单层JSON键存在性，区分显式null与缺失键。"""

        return int(json.loads(path[2:]) in json.loads(document or "{}"))

    def keys(document):
        """返回参数对象的真实键名数组，供数据库统计整组变化列。"""

        return json.dumps(list(json.loads(document or "{}")))

    def locate(needle, haystack):
        """测试中文与ASCII字面子串匹配，不把百分号和下划线解释为通配符。"""

        return str(haystack).casefold().find(str(needle).casefold()) + 1

    def unquote(value):
        """SQLite JSON_EXTRACT已返回原生标量，因此无需再次剥离引号。"""

        return value

    def binary_compare(left, right):
        """保持模板ID、组ID和参数键的大小写与重音差异，不按搜索规则合并身份。"""

        return (left > right) - (left < right)

    # 仅安装测试方言缺少的内建函数；运行代码仍只依赖既有MySQL。
    database.connection.create_function("CONCAT", -1, concatenate)
    database.connection.create_function("JSON_CONTAINS_PATH", 3, contains_path)
    database.connection.create_function("JSON_KEYS", 1, keys)
    database.connection.create_function("LOCATE", 2, locate)
    database.connection.create_function("JSON_UNQUOTE", 1, unquote)
    database.connection.create_collation("utf8mb4_bin", binary_compare)
    database.connection.create_collation("utf8mb4_0900_as_ci", binary_compare)
    database._sql = translate
    database.case_query_sqlite_installed = True


def grouped_case_page(publication, items, query):
    """将授权候选保存到独立内存库后运行生产分页服务，返回真实SQL归组和分页结果。"""

    service, database, scope = publication
    install_case_query_sqlite(database)
    operations = {operation: index for index, operation in enumerate(sorted({item.get("operation_id", "query-1") for item in items}), 1)}
    for operation, identity in operations.items():
        if not database.fetch_one("SELECT baseline_interface_id FROM ot_baseline_interface WHERE baseline_interface_id=%s", (identity,)):
            seed_interface(database, identity)
        database.execute("UPDATE ot_baseline_interface SET operation_id=%s WHERE baseline_interface_id=%s", (operation, identity))
    # 每次调用替换夹具中的可见集合，隐藏来源不能从上一次断言残留记录取得授权。
    database.execute("DELETE FROM ot_case_draft")
    database.execute("DELETE FROM ot_case")
    database.execute("DELETE FROM ot_case_generation")
    generations = {}
    for item in items:
        generation = generations.setdefault(item["generation_id"], {"created_at": item["generated_at"], "variants": [],
            "case_bindings": [], "submission": {"case_templates": []}})
        generation["variants"].append({"variant_id": item["variant_id"], "template_id": item["template_id"],
            "ordinal": len(generation["variants"]) + 1, "parameter_values": item["parameter_values"], "blocked_reason": ""})
        generation["case_bindings"].append({"case_id": item["case_id"], "variant_id": item["variant_id"],
            "origin_kind": item["origin_kind"], "source_case": item.get("source_case"), "knowledge_dependencies": []})
        templates = generation["submission"]["case_templates"]
        if not any(template["template_id"] == item["template_id"] for template in templates):
            templates.append({"template_id": item["template_id"], "title": item["title"], "coverage_kind": "happy_path"})
        database.execute("INSERT INTO ot_case(case_id,baseline_interface_id,current_generation_id,current_variant_id) VALUES(%s,%s,%s,%s)",
                         (item["case_id"], operations[item.get("operation_id", "query-1")], item["generation_id"], item["variant_id"]))
    for generation_id, payload in generations.items():
        database.execute("INSERT INTO ot_case_generation VALUES(%s,'orders','baseline-one','employee-a',%s)",
                         (generation_id, json.dumps(payload, ensure_ascii=False)))
    return service.case_summary_page(scope, query)


@pytest.mark.parametrize(("summary", "expected"), [
    ({"status": "PARTIAL", "failure_kind": "BEHAVIOR_DIFF"}, "ASSERTION_FAILED"),
    ({"status": "PARTIAL"}, "UNKNOWN"),
    ({"status": "BLOCKED"}, "UNKNOWN"),
    ({"status": "COMPLETED", "cleanup_failed": True}, "CLEANUP_FAILED"),
    ({"status": "PARTIAL", "failure_kind": "OBSERVATION_FAILED", "failed_assertion_count": 1}, "OBSERVATION_FAILED"),
    ({"status": "BLOCKED", "failure_kind": "DATA_PREPARATION_FAILED", "assertions_passed": False}, "DATA_BLOCKED"),
    ({"status": "COMPLETED", "assertions_passed": True}, "PASSED"),
    ({"status": "NOT_RUN"}, "NOT_RUN"),
])
def test_outcome_requires_single_case_evidence(summary, expected):
    """明确业务原因优先，旧PARTIAL/BLOCKED不推断为失败或通过，清理失败不能计通过。"""

    assert case_result_outcome(summary) == expected


def summary_item(case_id, generation_id, parameters, origin="GENERATED", source=None):
    """建立仅含列表授权字段的测试成员；同名标题故意相同以防错误合并独立批次。"""

    return {"case_id": case_id, "generation_id": generation_id, "variant_id": "variant-" + case_id,
            "template_id": "template-one", "title": "相同标题", "origin_kind": origin,
            "source_case": source, "parameter_values": parameters, "generated_at": "2026-10-30T01:00:00Z"}


def test_grouping_precedes_pages_and_retains_full_variation_names(publication):
    """同批参数组先统计后分页；独立批次同标题不合并，子页表头包含全组参数差异。"""

    service, _, _ = publication
    # 缺失state与显式null必须算作差异，不能因单页只有一项就隐藏该参数列。
    items = [summary_item("a", "generation-one", {"id": 1, "state": None}),
             summary_item("b", "generation-one", {"id": 2}), summary_item("c", "generation-two", {"id": 1})]
    page = grouped_case_page(publication, deepcopy(items), CaseListQuery(page_size=1))
    assert page["pagination"] == {"page": 1, "page_size": 1, "total": 2, "has_more": True}
    children = grouped_case_page(publication, deepcopy(items), CaseListQuery(group_id="generation-one:template-one", page_size=1, page=2))
    assert children["pagination"]["total"] == 2 and len(children["items"]) == 1
    assert children["items"][0]["variation_names"] == ["id", "state"]
    assert children["items"][0]["item_count"] == 2


def test_search_finds_case_outside_original_first_page(publication):
    """搜索先于分页，原第二页匹配的Case在搜索首页出现，并使用真实筛选总数。"""

    service, _, _ = publication
    items = [summary_item("a-target", "generation-target", {"id": 1}),
             summary_item("z-first", "generation-first", {"id": 2})]
    items[0]["title"] = "退款验证"
    items[1]["title"] = "普通查询"
    # 相同时间按稳定ID排序，先确认目标确实不在原首页，避免测试只覆盖页面内搜索。
    original = grouped_case_page(publication, deepcopy(items), CaseListQuery(page_size=1))
    assert original["items"][0]["case_id"] == "z-first" and original["pagination"]["has_more"]
    searched = grouped_case_page(publication, deepcopy(items), CaseListQuery(search="  退款  ", page_size=1))
    assert searched["items"][0]["case_id"] == "a-target"
    assert searched["pagination"] == {"page": 1, "page_size": 1, "total": 1, "has_more": False}
    assert searched["counts"]["case_items"] == 1


def test_search_preserves_complete_parameter_group_and_member_pages(publication):
    """组内一条标题命中时全部授权参数成员仍可翻页，组总数和差异参数名不随搜索子页缩水。"""

    service, _, _ = publication
    items = [summary_item("first", "generation-one", {"id": 1}),
             summary_item("second", "generation-one", {"id": 2}),
             summary_item("copy", "generation-copy", {"id": 1}, "COVERAGE_REUSED",
                 {"case_id": "first", "generation_id": "generation-one", "variant_id": "variant-first"})]
    items[0].update(title="同组其他参数", operation_id="Orders.Query")
    items[1].update(title="同组其他参数", operation_id="Orders.Query")
    items[2].update(title="目标参数", operation_id="Orders.Query")
    # 组头及成员页使用相同搜索，后续页不能只保留标题命中的单条参数。
    grouped = grouped_case_page(publication, deepcopy(items), CaseListQuery(search="目标"))
    assert grouped["pagination"]["total"] == 1 and grouped["items"][0]["item_count"] == 3
    members = grouped_case_page(publication, deepcopy(items),
        CaseListQuery(search="目标", group_id="generation-one:template-one", page_size=1, page=2))
    assert members["pagination"]["total"] == 3 and len(members["items"]) == 1
    assert members["items"][0]["variation_names"] == ["id"]
    assert members["counts"]["case_items"] == 3
    by_operation = grouped_case_page(publication, deepcopy(items), CaseListQuery(search="orders.query"))
    assert by_operation["items"][0]["item_count"] == 3


def test_sql_groups_and_parameter_keys_preserve_binary_identity(publication):
    """模板身份与参数键按大小写/重音精确区分，只有标题和接口搜索使用宽松大小写规则。"""

    items = [summary_item("upper-a", "generation-one", {"Id": 1, "id": 1, "e": 0, "é": 0}),
             summary_item("upper-b", "generation-one", {"Id": 2, "id": 3, "e": 1, "é": 2}),
             summary_item("lower", "generation-one", {"private": 1}),
             summary_item("accent", "generation-one", {"private": 1})]
    # 同一Generation的三个不同模板，不能被连接默认的ai_ci整理规则合并。
    for item, template in zip(items, ("Template", "Template", "template", "témplate")):
        item["template_id"] = template
    grouped = grouped_case_page(publication, deepcopy(items), CaseListQuery())
    assert grouped["pagination"]["total"] == 3
    selected = grouped_case_page(publication, deepcopy(items), CaseListQuery(group_id="generation-one:Template"))
    assert selected["pagination"]["total"] == 2
    assert set(selected["items"][0]["variation_names"]) == {"Id", "id", "e", "é"}
    assert all(item["template_id"] == "Template" for item in selected["items"])


def test_database_returns_parameter_bodies_only_for_current_page(publication, monkeypatch):
    """准确计数可查看窄元数据，但27组的参数正文只能返回当前2组，不能先全量传输再裁剪。"""

    _, database, _ = publication
    fetch_all = database.fetch_all
    parameter_rows = []

    def observe(sql, parameters=()):
        """记录数据库实际返回的参数正文行数，不改变SQL结果或模拟分页结论。"""

        rows = fetch_all(sql, parameters)
        parameter_rows.extend(row for row in rows if "parameter_values" in row)
        return rows

    # 相同SQL实现统计全部27组，同时正文查询必须只产生页面的两行。
    monkeypatch.setattr(database, "fetch_all", observe)
    items = [summary_item(f"case-{index:02}", f"generation-{index:02}", {"payload": "large" * 1000}) for index in range(27)]
    page = grouped_case_page(publication, items, CaseListQuery(page_size=2))
    assert page["pagination"]["total"] == 27 and page["counts"]["case_items"] == 27
    assert len(page["items"]) == len(parameter_rows) == 2
    assert len(page["batches"]) == 27


def test_published_pointer_change_between_page_and_details_requires_refresh(publication, monkeypatch):
    """数据库页冻结三元组后发生发布替换时明确失败，不能把新内容套进旧组计数。"""

    service, database, _ = publication
    read_details = service.store.case_summaries

    def replace_before_details(scope, view, operation_id, case_ids):
        """在读取已选页详情前模拟另一员工发布，使原三元组失去当前授权。"""

        database.execute("UPDATE ot_case SET current_generation_id='generation-replaced' WHERE case_id=%s", (case_ids[0],))
        return read_details(scope, view, operation_id, case_ids)

    # 只有详情切片发生替换；列表不得追随稳定case_id静默取另一份Generation。
    monkeypatch.setattr(service.store, "case_summaries", replace_before_details)
    with pytest.raises(KnowledgeValidationError, match="刷新列表"):
        grouped_case_page(publication, [summary_item("case-one", "generation-one", {"id": 1})], CaseListQuery())


def test_search_cannot_match_invisible_source_identity(publication):
    """搜索只匹配当前授权标题和接口，不借复制项来源ID命中或展示不可见原Case。"""

    service, _, _ = publication
    copied = summary_item("visible-copy", "generation-copy", {"id": 1}, "COVERAGE_REUSED",
        {"case_id": "PRIVATE-SOURCE", "generation_id": "private-generation", "variant_id": "private-variant"})
    copied.update(title="基础复测", operation_id="Visible.Query")
    # 已授权集合只含复制项，来源记录存在与否都不能扩充搜索范围或成员数量。
    hidden_match = grouped_case_page(publication, [deepcopy(copied)], CaseListQuery(search="PRIVATE-SOURCE"))
    assert hidden_match["items"] == [] and hidden_match["pagination"]["total"] == 0
    visible_match = grouped_case_page(publication, [deepcopy(copied)], CaseListQuery(search="visible.query"))
    assert visible_match["items"][0]["case_id"] == "visible-copy"
    assert visible_match["items"][0]["source_case"] is None
    assert visible_match["items"][0]["item_count"] == 1


def test_search_length_is_bounded():
    """公开搜索参数限制为200字符，超长查询在API契约校验阶段失败。"""

    assert len(CaseListQuery(search="查" * 200).search) == 200
    with pytest.raises(ValidationError):
        CaseListQuery(search="查" * 201)


def test_replay_uses_visible_stable_source_and_batch_filter_keeps_copy(publication):
    """来源已修订仍按稳定Case归并复测，但标明旧版本；批次筛选保留真实复制成员。"""

    service, _, _ = publication
    # 来源仍是同一稳定Case，但当前Generation已经变化；复测只能归组，不能恢复旧版本授权。
    source = summary_item("base", "generation-new", {"id": 1})
    copy = summary_item("copy", "generation-replay", {"id": 1}, "COVERAGE_REUSED",
        {"case_id": "base", "generation_id": "generation-old", "variant_id": "old-variant"})
    grouped = grouped_case_page(publication, deepcopy([source, copy]), CaseListQuery())
    assert grouped["pagination"]["total"] == 1
    assert grouped["items"][0]["item_count"] == 2
    assert grouped["counts"] == {"business_cases": 1, "replay_cases": 1, "case_items": 2}
    batch = grouped_case_page(publication, deepcopy([source, copy]), CaseListQuery(generation_id="generation-replay"))
    assert batch["items"][0]["case_id"] == "copy" and not batch["items"][0]["source_is_current"]
    hidden = grouped_case_page(publication, [deepcopy(copy)], CaseListQuery())
    assert hidden["items"][0]["source_case"] is None
    assert hidden["items"][0]["source_visibility"] == "unavailable"


def test_visible_selection_requires_current_exact_tuple(publication):
    """同名、旧版本和另一员工草稿均不授权；当前共享选择可在一次批量指针查询中命中。"""

    service, database, scope = publication
    generation = seed_published_case(service, database, scope)
    exact = CaseSelection(case_id="case-public", generation_id=generation.generation_id, variant_id=generation.variants[0].variant_id)
    # 先证明公开指针可读，再撤销公开指针只保留他人草稿，验证不会按作者或旧ID回退。
    assert service.visible_case_selections(scope, [exact])[exact.case_id]["view"] == "published"
    assert not service.visible_case_selections(scope, [exact.model_copy(update={"variant_id": "another-variant"})])
    database.execute("UPDATE ot_case SET current_generation_id=NULL,current_variant_id=NULL WHERE case_id='case-public'")
    database.execute("UPDATE ot_case_draft SET status='READY',owner_user_id='employee-b' WHERE case_id='case-public'")
    assert not service.visible_case_selections(scope, [exact])


def receipt_application(publication, monkeypatch, outcomes):
    """建立真实Case索引与固定请求，只替换执行摘要传输；返回应用、scope和固定选择。"""

    service, database, scope = publication
    generation = seed_published_case(service, database, scope)
    selections = []
    summaries = {}
    # 不同Generation属于同一次请求；真实索引用于后续版本替换和权限收缩验证。
    for index, result in enumerate(outcomes):
        identity = "receipt-case-" + str(index)
        generation_id = generation.generation_id if index == 0 else "case-template-generation-" + str(index) * 20
        variant_id = "case-variant-v4-" + str(index) * 20
        selection = CaseSelection(case_id=identity, generation_id=generation_id, variant_id=variant_id)
        selections.append(selection)
        database.execute("INSERT INTO ot_case(case_id,baseline_interface_id,current_generation_id,current_variant_id) VALUES(%s,1,%s,%s)",
                         (identity, generation_id, variant_id))
        summaries["execution-" + str(index)] = {"system_id": scope.system_id, "baseline_id": scope.baseline_id,
            "generation_id": generation_id, "environment_id": "qa", "status": "PASSED",
            "selected_cases": [selection.model_dump()], "variant_summaries": [dict(result, variant_id=variant_id)] if result else []}
    receipt = {"system_id": scope.system_id, "baseline_id": scope.baseline_id, "owner_user_id": scope.user_id,
               "environment_id": "qa", "request": {"case_selection": [item.model_dump() for item in selections]},
               "execution_ids": list(summaries)}

    def get_receipt(kind, request_id):
        """只给当前固定请求返回回执，缺失身份保持None，便于验证读取不创建请求。"""

        return deepcopy(receipt) if kind == "case_execution_request" and request_id == "request-existing" else None

    def read_summaries(current_scope, execution_ids):
        """只返回被请求的执行ID，模拟数据库已按系统和基准授权的摘要传输。"""

        return {identity: deepcopy(summaries[identity]) for identity in execution_ids}

    def read_titles(current_scope, view, operation_id, case_ids):
        """基于固定选择返回标题，不提供请求外Case或其他Generation的正文。"""

        return [item.model_dump() | {"title": "可见标题"} for item in selections if item.case_id in case_ids]

    monkeypatch.setattr(database, "get_workflow", get_receipt, raising=False)
    monkeypatch.setattr(service.store, "execution_summaries", read_summaries)
    monkeypatch.setattr(service.store, "case_summaries", read_titles)
    application = SimpleNamespace(publications=service, store=SimpleNamespace(metadata=database))
    return application, scope, selections


def test_receipt_keeps_cross_generation_denominator_when_filtering(publication, monkeypatch):
    """跨批请求按原三个实际Case统计，筛选通过明细不把成功率改成100%。"""

    # 三种明确终态独立计数；只看通过项时仍使用原始三个Case作为成功率分母。
    application, scope, _ = receipt_application(publication, monkeypatch, [
        {"status": "COMPLETED"}, {"status": "PARTIAL", "failure_kind": "BEHAVIOR_DIFF"},
        {"status": "BLOCKED", "failure_kind": "ENVIRONMENT_DEPENDENCY"}])
    result = execution_request_projection(application, scope, "request-existing", CaseExecutionReceiptQuery(outcome="PASSED"))
    assert result["pass_rate"] == pytest.approx(1 / 3) and result["terminal"]
    assert result["counts"]["completed"] == 3 and result["counts"]["failed"] == 1 and result["counts"]["blocked"] == 1
    assert result["pagination"]["total"] == 1 and result["items"][0]["title"] == "可见标题"


def test_receipt_hides_replaced_items_and_disables_whole_rate(publication, monkeypatch):
    """一个选择变旧即关闭整批成功率，全部变旧明确不可用，不用剩余可见项重算分母。"""

    application, scope, selections = receipt_application(publication, monkeypatch,
        [{"status": "COMPLETED"}, {"status": "FAILED", "error": "PRIVATE-OLD-RESULT"}])
    database = application.store.metadata
    # 先隐藏失败项再隐藏剩余项，观察两种权限收缩都不能把旧报告变成全批成功。
    database.execute("UPDATE ot_case SET current_generation_id='replaced' WHERE case_id=%s", (selections[1].case_id,))
    result = execution_request_projection(application, scope, "request-existing", CaseExecutionReceiptQuery())
    assert result["visibility"] == "partial" and result["pass_rate"] is None
    assert result["counts"]["planned"] == 2 and result["counts"]["visible"] == 1
    assert "PRIVATE" not in json.dumps(result)
    database.execute("UPDATE ot_case SET current_generation_id='replaced' WHERE case_id=%s", (selections[0].case_id,))
    unavailable = execution_request_projection(application, scope, "request-existing", CaseExecutionReceiptQuery())
    assert unavailable["visibility"] == "unavailable" and unavailable["pass_rate"] is None and unavailable["items"] == []


def test_receipt_legacy_unknown_and_other_owner_do_not_imply_success(publication, monkeypatch):
    """旧摘要没有逐项结果时保留未知；其他员工不能因知道request ID读取回执。"""

    # 缺少结果是未知，不能从整批PASSED替当前单项推断通过。
    application, scope, _ = receipt_application(publication, monkeypatch, [{}])
    result = execution_request_projection(application, scope, "request-existing", CaseExecutionReceiptQuery())
    assert result["counts"]["unknown"] == 1 and not result["terminal"] and result["pass_rate"] is None
    with pytest.raises(KnowledgeNotFoundError):
        execution_request_projection(application, scope.model_copy(update={"user_id": "employee-b"}),
            "request-existing", CaseExecutionReceiptQuery())


def test_running_projection_distinguishes_active_from_queued(publication):
    """运行中只给当前variant展示阶段和真实开始时间，其余固定选择保持等待且不泄露同批结果。"""

    service, _, _ = publication
    first = CaseSelection(case_id="first", generation_id="generation", variant_id="variant-first")
    second = CaseSelection(case_id="second", generation_id="generation", variant_id="variant-second")
    summary = {"status": "RUNNING", "selected_cases": [first.model_dump(), second.model_dump()],
        "current_variant_id": first.variant_id, "current_variant_started_at": "2026-10-30T00:00:00Z", "current_phase": "DATA"}
    # 同一份运行摘要只允许当前执行项读取阶段，等待项没有伪造的开始时间。
    active = service.project_execution_summary(first, "execution", summary)
    queued = service.project_execution_summary(second, "execution", summary)
    assert active["outcome"] == "RUNNING" and active["current_phase"] == "DATA" and active["started_at"]
    assert queued["outcome"] == "WAITING" and queued["started_at"] is None and queued["current_phase"] is None


def json_contains(document, candidate):
    """为SQLite回归实现MySQL精确选择包含谓词，保留实际SQL筛选与LIMIT顺序。"""

    if document is None:
        return None
    return json.loads(candidate) in json.loads(document)


def json_length(document):
    """为测试数据库提供JSON数组长度，NULL不伪造为空数组。"""

    return len(json.loads(document)) if document is not None else None


def test_history_filters_exact_selection_before_pagination(publication):
    """大量同批其他Case执行不能挤掉当前Case首屏，环境和总数在同一SQL谓词中准确过滤。"""

    service, database, scope = publication
    generation = seed_published_case(service, database, scope)
    selection = CaseSelection(case_id="case-public", generation_id=generation.generation_id, variant_id=generation.variants[0].variant_id)
    database.execute("ALTER TABLE ot_execution ADD COLUMN summary_json TEXT")
    database.connection.create_function("JSON_CONTAINS", 2, json_contains)
    database.connection.create_function("JSON_LENGTH", 1, json_length)
    # 把不属于当前Case的执行交错插入，验证LIMIT之前已应用精确选择而非分页后过滤。
    for index in range(45):
        selected = selection.model_dump()
        if index % 2:
            selected["case_id"] = "private-case"
        # 本测试只验证新格式的SQL候选范围，旧格式正文补齐另由下方回归覆盖。
        summary = {"selected_cases": [selected], "variant_summaries": []}
        database.execute("INSERT INTO ot_execution(execution_id,execution_kind,system_id,baseline_id,generation_id,environment_id,created_at,summary_json) "
            "VALUES(%s,'case','orders','baseline-one',%s,%s,%s,%s)",
            (f"execution-{index:02}", generation.generation_id, "uat" if index == 44 else "qa", f"2026-10-30T00:00:{index:02}Z", json.dumps(summary)))
    page = service.store.case_execution_page(scope, selection, CaseExecutionQuery(environment_id="qa", page_size=20))
    assert page["total"] == 22 and len(page["rows"]) == 20 and page["has_more"]
    next_page = service.store.case_execution_page(scope, selection,
        CaseExecutionQuery(environment_id="qa", page_size=20, before_execution_id=page["next_cursor"]))
    assert len(next_page["rows"]) == 2 and not next_page["has_more"]
    assert not {item["execution_id"] for item in page["rows"]}.intersection(item["execution_id"] for item in next_page["rows"])
    # 无选择的旧记录仅是需正文确认的候选；总数未知且下一游标仍来自实际扫描窗口。
    database.execute("INSERT INTO ot_execution(execution_id,execution_kind,system_id,baseline_id,generation_id,environment_id,created_at,summary_json) "
        "VALUES('legacy-execution','case','orders',NULL,%s,'qa','2026-10-30T01:00:00Z','{}')", (generation.generation_id,))
    legacy = service.store.case_execution_page(scope, selection, CaseExecutionQuery(environment_id="qa", page_size=1))
    assert legacy["total"] is None and legacy["next_cursor"] == "legacy-execution" and legacy["has_more"]


@pytest.fixture
def legacy_history(publication, monkeypatch):
    """建立当前可见Case及含压缩正文的真实执行表，返回服务、数据库、scope与精确选择。"""

    service, database, scope = publication
    generation = seed_published_case(service, database, scope)
    selection = CaseSelection(case_id="case-public", generation_id=generation.generation_id,
                              variant_id=generation.variants[0].variant_id)
    database.execute("ALTER TABLE ot_execution ADD COLUMN summary_json TEXT")
    database.execute("ALTER TABLE ot_execution ADD COLUMN payload_gzip BLOB")
    database.connection.create_function("JSON_CONTAINS", 2, json_contains)
    database.connection.create_function("JSON_LENGTH", 1, json_length)

    def no_receipts(current_scope, execution_ids):
        """此夹具未建立请求回执，历史关联为空；执行查询和授权仍走真实生产SQL。"""

        return {}

    # 本组只覆盖结果补齐；回执关联JSON_TABLE已在真实MySQL验收，避免测试方模拟业务过滤。
    monkeypatch.setattr(service.store, "execution_requests", no_receipts)
    return service, database, scope, selection


def legacy_execution_payload(scope, selection, index, variant_result):
    """构造缺少新字段的旧正文；scope/selection固定范围与三键，index区分身份，空结果不补造。"""

    # 不经新模型dump，确保缺少variant_summaries和真实起止时间的历史形状未被默认值掩盖。
    return {"execution_id": f"case-generation-execution-{index:020x}", "system_id": scope.system_id,
            "baseline_id": scope.baseline_id, "generation_id": selection.generation_id,
            "environment_id": "qa", "selected_cases": [selection.model_dump()], "status": "PASSED",
            "created_at": f"2026-10-30T00:00:{index:02}Z", "updated_at": f"2026-10-30T00:00:{index:02}Z",
            "variant_results": [{"variant_id": selection.variant_id, **variant_result}] if variant_result else []}


def insert_legacy_execution(database, payload):
    """按旧保存格式写入测试执行，摘要只排除逐项完整结果；返回ID，运行产品读接口不写库。"""

    # 重现旧存储只剥离大结果的格式，不生成当前版本才有的逐项摘要键。
    summary = {key: value for key, value in payload.items() if key != "variant_results"}
    database.execute("INSERT INTO ot_execution(execution_id,execution_kind,system_id,baseline_id,generation_id,environment_id,"
        "created_at,summary_json,payload_gzip) VALUES(%s,'case',%s,%s,%s,%s,%s,%s,%s)",
        (payload["execution_id"], payload["system_id"], payload["baseline_id"], payload["generation_id"],
         payload["environment_id"], payload["created_at"], json.dumps(summary), pack_json(payload)))
    return payload["execution_id"]


@pytest.mark.parametrize("variant_result,outcome", [
    ({"status": "COMPLETED"}, "PASSED"),
    ({"status": "PARTIAL", "failure_kind": "BEHAVIOR_DIFF", "assertions": [{"oracle_id": "oracle-1",
      "actual_path": "status", "operator": "eq", "passed": False}]}, "ASSERTION_FAILED"),
    (None, "UNKNOWN"),
])
def test_legacy_history_restores_only_actual_variant_result(legacy_history, variant_result, outcome):
    """旧摘要有精确选择时恢复正文真实通过/失败，无结果保留未知，created_at不充当起止时间。"""

    service, database, scope, selection = legacy_history
    payload = legacy_execution_payload(scope, selection, 1, variant_result)
    insert_legacy_execution(database, payload)
    before = database.connection.total_changes
    # 整批PASSED不能覆盖实际单项失败或无结果，且读完后旧摘要仍保持旧格式。
    page = service.case_execution_summary_page(scope, selection.case_id, CaseExecutionQuery(environment_id="qa"))
    assert len(page["items"]) == 1 and page["items"][0]["outcome"] == outcome
    assert page["items"][0]["started_at"] is None and page["items"][0]["ended_at"] is None
    assert database.connection.total_changes == before
    stored = database.fetch_one("SELECT summary_json FROM ot_execution WHERE execution_id=%s", (payload["execution_id"],))
    assert "variant_summaries" not in json.loads(stored["summary_json"])


@pytest.mark.parametrize("migrated_index", [False, True])
def test_legacy_history_keeps_nullable_baseline_contract(legacy_history, migrated_index):
    """历史正文基准为空仍按原详情规则读取，迁移只补索引和摘要基准不会让真实结果不可用。"""

    service, database, scope, selection = legacy_history
    payload = legacy_execution_payload(scope, selection, 1, {"status": "COMPLETED"})
    payload["baseline_id"] = None
    execution_id = insert_legacy_execution(database, payload)
    if migrated_index:
        # 模拟已有迁移事实，读取实现不得补写或篡改仍为NULL的历史正文。
        summary = {key: value for key, value in payload.items() if key != "variant_results"}
        summary["baseline_id"] = scope.baseline_id
        database.execute("UPDATE ot_execution SET baseline_id=%s,summary_json=%s WHERE execution_id=%s",
                         (scope.baseline_id, json.dumps(summary), execution_id))
    before = database.connection.total_changes
    page = service.case_execution_summary_page(scope, selection.case_id, CaseExecutionQuery(environment_id="qa"))
    assert page["items"][0]["outcome"] == "PASSED" and database.connection.total_changes == before


def test_legacy_history_reads_only_current_page_in_one_batch(legacy_history, monkeypatch):
    """先分页再批读旧正文，不读取上一页、has_more探测行、跨范围或非精确选择的执行。"""

    service, database, scope, selection = legacy_history
    visible_ids = []
    for index in range(5):
        visible_ids.append(insert_legacy_execution(database,
            legacy_execution_payload(scope, selection, index, {"status": "COMPLETED"})))
    # 外部记录时间更新，若权限或三键过滤被挪到LIMIT之后会挤占页面并读到这些正文。
    excluded = [("system_id", "private-system"), ("baseline_id", "private-baseline"),
                ("environment_id", "uat"), ("case_id", "private-case"),
                ("generation_id", "case-template-generation-" + "d" * 20),
                ("variant_id", "case-variant-v4-" + "d" * 20)]
    for index, (field, replacement) in enumerate(excluded, start=5):
        payload = legacy_execution_payload(scope, selection, index, {"status": "FAILED", "error": "PRIVATE"})
        if field in {"system_id", "baseline_id", "environment_id", "generation_id"}:
            payload[field] = replacement
        if field in {"case_id", "generation_id", "variant_id"}:
            payload["selected_cases"][0][field] = replacement
        insert_legacy_execution(database, payload)
    original = database.fetch_all
    payload_batches = []

    def fetch_all(sql, parameters=()):
        """记录生产SQL实际返回的正文ID，不在测试端过滤或改写结果。"""

        rows = original(sql, parameters)
        if "payload_gzip" in sql:
            payload_batches.append([row["execution_id"] for row in rows])
        return rows

    monkeypatch.setattr(database, "fetch_all", fetch_all)
    before = database.connection.total_changes
    page = service.case_execution_summary_page(scope, selection.case_id,
        CaseExecutionQuery(environment_id="qa", page=2, page_size=2))
    assert page["pagination"]["total"] == 5 and page["pagination"]["has_more"]
    assert [item["execution_id"] for item in page["items"]] == visible_ids[1:3][::-1]
    assert len(payload_batches) == 1 and set(payload_batches[0]) == set(visible_ids[1:3])
    assert "PRIVATE" not in json.dumps(page) and database.connection.total_changes == before


@pytest.mark.parametrize("with_result", [False, True])
def test_new_summary_even_empty_never_reads_execution_body(legacy_history, monkeypatch, with_result):
    """已保存variant_summaries键的新记录只用摘要，即使空数组也不读取正文推断结果。"""

    service, database, scope, selection = legacy_history
    payload = legacy_execution_payload(scope, selection, 1, {"status": "COMPLETED"})
    payload["variant_summaries"] = [{"variant_id": selection.variant_id, "status": "COMPLETED"}] if with_result else []
    execution_id = insert_legacy_execution(database, payload)
    database.execute("UPDATE ot_execution SET payload_gzip=%s WHERE execution_id=%s", (b"unreadable", execution_id))
    original = database.fetch_all

    def fetch_all(sql, parameters=()):
        """将任何新格式正文读取变成确定性失败，摘要查询仍由数据库执行。"""

        assert "payload_gzip" not in sql
        return original(sql, parameters)

    monkeypatch.setattr(database, "fetch_all", fetch_all)
    # 同时走历史页和回执共用的摘要入口，防止修一处却让另一处回退读取。
    history = service.case_execution_summary_page(scope, selection.case_id, CaseExecutionQuery(environment_id="qa"))
    summaries = service.store.execution_summaries(scope, [execution_id])
    assert history["items"][0]["outcome"] == ("PASSED" if with_result else "UNKNOWN")
    assert summaries[execution_id]["variant_summaries"] == payload["variant_summaries"]


@pytest.mark.parametrize("field,replacement", [
    ("system_id", "private-system"), ("baseline_id", "private-baseline"), ("environment_id", "uat"),
    ("generation_id", "case-template-generation-" + "d" * 20),
    ("execution_id", "case-generation-execution-" + "d" * 20),
    ("selected.case_id", "private-case"), ("selected.generation_id", "case-template-generation-" + "d" * 20),
    ("selected.variant_id", "case-variant-v4-" + "d" * 20),
])
def test_legacy_body_must_match_index_scope_and_exact_selection(legacy_history, field, replacement):
    """摘要与旧正文的系统、基准、环境、执行身份及Case三键不一致时明确拒绝，不借用结果。"""

    service, database, scope, selection = legacy_history
    payload = legacy_execution_payload(scope, selection, 1, {"status": "COMPLETED"})
    execution_id = insert_legacy_execution(database, payload)
    # 只破坏正文，保留授权索引和摘要，验证批量读取后仍检查完整来源身份。
    if field.startswith("selected."):
        payload["selected_cases"][0][field.split(".")[1]] = replacement
    else:
        payload[field] = replacement
    database.execute("UPDATE ot_execution SET payload_gzip=%s WHERE execution_id=%s", (pack_json(payload), execution_id))
    with pytest.raises(KnowledgeValidationError, match="范围不一致|精确选择不一致"):
        service.case_execution_summary_page(scope, selection.case_id, CaseExecutionQuery(environment_id="qa"))


@pytest.mark.parametrize("failure", ["missing", "corrupt", "database"])
def test_legacy_body_read_failure_is_not_an_empty_result(legacy_history, monkeypatch, failure):
    """旧正文缺失、压缩损坏或数据库异常均显式失败，不能静默变为UNKNOWN或无执行记录。"""

    service, database, scope, selection = legacy_history
    payload = legacy_execution_payload(scope, selection, 1, {"status": "COMPLETED"})
    execution_id = insert_legacy_execution(database, payload)
    if failure == "corrupt":
        database.execute("UPDATE ot_execution SET payload_gzip=%s WHERE execution_id=%s", (b"invalid", execution_id))
    original = database.fetch_all

    def fetch_all(sql, parameters=()):
        """只在第二次正文读取边界注入消失或存储错误，前一阶段摘要查询保持真实。"""

        if "payload_gzip" in sql and failure == "missing":
            return []
        if "payload_gzip" in sql and failure == "database":
            raise RuntimeError("database unavailable")
        return original(sql, parameters)

    monkeypatch.setattr(database, "fetch_all", fetch_all)
    expected = {"missing": KnowledgeNotFoundError, "corrupt": KnowledgeValidationError, "database": RuntimeError}[failure]
    with pytest.raises(expected):
        service.store.execution_summaries(scope, [execution_id])


def test_legacy_receipt_recovers_real_success_rate_from_fixed_executions(legacy_history, monkeypatch):
    """原请求的旧执行正文批量补齐后按真实单项统计成功率，其他请求与不可见选择不成为分母。"""

    service, database, scope, first = legacy_history
    second = CaseSelection(case_id="case-second", generation_id=first.generation_id,
                           variant_id="case-variant-v4-" + "b" * 20)
    database.execute("INSERT INTO ot_case(case_id,baseline_interface_id,current_generation_id,current_variant_id) VALUES(%s,1,%s,%s)",
                     (second.case_id, second.generation_id, second.variant_id))
    payload = legacy_execution_payload(scope, first, 1, {"status": "COMPLETED"})
    payload["selected_cases"].append(second.model_dump())
    payload["variant_results"].append({"variant_id": second.variant_id, "status": "PARTIAL", "failure_kind": "BEHAVIOR_DIFF"})
    execution_id = insert_legacy_execution(database, payload)
    unrelated_id = insert_legacy_execution(database, legacy_execution_payload(scope, first, 2, {"status": "COMPLETED"}))
    database.execute("UPDATE ot_execution SET payload_gzip=%s WHERE execution_id=%s", (b"unrelated", unrelated_id))
    receipt = {"system_id": scope.system_id, "baseline_id": scope.baseline_id, "owner_user_id": scope.user_id,
               "environment_id": "qa", "request": {"case_selection": [first.model_dump(), second.model_dump()]},
               "execution_ids": [execution_id]}

    def get_receipt(kind, request_id):
        """返回一个已有请求，查询不得修改它或扩展执行ID集合。"""

        assert kind == "case_execution_request" and request_id == "request-existing"
        return deepcopy(receipt)

    def no_titles(current_scope, view, operation_id, case_ids):
        """本组只验证旧执行统计，标题缺席不影响真实索引授权与结果匹配。"""

        return []

    monkeypatch.setattr(database, "get_workflow", get_receipt, raising=False)
    monkeypatch.setattr(service.store, "case_summaries", no_titles)
    application = SimpleNamespace(publications=service, store=SimpleNamespace(metadata=database))
    before = database.connection.total_changes
    result = execution_request_projection(application, scope, "request-existing", CaseExecutionReceiptQuery())
    assert result["pass_rate"] == 0.5 and result["terminal"]
    assert result["counts"]["passed"] == 1 and result["counts"]["failed"] == 1 and result["counts"]["unknown"] == 0
    assert result["started_at"] is None and result["ended_at"] is None
    assert database.connection.total_changes == before
    # 请求环境和三键仍在摘要消费时精确匹配，正文补齐不能放宽原回执规则。
    receipt["environment_id"] = "uat"
    wrong_environment = execution_request_projection(application, scope, "request-existing", CaseExecutionReceiptQuery())
    assert wrong_environment["counts"]["unknown"] == 2 and wrong_environment["pass_rate"] is None


def test_case_directory_uses_only_visible_indexes(publication, monkeypatch):
    """首屏历史接口目录只查索引计数，生成摘要和正文即使不可用也不会被读取。"""

    service, database, scope = publication
    seed_published_case(service, database, scope)
    database.execute("UPDATE ot_baseline_interface SET availability='REMOVED' WHERE baseline_interface_id=1")

    def reject_generation_read(current_scope, view, operation_id):
        """将意外Generation访问变成确定性失败；目录必须只依赖可见Case指针。"""

        raise AssertionError("目录不应读取Generation")

    # 已移除接口仍存在可读Case，目录不能因接口不在共享列表而丢入口。
    monkeypatch.setattr(service.store, "case_summaries", reject_generation_read)
    page = service.case_summary_page(scope, CaseListQuery(representation="summary", directory_only=True))
    assert page == {"operations": [{"operation_id": "query-1", "case_count": 1}]}
