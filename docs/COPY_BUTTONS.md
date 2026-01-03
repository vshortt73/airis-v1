# Copy Buttons for Code Blocks

## Feature Overview

Every code block now has a convenient **Copy** button in the top-right corner that copies the code to the clipboard with one click.

## Features

### 1. Positioned in Top-Right Corner
- Appears on hover or always visible (depending on screen size)
- Doesn't interfere with code readability
- Positioned using `position: absolute` on the `<pre>` element

### 2. Visual Feedback
- **Default state**: Gray background with 📋 clipboard icon
- **Hover state**: Slightly lighter background
- **Copied state**: Cyan background (#03dac6) with ✓ checkmark
- **Failed state**: Shows ✗ icon if copy fails

### 3. Auto-Reset
- After copying, button shows "Copied!" for 2 seconds
- Then automatically resets to "Copy" state
- Provides clear feedback without requiring user action

### 4. Error Handling
- Catches clipboard API errors
- Shows "Failed" message if copy doesn't work
- Automatically resets after 2 seconds

## How It Works

### Button Creation
```javascript
function addCopyButtonsToCodeBlocks(container) {
    const codeBlocks = container.querySelectorAll('pre code');

    codeBlocks.forEach((codeBlock) => {
        const pre = codeBlock.parentElement;

        // Skip if button already exists
        if (pre.querySelector('.code-copy-button')) {
            return;
        }

        // Create and append button
        const button = document.createElement('button');
        button.className = 'code-copy-button';
        button.innerHTML = '<span>📋</span><span>Copy</span>';

        pre.appendChild(button);
    });
}
```

### Copy Functionality
```javascript
button.addEventListener('click', async () => {
    const code = codeBlock.textContent;

    try {
        await navigator.clipboard.writeText(code);

        // Success feedback
        button.innerHTML = '<span>✓</span><span>Copied!</span>';
        button.classList.add('copied');

        // Reset after 2 seconds
        setTimeout(() => {
            button.innerHTML = '<span>📋</span><span>Copy</span>';
            button.classList.remove('copied');
        }, 2000);
    } catch (err) {
        // Error handling
        button.innerHTML = '<span>✗</span><span>Failed</span>';
        setTimeout(() => {
            button.innerHTML = '<span>📋</span><span>Copy</span>';
        }, 2000);
    }
});
```

### Integration Points

Copy buttons are added at two points:

1. **Streaming Messages** (line 519):
   ```javascript
   case 'chunk':
       textSpan.innerHTML = marked.parse(currentAssistantText);
       addCopyButtonsToCodeBlocks(textSpan);  // ← Add buttons
   ```

2. **Loaded History** (line 619):
   ```javascript
   textSpan.innerHTML = marked.parse(content);
   addCopyButtonsToCodeBlocks(textSpan);  // ← Add buttons
   ```

This ensures both new messages and loaded history have copy buttons.

## Styling

### Button Design
```css
.code-copy-button {
    position: absolute;
    top: 0.5rem;
    right: 0.5rem;
    background: #3a3f4b;
    color: #abb2bf;
    border: 1px solid #4b5263;
    border-radius: 0.25rem;
    padding: 0.4rem 0.8rem;
    font-size: 0.75rem;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.3rem;
    transition: all 0.2s;
}
```

### Hover State
```css
.code-copy-button:hover {
    background: #4b5263;
    border-color: #5c6370;
    color: #fff;
}
```

### Copied State
```css
.code-copy-button.copied {
    background: #03dac6;  /* Cyan - matches links */
    border-color: #03dac6;
    color: #000;
}
```

### Active State
```css
.code-copy-button:active {
    transform: scale(0.95);  /* Subtle press effect */
}
```

## Code Block Adjustments

Added extra padding to `<pre>` elements to make room for the button:

```css
.message-content pre {
    padding-top: 2.5rem;  /* Make room for copy button */
}
```

This prevents the button from overlapping with code on the first line.

## Browser Compatibility

Uses the modern **Clipboard API**:
```javascript
await navigator.clipboard.writeText(code);
```

**Supported browsers:**
- Chrome 66+
- Firefox 63+
- Safari 13.1+
- Edge 79+

**Fallback:** If the Clipboard API fails, the error is caught and "Failed" is shown.

## User Experience

### Normal Flow:
1. User sees code block with subtle "📋 Copy" button in top-right
2. Hovers over button → button highlights
3. Clicks button → code is copied to clipboard
4. Button turns cyan and shows "✓ Copied!" for 2 seconds
5. Button automatically resets to normal state

### Error Flow:
1. User clicks copy button
2. Clipboard API fails (permissions, browser, etc.)
3. Button shows "✗ Failed" for 2 seconds
4. Error logged to console for debugging
5. Button automatically resets to normal state

## Examples

When Iris provides code like:

````markdown
```python
def hello():
    print("Hello, World!")
```
````

The rendered output will have:
- Syntax-highlighted Python code
- A "📋 Copy" button in the top-right corner
- Clicking it copies the plain text (without syntax highlighting HTML)

## Benefits

1. **One-Click Copy**: No need to manually select and copy code
2. **Clean Copy**: Copies plain text, not HTML with styling
3. **Visual Feedback**: Clear indication when copy succeeds
4. **Error Handling**: Graceful failure if clipboard access denied
5. **Non-Intrusive**: Button positioned to not interfere with code
6. **Works Everywhere**: Both new messages and loaded history

## Future Enhancements

Potential improvements:
- Show language label next to copy button (e.g., "Python")
- Tooltip on hover
- Keyboard shortcut support
- Copy with formatting option
- "Download as file" option for large code blocks
- Line numbers toggle

## Technical Notes

- Button creation happens after markdown parsing
- Uses `textContent` to get plain code (strips HTML from syntax highlighting)
- Duplicate detection prevents multiple buttons on the same code block
- Async/await ensures non-blocking operation
- Clipboard API requires HTTPS (or localhost for development)
