"""独立浏览器验收服务：仅内存测试数据，运行真实Web资产，绝不接入业务服务。

在仓库根目录运行 python3 -m uvicorn case_fixture_server:app --app-dir tests/web --port 8789。
POST /__test__/finish 将本地替身批次推进到终态；重启即丢弃全部验收状态。
"""
from copy import deepcopy
import asyncio
from pathlib import Path
import re
import time

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

WEB = Path(__file__).resolve().parents[2] / "opentest" / "web"
SYSTEM = "presentation.test.system"
GENERATION = "case-template-generation-" + "a" * 20
OPERATION = "job:Inspection#run"
VERSION = re.search(r'name="opentest-page-version" content="([^"]+)"', (WEB / "index.html").read_text())[1]
app = FastAPI()
app.mount("/assets", StaticFiles(directory=WEB), name="assets")
COMPLEX = {"nil": None, "object": {}, "array": [], "text": "", "zero": 0, "disabled": False,
           "items": [{"name": "第一项", "tags": ["A", "B"]}, None, 0, False, {"name": "最后一项"}],
           "long": "明确标注的隔离测试长内容。" * 40}
TEMPLATE = {"template_id": "inspection", "title": "开发验收：不同准备状态的检查", "coverage_kind": "business",
            "parameters": [{"name": "state", "function_id": "enum.values"}],
            "request_bindings": [{"field": "id", "source": {"kind": "data_output", "call_id": "lookup", "output_name": "id"}},
                                 {"field": "reason", "source": {"kind": "parameter", "name": "state", "path": "code"}},
                                 {"field": "options", "source": {"kind": "literal", "value": COMPLEX}}]}
ORACLE = {"oracle_id": "business", "channel": "response", "assertions": [
    {"actual_path": "accepted", "operator": "eq", "expected": {"kind": "literal", "value": False}}]}
VARIANTS = [{"variant_id": "case-variant-v4-" + str(i) * 20, "template_id": "inspection", "ordinal": i,
             "parameter_values": {"state": {"code": i, "name": name}}, "request_values": {"reason": i, "options": COMPLEX},
             "data_calls": [{"call_id": "lookup", "function_name": "find_record", "arguments": {"state": {"kind": "parameter", "name": "state", "path": "code"}}}],
             "oracles": [ORACLE], "cleanup": {"operation_id": "job:Cleanup#run", "arguments": {}}}
            for i, name in enumerate(["预期拒绝", "校验失败", "准备阻塞", "调用出错", "清理异常", "尚无结果"], 1)]
GEN = {"generation_id": GENERATION, "system_id": SYSTEM, "operation_id": OPERATION, "status": "READY", "created_at": "2026-09-08T08:00:00Z",
       "input_contract": {"fields": [{"path": "id", "description": "记录编号"}, {"path": "reason", "description": "检查条件"}, {"path": "options", "description": "复杂参数", "schema": {"type": "object"}}]},
       "submission": {"case_templates": [TEMPLATE], "data_functions": [{"name": "find_record", "description": "从隔离测试集合取得指定状态的记录"}]}, "variants": VARIANTS}


def fixture_result(index: int) -> dict:
    """按子用例序号构造既有报告形状，返回内存阶段和断言；没有外部调用。"""
    # 故意覆盖准备、目标、校验、清理四种失败边界及正确拒绝。
    target = {"stage_id": "target", "phase": "TARGET", "execution_id": "fixture-target", "function_id": OPERATION, "status": "COMPLETED",
              "actual_request": {"id": "LOCAL-ONLY-" + str(index), "options": COMPLEX},
              "actual_response": {"accepted": index == 2, "extra": COMPLEX}}
    assertions = [{"oracle_id": "business", "actual_path": "accepted", "operator": "eq", "expected_value": False, "actual_value": index == 2, "passed": index != 2, "error": "实际观测不符合预期拒绝" if index == 2 else ""}]
    operations = [{"phase": "DATA", "stage_id": "data:lookup", "function_id": "fixture.lookup", "status": "COMPLETED"}, target]
    status, error = "COMPLETED", ""
    if index == 2:
        status = "PARTIAL"
    elif index == 3:
        status, error, operations, assertions = "BLOCKED", "准备数据不满足：没有指定状态记录，目标尚未调用", [], []
    elif index == 4:
        status, error, assertions = "FAILED", "本地替身调用超时", []
        target.update(status="FAILED", error=error)
    elif index == 5:
        status = "FAILED"
        operations.append({"phase": "CLEANUP", "stage_id": "cleanup", "function_id": "fixture.cleanup", "status": "FAILED", "error": "隔离测试清理工具超时"})
    return {"variant_id": VARIANTS[index - 1]["variant_id"], "status": status, "error": error, "operations": operations, "assertions": assertions}


