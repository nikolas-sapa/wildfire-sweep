# Sampled-Video Evaluation Acceptance Plan

## Tests Before Implementation

1. `test_two_perfect_episodes`: truth/alarm `[0,1,1,0,1,1,0]`, 2 fps,
   exactly 2 matched episodes, recall/precision 1, delays 0, exposure 3.5 s.
2. `test_quantized_delays_and_nearest_rank`: truth
   `[0,1,1,1,0,1,1,1,1,0]`, alarms `[0,0,1,1,0,0,0,1,1,0]`, 2 fps:
   detected delays 0.5/1 s; p50 0.5 s and p90 1 s.
3. `test_preexisting_alarm_does_not_detect_later_fire`: truth
   `[0,0,1,1,0]`, alarms all 1, 1 fps: 0 matched, 1 missed, 1 false alarm,
   3 nonfire seconds, 1,200 false onsets/nonfire hour. Later overlap earns no credit.
4. `test_duplicates_are_not_negative_exposure_false_alarms`: truth
   `[0,1,1,1,1,1,0]`, alarms `[0,1,0,1,0,1,0]`: 1 matched, 2 duplicates,
   precision 1/3, recall 1, negative-exposure false alarms 0.
5. `test_no_fire_has_undefined_recall`: truth all 0 for 5 samples, alarms
   `[0,1,1,0,1]`, 1 fps: 2 false episodes, recall null, precision 0,
   1,440 false onsets/nonfire hour.
6. `test_no_alarm_and_no_negative_exposure`: truth `[1,1,1]`, alarms all 0:
   recall 0, precision null, false-alarm rate null, delays null, both censor flags.
7. `test_half_open_end_excludes_post_fire_alarm`: truth `[0,1,1,0]`,
   alarms `[0,0,0,1]`: 1 missed truth and 1 false alarm.
8. `test_misses_do_not_become_zero_delays`: truth `[1,0,1,1,1,0,1]`,
   alarms `[0,0,0,1,1,0,0]`, 1 fps: recall 1/3, p50/p90 both 1 s.
9. `test_invalid_sequences_and_rates_fail`: empty/misaligned/nonbinary
   sequences and bool/zero/nonfinite/>30 fps fail with ValueError.
10. `test_exhaustive_count_closure`: all 1,024 binary truth/alarm pairs of length
    5 close: truth=matched+missed; alarms=matched+duplicate+false.
11. `test_capture_binding`: complete labels evaluate only when recording ID,
    input SHA-256, geometry, sample rate, sample count and all sample times agree.
12. `test_fail_closed_inputs`: missing/duplicate/blank labels, changed hashes,
    changed metadata, non-test split or malformed alarm values fail before output.
13. `test_output_is_exclusive`: evaluation refuses existing output and preserves bytes.
14. `test_blinded_packet`: local 4-frame FFmpeg fixture creates exactly 4 blank
    label rows, 1 contact sheet and matching artifact hashes, with no scores.
15. `test_packet_streaming_and_overwrite`: 13 supplied frames produce 2 pages,
    decoder closes on failure; existing output is never overwritten.
16. Negative control: a mutant that credits an always-on alarm for later truth
    overlap must fail test 3, rather than achieving perfect recall.
17. Real CLI smoke fixture: concatenate 4 seconds black and 4 seconds
    RGB(255,160,0) at 1 fps. Explicit synthetic software labels 00001111,
    baseline persistence gives onset 6, strict matching gives one match and
    2 s sampled delay. This is a constructed I/O check, NOT detector accuracy.
18. Final gate: full unittest suite, three historical checks, CLI help, source
    capture immutability and both hosted Python jobs. Never rerun frozen studies.
19. Packet fault checks: an empty decoder must not emit a complete manifest;
    changing source bytes during decoding must fail and close the decoder.

## Chosen Interfaces

Keep the existing decoder, candidate thresholds and persistence unchanged.
This is an additive labelling/evaluation workflow, not a new detector.

### Annotation Packet (Delegated Software)

