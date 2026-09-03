# Design: 证据型契约与声明式能力

## Semantic operation contract

Java Sidecar v4 records non-static field Javadoc, annotations, literal initializer evidence and runtime-required evidence. Method evidence includes Javadoc, qualified parameter types and return type. `OperationCapability` v2 exposes input/output field evidence and keeps `required_fields` only for constraints proved by runtime validation annotations. A source initializer is descriptive evidence named `declared_initializer`; OpenTest never injects it into an execution request.

Old scan manifests remain immutable. When the latest manifest predates v4 and its source baseline still matches the registered source, the operation catalog runs the deterministic Sidecar and uses the result only while rebuilding the derived SQLite index. If that evidence cannot be obtained safely, the catalog retains compatible type-only evidence and does not promote documentation markers to runtime requirements.

## Discovery and execution

Search text combines operation identity, generic code vocabulary, method/type Javadoc, input/output field meanings and published summaries. Profile aliases may enrich a system without production code comparing a request to a concrete system, Facade, method or Job literal. Equivalent READ candidates are ranked deterministically; the Skill chooses the first sufficient result and calls one operation. WRITE and JOB ambiguity remains a business choice.

The execution layer validates only indexed provider bindings, QA scope, schema types and runtime-required fields. It neither fills defaults nor changes arguments. The existing request reservation hashes the canonical arguments actually submitted by Codex, so a reused request ID with different arguments remains a conflict.

## Capability profiles

`CapabilityProfileRegistry` loads reviewed YAML from `opentest/assets`. A profile owns system aliases, operation intent aliases, optional Job scan rules, QA Worker application identity, validation catalog asset and legacy workflow identities. Runtime services ask the registry for a capability and branch on capability presence or strategy, not business identity literals. Historical createOrder APIs and assets remain available for one compatibility cycle.

