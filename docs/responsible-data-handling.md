# Responsible data handling

2026-11-09. Practical handling notes for recorded video, annotation labels and rights records around this repository. These are operational hygiene notes, not legal advice, a license decision or a data release.

## Keep private material out of commits

- Keep raw video, label files and rights or permission records inside `research-runs/` (ignored by `.gitignore`) or outside the working tree entirely. The repository carries code, protocols and derived captures; do not commit footage, labels, datasets or weights.
- `results.csv`, `suppression.csv` and `*.png` are also ignored paths. Review `git status` before committing so a private artifact never lands by accident.

## Rights and provenance

- Code licensing and dataset rights are separate; no project license is selected here. Verify recording, platform and redistribution terms for every source independently and keep that evidence with the private records. The [proposed field protocol](../field_protocol.json) already flags a candidate dataset whose README restricts use while its LICENSE file reads differently.
- Keep per-recording provenance (source, date, site and permission basis) alongside the private files, not in committed documents.
- Nothing in this repository bundles or downloads datasets. Acquisition and term checking are a separate, human-verified step before any use.

## People and places in frames

- Anonymous recording IDs label rows; they do not anonymize people, property or locations visible in the imagery. Treat frames as potentially identifying even when the metadata is anonymous.
- Have a responsible human custodian review sensitive imagery and permissions before collection, sharing or publication. Escalate rather than deciding alone.
- Quarantine frames showing identifiable people or private property unless the recorded permission covers them.

## Collection boundaries

- No intentionally lit fires. Use only lawfully captured or professionally managed burns with organizer permission, per `field_protocol.json`.
- Nothing here is flight authorization. Field work requires a qualified operator, site approval and a site-specific risk assessment.
- Follow the [data-collection checklist](data-collection-checklist.md) for capture-handling steps and the [proposed field protocol](../field_protocol.json) for scope and preconditions.

## Hashes are integrity, not authenticity

- SHA-256 checks compare the bytes currently read with declared digests. They are not signatures: they cannot authenticate a rewritten manifest, prove who produced a file, or validate labels, completeness or split independence.
- Establish provenance and label truth through the human review chain above, not through checksums. See [capture integrity](2026-11-09-capture-integrity.md) for what a verified receipt does and does not mean.

## Retention and cleanup

- Existing captures, results and rendered outputs are preserved byte-for-byte. Never overwrite or silently remove a prior run.
- There is no automatic deletion. Manual cleanup requires explicit approval and goes through macOS Trash (`trash`), never permanent deletion. When in doubt, keep the capture.

## See also

- [Data-collection checklist](data-collection-checklist.md): software-oriented capture-handling steps.
- [Proposed field protocol](../field_protocol.json): evidence plan, not flight authorization.
- [Capture integrity](2026-11-09-capture-integrity.md) and the [integrity specification](2026-11-09-integrity-spec.md): the byte-integrity layer and its limits.
- [Research roadmap](research-roadmap.md): evidence still missing.
