"""验证语义Spike对高置信模式误报的离线质量门禁。"""

from __future__ import annotations

from opentest.application.semantic_spike import PatternExpectation, verify_patterns
from opentest.domain.models import SemanticAnalysisResult, SemanticPatternEvidence, SourceReference


def test_unexpected_high_confidence_pattern_is_reported_as_false_positive() -> None:
    """不在人工允许集内的高置信模式必须阻止Spike通过。"""

    source_ref = SourceReference(path="src/main/java/demo/Chain.java", symbol="demo.Chain#check()")
    analysis = SemanticAnalysisResult(
        system_id="demo-system",
        patterns=[
            SemanticPatternEvidence(
                symbol_id="demo.CreateOrderRequestCheckChain#check()",
                pattern="responsibility_chain",
                evidence="有序checker循环",
                source_refs=[source_ref],
                confidence=0.93,
            ),
            SemanticPatternEvidence(
                symbol_id="demo.UnrelatedService#save()",
                pattern="event_chain",
                evidence="错误的事件链推断",
                source_refs=[source_ref],
                confidence=0.98,
            ),
        ],
    )

    true_positives, unexpected, missing = verify_patterns(
        analysis,
        (PatternExpectation("responsibility_chain", "CreateOrderRequestCheckChain#check"),),
    )

    assert true_positives == 1
    assert unexpected == ["event_chain:demo.UnrelatedService#save()"]
    assert missing == []
