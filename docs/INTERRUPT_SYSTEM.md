# Interrupt System for Iris v3

## Overview

The interrupt system allows users to stop Iris's response generation mid-stream. This is particularly useful with the 72B model, which can be more aggressive about tool calling and may occasionally go down the wrong path.

## User Experience

### Frontend UI

**Stop Button**:
- Appears in place of the "Send" button when Iris is generating a response
- Red background with pulsing animation to indicate it's active
- Click to immediately interrupt generation
- Changes to "⏹ Stopping..." when clicked
- Hides when generation completes or is interrupted

**Visual Feedback**:
- System message appears after interrupt: "⏹ Generation stopped by user"
- Partial response is saved to conversation history
- UI returns to normal input state

### Usage Scenarios

1. **Tool Calling Gone Wrong**: Stop Iris if she starts calling tools you don't want
2. **Off-Topic Response**: Interrupt if the response is heading in the wrong direction
3. **Save Time**: Stop generation if you realize the question was wrong
4. **Resource Management**: Cancel long-running tool chains

## Architecture

### Backend (routes_chat.py)

**InterruptManager Class**:
```python
class InterruptManager:
    def __init__(self):
        self.interrupt_requested = False

    def request_interrupt(self):
        self.interrupt_requested = True

    def clear(self):
        self.interrupt_requested = False

    def is_interrupted(self):
        return self.interrupt_requested
```

**Interrupt Checks**:
1. **During streaming**: Checks after each chunk
2. **Before tool execution**: Checks before starting tool calls
3. **Between tools**: Checks before each tool in a multi-tool sequence
4. **After tools**: Checks after tool execution completes

**Message Flow**:
```
Client                          Server
  |                               |
  |------ interrupt message ----->|  (type: "interrupt")
  |                               |
  |                          [Set flag]
  |                               |
  |<---- interrupted response ----|  (type: "interrupted")
  |                               |
  |<---- system message ----------|  (generation stopped)
```

### Frontend (index.html)

**Button State Management**:
- `isStreaming = true` → Show Stop button, hide Send button
- `isStreaming = false` → Show Send button, hide Stop button

**Interrupt Request**:
```javascript
stopButton.addEventListener('click', () => {
    if (isStreaming && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'interrupt' }));
        stopButton.disabled = true;
        stopButton.textContent = '⏹ Stopping...';
    }
});
```

**Response Handling**:
```javascript
case 'interrupted':
    isStreaming = false;
    sendButton.style.display = 'block';
    stopButton.style.display = 'none';
    stopButton.disabled = false;
    stopButton.textContent = '⏹ Stop';
    // Add system message
    const interruptMsg = createMessage('system', '⏹ Generation stopped by user');
    chatContainer.appendChild(interruptMsg);
    break;
```

## Implementation Details

### Graceful Shutdown

When interrupt is detected:
1. **Save Partial Response**: Any text generated before interrupt is saved to conversation history
2. **Cancel Tool Execution**: No new tools are started after interrupt
3. **Clean State**: Conversation state remains consistent
4. **UI Reset**: Interface returns to ready state immediately

### Edge Cases Handled

1. **Mid-Stream Interrupt**: Breaks out of streaming loop cleanly
2. **Mid-Tool Interrupt**: Skips remaining tools in sequence
3. **Rapid Interrupts**: Only first interrupt is processed
4. **Disconnected WebSocket**: Gracefully handles connection issues

### Performance Impact

- **Latency**: Interrupt is checked after each chunk (~50-200ms intervals)
- **Overhead**: Minimal (simple boolean flag check)
- **Cleanup**: No background threads or timers needed

## Testing

### Manual Test Cases

1. **Basic Interrupt**:
   - Start a response
   - Click Stop button mid-generation
   - Verify: Response stops, partial text saved, system message appears

2. **Interrupt Before Tool**:
   - Send message that triggers tool calling
   - Click Stop before tool executes
   - Verify: Tool call is skipped, response saved

3. **Interrupt During Tool Chain**:
   - Trigger multi-tool sequence
   - Click Stop after first tool
   - Verify: Remaining tools are skipped

4. **Rapid Clicks**:
   - Click Stop button multiple times rapidly
   - Verify: Only one interrupt processed, UI remains stable

### Automated Testing

```python
# Test interrupt handling
async def test_interrupt():
    async with WebSocketClient("/ws/chat") as ws:
        # Send message
        await ws.send_json({"message": "Tell me a long story"})

        # Receive start
        msg = await ws.receive_json()
        assert msg["type"] == "start"

        # Receive a few chunks
        for _ in range(3):
            msg = await ws.receive_json()
            assert msg["type"] == "chunk"

        # Send interrupt
        await ws.send_json({"type": "interrupt"})

        # Should receive interrupted response
        msg = await ws.receive_json()
        assert msg["type"] == "interrupted"
```

## Future Enhancements

### Planned Features

1. **Tool Confirmation Mode** (Complementary feature):
   - Optional confirmation before executing non-autonomous tools
   - User can review tool call and approve/deny
   - Prevents wrong tools from executing in the first place

2. **Undo Last Tool**:
   - Rewind to before last tool execution
   - Useful if tool provided incorrect/unwanted results

3. **Pause/Resume**:
   - Pause generation temporarily
   - Resume from paused state
   - Useful for long responses

4. **Keyboard Shortcut**:
   - Add Escape key to trigger interrupt
   - Faster than clicking button

### Architecture Considerations

**Multi-User Support**:
- Current implementation uses global `interrupt_manager`
- For multi-user: Need per-session interrupt managers
- Solution: Store interrupt flag in session-specific object

**Distributed Systems**:
- If Iris runs across multiple servers
- Need shared interrupt state (Redis, database)
- Current implementation is single-server only

## Troubleshooting

### Issue: Stop button doesn't appear

**Cause**: CSS display property not updating
**Solution**: Check browser console for JavaScript errors
**Fix**: Ensure `isStreaming` flag is set correctly

### Issue: Interrupt doesn't stop generation

**Cause**: WebSocket connection lost or interrupt not received
**Solution**: Check network tab for WebSocket messages
**Fix**: Verify WebSocket is in OPEN state before sending interrupt

### Issue: Partial response not saved

**Cause**: Exception during interrupt handling
**Solution**: Check server logs for errors
**Fix**: Verify `add_assistant_message` is called in interrupt handler

### Issue: UI stuck in "Stopping..." state

**Cause**: Backend never sent `interrupted` response
**Solution**: Check server logs for interrupt handling
**Fix**: Ensure backend sends response on interrupt path

## Summary

The interrupt system provides essential user control over Iris's response generation, addressing the 72B model's tendency toward aggressive tool calling. The implementation is:

- ✅ **Clean**: Simple flag-based architecture
- ✅ **Fast**: Sub-second response to interrupt
- ✅ **Safe**: Graceful state management
- ✅ **Reliable**: Handles edge cases properly

Users can now confidently let Iris start responses, knowing they can stop at any time without losing conversation state.