BATCHES = [{"contract_version": "case-generation-execution/v1", "execution_id": "case-generation-execution-" + digit * 20,
            "generation_id": GENERATION, "system_id": SYSTEM, "environment_id": env, "created_at": date, "status": "PARTIAL",
            "variant_results": [fixture_result(i) for i in range(1, 7)]}
           for digit, env, date in [("b", "qa", "2026-09-08T09:00:00Z"), ("c", "qa", "2026-09-08T08:30:00Z"), ("d", "isolated", "2026-09-08T08:00:00Z")]]

# 共享工作台覆盖增强验收数据；页面和接口都走真实生产资产，只替换内存数据。
SHARED_OPERATION = "facade:example.RefundFacade#billSupplement"
SHARED_BASELINE = {"baseline_id": "baseline-fixture", "system_id": SYSTEM,
                   "source_commit": "a" * 40, "selected_revision": "fixture-v1",
                   "created_at": "2026-10-26T05:00:00Z"}
SHARED_INTERFACE = {"operation_id": SHARED_OPERATION, "baseline_interface_id": 1,
                    "interface_id": 1, "status": "READY", "contract_revision": 0,
                    "operation_summary": "账单补单", "scan_id": "scan-fixture"}
SHARED_CASE = {"case_id": "case-fixture-1", "baseline_id": "baseline-fixture",
               "baseline_interface_id": 1, "operation_id": SHARED_OPERATION,
               "generation_id": GENERATION, "source_scan_id": "scan-fixture",
               "view": "published", "publication_revision": 1,
               "template_id": "inspection", "title": "BSP已退款完成退票单重复补单幂等成功",
               "coverage_kind": "business", "impact_status": "CURRENT",
               "input_contract": {}, "data_functions": [], "knowledge_dependencies": [],
               "variant": deepcopy(VARIANTS[0])}
