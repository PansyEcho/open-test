# Design

Models receive the same closed decision task, contract and candidate spans. Candidate ticket identifiers are replaced locally by reversible placeholders; models never generate business identifiers. Jev uses the official HTTPS systemone API and a runtime key file. Codex runs ephemeral, tool-disabled CLI sessions using its configured provider, with model and effort explicitly overridden. The benchmark does not retry failed calls or silently fall back to another model. Codex's internal transport behavior remains the configured provider/CLI default and is included in observed client latency; it is not an inference-only measurement.

The decision contains intent, execution intent, target candidate and reason mode. Model output is validated before scoring or dispatch. Confidence is reported, not treated as business authorization. All arms share the same deterministic QA query/unique-target/cancel/readback workflow. Only a clear single cancellation request may reach the fixed cancel operation; no model may choose arbitrary tools.

Development samples may be used to tune the shared rubric. The rubric is frozen before held-out runs. Twenty held-out cases are repeated three times per arm with rotated arm order; errors remain in denominators. Process launch-to-turn-start is reported separately when the CLI emits turn.started; other latency is client-observed, not claimed as inference-only. Real QA uses three distinct orders per arm; report medians/ranges, not meaningful tail estimates from three observations. Data preparation and service startup are separate from workflow timing.

Local experiment outputs are necessary for reproducibility and matching existing request-ID execution records; they live under the already ignored .opentest directory. Source fixtures contain synthetic values only. Real cancellations use canonical QA, existing versioned data methods, source-proven operation contracts and stable request IDs. Unknown outcomes are inspected through existing execution records before any further write. Product runtime and global Codex settings stay unchanged.

## Reproduction

Use the project virtual environment and a running local OpenTest service. On this host the desktop CLI is compatible with the configured model catalog; the older CLI on PATH is not. Select it only for the experiment process:

```sh
export OPENTEST_BENCHMARK_CODEX=/Applications/ChatGPT.app/Contents/Resources/codex
.venv/bin/python -m scripts.benchmark_refund_models --split development --output .opentest/jev-refund/development
.venv/bin/python -m scripts.benchmark_refund_qa --phase prepare --run-id jev-refund-YYYYMMDD-pilot --output .opentest/jev-refund/qa
.venv/bin/python -m scripts.benchmark_refund_qa --phase run --run-id jev-refund-YYYYMMDD-pilot --output .opentest/jev-refund/qa
.venv/bin/python -m scripts.benchmark_refund_models --split heldout --repeats 3 --output .opentest/jev-refund/heldout
.venv/bin/python -m scripts.benchmark_refund_models --report --output .opentest/jev-refund
```

Use a fresh output root for a genuinely new experiment and preserve the same run ID when recovering a QA run. Model fixtures use synthetic identifiers; QA inputs with real IDs remain in the owner-only ignored output directory. Do not run model and QA measurements simultaneously because they share the provider. A recommendation threshold is an experimental decision criterion, not a promise of improved accuracy or a production approval mechanism.

## Observed results (2026-09-23)

The completed held-out run contains 180 successful calls: 60 per arm, covering 20 cases repeated three times. Jev scored 100%, xhigh 95% and low 100%, with zero unsafe cancellation routes in every arm. The three xhigh mismatches are repetitions of h10: it selected no target for a consultation using an example ticket, while the frozen rubric expects the mentioned candidate. No expected labels were changed after the rubric was frozen.

Client decision medians were 0.763 seconds (Jev), 8.188 seconds (xhigh) and 8.781 seconds (low). P95 values were 1.941, 13.551 and 12.793 seconds respectively. Nine distinct QA refunds were independently verified as REFUND_CANCEL; total workflow medians were 6.949, 14.288 and 14.010 seconds. Data preparation took 79.114 seconds separately. These observations meet the predefined criteria for further Jev fixed-workflow integration, but do not establish faster execution in the unchanged Codex chat entry.

Development results are retained separately: the initial rubric scored 8/10, 10/10 and 9/10; after common-rubric refinement, Jev returned nine correct answers and one URLError, while both Codex arms scored 10/10. The error was preserved rather than silently retried. Held-out results use the subsequently frozen common rubric, without further tuning. Source fixtures are synthetic; detailed local evidence and the generated report are under `.opentest/jev-refund`.

OCR delegation reviewed both scripts, the fixtures and focused tests. One Medium finding about overlapping ticket identifiers was fixed using full regex-match substitution and a regression test; the follow-up found no unresolved High or Medium issues. All 12 focused tests passed. The fix was verified not to change any of the 30 fixture contexts or nine actual QA model contexts.
