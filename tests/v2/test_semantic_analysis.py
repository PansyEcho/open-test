"""验证JavaParser Sidecar的Python端口和严格JSON身份边界。"""

from __future__ import annotations

from pathlib import Path

from opentest.adapters.semantic_analysis import JavaParserSemanticAnalyzer
from opentest.domain.models import SemanticAnalysisResult


def test_java_parser_sidecar_returns_parser_independent_contract(tmp_path: Path) -> None:
    """真实Sidecar应返回稳定方法、字段关系、调用边和中文枚举展示名。

    Args:
        tmp_path: pytest隔离的Java源码项目目录。

    Returns:
        None；通过解析器无关模型断言验证Sidecar结果。
    """

    source_root = tmp_path / "project"
    java_root = source_root / "src/main/java/demo"
    java_root.mkdir(parents=True)
    (java_root / "OrderState.java").write_text(
        "package demo; public enum OrderState { PENDING_APPLY(\"待申请\");"
        " private final String desc; OrderState(String desc) { this.desc = desc; } }",
        encoding="utf-8",
    )
    (java_root / "OrderFacade.java").write_text(
        "package demo; public class OrderFacade { public void detail() { helper(); } private void helper() {} }",
        encoding="utf-8",
    )
    (java_root / "OrderContext.java").write_text(
        "package demo; import java.util.List; public class OrderContext { private List<OrderFacade> orders; }",
        encoding="utf-8",
    )
    worker_jar = (
        Path(__file__).parents[2]
        / "workers/java-semantic-analyzer/target/opentest-java-semantic-analyzer.jar"
    )

    result = JavaParserSemanticAnalyzer(worker_jar).analyze("demo-system", source_root)

    assert result.analyzer == "javaparser-symbol-solver"
    assert len(result.methods) == 2
    assert len(result.call_edges) == 1
    assert result.call_edges[0].resolution_status == "resolved"
    assert result.enum_values[0].display_name == "待申请"
    assert result.enum_values[0].description_field == "desc"
    order_context = next(item for item in result.types if item.qualified_class_name == "demo.OrderContext")
    assert order_context.fields[0].referenced_type == "demo.OrderFacade"
    assert order_context.fields[0].collection is True


def test_missing_sidecar_is_explicitly_reported_without_fabricated_semantics(tmp_path: Path) -> None:
    """构建产物缺失时应返回明确warning和空关系，而不是伪造调用图。

    Args:
        tmp_path: pytest隔离的源码与缺失JAR路径根目录。

    Returns:
        None；通过空语义结果和warning断言验证安全降级。
    """

    source_root = tmp_path / "project"
    source_root.mkdir()

    result = JavaParserSemanticAnalyzer(tmp_path / "missing.jar").analyze("demo-system", source_root)

    assert result.methods == []
    assert result.call_edges == []
    assert result.types == []
    assert result.analyzer_version == "unavailable"
    assert "尚未构建" in result.warnings[0]


def test_legacy_semantic_yaml_without_types_remains_compatible() -> None:
    """旧语义产物缺少types字段时应按空集合读取，不伪造领域关系。

    Returns:
        None；通过严格模型默认值断言验证旧YAML兼容。
    """

    result = SemanticAnalysisResult.model_validate(
        {
            "schema_version": 1,
            "analyzer": "legacy",
            "analyzer_version": "1.0",
            "system_id": "demo-system",
            "methods": [],
            "call_edges": [],
            "enum_values": [],
            "patterns": [],
            "warnings": [],
        }
    )

    assert result.types == []
    assert result.schema_version == 1