SHARED_ADDED_CASES = [
    {"case_id": "case-added-1", "title": "无原交易单时拒绝补单", "variant": 0},
    {"case_id": "case-added-2", "title": "退票类型待人工确认", "variant": 1},
    {"case_id": "case-added-3", "title": "退款金额为零的边界校验", "variant": 2},
    {"case_id": "case-added-4", "title": "下游服务超时返回处理", "variant": 3},
    {"case_id": "case-added-5", "title": "重复补单的幂等校验", "variant": 4},
    {"case_id": "case-added-6", "title": "已退款完成状态校验", "variant": 5},
]
SHARED_CASES = [SHARED_CASE] + [
    {**SHARED_CASE, "case_id": item["case_id"], "title": item["title"],
     "variant": deepcopy(VARIANTS[item["variant"]])}
    for item in SHARED_ADDED_CASES
]
SHARED_CASE_BY_ID = {item["case_id"]: item for item in SHARED_CASES}
SHARED_COVERAGE = {
    "enhancement_id": "coverage-fixture",
    "operation_id": SHARED_OPERATION,
    "status": "COMPLETED",
    "stage": "FINISHED",
    "environment_id": "qa",
    "latest_at": "2026-10-26T06:32:00Z",
    "reason_codes": [],
    "baseline": {"status": "VALID", "valid": True, "line": {"covered": 52, "missed": 20, "percent": 72.2},
                 "method": {"covered": 3, "missed": 1, "percent": 75.0},
                 "branch": {"covered": 12, "missed": 8, "percent": 60.0},
                 "scope_status": "PARTIAL", "scope_reason": "仅纳入可信已解析调用闭包。",
                 "candidate_gap_count": 3, "deferred_gap_count": 0},
    "verification": {"status": "VALID", "valid": True, "line": {"covered": 60, "missed": 10, "percent": 85.6},
                     "method": {"covered": 4, "missed": 0, "percent": 100.0},
                     "branch": {"covered": 16, "missed": 4, "percent": 80.0},
                     "scope_status": "PARTIAL", "scope_reason": "仅纳入可信已解析调用闭包。",
                     "candidate_gap_count": 3, "deferred_gap_count": 0},
    "coverage_phase": "verification", "line_percent": 85.6,
    "added_cases": [
        {"case_id": "case-added-1", "variant_id": VARIANTS[0]["variant_id"], "generation_id": GENERATION,
         "title": "无原交易单时拒绝补单", "view": "published", "verification": "PASSED", "execution_status": "COMPLETED"},
        {"case_id": "case-added-2", "variant_id": VARIANTS[1]["variant_id"], "generation_id": GENERATION,
         "title": "退票类型待人工确认", "view": "published", "verification": "PASSED", "execution_status": "COMPLETED"},
        {"case_id": "case-added-3", "variant_id": VARIANTS[2]["variant_id"], "generation_id": GENERATION,
         "title": "退款金额为零的边界校验", "view": "published", "verification": "PASSED", "execution_status": "COMPLETED"},
        {"case_id": "case-added-4", "variant_id": VARIANTS[3]["variant_id"], "generation_id": GENERATION,
         "title": "下游服务超时返回处理", "view": "published", "verification": "PASSED", "execution_status": "COMPLETED"},
        {"case_id": "case-added-5", "variant_id": VARIANTS[4]["variant_id"], "generation_id": GENERATION,
         "title": "重复补单的幂等校验", "view": "published", "verification": "PASSED", "execution_status": "COMPLETED"},
        {"case_id": "case-added-6", "variant_id": VARIANTS[5]["variant_id"], "generation_id": GENERATION,
         "title": "已退款完成状态校验", "view": "published", "verification": "PASSED", "execution_status": "COMPLETED"},
    ],
    "added_case_counts": {"total": 6, "passed": 6, "failed": 0, "pending": 0},
    "uncovered": [
        {"source_path": "app/validator/src/main/java/com/ly/flight/chainsaas/refund/validator/RefundValidator.java",
         "class_name": "com/ly/flight/chainsaas/refund/validator/RefundValidator", "method_name": "validateRefund",
         "ranges": [{"start": 92, "end": 99}], "line_count": 8, "whole_method": True, "kinds": ["METHOD"]},
        {"source_path": "app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/BillSupplementService.java",
         "class_name": "com/ly/flight/chainsaas/refund/facade/impl/BillSupplementService", "method_name": "handleSupplement",
         "ranges": [{"start": 216, "end": 227}], "line_count": 12, "whole_method": True, "kinds": ["METHOD"]},
        {"source_path": "app/facade-impl/src/main/java/com/ly/flight/chainsaas/refund/facade/impl/RefundCallbackHandler.java",
         "class_name": "com/ly/flight/chainsaas/refund/facade/impl/RefundCallbackHandler", "method_name": "onFailure",
         "ranges": [{"start": 68, "end": 73}], "line_count": 6, "whole_method": True, "kinds": ["METHOD"]},
    ],
    "uncovered_summary": {"location_count": 3, "line_count": 26, "whole_method_count": 3,
                          "candidate_gap_count": 3, "deferred_gap_count": 0},
    "source_available": True, "attribution": "UNVERIFIED", "verified_resolved_count": None,
    "anchor_case": {"case_id": "case-fixture-1", "variant_id": VARIANTS[0]["variant_id"],
                    "generation_id": GENERATION, "view": "published"},
    "case_count": 1, "verification_case_count": 7,
    "scope_status": "PARTIAL", "scope_reason": "仅纳入可信已解析调用闭包。",
    "candidate_gap_count": 3, "deferred_gap_count": 0,
}

@app.get("/console")
def console() -> FileResponse:
    """返回仓库当前真实HTML；无静态替代页面或浏览器状态注入。"""
    return FileResponse(WEB / "index.html")


@app.post("/__test__/finish")
def finish() -> dict:
    """仅推进本进程中的测试批次，返回结果数量供浏览器验收确认。"""
    # 结果按现有执行器整批落盘的时机一次到达。
    batch = BATCHES[0]
    batch.update(status="PARTIAL", variant_results=[fixture_result(i) for i in range(1, 7)])
    return {"recorded": 6}


