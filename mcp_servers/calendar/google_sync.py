"""
Google Calendar Sync - Phase 2

Bidirectional sync between local calendar_events table and Google Calendar.
Gated by CALENDAR_GOOGLE_SYNC_ENABLED config flag.

Requirements (install when enabling):
    pip install google-api-python-client google-auth-oauthlib google-auth-httplib2

Setup:
    1. Create Google Cloud project with Calendar API enabled
    2. Download OAuth2 credentials JSON
    3. Set CALENDAR_GOOGLE_CREDENTIALS_PATH in system_config
    4. Set CALENDAR_GOOGLE_SYNC_ENABLED = true
    5. Run first sync to complete OAuth flow (will open browser)
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional
import os
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from app import config


class GoogleCalendarSync:
    """
    Bidirectional Google Calendar sync.

    Conflict resolution: most-recently-modified wins using google_etag.
    """

    def __init__(self):
        self.enabled = getattr(config, 'CALENDAR_GOOGLE_SYNC_ENABLED', False)
        self.credentials_path = getattr(config, 'CALENDAR_GOOGLE_CREDENTIALS_PATH', '')

        if not self.enabled:
            raise RuntimeError("Google Calendar sync is not enabled. Set CALENDAR_GOOGLE_SYNC_ENABLED=true in system_config.")

    def _get_service(self):
        """Build Google Calendar API service (lazy, cached)"""
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError:
            raise RuntimeError(
                "Google Calendar dependencies not installed. "
                "Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
            )

        SCOPES = ['https://www.googleapis.com/auth/calendar']
        token_path = Path(self.credentials_path).parent / 'token.json'

        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, 'w') as token:
                token.write(creds.to_json())

        return build('calendar', 'v3', credentials=creds)

    def push_event(self, event_id: int, cursor=None) -> Optional[str]:
        """
        Push a local event to Google Calendar.

        Args:
            event_id: Local calendar_events.id
            cursor: Optional existing DB cursor

        Returns:
            Google event ID on success, None on failure
        """
        # TODO: Implement in Phase 2
        print(f"[google_sync] push_event({event_id}) - not yet implemented")
        return None

    def pull_events(self, calendar_id: str = 'primary') -> int:
        """
        Pull events from Google Calendar into local database.

        Args:
            calendar_id: Google Calendar ID (default: primary)

        Returns:
            Number of events synced
        """
        # TODO: Implement in Phase 2
        print(f"[google_sync] pull_events({calendar_id}) - not yet implemented")
        return 0

    def update_event(self, event_id: int) -> bool:
        """
        Push local event updates to Google Calendar.

        Args:
            event_id: Local calendar_events.id

        Returns:
            True on success
        """
        # TODO: Implement in Phase 2
        print(f"[google_sync] update_event({event_id}) - not yet implemented")
        return False

    def delete_event(self, google_event_id: str) -> bool:
        """
        Delete an event from Google Calendar.

        Args:
            google_event_id: Google Calendar event ID

        Returns:
            True on success
        """
        # TODO: Implement in Phase 2
        print(f"[google_sync] delete_event({google_event_id}) - not yet implemented")
        return False
