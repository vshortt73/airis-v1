# Directions Maker - Usage Instructions

CLI tool for processing cruise ship deck plan images into navigation JSON.

## Prerequisites

- PaddleOCR server running on node2:5200
- Tesseract OCR installed locally (`apt install tesseract-ocr`)
- Python packages: `opencv-python`, `numpy`, `httpx`, `pytesseract`

## Basic Usage

```bash
python directions_maker.py \
    --title "Ship Name" \
    --input_dir /path/to/deck/images \
    --output_dir /path/to/output
```

## Options

| Flag | Description |
|------|-------------|
| `--title` | Ship name (required) |
| `--input_dir` | Directory containing deck images (required) |
| `--output_dir` | Output directory for JSON (required) |
| `--debug` | Save debug images (stair/elevator detection overlays) |
| `--verbose` | Show detailed HTTP logging |
| `--ocr-url` | PaddleOCR server URL (default: http://node2:5200) |
| `--min-confidence` | Minimum OCR confidence 0-1 (default: 0.7) |

## Input Requirements

**Image naming**: Files must contain deck number in the name:
- `deck05.jpg`
- `oasis-of-the-seas-deck05.webp`
- `ship_deck_05.png`

**Supported formats**: JPG, JPEG, PNG, WebP

## Output

Creates `{ship_name}_navigation.json` with:
- Venue locations with neighbors (N/S/E/W)
- Staircases with vertical links between decks
- Elevator banks with vertical links
- Position classification (forward/mid/aft, port/center/starboard)
- Category classification (dining, entertainment, bar, etc.)

## Examples

**Process Oasis of the Seas**:
```bash
python directions_maker.py \
    --title "Oasis of the Seas" \
    --input_dir /iris-v3/mcp_servers/directions/ships/RC_oasis_of_the_seas \
    --output_dir /iris-v3/mcp_servers/directions/output
```

**With debug images**:
```bash
python directions_maker.py \
    --title "Symphony of the Seas" \
    --input_dir ./symphony_decks \
    --output_dir ./output \
    --debug
```

## Processing Time

Approximately 6-8 seconds per deck image (~77 seconds for 13 decks).

## Troubleshooting

**PaddleOCR connection failed**: Verify server is running:
```bash
curl http://node2:5200/health
```

**No venues detected**: Check `--min-confidence` threshold or verify image quality.

**Missing staircases**: Run with `--debug` to see detection overlays. Yellow regions may not match expected HSV range.

**No elevators found**: "ELEV" text may be too small. Tesseract uses 4x upscaling but very small text may still fail.