`annotation_packet.py VIDEO --recording-id ID --split train|validation|test
--output DIR [--sample-fps 1] [--max-frames 600]`

Expose `create_packet(video, output, recording_id, split, sample_fps=1.0,
max_frames=600)`. Reuse `video_io.iter_video_frames` and `FRAME_GEOMETRY`.
Validate ID against `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`; validate split/rate/limit
before creating output. Require fresh directory, no overwrites.

Stream at most 12 frames per contact sheet; do not retain the full recording
in memory. Page names `sheet-0001.png`, etc. Label every image with sample index
and resampled time, no predictions, candidate fractions or inferred labels.
Use existing blue/slate styling. Figures are review aids, not scientific plots;
do not import detection, event evaluation or simulation code.

`labels.csv` exact columns are the six protocol fields. Fire is blank on every
row. Times are index/sample_fps. Preserve the original template; annotate a copy.
Assign split before reviewing. Labels describe visible flame, not smoke-only
or thermal targets. Uncertainty stays blank until adjudicated.

`manifest.json`, written last with exclusive creation:
schema_version=1, status=complete, purpose="blind annotation packet",
recording_id, split, input_name (basename only), input_sha256,
sample_fps, max_frames, decoded_frames, geometry,
sample_limit_reached=(decoded_frames==max_frames), label_fields (protocol order),
source_sha256 for annotation_packet.py/video_io.py,
artifact_sha256 for labels.csv and every sheet. Hash source video before and
after decoding; fail if it changes. No full video copy. CLI errors exit 2
without traceback. Context managers must close decoder/figures on failure.

### Baseline Capture (Lead)

Add only `status="complete"` and `artifact_sha256["predictions.csv"]` to the
existing detector manifest. Do not change thresholds, row values or field names.
New event evaluation requires this fingerprint; old captures remain unchanged.

### Event Evaluation (Lead Scientific Work)

`event_evaluation.py --predictions DIR --packet DIR --labels CSV
--annotator-id ID --output DIR`

Expose `episode_metrics(truth, alarms, sample_fps)` and
`run_evaluation(predictions, packet, labels, output, annotator_id)`.
Follow event_protocol.json exactly. No model runs or metric aggregation across
recordings. Core metrics return counts/shares/exposure, conditional detected
delay p50/p90, censor counts, fire_episode_details and alarm_episode_details.
Details use half-open start/end sample indices, times and matching status.

Verify both manifests complete/schema 1, packet purpose and test split, all
packet artifact hashes (including template), predictions.csv fingerprint,
matching recording/input hash/geometry/fps/count, and 6-column label template.
Require matching captured video_io.py source fingerprints as well; identical
video names, rates and counts alone cannot establish the same sampling logic.
Packet artifact inventory must be exactly labels.csv plus the expected
ceil(decoded_frames/12) sheet-NNNN.png pages; no manifest-supplied external paths.
All template fire cells must be blank. Completed label rows may be reordered
but must change only fire, cover every index exactly once, and be binary.
Predictions require recording_id/sample_index/sample_time_s/alarm columns,
complete coverage, uniform index/fps times within 1e-9 s; alarm must be literal
True/False. Extra candidate/config fields remain captured, not re-estimated.
Parse manifests and CSVs from byte snapshots; provenance hashes must describe
the bytes actually parsed, not a later version reread from a changing file.

Write fresh output containing report.json (metrics and limitations) and
manifest.json (status complete, protocol, recording/split/input identity,
annotator ID, input manifest/artifact hashes, Python/source hashes, report hash).
Report annotator ID as self-reported, not verified independence. Emit no
confidence intervals, pass/fail target verdict or claimed incident recall.
No scientific code imports from the renderer/annotation side.

## Non-Goals And Reporting

No real footage is independently labelled by this work. No new dataset,
training, benchmark leaderboard, live drone or flight. No change to simulator
or frozen evidence. Update README, roadmap and proposed field protocol to
distinguish implemented sampled-episode mechanics from missing independent
labels, cross-recording uncertainty, empirical validation and authorization.
Never describe synthetic colored fixtures as accuracy evidence.
