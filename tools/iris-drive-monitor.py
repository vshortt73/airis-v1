#!/usr/bin/env python3
"""
Iris Drive Monitor — GTK3 desktop widget

Watches /tmp/iris/drive_state.json (written by drive_daemon.py) via inotify.
Displays 7 inner drive variables as horizontal bars with:
  - Current value (0.0–1.0 bar + numeric)
  - Threshold marker (vertical line on bar)
  - Mini sparkline from history data
  - Color changes when value exceeds threshold

Usage:
    python tools/iris-drive-monitor.py
Desktop: ~/.local/share/applications/iris-drive-monitor.desktop
"""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Notify', '0.7')
from gi.repository import Gtk, GLib, Gdk, Gio, Pango, Notify
import cairo
import json
import math

# Initialize libnotify
Notify.init("Iris Drive")

STATUS_FILE = "/tmp/iris/drive_state.json"

# Colors
COLOR_BG = "#1a1a2e"
COLOR_BAR_BG = "#2a2a3e"
COLOR_BAR_FILL = "#4a6fa5"
COLOR_BAR_HOT = "#e85d75"
COLOR_THRESHOLD = "#ffffff"
COLOR_SPARK = "#6ec6ff"
COLOR_SPARK_HOT = "#ff6b8a"
COLOR_TEXT = "#e0e0e0"
COLOR_TEXT_DIM = "#888888"
COLOR_TEXT_HOT = "#ff8a8a"
COLOR_WAKE_ACTIVE = "#ff4444"
COLOR_WAKE_DIM = "#555555"

# Variable display names (short)
DISPLAY_NAMES = {
    "connection_need": "Connection",
    "restlessness": "Restless",
    "curiosity": "Curiosity",
    "unfinished_business": "Unfinished",
    "concern": "Concern",
    "creative_pressure": "Creative",
    "reflection_need": "Reflection",
}

# Variable order
VARIABLE_ORDER = [
    "connection_need",
    "curiosity",
    "creative_pressure",
    "reflection_need",
    "restlessness",
    "unfinished_business",
    "concern",
]

BAR_HEIGHT = 10
BAR_WIDTH = 140
SPARK_WIDTH = 140
SPARK_HEIGHT = 24
SPARK_POINTS = 120  # show last 120 ticks (~10 min at 5s)


def _hex_to_rgb(hex_color):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


class SparkDrawingArea(Gtk.DrawingArea):
    """Draws a mini sparkline from history data."""

    def __init__(self):
        super().__init__()
        self.set_size_request(SPARK_WIDTH, SPARK_HEIGHT)
        self.history = []
        self.threshold = 1.0
        self.is_hot = False
        self.connect("draw", self._on_draw)

    def update(self, history, threshold, is_hot):
        self.history = history[-SPARK_POINTS:] if history else []
        self.threshold = threshold
        self.is_hot = is_hot
        self.queue_draw()

    def _on_draw(self, widget, cr):
        alloc = widget.get_allocation()
        w, h = alloc.width, alloc.height

        # Background
        r, g, b = _hex_to_rgb(COLOR_BAR_BG)
        cr.set_source_rgba(r, g, b, 0.3)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        if len(self.history) < 2:
            return

        # Threshold line
        th_y = h - (self.threshold * h)
        cr.set_source_rgba(1, 1, 1, 0.15)
        cr.set_line_width(0.5)
        cr.set_dash([2, 2])
        cr.move_to(0, th_y)
        cr.line_to(w, th_y)
        cr.stroke()
        cr.set_dash([])

        # Sparkline
        color = COLOR_SPARK_HOT if self.is_hot else COLOR_SPARK
        r, g, b = _hex_to_rgb(color)
        cr.set_source_rgba(r, g, b, 0.8)
        cr.set_line_width(1.2)

        points = self.history
        n = len(points)
        step = w / max(n - 1, 1)

        cr.move_to(0, h - (points[0] * h))
        for i in range(1, n):
            x = i * step
            y = h - (points[i] * h)
            cr.line_to(x, y)
        cr.stroke()

        # Fill under line
        cr.set_source_rgba(r, g, b, 0.1)
        cr.move_to(0, h - (points[0] * h))
        for i in range(1, n):
            x = i * step
            y = h - (points[i] * h)
            cr.line_to(x, y)
        cr.line_to(w, h)
        cr.line_to(0, h)
        cr.close_path()
        cr.fill()

        return False


