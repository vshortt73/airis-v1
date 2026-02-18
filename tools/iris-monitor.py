#!/usr/bin/env python3
"""
Iris Service Monitor - Compact GTK3 panel widget
Shows status of all Iris services across localhost and node2.

Watches /tmp/iris/services.json via inotify (Gio.File.monitor_file)
instead of polling HTTP. Falls back to default display if the file
doesn't exist yet.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk, Gio, Pango
import json

STATUS_FILE = "/tmp/iris/services.json"

# Default service list — shown when status file doesn't exist yet
DEFAULT_SERVICES = [
    {"name": "Main Inference", "status": "checking", "model": None, "location": "localhost", "gpu": "GPU 0 (RTX 5090)", "icon": ""},
    {"name": "Iris",           "status": "checking", "model": None, "location": "localhost", "gpu": "CPU", "icon": ""},
    {"name": "Vision / Freud", "status": "checking", "model": None, "location": "node2", "gpu": "GPU 0 (RTX 4080 SUPER)", "icon": ""},
    {"name": "STT (Whisper)",  "status": "checking", "model": None, "location": "node2", "gpu": "GPU 1 (RTX 3060)", "icon": ""},
    {"name": "XTTS",           "status": "checking", "model": None, "location": "node2", "gpu": "GPU 1 (RTX 3060)", "icon": ""},
    {"name": "FLOAT",          "status": "checking", "model": None, "location": "node2", "gpu": "GPU 0 (RTX 4080 SUPER)", "icon": ""},
    {"name": "Sentiment",      "status": "checking", "model": None, "location": "node2", "gpu": "GPU 1 (RTX 3060)", "icon": ""},
    {"name": "Transcribe",     "status": "checking", "model": None, "location": "node2", "gpu": "GPU 0 (RTX 4080 SUPER)", "icon": ""},
]

COLOR_UP = "#4CAF50"
COLOR_DOWN = "#F44336"
COLOR_CHECKING = "#FFC107"
COLOR_STOPPED = "#888888"
COLOR_BG = "#1a1a2e"
COLOR_BG_HEADER = "#16213e"
COLOR_TEXT = "#e0e0e0"
COLOR_TEXT_DIM = "#888888"


def _shorten_gpu(gpu_label):
    """Shorten GPU labels for compact display."""
    if "RTX 5090" in gpu_label:
        return "GPU0"
    elif "4080" in gpu_label:
        return "GPU0"
    elif "3060" in gpu_label:
        return "GPU1"
    return gpu_label


class IrisMonitor(Gtk.Window):
    def __init__(self):
        super().__init__(title="Iris Services")
        self.set_default_size(220, -1)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_decorated(True)
        self.set_skip_taskbar_hint(True)

        # Allow moving by dragging
        self.connect("button-press-event", self._on_button_press)

        # Apply dark theme CSS
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
            .service-name {{
                color: {COLOR_TEXT};
                font-size: 11px;
            }}
            .service-info {{
                color: {COLOR_TEXT_DIM};
                font-size: 9px;
            }}
            .section-header {{
                color: {COLOR_TEXT_DIM};
                font-size: 9px;
                font-weight: bold;
            }}
            .dot {{
                font-size: 14px;
            }}
        """.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Main layout
        self.vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.vbox.set_margin_start(8)
        self.vbox.set_margin_end(8)
        self.vbox.set_margin_top(6)
        self.vbox.set_margin_bottom(6)

        # Title bar
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        title = Gtk.Label(label="IRIS SERVICES")
        title.get_style_context().add_class("header-label")
        title_box.pack_start(title, False, False, 0)

        self.status_overall = Gtk.Label(label="...")
        self.status_overall.get_style_context().add_class("service-info")
        title_box.pack_end(self.status_overall, False, False, 0)
        self.vbox.pack_start(title_box, False, False, 0)

        # Separator
        sep = Gtk.Separator()
        self.vbox.pack_start(sep, False, False, 2)

        # Build initial service rows from defaults
        self.indicators = {}
        self.info_labels = {}
        self._current_service_names = []
        self._build_rows(DEFAULT_SERVICES)

        self.add(self.vbox)
        self.show_all()

        # Try loading the file immediately
        self._load_status()

        # Set up inotify file monitor
        self._setup_file_monitor()

    def _setup_file_monitor(self):
        """Watch STATUS_FILE via Gio inotify. Handles file not existing yet."""
        gfile = Gio.File.new_for_path(STATUS_FILE)
        try:
            self._monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self._monitor.connect("changed", self._on_file_changed)
        except Exception as e:
            print(f"[monitor] Failed to set up file watch: {e}")

    def _on_file_changed(self, monitor, file, other_file, event_type):
        """Called by Gio when the status file changes."""
        if event_type in (Gio.FileMonitorEvent.CHANGES_DONE_HINT,
                          Gio.FileMonitorEvent.CREATED):
            GLib.idle_add(self._load_status)
        elif event_type == Gio.FileMonitorEvent.DELETED:
            GLib.idle_add(self._show_waiting)

    def _load_status(self):
        """Read the JSON status file and update the UI."""
        try:
            with open(STATUS_FILE, "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            self._show_waiting()
            return False
        except (json.JSONDecodeError, OSError):
            # Partial write or permission error — ignore, next event will retry
            return False

        services = data.get("services", [])
        if services:
            self._update_ui_from_data(services)
        return False  # don't repeat idle_add

    def _show_waiting(self):
        """Show default services in checking state (file missing)."""
        self._build_rows(DEFAULT_SERVICES)
        self.status_overall.set_text("waiting...")
        return False

    def _build_rows(self, services):
        """Build service display rows from a list of service dicts."""
        # Remove old service rows (keep title + separator = first 2 children)
        children = self.vbox.get_children()
        for child in children[2:]:
            self.vbox.remove(child)

        self.indicators.clear()
        self.info_labels.clear()
        self._current_service_names = []
        current_location = None

        for svc in services:
            name = svc["name"]
            location = svc.get("location", "localhost")
            gpu = svc.get("gpu", "")
            note = _shorten_gpu(gpu)

            # Normalize location for grouping
            loc_group = "local" if location == "localhost" else "node2"

            if loc_group != current_location:
                current_location = loc_group
                section = Gtk.Label()
                section.set_text("LOCALHOST" if loc_group == "local" else "NODE2")
                section.set_halign(Gtk.Align.START)
                section.get_style_context().add_class("section-header")
                section.set_margin_top(4)
                self.vbox.pack_start(section, False, False, 0)

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

            dot = Gtk.Label(label="\u25CF")  # filled circle
            dot.get_style_context().add_class("dot")
            dot.set_markup(f'<span foreground="{COLOR_CHECKING}">\u25CF</span>')
            row.pack_start(dot, False, False, 0)
            self.indicators[name] = dot

            svc_label = Gtk.Label(label=name)
            svc_label.get_style_context().add_class("service-name")
            svc_label.set_halign(Gtk.Align.START)
            svc_label.set_width_chars(12)
            svc_label.set_xalign(0)
            row.pack_start(svc_label, False, False, 0)

            info = Gtk.Label(label=note)
            info.get_style_context().add_class("service-info")
            info.set_halign(Gtk.Align.END)
            info.set_xalign(1)
            row.pack_end(info, True, True, 0)
            self.info_labels[name] = info

            self._current_service_names.append(name)
            self.vbox.pack_start(row, False, False, 1)

        self.vbox.show_all()

    def _on_button_press(self, widget, event):
        if event.button == 1:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)

    def _update_ui_from_data(self, services):
        """Update UI from service status data."""
        # Rebuild rows if service list changed
        current_names = [s["name"] for s in services]
        if current_names != self._current_service_names:
            self._build_rows(services)

        up_count = 0
        total = len(services)

        for svc in services:
            name = svc["name"]
            status = svc.get("status", "stopped")
            model = svc.get("model")
            is_up = status == "running"

            if name not in self.indicators:
                continue

            if is_up:
                color = COLOR_UP
                up_count += 1
            elif status == "stopped":
                color = COLOR_STOPPED
            elif status == "disabled":
                color = COLOR_TEXT_DIM
            elif status == "checking":
                color = COLOR_CHECKING
            else:
                color = COLOR_DOWN

            self.indicators[name].set_markup(f'<span foreground="{color}">\u25CF</span>')

            if is_up and model and model not in ("up", "ready"):
                short = model.split("/")[-1] if "/" in model else model
                if len(short) > 20:
                    short = short[:18] + ".."
                self.info_labels[name].set_text(short)
            elif not is_up and status != "checking":
                self.info_labels[name].set_text(status)

        self.status_overall.set_text(f"{up_count}/{total}")


def main():
    win = IrisMonitor()
    win.connect("destroy", Gtk.main_quit)
    # Position at top-right of screen
    screen = Gdk.Screen.get_default()
    monitor = screen.get_primary_monitor() or screen.get_monitor_at_point(0, 0)
    geom = screen.get_monitor_geometry(monitor)
    win.move(geom.x + geom.width - 240, geom.y + 30)
    Gtk.main()


if __name__ == "__main__":
    main()
