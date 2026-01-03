# Markdown Support Added to Iris v3

## What Changed

Added full markdown rendering support to the UI using `marked.js`. Iris can now use natural markdown formatting that will be properly rendered in the chat interface.

## Supported Markdown Features

### Text Formatting
- **Bold**: `**text**` or `__text__`
- *Italic*: `*text*` or `_text_`
- ***Bold + Italic***: `***text***`
- ~~Strikethrough~~: `~~text~~` (if supported by marked.js)

### Code
- Inline code: `` `code` ``
- Code blocks:
  ````markdown
  ```python
  def hello():
      print("Hello!")
  ```
  ````

### Lists
- Unordered: `- item` or `* item`
- Ordered: `1. item`
- Nested lists supported

### Links & Images
- Links: `[text](url)`
- Images: `![alt](url)`

### Blockquotes
```markdown
> This is a quote
> Multi-line support
```

### Headers
```markdown
# H1
## H2
### H3
```

### Horizontal Rules
```markdown
---
***
```

## How It Works

### Streaming Rendering
1. As chunks arrive from Ollama, text is accumulated
2. Each chunk triggers a re-parse of the full accumulated text
3. Markdown is converted to HTML and rendered
4. This allows partial markdown (like `**bol` + `d**`) to render correctly once complete

### Configuration
```javascript
marked.setOptions({
    breaks: true,        // Convert \n to <br>
    gfm: true,          // GitHub Flavored Markdown
    headerIds: false,   // Don't add IDs to headers
    mangle: false,      // Don't escape email addresses
    highlight: function(code, lang) {
        // Use highlight.js for syntax highlighting
        if (lang && hljs.getLanguage(lang)) {
            return hljs.highlight(code, { language: lang }).value;
        }
        // Auto-detect language if not specified
        return hljs.highlightAuto(code).value;
    }
});
```

## Styling

Custom CSS was added to style markdown elements:
- **Code blocks**: Dark background (#1a1a1a) with rounded corners
- **Inline code**: Monospace font with subtle background
- **Links**: Cyan color (#03dac6)
- **Blockquotes**: Purple left border (#bb86fc)
- **Lists**: Proper indentation and spacing
- **Bold text**: Brighter white (#fff) for emphasis

## Examples of What Iris Can Now Use

Instead of deprecated HTML:
```html
<font color="violet">Iris:</font> Hello!
```

She can use natural markdown:
```markdown
**Iris:** Hello!

I can use:
- **Bold text** for emphasis
- *Italic text* for style
- `inline code` for technical terms
- Links like [this](https://example.com)

```python
# Even code blocks!
def greet():
    return "Hello!"
```
```

## Technical Implementation

### Files Modified
1. **static/index.html**:
   - Added `marked.js` CDN (line 7)
   - Added `highlight.js` CDN - JS and CSS (lines 8-9)
   - Configured marked.js with syntax highlighting (lines 242-265)
   - Added `currentAssistantText` variable to accumulate streaming text
   - Modified chunk handler to parse markdown (lines 407-421)
   - Modified message creation to parse markdown (line 514)
   - Added comprehensive markdown CSS (lines 95-134)
   - Added syntax highlighting CSS adjustments (lines 110-128)

### Key Code Changes

**Streaming chunk handler:**
```javascript
case 'chunk':
    if (currentAssistantMessage) {
        // Accumulate the text
        currentAssistantText += data.content;

        // Parse accumulated markdown and render
        const textSpan = content.querySelector('span');
        if (textSpan) {
            textSpan.innerHTML = marked.parse(currentAssistantText);
        }
        scrollToBottom();
    }
    break;
```

**Message creation:**
```javascript
if (content) {
    const textSpan = document.createElement('span');
    textSpan.innerHTML = marked.parse(content);
    contentDiv.appendChild(textSpan);
}
```

## Benefits

1. **Natural for LLMs**: Markdown is the native formatting language for most LLMs
2. **No deprecated HTML**: No more `<font>` tags
3. **Rich formatting**: Code blocks, lists, quotes, etc.
4. **Streaming-safe**: Handles partial markdown during streaming
5. **Consistent**: Both new messages and loaded history use markdown
6. **Extensible**: Easy to add syntax highlighting or other features

## Syntax Highlighting ✨

### Added highlight.js Integration

Code blocks now have beautiful syntax highlighting using **highlight.js** with the **Atom One Dark** theme.

### Supported Languages

Highlight.js supports **190+ languages**, including:

**Popular Languages:**
- `python` - Python code
- `javascript` / `js` - JavaScript
- `typescript` / `ts` - TypeScript
- `json` - JSON data
- `html` - HTML markup
- `css` - CSS styles
- `bash` / `sh` - Shell scripts
- `sql` - SQL queries
- `yaml` / `yml` - YAML config
- `markdown` / `md` - Markdown

**Other Languages:**
- `java`, `c`, `cpp`, `csharp`, `go`, `rust`, `php`, `ruby`, `perl`, `swift`, `kotlin`
- `r`, `matlab`, `julia`
- `dockerfile`, `nginx`, `apache`
- And many more!

### How to Use

Iris can specify the language after the opening fence:

````markdown
```python
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
```
````

Or leave it blank for auto-detection:

````markdown
```
{
  "name": "iris",
  "version": "3.0",
  "features": ["markdown", "syntax-highlighting"]
}
```
````

### Features

1. **Specified Language**: When Iris uses ` ```python `, highlight.js applies Python syntax highlighting
2. **Auto-Detection**: When language isn't specified, highlight.js automatically detects it
3. **Fallback**: If highlighting fails, displays as plain code
4. **Theme**: Atom One Dark theme matches the dark UI (#282c34 background)
5. **Error Handling**: Gracefully handles highlighting errors without breaking the UI

### Color Scheme

The Atom One Dark theme provides:
- **Keywords**: Purple/magenta (`def`, `class`, `if`, etc.)
- **Strings**: Green
- **Numbers**: Orange
- **Comments**: Gray
- **Functions**: Blue
- **Variables**: Red/orange
- **Operators**: Cyan

### Example Output

When Iris provides code like:

````markdown
```python
# Calculate factorial
def factorial(n):
    """Returns n!"""
    if n <= 1:
        return 1
    return n * factorial(n - 1)

result = factorial(5)
print(f"5! = {result}")
```
````

The UI will display it with:
- Comments in gray
- Keywords (`def`, `if`, `return`) in purple
- Strings (`"Returns n!"`) in green
- Numbers (`1`, `5`) in orange
- Function names (`factorial`, `print`) in blue
- Proper indentation and spacing

## Future Enhancements

Potential additions:
- LaTeX/Math rendering (using KaTeX)
- Mermaid diagrams
- Custom markdown extensions
- Emoji support `:smile:`
- Copy button for code blocks
- Line numbers for code blocks

## Notes

- Markdown is parsed client-side using marked.js CDN (~50KB)
- Syntax highlighting uses highlight.js CDN (~80KB + theme)
- Total overhead: ~130KB (cached after first load)
- Parsing and highlighting happen on every chunk during streaming (negligible performance impact)
- Both user and assistant messages support markdown and syntax highlighting
- Historical messages are also parsed and highlighted when loaded
- Auto-detection works well for most languages, but specifying the language is more reliable
- The Atom One Dark theme was chosen to match the dark UI aesthetic