@app.api_route("/api/v2/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def fixture_api(path: str, request: Request):
    """为真实页面提供明确标注的测试HTTP数据；只允许本地替身执行写入。

    Args:
        path: 页面请求的API相对路径。
        request: 用于区分读取与执行，读取实际提交的环境。
    Returns:
        内存API数据或拒绝未知写入的403；永不转发网络请求。
    """
    if request.method != "GET":
        if request.method == "POST" and path.endswith("/executions"):
            body = await request.json()
            batch = deepcopy(BATCHES[0])
            batch.update(execution_id="case-generation-execution-" + "e" * 20, status="RUNNING", environment_id=body["environment_id"], variant_results=[], created_at="2026-09-08T10:00:00Z")
            BATCHES.insert(0, batch)
            return {"execution": batch}
        return JSONResponse({"detail": "隔离验收服务不支持该写操作"}, status_code=403)
    # 非Case页面只获得空目录，避免启动源码扫描、Agent或真实业务工具。
    if path == "health": return {"version": "0.2.0 · 隔离验收", "page_version": VERSION}
    if path == "auth/session": return {"authenticated": True, "csrf_token": "fixture-csrf",
        "expires_at": time.time() + 3600, "employee": {"user_id": "1214259", "name": "隔离验收",
        "display_name": "隔离验收-1214259"}}
    if path.endswith("/baselines"): return {"baselines": [SHARED_BASELINE]}
    if path.endswith("/interfaces"): return {"items": [SHARED_INTERFACE]}
    if path.endswith("/context"): return {"context": {}}
    if path.endswith("/console-summary"): return {"entry_count": 1, "resource_count": 0}
    if path.endswith("/cases"): return {"items": SHARED_CASES}
    if "/cases/" in path:
        case = SHARED_CASE_BY_ID.get(path.rsplit("/", 1)[-1])
        if case is None: return JSONResponse({"detail": "Case不存在"}, status_code=404)
        return case
    if path.endswith("/case-executions"): return {"executions": []}
    if path.endswith("/coverage/source"):
        source = request.query_params.get("path", "")
        location = next((item for item in SHARED_COVERAGE["uncovered"]
                         if source.endswith(item["source_path"])), None)
        if location is None:
            return JSONResponse({"detail": "未知源码路径"}, status_code=404)
        start = max(1, int(request.query_params.get("start_line", "1")))
        end = min(start + 799, int(request.query_params.get("end_line", str(start + 20))))
        uncovered = [number for number in range(location["ranges"][0]["start"], location["ranges"][0]["end"] + 1)
                     if start <= number <= end]
        return {"path": source, "start_line": start, "end_line": end, "total_lines": 400,
                "lines": [{"number": number, "text": f"// 隔离源码第 {number} 行"} for number in range(start, end + 1)],
                "uncovered_lines": uncovered}
    if path.endswith("/coverage"): return {"coverage": SHARED_COVERAGE}
    if path == "systems": return {"systems": [
        {"system_id": SYSTEM, "name": "开发验收（隔离测试数据）", "source_path": "/test-only"},
        {"system_id": "presentation.empty.system", "name": "无环境验收", "source_path": "/test-empty"},
        {"system_id": "presentation.failed.system", "name": "环境失败验收", "source_path": "/test-failed"},
    ]}
    if path == "system-archives": return {"archives": []}
    if path == "local-settings/runtime": return {"settings": {}, "status": {"status": "BLOCKED", "message": "隔离验收不启动扫描器"}}
    if path == "tasks": return {"tasks": []}
    if path == "console/activity": return {"activity": {"active": False}}
    if path.endswith("/local-settings"): return {"local_settings": {}}
    if path.endswith("/environments"):
        # 环境失败和无配置均不得阻止Case目录继续读取。
        if "presentation.failed.system" in path:
            return JSONResponse({"detail": "隔离环境目录读取失败"}, status_code=500)
        return {"environments": [] if "presentation.empty.system" in path else [{"environment": "qa"}, {"environment": "isolated"}]}
    if path.endswith("/scans"):
        # 故意延迟扫描历史，让浏览器验证环境早于扫描返回，而非仅检查源代码顺序。
        await asyncio.sleep(3)
        return {"scans": []}
    if path.endswith("/catalog"): return {"catalog": {"scan_id": "fixture", "targets": [
        {"target_id": OPERATION, "category": "job", "display_name": "隔离检查任务"},
        {"target_id": "facade:example.RefundFacade#createOrder", "category": "facade", "display_name": "创建退票 · RefundFacade#createOrder"},
        {"target_id": "facade:example.RefundFacade#queryList", "category": "facade", "display_name": "查询退票 · RefundFacade#queryList"},
        {"target_id": "mq:example.OrderConsumer#receive", "category": "mq_consumer", "display_name": "订单消息"},
    ], "counts": {"job": 1, "facade": 2, "mq_consumer": 1}, "warnings": []}}
    if path.endswith("/resources"): return {"resources": []}
    if path.endswith("/validation-capabilities"): return {"capabilities": []}
    if path.endswith("/knowledge/context"): return {"context": {}}
    if path.endswith("/knowledge/workflow"): return {"workflow": {"steps": [], "next_action": "仅验收Case展示"}}
    if path.endswith("/dsf-operations"): return {"catalog": {"operations": []}}
    if path.endswith("/case-generations"): return {"generations": [GEN]}
    if "/case-generations/" in path: return {"generation": GEN}
    if path.endswith("/case-executions"): return {"executions": BATCHES}
    if "/case-executions/" in path: return {"execution": next(item for item in BATCHES if item["execution_id"] == path.split("/")[-1])}
    return JSONResponse({"detail": "未配置的隔离读取"}, status_code=404)
