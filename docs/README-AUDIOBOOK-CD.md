# Audiobook CD Ripping

ARM can treat an audio CD as an audiobook when the drive is running in manual mode.

## Workflow

1. Insert the audiobook CD in a drive configured for manual mode.
2. ARM detects the disc as an audio CD and waits for manual input.
3. Open the job detail page and choose `Audiobook Title Search`.
4. On the shared title search page, choose `Audiobook`, enter title/author search terms, and search Open Library.
5. Select a result to save it, or use `Save Audiobook Manually` if you need to enter the metadata yourself.

Required fields:

- Author
- Title
- Disc number

Optional fields:

- Year
- Total discs
- Open Library work key
- Open Library cover ID

The title search page includes Open Library lookup results that can prefill title, author, year, work key, and cover ID from `https://openlibrary.org/search.json`.

## Output Layout

Audiobook tracks are encoded with the existing `abcde` configuration and then moved to:

```text
AUDIOBOOK_PATH/<Author>/<Title>/Disc NN/<track-number> - <track-title-or-Track NN>.<ext>
```

The default path is:

```yaml
AUDIOBOOK_PATH: "/home/arm/audiobooks/"
```

## V1 Limits

- ARM does not generate M4B files.
- ARM does not concatenate tracks or discs.
- Multi-disc books are represented as separate jobs that share author/title metadata and use different disc numbers.
- MusicBrainz remains the metadata provider for music CDs only.
