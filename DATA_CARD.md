# Data card

## Public synthetic demo

`examples/demo_event_cards.jsonl` contains four fictional event cards written only to make a clean
clone and Docker image runnable. They contain no scraped user content, user identifiers or real
engagement statistics, and must not be included in claims about the 12-event retrieval benchmark.

## Source and scope

- 12 Weibo event topics collected for an undergraduate research project.
- 2,736 raw comments before global deduplication.
- 2,289 comments after normalization and global deduplication.
- 242 labeled comments currently used for evaluation.
- 107 high-risk comments completed a focused second-pass adjudication; 24 labels changed.

## Allowed project use

The local dataset is used to develop and evaluate the portfolio project. It is not automatically
licensed for redistribution. Raw usernames, user IDs and comment IDs are excluded from processed
tables, but comment and post text remains user-generated content.

## Public-repository policy

The following files are excluded from Git by default:

- `data/processed/comments_deduplicated.csv`
- `data/processed/event_cards.jsonl`
- `data/evaluation/*.jsonl`
- all raw/private and legacy split directories

Metrics JSON files and code may be shared because they do not contain the full source corpus. A
public demo dataset must be separately reviewed, minimized and documented before release.

## Label status

The reference set has mixed status: 107 high-risk comments are `second_pass_adjudicated`, while
135 comments remain `provisional_single_annotator`. The focused repeat review was not performed by
an independent second annotator and must not be described as inter-annotator agreement or a gold
standard. Known risks include short-text ambiguity, sarcasm, context dependence and annotator
over-confidence. The set is suitable for engineering experiments, not production-quality claims.