class BarDrawingArea(Gtk.DrawingArea):
    """Draws a horizontal bar with threshold marker."""

    def __init__(self):
        super().__init__()
        self.set_size_request(BAR_WIDTH, BAR_HEIGHT)
        self.value = 0.0
        self.threshold = 1.0
        self.is_hot = False
        self.connect("draw", self._on_draw)

    def update(self, value, threshold, is_hot):
        self.value = value
        self.threshold = threshold
        self.is_hot = is_hot
        self.queue_draw()

    def _on_draw(self, widget, cr):
        alloc = widget.get_allocation()
        w, h = alloc.width, alloc.height
        radius = 3

        # Background bar (rounded)
        r, g, b = _hex_to_rgb(COLOR_BAR_BG)
        cr.set_source_rgb(r, g, b)
        self._rounded_rect(cr, 0, 0, w, h, radius)
        cr.fill()

        # Fill bar
        fill_w = max(0, min(w, self.value * w))
        if fill_w > 1:
            color = COLOR_BAR_HOT if self.is_hot else COLOR_BAR_FILL
            r, g, b = _hex_to_rgb(color)
            cr.set_source_rgb(r, g, b)
            self._rounded_rect(cr, 0, 0, fill_w, h, radius)
            cr.fill()

        # Threshold marker
        th_x = self.threshold * w
        cr.set_source_rgba(1, 1, 1, 0.6)
        cr.set_line_width(1.5)
        cr.move_to(th_x, 1)
        cr.line_to(th_x, h - 1)
        cr.stroke()

        return False

    def _rounded_rect(self, cr, x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()


class IrisDriveMonitor(Gtk.Window):
    def __init__(self):
        super().__init__(title="Iris Drive")
        self.set_default_size(280, -1)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_decorated(True)
        self.set_skip_taskbar_hint(True)

        # Dragging
        self.connect("button-press-event", self._on_button_press)

        # CSS
        css = Gtk.CssProvider()
        css.load_from_data(f"""
            window {{
                background-color: {COLOR_BG};
            }}
            label {{
                color: {COLOR_TEXT};
            }}
            .header-label {{
                color: {COLOR_TEXT};
                font-weight: bold;
                font-size: 11px;
            }}
            .var-name {{
                color: {COLOR_TEXT};
                font-size: 10px;
            }}
            .var-name-hot {{
                color: {COLOR_TEXT_HOT};
                font-size: 10px;
                font-weight: bold;
            }}
            .var-value {{
                color: {COLOR_TEXT_DIM};
                font-size: 10px;
                font-family: monospace;
            }}
            .var-value-hot {{
                color: {COLOR_TEXT_HOT};
                font-size: 10px;
                font-family: monospace;
                font-weight: bold;
            }}
            .status-dim {{
                color: {COLOR_TEXT_DIM};
                font-size: 9px;
            }}
            .wake-header {{
                color: {COLOR_TEXT};
                font-weight: bold;
                font-size: 10px;
            }}
            .wake-active {{
                color: {COLOR_WAKE_ACTIVE};
                font-size: 10px;
                font-weight: bold;
            }}
            .wake-dim {{
                color: {COLOR_WAKE_DIM};
                font-size: 9px;
            }}
            .wake-info {{
                color: {COLOR_TEXT_DIM};
                font-size: 9px;
            }}
        """.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Main layout
        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.vbox.set_margin_start(10)
        self.vbox.set_margin_end(10)
        self.vbox.set_margin_top(6)
        self.vbox.set_margin_bottom(8)

        # Title
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        title = Gtk.Label(label="IRIS DRIVE STATE")
        title.get_style_context().add_class("header-label")
        title_box.pack_start(title, False, False, 0)

        self.status_label = Gtk.Label(label="waiting...")
        self.status_label.get_style_context().add_class("status-dim")
        title_box.pack_end(self.status_label, False, False, 0)
        self.vbox.pack_start(title_box, False, False, 0)

        sep = Gtk.Separator()
        self.vbox.pack_start(sep, False, False, 2)

        # Build variable rows
        self.name_labels = {}
        self.value_labels = {}
        self.bars = {}
        self.sparks = {}

        for var_name in VARIABLE_ORDER:
            display = DISPLAY_NAMES.get(var_name, var_name)
            self._build_var_row(var_name, display)

        # Wake status section
        wake_sep = Gtk.Separator()
        self.vbox.pack_start(wake_sep, False, False, 4)

        wake_header = Gtk.Label(label="WAKE STATUS")
        wake_header.get_style_context().add_class("wake-header")
        wake_header.set_halign(Gtk.Align.START)
        self.vbox.pack_start(wake_header, False, False, 0)

        self.wake_status_label = Gtk.Label(label="no wakes yet")
        self.wake_status_label.get_style_context().add_class("wake-dim")
        self.wake_status_label.set_halign(Gtk.Align.START)
        self.wake_status_label.set_xalign(0)
        self.wake_status_label.set_line_wrap(True)
        self.wake_status_label.set_max_width_chars(35)
        self.vbox.pack_start(self.wake_status_label, False, False, 0)

        self.wake_reasoning_label = Gtk.Label(label="")
        self.wake_reasoning_label.get_style_context().add_class("wake-info")
        self.wake_reasoning_label.set_halign(Gtk.Align.START)
        self.wake_reasoning_label.set_xalign(0)
        self.wake_reasoning_label.set_line_wrap(True)
        self.wake_reasoning_label.set_max_width_chars(35)
        self.vbox.pack_start(self.wake_reasoning_label, False, False, 0)

        self.add(self.vbox)
        self.show_all()

        # Phase 4: Track last contact event to avoid duplicate notifications
        self._last_contact_time = None

        # Load initial data
        self._load_status()

        # inotify watch
        self._setup_file_monitor()

    def _build_var_row(self, var_name, display_name):
        """Build a row: name + value on top, bar below, sparkline below that."""
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        container.set_margin_top(2)

        # Name + value row
        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        name_lbl = Gtk.Label(label=display_name)
        name_lbl.get_style_context().add_class("var-name")
        name_lbl.set_halign(Gtk.Align.START)
        name_lbl.set_xalign(0)
        header_row.pack_start(name_lbl, False, False, 0)
        self.name_labels[var_name] = name_lbl

        val_lbl = Gtk.Label(label="0.000")
        val_lbl.get_style_context().add_class("var-value")
        val_lbl.set_halign(Gtk.Align.END)
        val_lbl.set_xalign(1)
        header_row.pack_end(val_lbl, False, False, 0)
        self.value_labels[var_name] = val_lbl

        container.pack_start(header_row, False, False, 0)

        # Bar
        bar = BarDrawingArea()
        container.pack_start(bar, False, False, 0)
        self.bars[var_name] = bar

        # Sparkline
        spark = SparkDrawingArea()
        container.pack_start(spark, False, False, 0)
        self.sparks[var_name] = spark

        self.vbox.pack_start(container, False, False, 0)

    def _setup_file_monitor(self):
        gfile = Gio.File.new_for_path(STATUS_FILE)
        try:
            self._monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self._monitor.connect("changed", self._on_file_changed)
        except Exception as e:
            print(f"[drive-monitor] File watch failed: {e}")

    def _on_file_changed(self, monitor, file, other_file, event_type):
        if event_type in (Gio.FileMonitorEvent.CHANGES_DONE_HINT,
                          Gio.FileMonitorEvent.CREATED):
            GLib.idle_add(self._load_status)
        elif event_type == Gio.FileMonitorEvent.DELETED:
            GLib.idle_add(self._show_waiting)

    def _load_status(self):
        try:
            with open(STATUS_FILE, "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            self._show_waiting()
            return False
        except (json.JSONDecodeError, OSError):
            return False

        variables = data.get("variables", {})
        if variables:
            self._update_ui(variables)
            # Show tick interval in status
            tick = data.get("tick_interval", "?")
            self.status_label.set_text(f"{tick}s tick")

        # Update wake status
        wake = data.get("wake", {})
        self._update_wake_ui(wake)
        return False

    def _show_waiting(self):
        self.status_label.set_text("waiting...")
        for var_name in VARIABLE_ORDER:
            self.bars[var_name].update(0, 1.0, False)
            self.sparks[var_name].update([], 1.0, False)
            self.value_labels[var_name].set_text("-.---")
        return False

    def _update_ui(self, variables):
        hot_count = 0
        for var_name in VARIABLE_ORDER:
            if var_name not in variables:
                continue

            info = variables[var_name]
            value = info.get("value", 0)
            threshold = info.get("threshold", 1.0)
            history = info.get("history", [])
            is_hot = value >= threshold

            if is_hot:
                hot_count += 1

            # Update name label style
            name_lbl = self.name_labels[var_name]
            ctx = name_lbl.get_style_context()
            if is_hot:
                ctx.remove_class("var-name")
                ctx.add_class("var-name-hot")
            else:
                ctx.remove_class("var-name-hot")
                ctx.add_class("var-name")

            # Update value label
            val_lbl = self.value_labels[var_name]
            val_lbl.set_text(f"{value:.3f}")
            ctx = val_lbl.get_style_context()
            if is_hot:
                ctx.remove_class("var-value")
                ctx.add_class("var-value-hot")
            else:
                ctx.remove_class("var-value-hot")
                ctx.add_class("var-value")

            # Update bar
            self.bars[var_name].update(value, threshold, is_hot)

            # Update sparkline
            self.sparks[var_name].update(history, threshold, is_hot)

        if hot_count > 0:
            self.status_label.set_text(f"{hot_count} above threshold")
        else:
            self.status_label.set_text("nominal")

    def _update_wake_ui(self, wake):
        """Update the wake status section from JSON data."""
        in_progress = wake.get("in_progress", False)
        last_time = wake.get("last_wake_time")
        last_action = wake.get("last_action")
        last_reasoning = wake.get("last_reasoning")

        ctx = self.wake_status_label.get_style_context()

        if in_progress:
            ctx.remove_class("wake-dim")
            ctx.add_class("wake-active")
            self.wake_status_label.set_text("WAKING...")
            self.wake_reasoning_label.set_text("")
        elif last_time:
            ctx.remove_class("wake-active")
            ctx.remove_class("wake-dim")
            ctx.add_class("wake-info")

            # Calculate time ago
            try:
                from datetime import datetime, timezone
                wake_dt = datetime.fromisoformat(last_time)
                now = datetime.now(timezone.utc)
                delta_sec = (now - wake_dt).total_seconds()
                if delta_sec < 60:
                    ago = f"{int(delta_sec)}s ago"
                elif delta_sec < 3600:
                    ago = f"{int(delta_sec / 60)}m ago"
                else:
                    ago = f"{delta_sec / 3600:.1f}h ago"
            except (ValueError, TypeError):
                ago = "?"

            action_str = last_action or "?"
            self.wake_status_label.set_text(f"Last: {ago} — {action_str}")

            # Reasoning snippet
            if last_reasoning:
                snippet = last_reasoning[:80]
                if len(last_reasoning) > 80:
                    snippet += "..."
                self.wake_reasoning_label.set_text(snippet)
            else:
                self.wake_reasoning_label.set_text("")
        else:
            ctx.remove_class("wake-active")
            ctx.remove_class("wake-info")
            ctx.add_class("wake-dim")
            self.wake_status_label.set_text("no wakes yet")
            self.wake_reasoning_label.set_text("")

        # Phase 4: Check for contact events and fire desktop notification
        last_contact = wake.get("last_contact")
        if last_contact:
            contact_time = last_contact.get("time")
            contact_msg = last_contact.get("message", "")
            if contact_time and contact_time != self._last_contact_time:
                self._last_contact_time = contact_time
                # Fire desktop notification
                try:
                    notification = Notify.Notification.new(
                        "Iris",
                        contact_msg[:200] if contact_msg else "Iris wants to talk",
                        "dialog-information",
                    )
                    notification.set_urgency(Notify.Urgency.NORMAL)
                    notification.show()
                except Exception as e:
                    print(f"[drive-monitor] Notification error: {e}")

    def _on_button_press(self, widget, event):
        if event.button == 1:
            self.begin_move_drag(
                event.button, int(event.x_root), int(event.y_root), event.time
            )


def main():
    win = IrisDriveMonitor()
    win.connect("destroy", Gtk.main_quit)

    # Position below the service monitor (top-right, offset down)
    screen = Gdk.Screen.get_default()
    monitor = screen.get_primary_monitor() or screen.get_monitor_at_point(0, 0)
    geom = screen.get_monitor_geometry(monitor)
    win.move(geom.x + geom.width - 310, geom.y + 330)

    Gtk.main()


if __name__ == "__main__":
    main()
