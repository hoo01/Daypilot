import json
import asyncio
from datetime import datetime, timedelta

import httplib2
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from google import genai
from google.genai import types as genai_types

from agents.memory import MemoryAgent
from schemas import Entity, EntityType, Relation, UpcomingEvent
from config import settings

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.metadata",
    "https://www.googleapis.com/auth/contacts.readonly",
]

_genai_client = genai.Client(api_key=settings.gemini_api_key)


class IngestionAgent:
    """Cold-start and incremental ingestion: reads Google Calendar/Gmail/Contacts
    and extracts entities → writes to Knowledge Graph via MemoryAgent."""

    def __init__(self, memory: MemoryAgent):
        self.memory = memory

    async def run(self, input_data: dict) -> dict:
        """
        input_data keys:
          user_id      : str
          credentials  : dict with access_token, refresh_token, etc.
          source       : "cold_start" | "incremental"
        """
        user_id = input_data["user_id"]
        credentials_dict = input_data["credentials"]
        source = input_data.get("source", "incremental")

        creds = Credentials(
            token=credentials_dict.get("access_token"),
            refresh_token=credentials_dict.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=SCOPES,
        )

        loop = asyncio.get_event_loop()
        raw_data = await loop.run_in_executor(
            None, self._fetch_google_data_sync, creds, source
        )

        entities = await self._extract_entities(user_id, raw_data)

        count = 0
        for entity in entities:
            await self.memory.write_entity(entity)
            count += 1

        return {"status": "ok", "source": source, "entities_ingested": count}

    def _build_authorized_http(self, creds: Credentials):
        import os
        proxy_port = os.getenv("INGESTION_PROXY_PORT")  # set in China (e.g. 7897); unset elsewhere
        if proxy_port:
            proxy_info = httplib2.ProxyInfo(
                httplib2.socks.PROXY_TYPE_HTTP,
                "127.0.0.1",
                int(proxy_port),
            )
            return AuthorizedHttp(creds, http=httplib2.Http(proxy_info=proxy_info))
        # No proxy configured → direct connection (US / servers outside China)
        return AuthorizedHttp(creds, http=httplib2.Http())
    
    
    def _fetch_google_data_sync(self, creds: Credentials, source: str) -> dict:
        now = datetime.utcnow()
        lookback_days = 90 if source == "cold_start" else 7
        time_min = (now - timedelta(days=lookback_days)).isoformat() + "Z"
        time_max = (now + timedelta(days=30)).isoformat() + "Z"

        result: dict = {"calendar_events": [], "gmail_senders": [], "contacts": []}
        http = self._build_authorized_http(creds)

        # Google Calendar
        try:
            cal = build("calendar", "v3", http=http)
            events_resp = cal.events().list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=200,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            result["calendar_events"] = [
                {
                    "summary": e.get("summary", ""),
                    "start": (e.get("start") or {}).get("dateTime")
                        or (e.get("start") or {}).get("date"),
                    "end": (e.get("end") or {}).get("dateTime")
                        or (e.get("end") or {}).get("date"),
                    "attendees": [a.get("email") for a in e.get("attendees", [])],
                    "is_recurring": bool(e.get("recurrence") or e.get("recurringEventId")),
                }
                for e in events_resp.get("items", [])
            ]
        except Exception:
            pass

        # Gmail - metadata only (From headers, no message body)
        try:
            gmail = build("gmail", "v1", http=http)
            msgs_resp = gmail.users().messages().list(
                userId="me", maxResults=100
            ).execute()
            sender_counts: dict[str, int] = {}
            for msg in (msgs_resp.get("messages") or [])[:50]:
                msg_data = gmail.users().messages().get(
                    userId="me", id=msg["id"], format="metadata",
                    metadataHeaders=["From"],
                ).execute()
                for header in (msg_data.get("payload") or {}).get("headers", []):
                    if header["name"] == "From":
                        sender_counts[header["value"]] = sender_counts.get(header["value"], 0) + 1
            result["gmail_senders"] = sorted(
                [{"email": k, "message_count": v} for k, v in sender_counts.items()],
                key=lambda x: -x["message_count"],
            )[:20]
        except Exception:
            pass

        # Google People / Contacts
        try:
            people = build("people", "v1", http=http)
            connections_resp = people.people().connections().list(
                resourceName="people/me",
                pageSize=100,
                personFields="names,emailAddresses,birthdays,events",
            ).execute()
            result["contacts"] = [
                {
                    "name": ((c.get("names") or [{}])[0]).get("displayName", ""),
                    "email": ((c.get("emailAddresses") or [{}])[0]).get("value", ""),
                    "birthday": ((c.get("birthdays") or [{}])[0]).get("date", {}),
                    "events": [
                        {
                            "label": ev.get("formattedType", ""),
                            "date": ev.get("date", {}),
                        }
                        for ev in (c.get("events") or [])
                    ],
                }
                for c in (connections_resp.get("connections") or [])
                if ((c.get("names") or [{}])[0]).get("displayName")
            ]
        except Exception:
            pass

        return result

    async def _extract_entities(self, user_id: str, raw_data: dict) -> list[Entity]:
        prompt = f"""You are an entity extractor for a personal AI assistant. Analyze the user's Google data and extract meaningful entities.

Return a JSON array. Each object must have:
- entity_name: string (person name, or short phrase for goals/preferences)
- entity_type: one of "person", "goal", "preference", "event", "interest"
- relation_type: string describing the relationship or context (e.g. "partner", "colleague", "recurring commitment")
- since: ISO date string when this relationship started, or null
- upcoming_dates: array of objects with "event" (description) and "date" (YYYY-MM-DD) for upcoming important dates

Focus on:
- People the user meets with regularly or emails frequently
- Recurring commitments (gym, classes, standups) → "preference" type
- Important upcoming dates (birthdays, anniversaries from contacts data)
- Patterns suggesting goals (recurring "Leetcode", "language lesson", "workout" events)

Raw data:
{json.dumps(raw_data, indent=2)[:8000]}

Today: {datetime.utcnow().date().isoformat()}

Return ONLY a valid JSON array, no explanation text."""

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: _genai_client.models.generate_content(
                model=settings.ingestion_model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            ),
        )

        try:
            extracted = json.loads(response.text)
        except (json.JSONDecodeError, ValueError):
            return []

        entities: list[Entity] = []
        for item in extracted:
            if not isinstance(item, dict) or not item.get("entity_name"):
                continue
            try:
                entity_type = EntityType(item.get("entity_type", "person"))
            except ValueError:
                entity_type = EntityType.person

            upcoming = [
                UpcomingEvent(event=ud["event"], date=ud["date"])
                for ud in (item.get("upcoming_dates") or [])
                if isinstance(ud, dict) and ud.get("event") and ud.get("date")
            ]
            relations = []
            if item.get("relation_type") or upcoming:
                relations.append(Relation(
                    type=item.get("relation_type", "related"),
                    since=item.get("since"),
                    upcoming_dates=upcoming,
                ))

            entities.append(Entity(
                user_id=user_id,
                entity_name=item["entity_name"],
                entity_type=entity_type,
                relations=relations,
            ))

        return entities
