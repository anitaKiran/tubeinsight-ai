# Evaluation references and fixtures

`datasets/offline.json` contains synthetic gardening and astronomy captions. They
are not actual YouTube videos. Its 18 cases cover factual retrieval, three absent
facts, timestamps and out-of-range requests, full/interval summaries, sequential
memory, single/combined tools, and six audio outcomes. Scripted providers exercise
the real services and tools. A passing offline case is a regression result, not
measured real AI quality.

`datasets/curated.json` is an **unreviewed real-video template**. Its placeholder
questions, facts, timestamps and tool expectations must be replaced after reading
the entire selected cached transcript. All examples remain untested by default.
Do not set `reviewed=true` just to obtain scores.

Each chat case supplies `id`, `category`, `video_id`, `reviewed`, `review_note`,
and one to three `turns`. Each turn supplies `question`, `answerable`,
`expected_facts`, optional `[start,end]` `expected_range`, and `acceptable_tools`
(alternative sets of tool names; ordering is not required). Real reviewed cases
also require `transcript_sha256`. A changed cached transcript invalidates the
reference. Real transcripts are loaded privately from Supabase, never embedded
in the dataset or exported report. Unsupported expectations need full-transcript
review, including negations and potentially relevant later passages.

To inspect a selected cached video and calculate the pin locally, run Python from
`backend/` (this only reads Supabase; it does not extract or index):

```python
from dotenv import load_dotenv
load_dotenv('.env')
from app.repositories.video_repository import get_video
from app.evaluation.dataset import transcript_hash
video = get_video('YOUR_VIDEO_ID')
assert video is not None
print(transcript_hash(video))
for segment in video.transcript:
    print(segment.start_seconds, segment.end_seconds, segment.text)
```

Keep private references in `datasets/private-*.json` (ignored). Review all factual
reference claims and timestamp ranges, and record who reviewed them and when in
`review_note`. Publish only public, permissioned reference questions and facts.
To evaluate conversational reference resolution, the second turn's facts must be
specific to the referenced earlier topic, not just a generic answer. Include
negative controls with independent sessions. Existing pytest memory tests cover
ordering, lease contention, cross-video rejection, bounded windows, and fresh app
instances; actual DB durability across a process restart remains a live check.

Audio fixtures are local Windows speech synthesis of:
“What are the main topics in this video?” `clear-question.wav` is synthesized
speech; `noisy-question.wav` adds deterministic quiet noise (seed 42, signed
16-bit amplitude ±100). Neither is human-recorded speech. `silent.wav` contains
zero PCM samples; the other files exercise empty, unsupported and invalid inputs.
Regenerate speech on Windows with `./evaluation/generate_speech.ps1`, then
`python evaluation/prepare_fixtures.py`. Installed Windows voices can vary.
The checked-in WAVs are usable on other operating systems without speech packages.

Offline transcription output is **mocked**, so WER remains null. A live audio case
compares actual recognized text with the reference using case/punctuation-normalized
word edit distance / reference word count. WER can exceed 1; it is not a complete
measure of question intent, accent handling, language quality, or safe silence
handling. Live ASR measurements require explicit authorization. Put any private
recordings under `fixtures/private*/` (ignored), never in version control.

Human semantic review rubric (record separately from automatic mechanical scores):

1. Compare every answer claim with the reviewed reference and original sources.
2. Award factual correctness only for all required facts, without added false claims.
3. Award evidence support only when cited excerpts entail all material answer claims.
4. For unsupported questions, require honest abstention and no invented details.
5. For follow-ups, verify the intended earlier topic and fresh evidence, not just
   conversation UUID reuse. For summaries, inspect coverage of later material too.

`--judge` optionally applies that rubric using the configured OpenAI chat model.
Judge scores are fallible estimates, not human ground truth. It sends the selected
question, reference facts, answer and verified sources to OpenAI, never LangSmith;
it does not send the whole history or raw audio. Inputs over the judge text budget
remain unjudged instead of being silently truncated.

Reports omit all raw questions, answers, source text, audio and conversation IDs.
They contain IDs/categories, safe error codes, actual tool names, scores and
monotonic timings. Phrase coverage is diagnostic and does not determine pass/fail.
Mechanical pass/fail cannot establish semantic groundedness. Generated reports
are ignored. See the backend README for commands, limits and LangSmith export.
