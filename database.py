from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

import numpy as np
from supabase import Client, create_client


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vector_literal(vector: List[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def _parse_vector(raw: Any) -> List[float]:
    if raw is None:
        return []
    if isinstance(raw, list):
        try:
            return [float(item) for item in raw]
        except (TypeError, ValueError):
            return []
    if isinstance(raw, str):
        candidate = raw.strip().strip("[]")
        if not candidate:
            return []
        output: List[float] = []
        for item in candidate.split(","):
            try:
                output.append(float(item.strip()))
            except ValueError:
                return []
        return output
    return []


def _cosine_similarity(left: List[float], right: List[float]) -> float:
    if not left or not right:
        return -1.0
    left_vec = np.array(left, dtype=np.float32)
    right_vec = np.array(right, dtype=np.float32)
    if left_vec.shape != right_vec.shape:
        return -1.0
    left_norm = np.linalg.norm(left_vec)
    right_norm = np.linalg.norm(right_vec)
    if left_norm == 0.0 or right_norm == 0.0:
        return -1.0
    return float(np.dot(left_vec, right_vec) / (left_norm * right_norm))


@dataclass
class ConnectivityStatus:
    ok: bool
    message: str


class SupabaseVectorDatabase:
    """
    Cloud memory layer for PIA:
    - user_profiles
    - chat_sessions
    - chat_messages
    - document_chunks (vectorized)
    """

    def __init__(self, url: str, key: str, match_rpc: str = "match_document_chunks") -> None:
        self.url = url
        self.key = key
        self.match_rpc = match_rpc
        self.client: Client | None = None
        self._fallback: Dict[str, Any] = {
            "profiles": {},
            "sessions": {},
            "messages": {},
            "chunks": [],
        }

        if url and key:
            try:
                self.client = create_client(url, key)
            except Exception:
                self.client = None

    @property
    def connected(self) -> bool:
        return self.client is not None

    def healthcheck(self) -> ConnectivityStatus:
        if self.client is None:
            return ConnectivityStatus(
                ok=False,
                message="Supabase credentials missing. Running in local fallback mode.",
            )
        try:
            self.client.table("chat_sessions").select("id").limit(1).execute()
            return ConnectivityStatus(ok=True, message="Supabase reachable.")
        except Exception as exc:
            return ConnectivityStatus(ok=False, message=f"Supabase not ready: {exc}")

    def upsert_user_profile(
        self,
        user_id: str,
        email: str,
        display_name: str,
        avatar_url: str = "",
    ) -> Dict[str, Any]:
        now = _utc_now_iso()
        payload = {
            "id": user_id,
            "email": email,
            "display_name": display_name,
            "avatar_url": avatar_url,
            "updated_at": now,
        }
        if self.client:
            try:
                response = self.client.table("user_profiles").upsert(payload, on_conflict="id").execute()
                if response.data:
                    return dict(response.data[0])
            except Exception:
                pass

        fallback = {
            "id": user_id,
            "email": email,
            "display_name": display_name,
            "avatar_url": avatar_url,
            "created_at": self._fallback["profiles"].get(user_id, {}).get("created_at", now),
            "updated_at": now,
        }
        self._fallback["profiles"][user_id] = fallback
        return fallback

    def create_chat_session(self, user_id: str, title: str) -> Dict[str, Any]:
        now = _utc_now_iso()
        payload = {"user_id": user_id, "title": title, "created_at": now, "updated_at": now}
        if self.client:
            try:
                response = self.client.table("chat_sessions").insert(payload).execute()
                if response.data:
                    return dict(response.data[0])
            except Exception:
                pass

        chat_id = str(uuid.uuid4())
        row = {"id": chat_id, **payload}
        self._fallback["sessions"][chat_id] = row
        self._fallback["messages"].setdefault(chat_id, [])
        return row

    def list_chat_sessions(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        if self.client:
            try:
                response = (
                    self.client.table("chat_sessions")
                    .select("id,title,created_at,updated_at")
                    .eq("user_id", user_id)
                    .order("updated_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                return [dict(item) for item in (response.data or [])]
            except Exception:
                pass

        sessions = [item for item in self._fallback["sessions"].values() if item.get("user_id") == user_id]
        sessions.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return sessions[:limit]

    def update_chat_title(self, chat_id: str, title: str) -> None:
        if self.client:
            try:
                self.client.table("chat_sessions").update(
                    {"title": title, "updated_at": _utc_now_iso()}
                ).eq("id", chat_id).execute()
                return
            except Exception:
                pass

        if chat_id in self._fallback["sessions"]:
            self._fallback["sessions"][chat_id]["title"] = title
            self._fallback["sessions"][chat_id]["updated_at"] = _utc_now_iso()

    def touch_chat(self, chat_id: str) -> None:
        if self.client:
            try:
                self.client.table("chat_sessions").update({"updated_at": _utc_now_iso()}).eq(
                    "id", chat_id
                ).execute()
                return
            except Exception:
                pass

        if chat_id in self._fallback["sessions"]:
            self._fallback["sessions"][chat_id]["updated_at"] = _utc_now_iso()

    def save_chat_message(
        self,
        chat_id: str,
        user_id: str,
        role: str,
        content: str,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        now = _utc_now_iso()
        payload = {
            "chat_id": chat_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "created_at": now,
        }
        if self.client:
            try:
                response = self.client.table("chat_messages").insert(payload).execute()
                self.touch_chat(chat_id)
                if response.data:
                    return dict(response.data[0])
            except Exception:
                pass

        row = {"id": str(uuid.uuid4()), **payload}
        self._fallback["messages"].setdefault(chat_id, []).append(row)
        self.touch_chat(chat_id)
        return row

    def load_chat_messages(self, chat_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        if self.client:
            try:
                response = (
                    self.client.table("chat_messages")
                    .select("role,content,created_at,metadata")
                    .eq("chat_id", chat_id)
                    .order("created_at", desc=False)
                    .limit(limit)
                    .execute()
                )
                return [dict(item) for item in (response.data or [])]
            except Exception:
                pass

        return list(self._fallback["messages"].get(chat_id, []))[-limit:]

    def delete_chat_session(self, user_id: str, chat_id: str) -> bool:
        if self.client:
            try:
                # Best-effort cascading cleanup for deployments without DB-level cascades.
                self.client.table("chat_messages").delete().eq("chat_id", chat_id).execute()
                self.client.table("document_chunks").delete().eq("chat_id", chat_id).execute()
                response = (
                    self.client.table("chat_sessions")
                    .delete()
                    .eq("id", chat_id)
                    .eq("user_id", user_id)
                    .execute()
                )
                return bool(response.data is not None)
            except Exception:
                return False

        session = self._fallback["sessions"].get(chat_id)
        if session and session.get("user_id") == user_id:
            self._fallback["sessions"].pop(chat_id, None)
            self._fallback["messages"].pop(chat_id, None)
            self._fallback["chunks"] = [
                row for row in self._fallback["chunks"] if row.get("chat_id") != chat_id
            ]
            return True
        return False

    def save_document_chunks(
        self,
        user_id: str,
        chat_id: str,
        document_name: str,
        chunks: List[str],
        embeddings: List[List[float]],
        metadata: Dict[str, Any] | None = None,
    ) -> int:
        if not chunks:
            return 0

        now = _utc_now_iso()
        rows = []
        for chunk_index, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            rows.append(
                {
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "document_name": document_name,
                    "chunk_index": chunk_index,
                    "content": chunk_text,
                    "embedding": _vector_literal(embedding),
                    "metadata": metadata or {},
                    "created_at": now,
                }
            )

        if self.client:
            try:
                self.client.table("document_chunks").insert(rows).execute()
                self.touch_chat(chat_id)
                return len(rows)
            except Exception:
                pass

        for row in rows:
            row["id"] = str(uuid.uuid4())
            self._fallback["chunks"].append(row)
        return len(rows)

    def search_document_chunks(
        self,
        user_id: str,
        query_embedding: List[float],
        chat_id: str | None = None,
        top_k: int = 6,
    ) -> List[Dict[str, Any]]:
        if not query_embedding:
            return []

        if self.client:
            try:
                response = self.client.rpc(
                    self.match_rpc,
                    {
                        "query_embedding": _vector_literal(query_embedding),
                        "match_count": top_k,
                        "filter_user_id": user_id,
                        "filter_chat_id": chat_id,
                    },
                ).execute()
                if response.data:
                    return [dict(item) for item in response.data]
            except Exception:
                pass

            try:
                query = self.client.table("document_chunks").select(
                    "id,document_name,chunk_index,content,metadata,embedding,created_at,chat_id,user_id"
                ).eq("user_id", user_id)
                if chat_id:
                    query = query.eq("chat_id", chat_id)
                response = query.limit(max(top_k * 8, 48)).execute()
                rows = response.data or []
                scored = []
                for row in rows:
                    vector = _parse_vector(row.get("embedding"))
                    score = _cosine_similarity(query_embedding, vector)
                    scored.append({**row, "similarity": score})
                scored.sort(key=lambda item: item.get("similarity", -1.0), reverse=True)
                return scored[:top_k]
            except Exception:
                pass

        scored = []
        for row in self._fallback["chunks"]:
            if row.get("user_id") != user_id:
                continue
            if chat_id and row.get("chat_id") != chat_id:
                continue
            vector = _parse_vector(row.get("embedding"))
            score = _cosine_similarity(query_embedding, vector)
            scored.append({**row, "similarity": score})
        scored.sort(key=lambda item: item.get("similarity", -1.0), reverse=True)
        return scored[:top_k]

    def list_user_documents(
        self,
        user_id: str,
        chat_id: str | None = None,
        limit: int = 5000,
    ) -> List[str]:
        rows: List[Dict[str, Any]] = []
        if self.client:
            try:
                query = self.client.table("document_chunks").select("document_name,chat_id,created_at").eq(
                    "user_id", user_id
                )
                if chat_id:
                    query = query.eq("chat_id", chat_id)
                response = query.order("created_at", desc=True).limit(limit).execute()
                rows = [dict(item) for item in (response.data or [])]
            except Exception:
                rows = []
        else:
            rows = [dict(row) for row in self._fallback["chunks"] if row.get("user_id") == user_id]
            if chat_id:
                rows = [row for row in rows if row.get("chat_id") == chat_id]
            rows.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
            rows = rows[:limit]

        unique: List[str] = []
        seen: set[str] = set()
        for row in rows:
            name = str(row.get("document_name", "")).strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(name)
        return unique
