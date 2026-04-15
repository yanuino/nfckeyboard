# nfckeyboard

nfckeyboard reads supported NFC tags and types the extracted Imagotag serial as keyboard input.

## Overview

- Watches for NFC cards using PC/SC readers
- Parses NDEF payloads to extract `nfc.imagotag.com/<serial>` values
- Types the serial and presses Enter automatically
- Runs in system tray by default

## Usage

Install dependencies:

```bash
uv sync
```

Run in system tray mode (default):

```bash
uv run -m nfckeyboard
```

Run in interactive mode:

```bash
uv run -m nfckeyboard --interactive
```

## Build

Build docs locally:

```bash
uv run mkdocs build --strict
```
