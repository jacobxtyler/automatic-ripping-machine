# Audiobook CD Feature Implementation Plan

This handoff captures the planned v1 implementation for audiobook CD ripping so the feature can be built without repeating the planning work.

## Product Decisions

- Add `audiobook` as a first-class `Job.disctype`.
- Audio CDs remain auto-detected as audio, but during manual wait the user chooses `Music` or `Audiobook`.
- Audiobook metadata is entered manually, with optional Open Library search prefill.
- Required audiobook fields:
  - `author`
  - `title`
  - `disc_number`
- Optional audiobook fields:
  - `year`
  - `total_discs`
  - `open_library_work_key`
  - `cover_id`
- Output layout:

  ```text
  AUDIOBOOK_PATH/<Author>/<Title>/Disc NN/<track-number> - <track-title-or-Track NN>.<ext>
  ```

- Add this config default:

  ```yaml
  AUDIOBOOK_PATH: "/home/arm/audiobooks/"
  ```

- Reuse existing `abcde` ripping and encoding settings.
- Do not add M4B generation or track concatenation in v1.
- Keep MusicBrainz behavior for music CDs only.

## Implementation Checklist

- Update the job model and migration with audiobook metadata fields.
- Extend UI forms, routes, and templates for audiobook metadata entry and Open Library lookup.
- Extend the change-params/manual wait UI to allow `audiobook`.
- Add an Open Library client/parser using `https://openlibrary.org/search.json`.
- Add `rip_audiobook(job, logfile)` that runs `abcde`, then moves and renames files into the audiobook folder layout.
- Route `job.disctype == "audiobook"` through the new audiobook rip path.
- Add setup and config handling for `AUDIOBOOK_PATH`.
- Update notifications and docs.

## Tests

- Unit test Open Library parsing for normal, missing-field, and no-result responses.
- Unit test audiobook path sanitization and `Disc NN` formatting.
- Unit test routing so `music` uses MusicBrainz/current flow and `audiobook` skips MusicBrainz metadata.
- Unit test manual metadata updates set manual fields, `hasnicetitle`, and `manual_start`.
- Run:

  ```bash
  python3 -m unittest discover -s test/unittest -p 'test_*.py' -v
  ```

- Run:

  ```bash
  flake8 . --max-complexity=15 --max-line-length=120 --show-source --statistics
  ```

## Assumptions

- V1 requires manual confirmation before ripping an audiobook disc.
- Open Library is the only lookup provider in v1.
- Multi-disc books are separate jobs linked by shared author/title and disc number fields.
- Existing `abcde.conf` remains the source of truth for format, bitrate, and encoder settings.
