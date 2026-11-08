# Research roadmap

## Current evidence

- [Synthetic dispatch study](../README.md#captured-anchor): assumed alerts, fixed winds and unmeasured aircraft inputs, not field performance.
- [Assumption stress study](2026-11-08-robustness-study.md): paired changes to operating assumptions within the synthetic dispatch model.
- [Full-factorial extension](2026-11-08-factorial-study.md): completes the declared stress combinations using the same source alerts. Reuse is not independent replication.
- [Recorded-video RGB baseline](../README.md#recorded-video-baseline): color/persistence behavior, not established detector accuracy. Sampled [event-episode mechanics](2026-11-08-video-evaluation.md) are implemented; independent labelled data and recording-clustered uncertainty remain missing.
- [Proposed field protocol](../field_protocol.json): a separate evidence plan, not flight authorization or completed field validation.

## Priorities

1. Measure usable endurance and launch latency under a qualified, authorized, conservative VLOS protocol. This is a future evidence gate, not an instruction to fly now.
2. Label independent recordings. Split by recording, site and date before threshold tuning; do not split frames from the same recording across partitions. Event-episode mechanics exist; independent labels and recording-clustered uncertainty remain missing.
3. Calibrate physical and time assumptions before adding historical weather and clustered-alert inputs.
4. Freeze the analysis before collecting new independent-seed captures. Use fresh output paths and never overwrite existing captures.

## Completion criteria

- Measured inputs with traceable provenance.
- Independent held-out data, separated before tuning.
- Reported misses, false alarms and delays, with uncertainty.
- Clear regulatory scope and the distinction between research evidence and authorization.

## Interview checklist

- Which inputs are shared across scenarios, and what dependence does that create?
- Why are results event-weighted, and why do rejected alerts remain in denominators?
- What does the paired whole-season bootstrap preserve?
- How does Monte Carlo sampling uncertainty differ from input and model uncertainty?
- Why are pair contrasts full differences-in-differences rather than half-scaled orthogonal factorial effects?
- Why does reusing source alerts complete a design without providing independent replication?

## Non-goals

This roadmap does not establish detector accuracy, field readiness, publication, sole authorship or live deployment. It does not authorize flight or change the frozen scientific assumptions and evidence.
