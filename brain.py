
from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Dict, Generator, List, Tuple

import numpy as np
import requests
from llama_api_client import LlamaAPIClient
from openai import OpenAI

from config import (
    CURRENT_EVENT_HINT_KEYWORDS,
    EMBEDDING_ALLOW_DOWNLOADS,
    EMBEDDING_DIM,
    EMBEDDING_MODEL_NAME,
    GOOGLE_DEFAULT_CALENDAR_ID,
    GOOGLE_OAUTH_ACCESS_TOKEN,
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    GOOGLE_OAUTH_REFRESH_TOKEN,
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_OAUTH_TOKEN_JSON,
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MAX_RETRIES,
    GROQ_TIMEOUT_SECONDS,
    GROQ_VISION_MODEL,
    GROQ_WHISPER_MODEL,
    LLAMA_API_KEY,
    LLAMA_COMPAT_BASE_URL,
    LLAMA_LONGFORM_MAX_TOKENS,
    LLAMA_MAX_TOKENS,
    LLAMA_MAX_RETRIES,
    LLAMA_MODEL,
    LLAMA_TEMPERATURE,
    LLAMA_TIMEOUT_SECONDS,
    LLAMA_TOOLCALL_TIMEOUT_SECONDS,
    RAG_CHUNK_OVERLAP,
    RAG_CHUNK_SIZE,
    RAG_TOP_K,
    SHORT_TERM_HISTORY_TURNS,
    SUPPORTED_DATA_EXTENSIONS,
    SUPPORTED_DOC_EXTENSIONS,
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    SYSTEM_PROMPT,
    TAVILY_API_KEY,
    TAVILY_SEARCH_URL,
    TAVILY_TIMEOUT_SECONDS,
    TEMP_DIR,
    VISION_FRAME_STEP_SECONDS,
    VISION_MAX_FRAMES,
)
from database import SupabaseVectorDatabase

try:
    import cv2
except Exception:
    cv2 = None

try:
    import pandas as pd
except Exception:
    pd = None

try:
    import plotly.express as px
except Exception:
    px = None

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from docx import Document as DocxDocument
except Exception:
    DocxDocument = None

try:
    from PIL import Image
except Exception:
    Image = None

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None

try:
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except Exception:
    GoogleRequest = None
    Credentials = None
    build = None


@dataclass
class AttachmentInsights:
    notes: List[str]
    figures: List[Any]
    errors: List[str]


class PIAEngine:
    def __init__(self, store: SupabaseVectorDatabase) -> None:
        self.store = store
        self.meta_client = (
            OpenAI(
                api_key=LLAMA_API_KEY,
                base_url=LLAMA_COMPAT_BASE_URL,
                timeout=LLAMA_TIMEOUT_SECONDS,
                max_retries=LLAMA_MAX_RETRIES,
            )
            if LLAMA_API_KEY
            else None
        )
        self.meta_native_client = (
            LlamaAPIClient(
                api_key=LLAMA_API_KEY,
                timeout=LLAMA_TIMEOUT_SECONDS,
                max_retries=LLAMA_MAX_RETRIES,
            )
            if LLAMA_API_KEY
            else None
        )
        self.groq_client = (
            OpenAI(
                api_key=GROQ_API_KEY,
                base_url=GROQ_BASE_URL,
                timeout=GROQ_TIMEOUT_SECONDS,
                max_retries=GROQ_MAX_RETRIES,
            )
            if GROQ_API_KEY
            else None
        )
        self._embedding_model: Any = None
        self._resolved_llama_model: str | None = None
        self._google_diagnostics: str = ""
        self._google_granted_scopes: set[str] = set()
        self._last_transcription_error: str = ""
        self._compat_chat_unavailable_reason: str = ""
        self._prefer_native_meta: bool = self.meta_native_client is not None

    @property
    def ready_for_chat(self) -> bool:
        return self.meta_client is not None or self.meta_native_client is not None

    def _active_llama_model(self) -> str:
        return self._resolved_llama_model or LLAMA_MODEL

    def _coerce_text(self, payload: Any) -> str:
        if payload is None:
            return ""
        if isinstance(payload, str):
            return payload
        if isinstance(payload, list):
            return "".join(self._coerce_text(item) for item in payload)
        if isinstance(payload, dict):
            for key in ("text", "content", "value", "output_text", "output"):
                if key in payload:
                    text = self._coerce_text(payload.get(key))
                    if text:
                        return text
            return ""

        text_attr = getattr(payload, "text", None)
        if text_attr is not None and text_attr is not payload:
            text = self._coerce_text(text_attr)
            if text:
                return text

        content_attr = getattr(payload, "content", None)
        if content_attr is not None and content_attr is not payload:
            text = self._coerce_text(content_attr)
            if text:
                return text

        if hasattr(payload, "model_dump"):
            try:
                return self._coerce_text(payload.model_dump())
            except Exception:
                return ""

        return ""

    def _extract_llama_text(self, completion: Any) -> str:
        completion_message = getattr(completion, "completion_message", None)
        candidates = [
            getattr(getattr(completion_message, "content", None), "text", None),
            getattr(completion_message, "content", None),
            getattr(completion_message, "text", None),
        ]
        for candidate in candidates:
            text = self._coerce_text(candidate).strip()
            if text:
                return text

        choices = getattr(completion, "choices", None) or []
        if choices:
            message = getattr(choices[0], "message", None)
            text = self._coerce_text(getattr(message, "content", None)).strip()
            if text:
                return text
        return self._coerce_text(completion).strip()

    def _extract_llama_tool_calls(self, completion: Any) -> List[Any]:
        completion_message = getattr(completion, "completion_message", None)
        tool_calls = getattr(completion_message, "tool_calls", None)
        if tool_calls:
            return list(tool_calls)
        if isinstance(completion, dict):
            completion_message = completion.get("completion_message", {}) or {}
            tool_calls = completion_message.get("tool_calls")
            if tool_calls:
                return list(tool_calls)

        choices = getattr(completion, "choices", None) or []
        if choices:
            message = getattr(choices[0], "message", None)
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                return list(tool_calls)
        if isinstance(completion, dict):
            choices = completion.get("choices", []) or []
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message", {}) or {}
                tool_calls = message.get("tool_calls")
                if tool_calls:
                    return list(tool_calls)
        return []

    def _extract_llama_message_content(self, completion: Any) -> str:
        completion_message = getattr(completion, "completion_message", None)
        if completion_message is not None:
            content = self._coerce_text(getattr(completion_message, "content", None)).strip()
            if content:
                return content
        if isinstance(completion, dict):
            completion_message = completion.get("completion_message", {}) or {}
            content = self._coerce_text(completion_message.get("content", "")).strip()
            if content:
                return content

        choices = getattr(completion, "choices", None) or []
        if choices:
            message = getattr(choices[0], "message", None)
            content = self._coerce_text(getattr(message, "content", None)).strip()
            if content:
                return content
        if isinstance(completion, dict):
            choices = completion.get("choices", []) or []
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message", {}) or {}
                content = self._coerce_text(message.get("content", "")).strip()
                if content:
                    return content
        return ""

    def _native_meta_active(self) -> bool:
        return bool(self.meta_native_client and (self._prefer_native_meta or not self.meta_client))

    def _extract_tool_call_payload(self, call: Any, index: int) -> Tuple[str, str, str]:
        call_id = str(getattr(call, "id", "") or "").strip()
        function_obj = getattr(call, "function", None)
        tool_name = str(getattr(function_obj, "name", "") or "").strip()
        raw_arguments: Any = getattr(function_obj, "arguments", "{}")

        if isinstance(call, dict):
            call_id = str(call.get("id", call_id) or "").strip()
            function_obj = call.get("function", {}) or {}
            tool_name = str(function_obj.get("name", tool_name) or "").strip()
            raw_arguments = function_obj.get("arguments", raw_arguments)

        if isinstance(raw_arguments, (dict, list)):
            raw_arguments = json.dumps(raw_arguments, ensure_ascii=False)
        raw_arguments = str(raw_arguments or "{}")
        if not raw_arguments.strip():
            raw_arguments = "{}"
        if not call_id:
            call_id = f"tool_call_{index + 1}"

        return call_id, tool_name, raw_arguments

    def _normalize_messages_for_native(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized_messages: List[Dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue

            role = str(message.get("role", "")).strip().lower()
            if role not in {"system", "user", "assistant", "tool"}:
                continue

            payload: Dict[str, Any] = {"role": role}
            content = self._coerce_text(message.get("content", ""))

            if role == "assistant":
                tool_calls = message.get("tool_calls") or []
                normalized_tool_calls: List[Dict[str, Any]] = []
                for index, call in enumerate(tool_calls):
                    call_id, tool_name, raw_arguments = self._extract_tool_call_payload(call, index)
                    if not tool_name:
                        continue
                    normalized_tool_calls.append(
                        {
                            "id": call_id,
                            "function": {
                                "name": tool_name,
                                "arguments": raw_arguments,
                            },
                        }
                    )

                if normalized_tool_calls:
                    payload["tool_calls"] = normalized_tool_calls
                    if content.strip():
                        payload["content"] = content.strip()
                else:
                    payload["content"] = content
            elif role == "tool":
                tool_call_id = str(message.get("tool_call_id", "")).strip()
                if not tool_call_id:
                    continue
                payload["tool_call_id"] = tool_call_id
                payload["content"] = content or "{}"
            else:
                payload["content"] = content

            normalized_messages.append(payload)
        return normalized_messages

    def _text_to_word_stream(self, text: str) -> Generator[str, None, None]:
        for word in re.findall(r"\S+\s*", text):
            yield word

    def _extract_model_ids(self, listing: Any) -> List[str]:
        entries: Any = listing
        for attr in ("data", "models", "items"):
            value = getattr(entries, attr, None)
            if value is not None:
                entries = value
                break

        if hasattr(entries, "model_dump"):
            try:
                entries = entries.model_dump()
            except Exception:
                pass

        if isinstance(entries, dict):
            for key in ("data", "models", "items"):
                if key in entries:
                    entries = entries.get(key, [])
                    break
            else:
                entries = [entries]

        if entries is None:
            return []

        if not isinstance(entries, list):
            try:
                entries = list(entries)
            except TypeError:
                entries = [entries]

        model_ids: List[str] = []
        for item in entries:
            if hasattr(item, "model_dump"):
                try:
                    item = item.model_dump()
                except Exception:
                    pass

            if isinstance(item, str):
                candidate = item.strip()
                if candidate:
                    model_ids.append(candidate)
                continue

            if isinstance(item, dict):
                for key in ("id", "model", "name"):
                    candidate = str(item.get(key, "")).strip()
                    if candidate:
                        model_ids.append(candidate)
                        break
                continue

            for attr in ("id", "model", "name"):
                candidate = str(getattr(item, attr, "")).strip()
                if candidate:
                    model_ids.append(candidate)
                    break

        return list(dict.fromkeys(model_ids))

    def _pick_best_70b_model(self, model_ids: List[str]) -> str | None:
        preferred = LLAMA_MODEL.strip()
        if preferred and preferred in model_ids:
            return preferred

        ranked: List[Tuple[int, str]] = []
        for model_id in model_ids:
            normalized = model_id.lower()
            if "70b" not in normalized:
                continue

            score = 0
            if "instruct" in normalized:
                score += 10
            if "3.3" in normalized or "3-3" in normalized:
                score += 8
            if normalized == preferred.lower():
                score += 100
            if "llama" in normalized:
                score += 4
            ranked.append((score, model_id))

        if not ranked:
            return None

        ranked.sort(key=lambda item: (-item[0], item[1]))
        return ranked[0][1]

    def _looks_like_model_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return "model" in message and any(
            fragment in message
            for fragment in (
                "not found",
                "does not exist",
                "invalid",
                "unknown",
                "unsupported",
                "not available",
            )
        )

    def _looks_like_token_limit_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return any(
            fragment in message
            for fragment in (
                "max token",
                "max_tokens",
                "max_completion_tokens",
                "too many tokens",
                "context length",
                "context_length",
                "maximum context",
                "token limit",
                "length exceeded",
            )
        )

    def _looks_like_compat_permission_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return "permission" in message or "permission_denied" in message or "not available for your application" in message

    def _disable_compat_meta(self, exc: Exception) -> None:
        self._compat_chat_unavailable_reason = str(exc)
        self._prefer_native_meta = True

    def _invoke_native_llama_completion(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        if not self.meta_native_client:
            raise RuntimeError("LLAMA_API_KEY is not configured.")

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": self._normalize_messages_for_native(messages),
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_completion_tokens"] = max_tokens

        try:
            return self.meta_native_client.chat.completions.create(**kwargs)
        except TypeError:
            kwargs.pop("temperature", None)
            kwargs.pop("max_completion_tokens", None)
            return self.meta_native_client.chat.completions.create(**kwargs)

    def _invoke_native_llama_tool_completion(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: Any = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        if not self.meta_native_client:
            raise RuntimeError("LLAMA_API_KEY is not configured.")

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": self._normalize_messages_for_native(messages),
            "tools": tools,
            "tool_choice": tool_choice,
            "timeout": LLAMA_TOOLCALL_TIMEOUT_SECONDS,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_completion_tokens"] = max_tokens

        try:
            return self.meta_native_client.chat.completions.create(**kwargs)
        except TypeError:
            kwargs.pop("temperature", None)
            kwargs.pop("max_completion_tokens", None)
            kwargs.pop("timeout", None)
            kwargs.pop("tool_choice", None)
            return self.meta_native_client.chat.completions.create(**kwargs)

    def _list_llama_models(self) -> List[str]:
        if not self.meta_client:
            return []
        try:
            listing = self.meta_client.models.list()
        except Exception:
            return []
        return self._extract_model_ids(listing)

    def _resolve_available_70b_model(self) -> str | None:
        candidate = self._pick_best_70b_model(self._list_llama_models())
        if candidate:
            self._resolved_llama_model = candidate
        return candidate

    def _invoke_llama_completion(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        if not self.meta_client and not self.meta_native_client:
            raise RuntimeError("LLAMA_API_KEY is not configured.")

        if self.meta_native_client and self._prefer_native_meta:
            return self._invoke_native_llama_completion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        kwargs: Dict[str, Any] = {
            "messages": messages,
            "model": model,
            "timeout": LLAMA_TIMEOUT_SECONDS,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        if self.meta_client and not self._compat_chat_unavailable_reason:
            try:
                return self.meta_client.chat.completions.create(**kwargs)
            except TypeError:
                kwargs.pop("temperature", None)
                kwargs.pop("max_tokens", None)
                kwargs.pop("timeout", None)
                return self.meta_client.chat.completions.create(**kwargs)
            except Exception as exc:
                if not self.meta_native_client or not self._looks_like_compat_permission_error(exc):
                    raise
                self._disable_compat_meta(exc)

        return self._invoke_native_llama_completion(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _create_llama_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        active_model = self._active_llama_model()
        attempted_models: List[str] = []
        last_error: Exception | None = None

        while active_model and active_model not in attempted_models:
            attempted_models.append(active_model)
            try:
                completion = self._invoke_llama_completion(
                    model=active_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._resolved_llama_model = active_model
                return completion
            except Exception as exc:
                last_error = exc
                if not self._looks_like_model_error(exc):
                    break
                fallback_model = self._resolve_available_70b_model()
                if not fallback_model or fallback_model in attempted_models:
                    break
                active_model = fallback_model

        if last_error is not None:
            raise last_error
        raise RuntimeError("Unable to create a Llama completion.")

    def _create_google_tool_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: Any = "auto",
        temperature: float = 0.15,
        max_tokens: int = 380,
    ) -> Any:
        if not self.meta_client and not self.meta_native_client:
            raise RuntimeError("LLAMA_API_KEY is not configured.")

        active_model = self._active_llama_model()
        attempted_models: List[str] = []
        last_error: Exception | None = None

        while active_model and active_model not in attempted_models:
            attempted_models.append(active_model)
            try:
                if self.meta_native_client and self._prefer_native_meta:
                    completion = self._invoke_native_llama_tool_completion(
                        model=active_model,
                        messages=messages,
                        tools=tools,
                        tool_choice=tool_choice,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    self._resolved_llama_model = active_model
                    return completion

                if self.meta_client and not self._compat_chat_unavailable_reason:
                    kwargs: Dict[str, Any] = {
                        "model": active_model,
                        "messages": messages,
                        "tools": tools,
                        "tool_choice": tool_choice,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "timeout": LLAMA_TOOLCALL_TIMEOUT_SECONDS,
                    }
                    try:
                        completion = self.meta_client.chat.completions.create(**kwargs)
                    except TypeError:
                        kwargs.pop("temperature", None)
                        kwargs.pop("max_tokens", None)
                        kwargs.pop("timeout", None)
                        completion = self.meta_client.chat.completions.create(**kwargs)
                    self._resolved_llama_model = active_model
                    return completion

                completion = self._invoke_native_llama_tool_completion(
                    model=active_model,
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._resolved_llama_model = active_model
                return completion
            except Exception as exc:
                last_error = exc
                if self.meta_native_client and self._looks_like_compat_permission_error(exc):
                    self._disable_compat_meta(exc)
                    try:
                        completion = self._invoke_native_llama_tool_completion(
                            model=active_model,
                            messages=messages,
                            tools=tools,
                            tool_choice=tool_choice,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        )
                        self._resolved_llama_model = active_model
                        return completion
                    except Exception as native_exc:
                        last_error = native_exc

                if not self._looks_like_model_error(last_error):
                    break
                fallback_model = self._resolve_available_70b_model()
                if not fallback_model or fallback_model in attempted_models:
                    break
                active_model = fallback_model

        if last_error is not None:
            raise last_error
        raise RuntimeError("Unable to create a Google tool completion.")

    def _invoke_llama_stream(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        if self.meta_native_client and self._prefer_native_meta:
            kwargs: Dict[str, Any] = {
                "messages": self._normalize_messages_for_native(messages),
                "model": model,
                "stream": True,
                "timeout": LLAMA_TIMEOUT_SECONDS,
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            if max_tokens is not None:
                kwargs["max_completion_tokens"] = max_tokens
            try:
                return self.meta_native_client.chat.completions.create(**kwargs)
            except TypeError:
                kwargs.pop("temperature", None)
                kwargs.pop("max_completion_tokens", None)
                kwargs.pop("timeout", None)
                return self.meta_native_client.chat.completions.create(**kwargs)

        if not self.meta_client:
            raise RuntimeError("LLAMA_API_KEY is not configured.")
        if self._compat_chat_unavailable_reason:
            raise RuntimeError(self._compat_chat_unavailable_reason)

        kwargs: Dict[str, Any] = {
            "messages": messages,
            "model": model,
            "stream": True,
            "timeout": LLAMA_TIMEOUT_SECONDS,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        try:
            return self.meta_client.chat.completions.create(**kwargs)
        except TypeError:
            kwargs.pop("temperature", None)
            kwargs.pop("max_tokens", None)
            kwargs.pop("timeout", None)
            return self.meta_client.chat.completions.create(**kwargs)

    def _stream_llama_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Generator[str, None, None]:
        active_model = self._active_llama_model()
        attempted_models: List[str] = []
        last_error: Exception | None = None

        while active_model and active_model not in attempted_models:
            attempted_models.append(active_model)
            try:
                emitted_any = False
                stream = self._invoke_llama_stream(
                    model=active_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._resolved_llama_model = active_model

                for chunk in stream:
                    event = getattr(chunk, "event", None)
                    if event is not None:
                        delta = getattr(event, "delta", None)
                        if delta is not None:
                            delta_type = str(getattr(delta, "type", "")).strip().lower()
                            if delta_type == "text":
                                piece = self._coerce_text(getattr(delta, "text", None))
                                if piece:
                                    emitted_any = True
                                    yield piece
                                continue

                    choices = getattr(chunk, "choices", None) or []
                    if not choices:
                        continue
                    delta = getattr(choices[0], "delta", None)
                    piece = self._coerce_text(getattr(delta, "content", None))
                    if not piece:
                        continue
                    emitted_any = True
                    yield piece

                if not emitted_any:
                    completion = self._invoke_llama_completion(
                        model=active_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    fallback_text = self._extract_llama_text(completion)
                    if fallback_text:
                        yield from self._text_to_word_stream(fallback_text)
                return
            except Exception as exc:
                if self.meta_native_client and self._looks_like_compat_permission_error(exc):
                    self._disable_compat_meta(exc)
                    completion = self._invoke_native_llama_completion(
                        model=active_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    text = self._extract_llama_text(completion)
                    if text:
                        self._resolved_llama_model = active_model
                        yield from self._text_to_word_stream(text)
                        return
                last_error = exc
                if not self._looks_like_model_error(exc):
                    break
                fallback_model = self._resolve_available_70b_model()
                if not fallback_model or fallback_model in attempted_models:
                    break
                active_model = fallback_model

        if last_error is not None:
            raise last_error
        raise RuntimeError("Unable to stream a Llama completion.")

    def _load_embedding_model(self) -> Any:
        if self._embedding_model is not None:
            return self._embedding_model
        if SentenceTransformer is None:
            return None
        try:
            # Prefer local model files so the first prompt does not hang on model downloads.
            self._embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME, local_files_only=True)
        except TypeError:
            try:
                self._embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
            except Exception:
                self._embedding_model = None
        except Exception:
            if EMBEDDING_ALLOW_DOWNLOADS:
                try:
                    self._embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
                except Exception:
                    self._embedding_model = None
            else:
                self._embedding_model = None
        return self._embedding_model

    def _hash_text_embedding(self, text: str, dim: int = EMBEDDING_DIM) -> List[float]:
        dim = max(int(dim or 0), 8)
        vec = np.zeros(dim, dtype=np.float32)
        tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
        if not tokens:
            return vec.astype(float).tolist()

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + (digest[5] % 7) / 10.0
            vec[index] += sign * weight

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.astype(float).tolist()

    def _fallback_embeddings(self, texts: List[str]) -> List[List[float]]:
        return [self._hash_text_embedding(text) for text in texts]

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        model = self._load_embedding_model()
        if not texts:
            return []
        if not model:
            return self._fallback_embeddings(texts)
        try:
            vectors = model.encode(texts, normalize_embeddings=True)
        except Exception:
            return self._fallback_embeddings(texts)
        if isinstance(vectors, np.ndarray):
            return [row.astype(float).tolist() for row in vectors]
        return [[float(value) for value in row] for row in vectors]

    def chunk_text(self, text: str) -> List[str]:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return []
        chunks: List[str] = []
        start = 0
        text_len = len(cleaned)
        while start < text_len:
            end = min(start + RAG_CHUNK_SIZE, text_len)
            chunk = cleaned[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= text_len:
                break
            start = max(end - RAG_CHUNK_OVERLAP, start + 1)
        return chunks

    def _extract_text_from_pdf(self, payload: bytes) -> str:
        if PdfReader is None:
            return ""
        try:
            reader = PdfReader(io.BytesIO(payload))
            return "\n".join((page.extract_text() or "").strip() for page in reader.pages)
        except Exception:
            return ""

    def _extract_text_from_docx(self, payload: bytes) -> str:
        if DocxDocument is None:
            return ""
        try:
            doc = DocxDocument(io.BytesIO(payload))
            return "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())
        except Exception:
            return ""

    def extract_text_from_file(self, filename: str, payload: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix == ".txt":
            try:
                return payload.decode("utf-8")
            except UnicodeDecodeError:
                return payload.decode("latin-1", errors="ignore")
        if suffix == ".pdf":
            return self._extract_text_from_pdf(payload)
        if suffix == ".docx":
            return self._extract_text_from_docx(payload)
        return ""

    def ingest_document(
        self,
        user_id: str,
        chat_id: str,
        filename: str,
        payload: bytes,
    ) -> str:
        text = self.extract_text_from_file(filename=filename, payload=payload)
        chunks = self.chunk_text(text)
        if not chunks:
            return f"Skipped `{filename}` because no text could be extracted."
        embeddings = self.embed_texts(chunks)
        inserted = self.store.save_document_chunks(
            user_id=user_id,
            chat_id=chat_id,
            document_name=filename,
            chunks=chunks,
            embeddings=embeddings,
            metadata={"source": "upload"},
        )
        return f"Ingested `{filename}` into RAG memory with {inserted} chunks."

    def retrieve_rag_context(self, user_id: str, chat_id: str, query: str) -> str:
        query_embedding = self.embed_texts([query])[0]
        matches = self.store.search_document_chunks(
            user_id=user_id,
            chat_id=chat_id,
            query_embedding=query_embedding,
            top_k=RAG_TOP_K,
        )
        # Fall back to user-wide memory when current-chat retrieval is sparse.
        if len(matches) < max(2, RAG_TOP_K // 2):
            global_matches = self.store.search_document_chunks(
                user_id=user_id,
                chat_id=None,
                query_embedding=query_embedding,
                top_k=RAG_TOP_K,
            )
            seen_ids: set[str] = set()
            merged: List[Dict[str, Any]] = []
            for item in [*matches, *global_matches]:
                item_id = str(item.get("id", "")) or f"{item.get('document_name','')}::{item.get('chunk_index','')}"
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                merged.append(item)
            matches = merged[:RAG_TOP_K]
        if not matches:
            return "No relevant document chunks found."
        lines = []
        for item in matches:
            source = item.get("document_name", "document")
            chunk_index = item.get("chunk_index", "?")
            score = item.get("similarity")
            score_text = f"{float(score):.3f}" if score is not None else "n/a"
            content = str(item.get("content", "")).strip()
            lines.append(f"- [{source} | chunk {chunk_index} | score {score_text}] {content}")
        return "\n".join(lines)

    def _document_inventory_context(self, user_id: str, chat_id: str) -> str:
        try:
            current_docs = self.store.list_user_documents(user_id=user_id, chat_id=chat_id, limit=1500)
            all_docs = self.store.list_user_documents(user_id=user_id, chat_id=None, limit=3000)
        except Exception:
            return "DOCUMENT_INVENTORY:\nUnavailable."

        current_count = len(current_docs)
        total_count = len(all_docs)
        sample_current = ", ".join(current_docs[:12]) if current_docs else "none"
        sample_total = ", ".join(all_docs[:20]) if all_docs else "none"
        return (
            "DOCUMENT_INVENTORY:\n"
            f"- Current chat documents: {current_count}\n"
            f"- All chats documents for this user: {total_count}\n"
            f"- Current chat sample: {sample_current}\n"
            f"- All chats sample: {sample_total}\n"
            "When the user asks how many files/documents/PDFs are available, rely on these counts."
        )

    def _is_current_events_prompt(self, prompt: str) -> bool:
        lowered = prompt.lower()
        return any(keyword in lowered for keyword in CURRENT_EVENT_HINT_KEYWORDS)

    def search_tavily(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        if not TAVILY_API_KEY:
            return []
        try:
            response = requests.post(
                TAVILY_SEARCH_URL,
                json={
                    "api_key": TAVILY_API_KEY,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": max_results,
                    "include_answer": True,
                },
                timeout=TAVILY_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            return payload.get("results", [])
        except Exception:
            return []

    def _format_web_context(self, results: List[Dict[str, Any]]) -> str:
        if not results:
            return "No fresh web data available."
        formatted = []
        for item in results:
            title = item.get("title", "")
            url = item.get("url", "")
            content = item.get("content", "")
            formatted.append(f"- {title}\n  URL: {url}\n  Snippet: {content}")
        return "\n".join(formatted)
    def transcribe_audio(self, payload: bytes, filename: str = "voice.wav") -> str:
        if not self.groq_client:
            self._last_transcription_error = "GROQ_API_KEY is missing, so voice transcription is disabled."
            return ""
        if not payload:
            self._last_transcription_error = "Voice payload is empty."
            return ""
        mime_type = mimetypes.guess_type(filename)[0] or "audio/wav"
        models = [GROQ_WHISPER_MODEL, "whisper-large-v3-turbo", "whisper-large-v3"]
        checked_models = [item for item in dict.fromkeys(models) if item]
        last_exc: Exception | None = None

        for model_name in checked_models:
            audio_stream = io.BytesIO(payload)
            audio_stream.name = filename
            try:
                transcript = self.groq_client.audio.transcriptions.create(
                    model=model_name,
                    file=(filename, audio_stream.read(), mime_type),
                    timeout=GROQ_TIMEOUT_SECONDS,
                )
                text = str(getattr(transcript, "text", "")).strip()
                if text:
                    self._last_transcription_error = ""
                    return text
            except Exception as exc:
                last_exc = exc

        if last_exc is not None:
            self._last_transcription_error = f"Groq transcription failed: {last_exc}"
        else:
            self._last_transcription_error = "Groq returned an empty transcript."
        return ""

    def last_transcription_error(self) -> str:
        return self._last_transcription_error

    def _image_to_base64(self, payload: bytes, filename: str, max_side: int = 1280, quality: int = 72) -> str:
        prepared_payload = payload
        mime = mimetypes.guess_type(filename)[0] or "image/jpeg"
        if Image is not None:
            try:
                image = Image.open(io.BytesIO(payload))
                image.load()
                if image.mode in {"RGBA", "LA", "P"}:
                    rgb = Image.new("RGB", image.size, (255, 255, 255))
                    alpha = image.convert("RGBA").split()[-1]
                    rgb.paste(image.convert("RGBA"), mask=alpha)
                    image = rgb
                elif image.mode != "RGB":
                    image = image.convert("RGB")

                if max(image.size) > max_side:
                    image.thumbnail((max_side, max_side))

                output = io.BytesIO()
                image.save(output, format="JPEG", quality=quality, optimize=True)
                prepared_payload = output.getvalue()
                mime = "image/jpeg"
            except Exception:
                prepared_payload = payload
        encoded = base64.b64encode(prepared_payload).decode("utf-8")
        return f"data:{mime};base64,{encoded}"

    def _groq_vision_call(self, image_url: str, user_prompt: str, filename: str) -> str:
        completion = self.groq_client.chat.completions.create(
            model=GROQ_VISION_MODEL,
            temperature=0.2,
            max_tokens=450,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Analyze this image quickly and extract actionable details relevant "
                                f"to this user request: {user_prompt}"
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
        )
        return str(completion.choices[0].message.content or "").strip()

    def analyze_image(self, filename: str, payload: bytes, user_prompt: str) -> str:
        if not self.groq_client:
            return "Vision unavailable because GROQ_API_KEY is missing."

        # First attempt with standard compression (1280px, quality 72).
        try:
            image_url = self._image_to_base64(payload=payload, filename=filename, max_side=1280, quality=72)
            return self._groq_vision_call(image_url, user_prompt, filename)
        except Exception as first_exc:
            first_error = str(first_exc)

        # Retry with aggressive compression (768px, quality 55) on any failure.
        try:
            image_url = self._image_to_base64(payload=payload, filename=filename, max_side=768, quality=55)
            return self._groq_vision_call(image_url, user_prompt, filename)
        except Exception as retry_exc:
            return f"Vision analysis failed for `{filename}`: {first_error} (retry also failed: {retry_exc})"

    def _extract_video_frames(self, filename: str, payload: bytes) -> List[Tuple[float, str]]:
        if cv2 is None:
            return []
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix.lower() or ".mp4"
        temp_path = None
        frames: List[Tuple[float, str]] = []
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=TEMP_DIR) as temp_file:
                temp_file.write(payload)
                temp_path = temp_file.name

            capture = cv2.VideoCapture(temp_path)
            fps = capture.get(cv2.CAP_PROP_FPS) or 24.0
            frame_step = max(int(fps * VISION_FRAME_STEP_SECONDS), 1)
            index = 0
            while capture.isOpened() and len(frames) < VISION_MAX_FRAMES:
                ok, frame = capture.read()
                if not ok:
                    break
                if index % frame_step == 0:
                    success, encoded = cv2.imencode(".jpg", frame)
                    if success:
                        second_mark = index / fps
                        frames.append((second_mark, base64.b64encode(encoded.tobytes()).decode("utf-8")))
                index += 1
            capture.release()
        except Exception:
            frames = []
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        return frames

    def analyze_video(self, filename: str, payload: bytes, user_prompt: str) -> str:
        if not self.groq_client:
            return "Video understanding unavailable because GROQ_API_KEY is missing."
        frames = self._extract_video_frames(filename=filename, payload=payload)
        if not frames:
            return f"Could not extract frames from `{filename}`."
        content: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "You are analyzing sampled video frames every 3 seconds. "
                    "Describe key events, entities, and signals relevant to: "
                    f"{user_prompt}"
                ),
            }
        ]
        for second_mark, b64_frame in frames:
            content.append({"type": "text", "text": f"Frame at ~{second_mark:.1f}s"})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_frame}"}})
        try:
            completion = self.groq_client.chat.completions.create(
                model=GROQ_VISION_MODEL,
                temperature=0.2,
                max_tokens=700,
                messages=[{"role": "user", "content": content}],
            )
            text = str(completion.choices[0].message.content or "").strip()
            return f"Video analysis for `{filename}`:\n{text}"
        except Exception as exc:
            return f"Video analysis failed for `{filename}`: {exc}"

    def _load_table_dataframe(self, filename: str, payload: bytes) -> Any:
        if pd is None:
            return None
        suffix = Path(filename).suffix.lower()
        stream = io.BytesIO(payload)
        try:
            if suffix == ".csv":
                return pd.read_csv(stream)
            if suffix in {".xlsx", ".xls"}:
                return pd.read_excel(stream)
        except Exception:
            return None
        return None

    def auto_visualize_dataframe(self, filename: str, df: Any, prompt: str) -> Tuple[Any, str]:
        if pd is None or px is None or df is None or getattr(df, "empty", True):
            return None, ""

        frame = df.copy()
        frame.columns = [str(col).strip() for col in frame.columns]
        numeric_cols = frame.select_dtypes(include=["number"]).columns.tolist()
        datetime_cols: List[str] = []
        for column in frame.columns:
            lowered = column.lower()
            if any(token in lowered for token in ("date", "time", "month", "year")):
                parsed = pd.to_datetime(frame[column], errors="coerce")
                if parsed.notna().sum() > 0:
                    frame[column] = parsed
                    datetime_cols.append(column)
        prompt_lower = prompt.lower()
        fig = None
        explanation = ""

        if len(numeric_cols) >= 2 and any(keyword in prompt_lower for keyword in ("correlation", "scatter", "vs")):
            x_col, y_col = numeric_cols[0], numeric_cols[1]
            fig = px.scatter(frame, x=x_col, y=y_col, title=f"{filename}: {y_col} vs {x_col}")
            explanation = f"Generated scatter plot for `{y_col}` vs `{x_col}` from `{filename}`."
        elif numeric_cols and datetime_cols:
            date_col = datetime_cols[0]
            value_col = numeric_cols[0]
            sorted_frame = frame.sort_values(date_col)
            fig = px.line(sorted_frame, x=date_col, y=value_col, title=f"{filename}: {value_col} over time")
            explanation = f"Generated trend line for `{value_col}` over `{date_col}` from `{filename}`."
        elif len(numeric_cols) >= 1:
            value_col = numeric_cols[0]
            fig = px.histogram(frame, x=value_col, nbins=25, title=f"{filename}: distribution of {value_col}")
            explanation = f"Generated histogram for `{value_col}` from `{filename}`."
        else:
            categorical_cols = frame.select_dtypes(exclude=["number", "datetime"]).columns.tolist()
            if categorical_cols:
                cat_col = categorical_cols[0]
                counts = frame[cat_col].astype(str).value_counts().head(20).reset_index()
                counts.columns = [cat_col, "count"]
                fig = px.bar(counts, x=cat_col, y="count", title=f"{filename}: top categories in {cat_col}")
                explanation = f"Generated bar chart for category counts in `{cat_col}` from `{filename}`."
        return fig, explanation

    def process_attachments(
        self,
        user_id: str,
        chat_id: str,
        prompt: str,
        uploads: List[Tuple[str, bytes]],
    ) -> AttachmentInsights:
        notes: List[str] = []
        figures: List[Any] = []
        errors: List[str] = []
        for filename, payload in uploads:
            suffix = Path(filename).suffix.lower()
            if suffix in SUPPORTED_DOC_EXTENSIONS:
                notes.append(self.ingest_document(user_id=user_id, chat_id=chat_id, filename=filename, payload=payload))
                continue
            if suffix in SUPPORTED_IMAGE_EXTENSIONS:
                notes.append(self.analyze_image(filename=filename, payload=payload, user_prompt=prompt))
                continue
            if suffix in SUPPORTED_VIDEO_EXTENSIONS:
                notes.append(self.analyze_video(filename=filename, payload=payload, user_prompt=prompt))
                continue
            if suffix in SUPPORTED_DATA_EXTENSIONS:
                dataframe = self._load_table_dataframe(filename=filename, payload=payload)
                if dataframe is None:
                    errors.append(f"Unable to parse tabular file `{filename}`.")
                    continue
                figure, explanation = self.auto_visualize_dataframe(filename=filename, df=dataframe, prompt=prompt)
                if figure is not None:
                    figures.append(figure)
                if explanation:
                    notes.append(explanation)
                preview = dataframe.head(8).to_markdown(index=False)
                notes.append(f"Data preview from `{filename}`:\n{preview}")
                continue
            errors.append(f"`{filename}` has an unsupported file type.")
        return AttachmentInsights(notes=notes, figures=figures, errors=errors)

    def _google_token_path(self) -> Path:
        return Path(GOOGLE_OAUTH_TOKEN_JSON).expanduser()

    def _google_env_creds_configured(self) -> bool:
        return bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REFRESH_TOKEN)

    def _google_credentials(self) -> Any:
        if Credentials is None:
            self._google_diagnostics = "Google auth libraries are not installed in the current environment."
            return None

        creds = None
        token_path = self._google_token_path()
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), scopes=GOOGLE_OAUTH_SCOPES)
            except Exception as exc:
                self._google_diagnostics = f"Invalid `{token_path.name}`: {exc}"
                creds = None

        if creds is None and self._google_env_creds_configured():
            try:
                creds = Credentials(
                    token=GOOGLE_OAUTH_ACCESS_TOKEN or None,
                    refresh_token=GOOGLE_OAUTH_REFRESH_TOKEN,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=GOOGLE_OAUTH_CLIENT_ID,
                    client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
                    scopes=GOOGLE_OAUTH_SCOPES,
                )
            except Exception as exc:
                self._google_diagnostics = f"Invalid Google OAuth env variables: {exc}"
                creds = None

        if creds is None and not token_path.exists() and not self._google_env_creds_configured():
            self._google_diagnostics = (
                f"Missing `{token_path.name}` and OAuth env credentials. "
                "Set GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_OAUTH_REFRESH_TOKEN "
                "(or create the token file after OAuth consent)."
            )
            return None

        if creds and creds.expired and creds.refresh_token and GoogleRequest is not None:
            try:
                creds.refresh(GoogleRequest())
            except Exception as exc:
                self._google_diagnostics = f"Google OAuth token refresh failed: {exc}"
                pass

        if creds and not creds.valid:
            self._google_diagnostics = "Google OAuth credentials are present but not valid."
            return None

        if creds:
            granted_scopes = getattr(creds, "granted_scopes", None) or getattr(creds, "scopes", None) or []
            self._google_granted_scopes = {str(scope).strip() for scope in granted_scopes if str(scope).strip()}
            try:
                token_path.write_text(creds.to_json(), encoding="utf-8")
            except Exception:
                pass
            self._google_diagnostics = "Google OAuth connected."
        return creds

    def _google_services(self) -> Tuple[Any, Any]:
        creds = self._google_credentials()
        if not creds or build is None:
            return None, None
        try:
            calendar_service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        except Exception:
            calendar_service = None
        try:
            gmail_service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        except Exception:
            gmail_service = None

        # Treat Google as fully connected when Gmail is reachable with a read-capable scope.
        if gmail_service and self._has_gmail_read_scope():
            if calendar_service and self._has_calendar_scope():
                self._google_diagnostics = "Google Calendar + Gmail connected."
            elif calendar_service:
                self._google_diagnostics = "Gmail connected (read scope OK). Calendar connected with limited scope."
            else:
                self._google_diagnostics = "Gmail connected (read scope OK)."
        elif calendar_service and gmail_service:
            self._google_diagnostics = "Google Calendar connected. Gmail scope may be limited."
        elif calendar_service:
            self._google_diagnostics = "Google Calendar connected but Gmail unavailable."
        elif gmail_service:
            self._google_diagnostics = (
                "Gmail connected but token is missing read-capable Gmail scope "
                "(`gmail.readonly` or `gmail.modify`)."
            )
        elif not self._google_diagnostics:
            self._google_diagnostics = "Google APIs are configured but service build failed."
        return calendar_service, gmail_service

    def google_connection_diagnostics(self) -> str:
        if self._google_diagnostics:
            return self._google_diagnostics
        return "Google Workspace is not connected."

    def _has_any_google_scope(self, *candidates: str) -> bool:
        if not self._google_granted_scopes:
            return True
        return any(scope in self._google_granted_scopes for scope in candidates if scope)

    def _has_gmail_read_scope(self) -> bool:
        return self._has_any_google_scope(
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://mail.google.com/",
        )

    def _has_calendar_scope(self) -> bool:
        return self._has_any_google_scope(
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
        )

    def _gmail_header_value(self, headers: List[Dict[str, Any]], name: str) -> str:
        target = name.lower().strip()
        for header in headers or []:
            header_name = str(header.get("name", "")).lower().strip()
            if header_name == target:
                return str(header.get("value", "")).strip()
        return ""

    def _extract_gmail_body_preview(self, payload: Dict[str, Any]) -> str:
        html_candidate = ""
        queue: List[Dict[str, Any]] = [payload or {}]

        while queue:
            part = queue.pop(0)
            mime_type = str(part.get("mimeType", "")).lower()
            body = part.get("body", {}) or {}
            data = body.get("data")
            if data:
                try:
                    decoded = base64.urlsafe_b64decode(str(data) + "=" * (-len(str(data)) % 4)).decode(
                        "utf-8",
                        errors="ignore",
                    )
                except Exception:
                    decoded = ""
                cleaned = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", decoded)).strip()
                if cleaned:
                    if mime_type == "text/plain":
                        return cleaned[:900]
                    if mime_type == "text/html" and not html_candidate:
                        html_candidate = cleaned[:900]
            queue.extend(part.get("parts") or [])

        return html_candidate

    def _normalize_gmail_query(self, raw_query: Any) -> str:
        query = str(raw_query or "").strip()
        if not query:
            return "in:inbox newer_than:14d"

        timeframe = ""
        timeframe_patterns: List[Tuple[str, int]] = [
            (r"\b(?:in:\s*)?(?:from\s+)?(?:last|past)\s+(\d{1,3})\s+days?\b", 1),
            (r"\b(?:in:\s*)?(?:from\s+)?(?:last|past)\s+(\d{1,2})\s+weeks?\b", 7),
            (r"\b(?:in:\s*)?(?:from\s+)?(?:last|past)\s+(\d{1,2})\s+months?\b", 30),
        ]
        for pattern, multiplier in timeframe_patterns:
            match = re.search(pattern, query, flags=re.IGNORECASE)
            if not match:
                continue
            amount = max(1, int(match.group(1))) * multiplier
            timeframe = f"newer_than:{amount}d"
            query = re.sub(pattern, " ", query, flags=re.IGNORECASE)
            break

        # If the model already emitted a loose leftover like "7 days", remove it after extracting timeframe.
        if timeframe:
            query = re.sub(r"\b\d{1,3}\s+(?:days?|weeks?|months?)\b", " ", query, flags=re.IGNORECASE)

        # Strip instruction-like filler so only search filters/keywords reach Gmail.
        query = re.sub(
            r"\b(?:summari[sz]e|summary|check|read|show|list|find|my|emails?|mail|gmail|inbox|messages?)\b",
            " ",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(r"\bin:\s+", "in:", query, flags=re.IGNORECASE)
        query = re.sub(
            r"\bin:(?=(?:newer_than:|older_than:|after:|before:|from:|to:|subject:|label:|category:|has:|is:|$))",
            " ",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(r"\s+", " ", query).strip(" ,")
        if query.lower() in {
            "emails",
            "email",
            "mail",
            "my emails",
            "my email",
            "inbox",
            "messages",
            "gmail",
        }:
            query = ""

        has_structured_filters = bool(
            re.search(
                r"\b(?:from:|to:|subject:|label:|category:|newer_than:|older_than:|after:|before:|rfc822msgid:|has:|is:|in:)\S*",
                query,
                flags=re.IGNORECASE,
            )
        )

        parts: List[str] = []
        if not has_structured_filters:
            parts.append("in:inbox")
        if timeframe and not re.search(r"\bnewer_than:\S+", query, flags=re.IGNORECASE):
            parts.append(timeframe)
        if query:
            parts.append(query)

        normalized = " ".join(parts).strip()
        return normalized or "in:inbox newer_than:14d"

    def _normalize_email_recipients(self, raw_recipients: Any) -> List[str]:
        values: List[str] = []
        if isinstance(raw_recipients, str):
            values = [raw_recipients]
        elif isinstance(raw_recipients, list):
            values = [str(item) for item in raw_recipients]
        else:
            return []

        normalized: List[str] = []
        seen: set[str] = set()
        email_pattern = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", flags=re.IGNORECASE)
        for value in values:
            for part in re.split(r"[;,]", str(value)):
                candidate = part.strip()
                if not candidate:
                    continue
                _, parsed = parseaddr(candidate)
                parsed = parsed.strip().lower()
                if not parsed:
                    parsed = candidate.lower()
                parsed = parsed.strip("<> ")
                if not email_pattern.match(parsed):
                    continue
                if parsed in seen:
                    continue
                seen.add(parsed)
                normalized.append(parsed)
        return normalized

    def _normalize_calendar_datetime(
        self,
        raw_value: Any,
        default_hour: int = 9,
        assume_tz: timezone | None = None,
    ) -> Tuple[Dict[str, str] | None, bool]:
        text = str(raw_value or "").strip()
        if not text:
            return None, False

        local_tz = assume_tz or datetime.now().astimezone().tzinfo or timezone.utc
        cleaned = text.replace("Z", "+00:00")

        # ISO date only -> all-day event.
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
            return {"date": cleaned}, True

        parsed: datetime | None = None
        try:
            parsed = datetime.fromisoformat(cleaned)
        except Exception:
            parsed = None

        if parsed is None:
            formats = [
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d %I:%M %p",
                "%Y/%m/%d %H:%M",
                "%Y/%m/%d %I:%M %p",
                "%d-%m-%Y %H:%M",
                "%d-%m-%Y %I:%M %p",
                "%m/%d/%Y %H:%M",
                "%m/%d/%Y %I:%M %p",
            ]
            for fmt in formats:
                try:
                    parsed = datetime.strptime(cleaned, fmt)
                    break
                except Exception:
                    continue

        if parsed is None and re.fullmatch(r"\d{4}-\d{2}-\d{2}\s+\d{1,2}", cleaned):
            try:
                parsed = datetime.strptime(cleaned, "%Y-%m-%d %H")
            except Exception:
                parsed = None

        if parsed is None:
            return None, False

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=local_tz)
        return {"dateTime": parsed.isoformat()}, False

    def _build_calendar_event_window(
        self,
        start_raw: Any,
        end_raw: Any,
    ) -> Tuple[Dict[str, str] | None, Dict[str, str] | None, str]:
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        start_obj, start_all_day = self._normalize_calendar_datetime(start_raw, default_hour=9, assume_tz=local_tz)
        if start_obj is None:
            return None, None, "Invalid `start_time`. Use a date like `2026-04-28` or datetime like `2026-04-28T10:00`."

        if start_all_day:
            if end_raw:
                end_obj, end_all_day = self._normalize_calendar_datetime(end_raw, default_hour=9, assume_tz=local_tz)
                if end_obj is None:
                    return None, None, "Invalid `end_time` for all-day event."
                if not end_all_day:
                    return None, None, "For all-day events, `end_time` should be a date (YYYY-MM-DD)."
                start_date = datetime.fromisoformat(start_obj["date"]).date()
                end_date = datetime.fromisoformat(end_obj["date"]).date()
                if end_date <= start_date:
                    end_date = start_date + timedelta(days=1)
                end_obj = {"date": end_date.isoformat()}
                return start_obj, end_obj, ""

            # Calendar API expects all-day end date to be exclusive.
            start_date = datetime.fromisoformat(start_obj["date"]).date()
            return start_obj, {"date": (start_date + timedelta(days=1)).isoformat()}, ""

        # Timed event path
        if end_raw:
            end_obj, end_all_day = self._normalize_calendar_datetime(end_raw, default_hour=10, assume_tz=local_tz)
            if end_obj is None:
                return None, None, "Invalid `end_time`."
            if end_all_day:
                return None, None, "Timed events require datetime `end_time`."
            try:
                start_dt = datetime.fromisoformat(start_obj["dateTime"])
                end_dt = datetime.fromisoformat(end_obj["dateTime"])
                if end_dt <= start_dt:
                    end_dt = start_dt + timedelta(hours=1)
                    end_obj = {"dateTime": end_dt.isoformat()}
            except Exception:
                pass
            return start_obj, end_obj, ""

        # End time missing -> default to +1 hour.
        try:
            start_dt = datetime.fromisoformat(start_obj["dateTime"])
            end_dt = start_dt + timedelta(hours=1)
            return start_obj, {"dateTime": end_dt.isoformat()}, ""
        except Exception:
            return None, None, "Unable to derive end time."

    def _google_tools_guidance(
        self,
        user_prompt: str,
        calendar_service: Any,
        gmail_service: Any,
    ) -> str:
        available_tools: List[str] = []
        if gmail_service:
            available_tools.extend(["read_gmail_messages", "manage_gmail_message"])
        if calendar_service:
            available_tools.extend(["list_calendar_events", "create_calendar_event"])

        tool_list = ", ".join(available_tools) if available_tools else "none"

        # Provide current date/time so the LLM can resolve relative dates
        # like "tomorrow", "next Monday", "this Friday", etc.
        now = datetime.now().astimezone()
        current_datetime = now.strftime("%Y-%m-%dT%H:%M:%S%z")
        current_date = now.strftime("%Y-%m-%d")
        current_day = now.strftime("%A")
        tomorrow_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")

        return (
            "You are an autonomous Personal Intelligence Agent. You HAVE access to Gmail and Calendar via "
            "tool-calling. If the user asks about emails or meetings, use the provided tools.\n"
            f"Available Google tools right now: {tool_list}.\n"
            f"Current date and time: {current_datetime} ({current_day}). "
            f"Today is {current_date}. Tomorrow is {tomorrow_date}.\n"
            "IMPORTANT: When the user says 'tomorrow', use the date listed above. "
            "Always provide start_time in ISO format like '2026-04-21T10:00' for timed events "
            "or '2026-04-21' for all-day events.\n"
            "If the user asks to summarize emails, check inbox status, inspect unread mail, or review upcoming "
            "meetings, you must call the relevant tool before answering. Do not claim you lack access when a "
            "tool is available.\n"
            "Never claim an email was sent/drafted or a calendar event was scheduled unless the corresponding "
            "tool call succeeded and returned an id.\n"
            f"User request: {user_prompt}"
        )

    def _forced_google_tool_choice(
        self,
        user_prompt: str,
        calendar_service: Any,
        gmail_service: Any,
    ) -> Dict[str, Any] | None:
        normalized = user_prompt.lower()

        gmail_read_intent = any(
            fragment in normalized
            for fragment in (
                "summarize my emails",
                "summarize emails",
                "summarize email",
                "check my emails",
                "check my email",
                "read my emails",
                "read my email",
                "inbox",
                "unread email",
                "unread emails",
                "latest emails",
                "recent emails",
                "email summary",
                "mail summary",
            )
        )
        gmail_send_intent = self._is_gmail_action_prompt(user_prompt)
        if gmail_service and gmail_send_intent:
            return {"type": "function", "function": {"name": "manage_gmail_message"}}
        if gmail_service and gmail_read_intent and not gmail_send_intent:
            return {"type": "function", "function": {"name": "read_gmail_messages"}}

        calendar_list_intent = any(
            fragment in normalized
            for fragment in (
                "my meetings",
                "meetings today",
                "upcoming meetings",
                "today agenda",
                "agenda",
                "calendar today",
                "calendar this week",
                "upcoming events",
                "my schedule",
                "today's schedule",
                "todays schedule",
                "what's on my calendar",
                "what is on my calendar",
                "show my calendar",
                "list events",
            )
        )
        calendar_create_intent = self._is_calendar_create_prompt(user_prompt)
        if calendar_service and calendar_create_intent:
            return {"type": "function", "function": {"name": "create_calendar_event"}}
        if calendar_service and calendar_list_intent and not calendar_create_intent:
            return {"type": "function", "function": {"name": "list_calendar_events"}}

        return None

    def google_tool_schemas(self) -> List[Dict[str, Any]]:
        # Keep schemas intentionally minimal for best compatibility with model tool-calling.
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_calendar_events",
                    "description": "List upcoming calendar events.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "max_results": {"type": "integer"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_calendar_event",
                    "description": "Create a calendar event.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                            "start_time": {"type": "string"},
                            "end_time": {"type": "string"},
                            "description": {"type": "string"},
                            "attendees": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["summary", "start_time"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_gmail_messages",
                    "description": "Read recent Gmail messages.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "max_results": {"type": "integer"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "manage_gmail_message",
                    "description": "Draft or send an email.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string"},
                            "to": {"type": "array", "items": {"type": "string"}},
                            "subject": {"type": "string"},
                            "body": {"type": "string"},
                        },
                        "required": ["action", "to", "subject", "body"],
                    },
                },
            },
        ]

    def execute_google_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        calendar_service: Any = None,
        gmail_service: Any = None,
    ) -> Dict[str, Any]:
        if calendar_service is None and gmail_service is None:
            calendar_service, gmail_service = self._google_services()
        arguments = arguments if isinstance(arguments, dict) else {}

        if tool_name == "list_calendar_events":
            if not calendar_service:
                return {
                    "status": "error",
                    "tool": tool_name,
                    "message": f"Google Calendar is not connected. {self.google_connection_diagnostics()}",
                }
            if not self._has_calendar_scope():
                return {
                    "status": "error",
                    "tool": tool_name,
                    "message": "Google Calendar read scope is missing. Re-run `python google_token_setup.py`.",
                }

            now = datetime.now(timezone.utc)
            query = str(arguments.get("query", "")).strip()
            time_min = str(arguments.get("time_min") or now.isoformat())
            time_max = str(arguments.get("time_max") or (now + timedelta(days=7)).isoformat())
            try:
                max_results = max(1, min(int(arguments.get("max_results", 8)), 15))
            except (TypeError, ValueError):
                max_results = 8

            try:
                response = (
                    calendar_service.events()
                    .list(
                        calendarId=GOOGLE_DEFAULT_CALENDAR_ID,
                        timeMin=time_min,
                        timeMax=time_max,
                        maxResults=max_results,
                        singleEvents=True,
                        orderBy="startTime",
                        q=query or None,
                    )
                    .execute()
                )
                events = []
                for item in response.get("items", []) or []:
                    start = (item.get("start") or {}).get("dateTime") or (item.get("start") or {}).get("date")
                    end = (item.get("end") or {}).get("dateTime") or (item.get("end") or {}).get("date")
                    attendees = [
                        attendee.get("email", "")
                        for attendee in (item.get("attendees") or [])
                        if attendee.get("email")
                    ]
                    events.append(
                        {
                            "id": item.get("id"),
                            "summary": item.get("summary") or "Untitled event",
                            "start": start,
                            "end": end,
                            "attendees": attendees,
                            "html_link": item.get("htmlLink"),
                        }
                    )
                return {
                    "status": "ok",
                    "tool": tool_name,
                    "count": len(events),
                    "time_min": time_min,
                    "time_max": time_max,
                    "events": events,
                }
            except Exception as exc:
                return {"status": "error", "tool": tool_name, "message": str(exc)}

        if tool_name == "create_calendar_event":
            if not calendar_service:
                return {
                    "status": "error",
                    "tool": tool_name,
                    "message": f"Google Calendar is not connected. {self.google_connection_diagnostics()}",
                }
            if not self._has_calendar_scope():
                return {
                    "status": "error",
                    "tool": tool_name,
                    "message": "Google Calendar write scope is missing. Re-run `python google_token_setup.py`.",
                }

            summary = str(arguments.get("summary", "PIA meeting")).strip() or "PIA meeting"
            description = str(arguments.get("description", "")).strip()
            start_obj, end_obj, window_error = self._build_calendar_event_window(
                arguments.get("start_time"),
                arguments.get("end_time"),
            )
            if window_error:
                return {"status": "error", "tool": tool_name, "message": window_error}

            attendees = [{"email": item} for item in self._normalize_email_recipients(arguments.get("attendees", []))]
            body = {
                "summary": summary,
                "description": description,
                "start": start_obj or {},
                "end": end_obj or {},
                "attendees": attendees,
            }
            try:
                event = (
                    calendar_service.events()
                    .insert(calendarId=GOOGLE_DEFAULT_CALENDAR_ID, body=body, sendUpdates="all")
                    .execute()
                )
                event_id = str(event.get("id", "")).strip()
                if not event_id:
                    return {"status": "error", "tool": tool_name, "message": "Calendar API returned no event id."}
                try:
                    verified = (
                        calendar_service.events()
                        .get(calendarId=GOOGLE_DEFAULT_CALENDAR_ID, eventId=event_id)
                        .execute()
                    )
                except Exception as verify_exc:
                    return {
                        "status": "error",
                        "tool": tool_name,
                        "message": f"Event created with id `{event_id}` but verification failed: {verify_exc}",
                        "event_id": event_id,
                    }
                return {
                    "status": "ok",
                    "tool": tool_name,
                    "event_id": event_id,
                    "html_link": verified.get("htmlLink") or event.get("htmlLink"),
                    "summary": verified.get("summary") or summary,
                    "start": (verified.get("start") or {}).get("dateTime") or (verified.get("start") or {}).get("date"),
                    "end": (verified.get("end") or {}).get("dateTime") or (verified.get("end") or {}).get("date"),
                    "attendees": [
                        attendee.get("email", "")
                        for attendee in (verified.get("attendees") or [])
                        if attendee.get("email")
                    ],
                    "verified": True,
                }
            except Exception as exc:
                return {"status": "error", "tool": tool_name, "message": str(exc)}

        if tool_name == "read_gmail_messages":
            if not gmail_service:
                return {
                    "status": "error",
                    "tool": tool_name,
                    "message": f"Gmail is not connected. {self.google_connection_diagnostics()}",
                }
            if not self._has_gmail_read_scope():
                return {
                    "status": "error",
                    "tool": tool_name,
                    "message": "Gmail read scope is missing. Re-run `python google_token_setup.py`.",
                }

            query = self._normalize_gmail_query(arguments.get("query"))
            try:
                max_results = max(1, min(int(arguments.get("max_results", 6)), 10))
            except (TypeError, ValueError):
                max_results = 6

            try:
                response = gmail_service.users().messages().list(
                    userId="me",
                    q=query,
                    maxResults=max_results,
                ).execute()
                message_refs = response.get("messages", []) or []
                messages: List[Dict[str, Any]] = []

                for ref in message_refs:
                    message_id = str(ref.get("id", "")).strip()
                    if not message_id:
                        continue
                    detail = gmail_service.users().messages().get(
                        userId="me",
                        id=message_id,
                        format="full",
                    ).execute()
                    payload = detail.get("payload", {}) or {}
                    headers = payload.get("headers", []) or []
                    messages.append(
                        {
                            "id": detail.get("id"),
                            "thread_id": detail.get("threadId"),
                            "subject": self._gmail_header_value(headers, "Subject"),
                            "from": self._gmail_header_value(headers, "From"),
                            "date": self._gmail_header_value(headers, "Date"),
                            "snippet": str(detail.get("snippet", "")).strip(),
                            "body_preview": self._extract_gmail_body_preview(payload),
                        }
                    )

                return {
                    "status": "ok",
                    "tool": tool_name,
                    "query": query,
                    "count": len(messages),
                    "messages": messages,
                }
            except Exception as exc:
                return {"status": "error", "tool": tool_name, "message": str(exc)}

        if tool_name == "manage_gmail_message":
            if not gmail_service:
                return {
                    "status": "error",
                    "tool": tool_name,
                    "message": f"Gmail is not connected. {self.google_connection_diagnostics()}",
                }
            raw_action = str(arguments.get("action", "draft")).lower().strip()
            send_aliases = {"send", "send_email", "send-email", "email_send", "send message", "send mail"}
            draft_aliases = {"draft", "create_draft", "create-draft", "draft_email", "draft-email"}
            if raw_action in send_aliases:
                action = "send"
            elif raw_action in draft_aliases:
                action = "draft"
            else:
                action = "draft"
            recipients = self._normalize_email_recipients(arguments.get("to", []))
            subject = str(arguments.get("subject", "")).strip()
            body = str(arguments.get("body", "")).strip()

            if not recipients or not subject or not body:
                return {
                    "status": "error",
                    "tool": tool_name,
                    "action": action,
                    "message": "Missing required email fields: `to`, `subject`, and `body` are required.",
                }

            email_message = EmailMessage()
            email_message["To"] = ", ".join(recipients)
            email_message["Subject"] = subject
            email_message.set_content(body)
            encoded = base64.urlsafe_b64encode(email_message.as_bytes()).decode()
            try:
                sender_email = ""
                try:
                    profile = gmail_service.users().getProfile(userId="me").execute()
                    sender_email = str(profile.get("emailAddress", "")).strip()
                except Exception:
                    sender_email = ""

                if action == "send":
                    result = gmail_service.users().messages().send(userId="me", body={"raw": encoded}).execute()
                    message_id = str(result.get("id", "")).strip()
                    if not message_id:
                        return {
                            "status": "error",
                            "tool": tool_name,
                            "action": "send",
                            "message": "Gmail send API returned no message id.",
                        }
                    try:
                        verified = (
                            gmail_service.users()
                            .messages()
                            .get(userId="me", id=message_id, format="metadata")
                            .execute()
                        )
                    except Exception as verify_exc:
                        return {
                            "status": "error",
                            "tool": tool_name,
                            "action": "send",
                            "message": f"Send returned id `{message_id}` but verification failed: {verify_exc}",
                            "message_id": message_id,
                        }
                    return {
                        "status": "ok",
                        "tool": tool_name,
                        "action": "send",
                        "message_id": message_id,
                        "thread_id": verified.get("threadId"),
                        "to": recipients,
                        "subject": subject,
                        "from": sender_email,
                        "verified": True,
                    }
                draft = gmail_service.users().drafts().create(userId="me", body={"message": {"raw": encoded}}).execute()
                draft_id = str(draft.get("id", "")).strip()
                if not draft_id:
                    return {
                        "status": "error",
                        "tool": tool_name,
                        "action": "draft",
                        "message": "Gmail draft API returned no draft id.",
                    }
                try:
                    verified_draft = gmail_service.users().drafts().get(userId="me", id=draft_id).execute()
                except Exception as verify_exc:
                    return {
                        "status": "error",
                        "tool": tool_name,
                        "action": "draft",
                        "message": f"Draft returned id `{draft_id}` but verification failed: {verify_exc}",
                        "draft_id": draft_id,
                    }
                draft_message = verified_draft.get("message", {}) or {}
                return {
                    "status": "ok",
                    "tool": tool_name,
                    "action": "draft",
                    "draft_id": draft_id,
                    "message_id": draft_message.get("id"),
                    "thread_id": draft_message.get("threadId"),
                    "to": recipients,
                    "subject": subject,
                    "from": sender_email,
                    "verified": True,
                }
            except Exception as exc:
                return {"status": "error", "tool": tool_name, "action": action, "message": str(exc)}

        return {"status": "error", "tool": tool_name, "message": f"Unknown tool: {tool_name}"}

    def _is_google_tool_candidate_prompt(self, prompt: str) -> bool:
        normalized = prompt.lower()
        keywords = (
            "gmail",
            "email",
            "mail",
            "inbox",
            "unread",
            "summarize",
            "summary",
            "agenda",
            "event",
            "events",
            "calendar",
            "meeting",
            "schedule",
            "invite",
            "send message",
            "draft message",
            "send this",
            "email this",
            "compose email",
        )
        return any(keyword in normalized for keyword in keywords)

    def _direct_tool_execution_fallback(
        self,
        user_prompt: str,
        calendar_service: Any,
        gmail_service: Any,
    ) -> Dict[str, Any] | None:
        """When LLM tool-calling doesn't trigger, extract parameters via a
        simple LLM call and directly execute the Google API."""

        now = datetime.now().astimezone()
        current_date = now.strftime("%Y-%m-%d")
        tomorrow_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        current_day = now.strftime("%A")

        # --- Calendar create fallback ---
        if calendar_service and self._is_calendar_create_prompt(user_prompt):
            extraction_prompt = (
                f"Today is {current_date} ({current_day}). Tomorrow is {tomorrow_date}.\n"
                f"The user said: \"{user_prompt}\"\n\n"
                "Extract calendar event details as JSON with these keys:\n"
                "- summary (string, required)\n"
                "- start_time (string in ISO format like '2026-04-21' or '2026-04-21T15:00', required)\n"
                "- end_time (string, optional)\n"
                "- description (string, optional)\n"
                "- attendees (array of email strings, optional)\n\n"
                "Reply with ONLY the JSON object, no other text."
            )
            try:
                params = self._extract_json_from_llm(extraction_prompt)
                if params and params.get("summary") and params.get("start_time"):
                    return self.execute_google_tool(
                        "create_calendar_event",
                        params,
                        calendar_service=calendar_service,
                        gmail_service=gmail_service,
                    )
            except Exception:
                pass

        # --- Gmail action fallback ---
        if gmail_service and self._is_gmail_action_prompt(user_prompt):
            raw_action = "send" if any(
                w in user_prompt.lower() for w in ("send email", "send an email", "send mail", "send this")
            ) else "draft"
            extraction_prompt = (
                f"The user said: \"{user_prompt}\"\n\n"
                "Extract email details as JSON with these keys:\n"
                "- to (array of email address strings, required)\n"
                "- subject (string, required)\n"
                "- body (string, required)\n\n"
                "Reply with ONLY the JSON object, no other text."
            )
            try:
                params = self._extract_json_from_llm(extraction_prompt)
                if params and params.get("to") and params.get("subject") and params.get("body"):
                    params["action"] = raw_action
                    return self.execute_google_tool(
                        "manage_gmail_message",
                        params,
                        calendar_service=calendar_service,
                        gmail_service=gmail_service,
                    )
            except Exception:
                pass

        return None

    def _extract_json_from_llm(self, prompt: str) -> Dict[str, Any] | None:
        """Ask the LLM a simple question and parse the JSON response."""
        try:
            completion = self._create_llama_completion(
                messages=[
                    {"role": "system", "content": "You are a JSON extraction assistant. Reply with ONLY valid JSON, no markdown, no explanation."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=400,
                temperature=0.0,
            )
            text = self._extract_llama_text(completion).strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3].strip()
            if text.startswith("json"):
                text = text[4:].strip()
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _resolve_google_tools(
        self,
        messages: List[Dict[str, Any]],
        user_prompt: str,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        try:
            if not self.meta_client and not self.meta_native_client:
                return messages, []
            if not self._is_google_tool_candidate_prompt(user_prompt):
                return messages, []
            calendar_service, gmail_service = self._google_services()
            if not calendar_service and not gmail_service:
                return messages, []

            tools = self.google_tool_schemas()
            tool_messages = list(messages)
            guidance = self._google_tools_guidance(
                user_prompt=user_prompt,
                calendar_service=calendar_service,
                gmail_service=gmail_service,
            )
            if guidance:
                insert_at = len(tool_messages) - 1 if tool_messages and tool_messages[-1].get("role") == "user" else len(tool_messages)
                tool_messages = [
                    *tool_messages[:insert_at],
                    {"role": "system", "content": guidance},
                    *tool_messages[insert_at:],
                ]

            try:
                first_pass = self._create_google_tool_completion(
                    messages=tool_messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.1,
                    max_tokens=320,
                )
            except Exception:
                return tool_messages, [
                    {
                        "status": "error",
                        "tool": "google_tool_router",
                        "message": (
                            "Google tool-calling is temporarily unavailable from the model API. "
                            "Please retry."
                        ),
                    }
                ]

            tool_calls = self._extract_llama_tool_calls(first_pass)
            if not tool_calls:
                forced_choice = self._forced_google_tool_choice(
                    user_prompt=user_prompt,
                    calendar_service=calendar_service,
                    gmail_service=gmail_service,
                )
                if forced_choice is not None:
                    try:
                        first_pass = self._create_google_tool_completion(
                            messages=tool_messages,
                            tools=tools,
                            tool_choice=forced_choice,
                            temperature=0.0,
                            max_tokens=320,
                        )
                        tool_calls = self._extract_llama_tool_calls(first_pass)
                    except Exception:
                        return tool_messages, [
                            {
                                "status": "error",
                                "tool": "google_tool_router",
                                "message": (
                                    "Model API rejected the forced Gmail/Calendar tool call. "
                                    "Please retry with a shorter request."
                                ),
                            }
                        ]
            if not tool_calls:
                # Fallback: extract parameters via a dedicated LLM call
                # and directly execute the tool.
                fallback_result = self._direct_tool_execution_fallback(
                    user_prompt=user_prompt,
                    calendar_service=calendar_service,
                    gmail_service=gmail_service,
                )
                if fallback_result is not None:
                    return tool_messages, [fallback_result]
                return tool_messages, []

            assistant_entry: Dict[str, Any] = {
                "role": "assistant",
                "tool_calls": [],
            }
            assistant_content = self._extract_llama_message_content(first_pass)
            if assistant_content:
                assistant_entry["content"] = assistant_content

            include_openai_tool_type = not self._native_meta_active()
            tool_results: List[Dict[str, Any]] = []
            executed_calls: List[Tuple[str, str]] = []

            for index, call in enumerate(tool_calls):
                call_id, tool_name, raw_arguments = self._extract_tool_call_payload(call, index)
                if not tool_name:
                    continue
                try:
                    arguments = json.loads(raw_arguments)
                    if not isinstance(arguments, dict):
                        arguments = {}
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                assistant_tool_call: Dict[str, Any] = {
                    "id": call_id,
                    "function": {"name": tool_name, "arguments": raw_arguments},
                }
                if include_openai_tool_type:
                    assistant_tool_call["type"] = "function"
                assistant_entry["tool_calls"].append(assistant_tool_call)
                result = self.execute_google_tool(
                    tool_name,
                    arguments,
                    calendar_service=calendar_service,
                    gmail_service=gmail_service,
                )
                executed_calls.append((call_id, tool_name))
                tool_results.append(result)

            if not assistant_entry["tool_calls"]:
                return tool_messages, []

            updated = [*tool_messages, assistant_entry]
            for (call_id, tool_name), result in zip(executed_calls, tool_results):
                model_result = self._compact_google_tool_result_for_model(result)
                tool_entry: Dict[str, Any] = {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(model_result, ensure_ascii=False),
                }
                if include_openai_tool_type:
                    tool_entry["name"] = tool_name
                updated.append(tool_entry)
            return updated, tool_results
        except Exception:
            return messages, [
                {
                    "status": "error",
                    "tool": "google_tool_router",
                    "message": (
                        "Google tool-calling encountered an unexpected error and was skipped. "
                        "Please retry."
                    ),
                }
            ]

    def _google_tool_fallback_response(self, user_prompt: str, tool_results: List[Dict[str, Any]]) -> str:
        if not tool_results:
            return ""

        normalized_prompt = user_prompt.lower()
        wants_email_summary = any(
            marker in normalized_prompt
            for marker in ("summarize", "summary", "email", "emails", "inbox", "unread")
        )
        if not wants_email_summary:
            return ""

        gmail_results = [
            item
            for item in tool_results
            if isinstance(item, dict) and item.get("tool") == "read_gmail_messages"
        ]
        if not gmail_results:
            return ""

        latest = gmail_results[-1]
        if latest.get("status") != "ok":
            message = str(latest.get("message", "Unable to read Gmail right now.")).strip()
            return f"Gmail tool execution failed: {message}"

        entries = latest.get("messages", []) or []
        if not entries:
            query = str(latest.get("query", "in:inbox newer_than:14d")).strip() or "in:inbox newer_than:14d"
            return f"I checked Gmail using query `{query}` but found no matching messages."

        total_count = int(latest.get("count", len(entries)) or len(entries))
        query = str(latest.get("query", "in:inbox newer_than:14d")).strip() or "in:inbox newer_than:14d"
        lines = [f"I reviewed {total_count} recent emails (query: `{query}`)."]
        lines.append("Here are the key messages:")
        for email in entries[:6]:
            subject = str(email.get("subject", "")).strip() or "(No subject)"
            sender = str(email.get("from", "")).strip() or "Unknown sender"
            date = str(email.get("date", "")).strip() or "Unknown date"
            snippet = str(email.get("snippet", "") or email.get("body_preview", "")).strip()
            if len(snippet) > 180:
                snippet = snippet[:177].rstrip() + "..."
            detail = f"- {subject} | {sender} | {date}"
            if snippet:
                detail += f" | {snippet}"
            lines.append(detail)

        if total_count > len(entries[:6]):
            lines.append(f"Showing {len(entries[:6])} of {total_count} emails from this time window.")
        return "\n".join(lines)

    def _is_gmail_action_prompt(self, user_prompt: str) -> bool:
        normalized = str(user_prompt or "").lower()
        markers = (
            "send email",
            "send an email",
            "send mail",
            "mail this",
            "draft email",
            "draft an email",
            "create draft",
            "create a draft",
            "make a draft",
            "save draft",
            "draft this",
            "draft in gmail",
            "compose email",
            "write email",
            "reply email",
            "email this to",
            "mail this to",
        )
        if any(marker in normalized for marker in markers):
            return True
        has_gmail_context = any(token in normalized for token in ("gmail", "email", "mail"))
        has_write_verb = any(token in normalized for token in ("draft", "compose", "write", "send", "reply"))
        return has_gmail_context and has_write_verb

    def _is_calendar_create_prompt(self, user_prompt: str) -> bool:
        normalized = str(user_prompt or "").lower()
        markers = (
            "set an event",
            "create event",
            "create a calendar event",
            "add event",
            "schedule meeting",
            "schedule a meeting",
            "schedule an event",
            "set schedule",
            "set a schedule",
            "book meeting",
            "put on calendar",
            "calendar event",
            "add to calendar",
            "create meeting",
            "add meeting",
            "set up meeting",
            "invite",
        )
        if any(marker in normalized for marker in markers):
            return True
        return "schedule" in normalized and any(
            token in normalized for token in ("meeting", "event", "appointment", "call", "invite", "reminder")
        )

    def _gmail_action_tool_response(self, user_prompt: str, tool_results: List[Dict[str, Any]]) -> str:
        if not self._is_gmail_action_prompt(user_prompt):
            return ""
        if not tool_results:
            return (
                "I could not execute Gmail send/draft yet. Please provide `to`, `subject`, and `body` "
                "and retry."
            )

        manage_results = [
            item
            for item in tool_results
            if isinstance(item, dict) and item.get("tool") == "manage_gmail_message"
        ]
        if not manage_results:
            return (
                "I did not execute the Gmail send/draft tool for this request. "
                "Please include `to`, `subject`, and `body` and try again."
            )

        latest = manage_results[-1]
        if latest.get("status") != "ok":
            message = str(latest.get("message", "Unknown Gmail action error.")).strip()
            return f"Gmail action failed: {message}"

        action = str(latest.get("action", "")).strip().lower()
        recipients = latest.get("to", []) or []
        if isinstance(recipients, str):
            recipients = [recipients]
        recipient_text = ", ".join(str(item).strip() for item in recipients if str(item).strip()) or "unknown recipient"
        subject = str(latest.get("subject", "")).strip() or "(No subject)"
        sender = str(latest.get("from", "")).strip() or "your Gmail account"

        if action == "send":
            message_id = str(latest.get("message_id", "")).strip() or "unknown"
            return (
                f"Email sent successfully via {sender} to {recipient_text}. "
                f"Subject: {subject}. Message ID: {message_id}."
            )
        if action == "draft":
            draft_id = str(latest.get("draft_id", "")).strip() or "unknown"
            return (
                f"Draft created successfully in {sender}. "
                f"To: {recipient_text}. Subject: {subject}. Draft ID: {draft_id}."
            )
        return "Gmail action completed successfully."

    def _is_calendar_action_prompt(self, user_prompt: str) -> bool:
        normalized = str(user_prompt or "").lower()
        markers = (
            "set an event",
            "create event",
            "add event",
            "schedule meeting",
            "book meeting",
            "put on calendar",
            "calendar event",
            "add to calendar",
            "agenda",
            "upcoming meetings",
            "list events",
        )
        if self._is_calendar_create_prompt(user_prompt):
            return True
        return any(marker in normalized for marker in markers)

    def _calendar_action_tool_response(self, user_prompt: str, tool_results: List[Dict[str, Any]]) -> str:
        if not self._is_calendar_action_prompt(user_prompt):
            return ""
        create_intent = self._is_calendar_create_prompt(user_prompt)
        if not tool_results:
            if create_intent:
                return (
                    "I could not create the calendar event yet. Please provide at least `summary` and "
                    "`start_time` (optional: `end_time`, `description`, `attendees`) and retry."
                )
            return "I could not execute the Calendar tool for this request."

        calendar_results = [
            item
            for item in tool_results
            if isinstance(item, dict) and item.get("tool") in {"create_calendar_event", "list_calendar_events"}
        ]
        if not calendar_results:
            if create_intent:
                return "I did not execute a Calendar create-event tool call for this request."
            return "No Calendar action was executed for this request."

        if create_intent:
            create_results = [
                item
                for item in calendar_results
                if isinstance(item, dict) and item.get("tool") == "create_calendar_event"
            ]
            if not create_results:
                return "I did not create a Calendar event for this request."
            latest = create_results[-1]
        else:
            latest = calendar_results[-1]

        if latest.get("status") != "ok":
            return f"Calendar action failed: {str(latest.get('message', 'Unknown error')).strip()}"

        tool_name = str(latest.get("tool", "")).strip()
        if tool_name == "create_calendar_event":
            event_id = str(latest.get("event_id", "")).strip() or "unknown"
            summary = str(latest.get("summary", "Untitled event")).strip()
            start = str(latest.get("start", "")).strip() or "unspecified start"
            end = str(latest.get("end", "")).strip() or "unspecified end"
            link = str(latest.get("html_link", "")).strip()
            base = (
                f"Calendar event created successfully. Summary: {summary}. "
                f"Start: {start}. End: {end}. Event ID: {event_id}."
            )
            if link:
                base += f" Link: {link}"
            return base

        if tool_name == "list_calendar_events":
            count = int(latest.get("count", 0) or 0)
            events = latest.get("events", []) or []
            if count <= 0 or not events:
                return "No upcoming calendar events found in the requested window."
            lines = [f"I found {count} upcoming calendar events:"]
            for event in events[:8]:
                if not isinstance(event, dict):
                    continue
                summary = str(event.get("summary", "Untitled event")).strip() or "Untitled event"
                start = str(event.get("start", "")).strip() or "unspecified start"
                lines.append(f"- {summary} ({start})")
            if count > len(events[:8]):
                lines.append(f"Showing {len(events[:8])} of {count}.")
            return "\n".join(lines)

        return ""

    def _response_max_tokens_for_prompt(self, user_prompt: str) -> int:
        base = max(256, int(LLAMA_MAX_TOKENS))
        longform_cap = max(base, int(LLAMA_LONGFORM_MAX_TOKENS))
        prompt = str(user_prompt or "")
        lowered = prompt.lower()

        # Heuristic for explicit long-form targets (e.g., "write 1000 words").
        requested_words = 0
        for match in re.finditer(r"\b(\d{2,5})\s+words?\b", lowered):
            try:
                requested_words = max(requested_words, int(match.group(1)))
            except Exception:
                continue

        wants_long_form = any(
            marker in lowered
            for marker in ("essay", "long essay", "detailed article", "1000 words", "long-form")
        )

        if requested_words > 0:
            # Rough conversion with safety margin.
            estimated = int(requested_words * 1.9) + 220
            return max(base, min(longform_cap, estimated))

        if wants_long_form:
            return max(base, min(longform_cap, 4096))

        return base

    def _requested_word_target(self, user_prompt: str) -> int:
        prompt = str(user_prompt or "").lower()
        requested_words = 0
        for match in re.finditer(r"\b(\d{2,5})\s+words?\b", prompt):
            try:
                requested_words = max(requested_words, int(match.group(1)))
            except Exception:
                continue
        if requested_words < 100:
            return 0
        return requested_words

    def _count_words(self, text: str) -> int:
        return len(re.findall(r"\b[^\W_]+\b", str(text or ""), flags=re.UNICODE))

    def _token_budget_candidates(self, requested_max_tokens: int) -> List[int]:
        requested = max(256, int(requested_max_tokens))
        floor = min(1024, requested)
        longform_cap = max(256, int(LLAMA_LONGFORM_MAX_TOKENS))

        candidates = [
            min(requested, longform_cap),
            min(8192, longform_cap),
            min(6144, longform_cap),
            min(4096, longform_cap),
            min(3072, longform_cap),
            min(2048, longform_cap),
            min(1536, longform_cap),
            floor,
            768,
            512,
            384,
            256,
        ]
        normalized: List[int] = []
        for value in candidates:
            token_budget = max(256, int(value))
            if token_budget not in normalized:
                normalized.append(token_budget)
        return normalized

    def _compact_google_tool_result_for_model(self, result: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {"status": "error", "message": "Invalid tool result payload."}

        compact: Dict[str, Any] = {
            "status": result.get("status"),
            "tool": result.get("tool"),
        }
        if "message" in result:
            compact["message"] = str(result.get("message", ""))[:400]
        if "query" in result:
            compact["query"] = str(result.get("query", ""))[:160]
        if "count" in result:
            compact["count"] = result.get("count")

        tool_name = str(result.get("tool", ""))
        if tool_name == "read_gmail_messages":
            compact_messages: List[Dict[str, str]] = []
            for email in (result.get("messages", []) or [])[:6]:
                if not isinstance(email, dict):
                    continue
                compact_messages.append(
                    {
                        "subject": str(email.get("subject", "")).strip()[:140],
                        "from": str(email.get("from", "")).strip()[:140],
                        "date": str(email.get("date", "")).strip()[:80],
                        "snippet": str(email.get("snippet", "")).strip()[:220],
                    }
                )
            compact["messages"] = compact_messages
        elif tool_name == "manage_gmail_message":
            compact["action"] = result.get("action")
            compact["verified"] = bool(result.get("verified"))
            if "message_id" in result:
                compact["message_id"] = str(result.get("message_id", ""))[:120]
            if "draft_id" in result:
                compact["draft_id"] = str(result.get("draft_id", ""))[:120]
            if "to" in result:
                recipients = result.get("to", []) or []
                if isinstance(recipients, str):
                    recipients = [recipients]
                compact["to"] = [str(item).strip()[:120] for item in recipients[:8] if str(item).strip()]
            if "subject" in result:
                compact["subject"] = str(result.get("subject", "")).strip()[:180]
            if "from" in result:
                compact["from"] = str(result.get("from", "")).strip()[:120]
        elif tool_name == "list_calendar_events":
            compact_events: List[Dict[str, str]] = []
            for event in (result.get("events", []) or [])[:8]:
                if not isinstance(event, dict):
                    continue
                compact_events.append(
                    {
                        "summary": str(event.get("summary", "")).strip()[:160],
                        "start": str(event.get("start", "")).strip()[:80],
                        "end": str(event.get("end", "")).strip()[:80],
                    }
                )
            compact["events"] = compact_events
        elif tool_name == "create_calendar_event":
            compact["verified"] = bool(result.get("verified"))
            if "event_id" in result:
                compact["event_id"] = str(result.get("event_id", ""))[:120]
            if "summary" in result:
                compact["summary"] = str(result.get("summary", "")).strip()[:180]
            if "start" in result:
                compact["start"] = str(result.get("start", "")).strip()[:120]
            if "end" in result:
                compact["end"] = str(result.get("end", "")).strip()[:120]
            if "html_link" in result:
                compact["html_link"] = str(result.get("html_link", "")).strip()[:240]

        return compact

    def stream_response(
        self,
        user_prompt: str,
        user_id: str,
        chat_id: str,
        chat_history: List[Dict[str, Any]],
        attachment_notes: List[str] | None = None,
    ) -> Generator[str, None, None]:
        if not self.meta_client and not self.meta_native_client:
            yield (
                "Llama API is not configured. Add `LLAMA_API_KEY` and `LLAMA_MODEL` to `.env` to enable PIA."
            )
            return

        rag_context = self.retrieve_rag_context(user_id=user_id, chat_id=chat_id, query=user_prompt)
        inventory_context = self._document_inventory_context(user_id=user_id, chat_id=chat_id)
        web_context = ""
        if self._is_current_events_prompt(user_prompt):
            web_results = self.search_tavily(user_prompt)
            web_context = self._format_web_context(web_results)

        messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT.strip()}]
        messages.append({"role": "system", "content": f"RAG_CONTEXT:\n{rag_context}"})
        messages.append({"role": "system", "content": inventory_context})

        if web_context:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "CURRENT_WEB_CONTEXT (fresh data from Tavily; use citations inline with URLs):\n"
                        f"{web_context}"
                    ),
                }
            )
        if attachment_notes:
            notes = "\n".join(f"- {note}" for note in attachment_notes if note.strip())
            if notes.strip():
                messages.append({"role": "system", "content": f"ATTACHMENT_CONTEXT:\n{notes}"})

        for item in chat_history[-SHORT_TERM_HISTORY_TURNS:]:
            role = str(item.get("role", "user"))
            if role not in {"user", "assistant"}:
                continue
            content = str(item.get("content", "")).strip()
            if content:
                messages.append({"role": role, "content": content})
            # Persist attachment analysis (images, docs, etc.) from previous
            # turns so PIA remembers what was uploaded earlier.
            item_meta = item.get("metadata") or {}
            if isinstance(item_meta, dict):
                prev_notes = item_meta.get("attachment_notes") or []
                if prev_notes and isinstance(prev_notes, list):
                    notes_text = "\n".join(
                        f"- {n}" for n in prev_notes if str(n).strip()
                    )
                    if notes_text.strip():
                        messages.append(
                            {
                                "role": "system",
                                "content": f"PREVIOUS_ATTACHMENT_ANALYSIS:\n{notes_text}",
                            }
                        )

        target_words = self._requested_word_target(user_prompt)
        if target_words:
            lower_bound = max(160, int(target_words * 0.9))
            upper_bound = int(target_words * 1.08)
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "The user has explicitly requested a target word count. "
                        f"Write a complete response between {lower_bound} and {upper_bound} words. "
                        "Do not stop early, and do not omit major sections."
                    ),
                }
            )

        messages.append({"role": "user", "content": user_prompt})
        messages, tool_results = self._resolve_google_tools(messages, user_prompt=user_prompt)
        gmail_action_result = self._gmail_action_tool_response(user_prompt=user_prompt, tool_results=tool_results)
        if gmail_action_result:
            yield gmail_action_result
            return
        calendar_action_result = self._calendar_action_tool_response(user_prompt=user_prompt, tool_results=tool_results)
        if calendar_action_result:
            yield calendar_action_result
            return

        # Anti-hallucination guard: if a Google action was clearly intended but
        # no tool was successfully executed, prevent the LLM from claiming it
        # performed the action.
        _successful_tool_results = [
            r for r in tool_results
            if isinstance(r, dict) and r.get("status") == "ok"
        ]
        _tool_errors = [
            r for r in tool_results
            if isinstance(r, dict) and r.get("status") == "error"
        ]
        _is_google_action = (
            self._is_gmail_action_prompt(user_prompt)
            or self._is_calendar_action_prompt(user_prompt)
        )
        if _is_google_action and not _successful_tool_results:
            if _tool_errors:
                error_details = "; ".join(
                    str(e.get("message", "unknown error")) for e in _tool_errors
                )
                yield (
                    "I was unable to complete this action. "
                    f"Error: {error_details}\n\n"
                    "Please check your Google Workspace connectivity in the sidebar."
                )
                return
            # No tool results at all — inject a system message so the LLM
            # does not hallucinate success.
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "CRITICAL: The Gmail/Calendar tool was NOT executed for this "
                        "request. You MUST NOT claim that you sent, drafted, or "
                        "composed any email, nor that you created or scheduled any "
                        "calendar event. Instead, explain that the action could not "
                        "be completed and ask the user to verify Google Workspace "
                        "connectivity via the sidebar."
                    ),
                }
            )

        try:
            requested_budget = self._response_max_tokens_for_prompt(user_prompt)
            token_budgets = self._token_budget_candidates(requested_budget)
            stream_exception: Exception | None = None

            for budget in token_budgets:
                emitted = False
                collected_chunks: List[str] = []
                try:
                    for token in self._stream_llama_completion(
                        messages=messages,
                        temperature=LLAMA_TEMPERATURE,
                        max_tokens=budget,
                    ):
                        emitted = True
                        collected_chunks.append(token)
                        yield token
                    if emitted:
                        # If explicit long-form target is under-shot, ask the model to continue.
                        if target_words:
                            produced_words = self._count_words("".join(collected_chunks))
                            min_required = max(150, int(target_words * 0.86))
                            if produced_words < min_required:
                                remaining_words = max(120, target_words - produced_words)
                                continuation_budget = min(
                                    int(LLAMA_LONGFORM_MAX_TOKENS),
                                    max(768, int(remaining_words * 2.3) + 180),
                                )
                                continuation_budgets = self._token_budget_candidates(continuation_budget)
                                continuation_messages = [
                                    *messages,
                                    {"role": "assistant", "content": "".join(collected_chunks)},
                                    {
                                        "role": "user",
                                        "content": (
                                            "Continue from exactly where you stopped. "
                                            f"Add approximately {remaining_words} more words so the total is close to "
                                            f"{target_words} words. Do not repeat previous content."
                                        ),
                                    },
                                ]
                                for cont_budget in continuation_budgets:
                                    continuation_emitted = False
                                    try:
                                        yield "\n\n"
                                        for token in self._stream_llama_completion(
                                            messages=continuation_messages,
                                            temperature=LLAMA_TEMPERATURE,
                                            max_tokens=cont_budget,
                                        ):
                                            continuation_emitted = True
                                            yield token
                                        if continuation_emitted:
                                            return
                                    except Exception as cont_exc:
                                        if self._looks_like_token_limit_error(cont_exc) and cont_budget != continuation_budgets[-1]:
                                            continue
                                        break
                        return
                    if budget == token_budgets[-1]:
                        yield "PIA received an empty response from the Llama API."
                        return
                except Exception as exc:
                    stream_exception = exc
                    if self._looks_like_token_limit_error(exc) and not emitted and budget != token_budgets[-1]:
                        continue
                    raise

            if stream_exception is not None:
                raise stream_exception
            yield "PIA received an empty response from the Llama API."
        except Exception as exc:
            lowered = str(exc).lower()
            if "500" in lowered or "internal server error" in lowered:
                fallback = self._google_tool_fallback_response(user_prompt=user_prompt, tool_results=tool_results)
                if fallback:
                    yield fallback
                    return
                yield (
                    "PIA encountered a temporary model API error while processing the request. "
                    "Please retry in a moment."
                )
            else:
                yield f"PIA encountered a Llama API error: {exc}"

    def run_connectivity_validation(self) -> Dict[str, str]:
        report: Dict[str, str] = {}

        if self.meta_client or self.meta_native_client:
            try:
                self._create_llama_completion(
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=12,
                    temperature=0.0,
                )
                active_model = self._active_llama_model()
                report["Llama"] = f"OK ({active_model})"
                if self.meta_native_client:
                    report["Llama Engine"] = "OK (native Meta SDK)"
                elif self.meta_client:
                    report["Llama Engine"] = "OK (OpenAI-compatible Meta endpoint)"
                else:
                    report["Llama Engine"] = "FAIL: Meta engine unavailable"

                model_ids = self._list_llama_models()
                if model_ids:
                    is_known_model = any(item.lower() == active_model.lower() for item in model_ids)
                    is_70b_model = "70b" in active_model.lower()
                    if is_known_model and is_70b_model:
                        report["Llama Model"] = f"OK (verified 70B: {active_model})"
                    elif is_known_model:
                        report["Llama Model"] = f"OK (verified: {active_model})"
                    elif is_70b_model:
                        report["Llama Model"] = f"OK (active 70B: {active_model})"
                    else:
                        report["Llama Model"] = f"OK (active model: {active_model})"
                else:
                    if "70b" in active_model.lower():
                        report["Llama Model"] = f"OK (active 70B: {active_model})"
                    else:
                        report["Llama Model"] = f"OK (active model: {active_model})"
            except Exception as exc:
                report["Llama"] = f"FAIL: {exc}"
                if "Llama Engine" not in report:
                    report["Llama Engine"] = "FAIL: Meta endpoint request failed"
                report["Llama Model"] = "FAIL: could not verify model"
        else:
            report["Llama"] = "FAIL: missing LLAMA_API_KEY"
            report["Llama Engine"] = "FAIL: missing META_API_KEY / LLAMA_API_KEY"
            report["Llama Model"] = "FAIL: missing model credentials"

        if self.groq_client:
            try:
                self.groq_client.models.list()
                report["Groq"] = "OK"
            except Exception as exc:
                report["Groq"] = f"FAIL: {exc}"
        else:
            report["Groq"] = "FAIL: missing GROQ_API_KEY"

        supa = self.store.healthcheck()
        report["Supabase"] = "OK" if supa.ok else f"FAIL: {supa.message}"

        if TAVILY_API_KEY:
            try:
                results = self.search_tavily("latest AI infrastructure news", max_results=1)
                report["Tavily"] = "OK" if results else "FAIL: empty results"
            except Exception as exc:
                report["Tavily"] = f"FAIL: {exc}"
        else:
            report["Tavily"] = "FAIL: missing TAVILY_API_KEY"

        calendar_service, gmail_service = self._google_services()
        diagnostics = self.google_connection_diagnostics()
        if gmail_service and self._has_gmail_read_scope():
            report["Google Workspace"] = "OK"
        elif gmail_service and not self._has_gmail_read_scope():
            report["Google Workspace"] = f"PARTIAL: {diagnostics}"
        elif calendar_service or gmail_service:
            report["Google Workspace"] = f"PARTIAL: {diagnostics}"
        else:
            report["Google Workspace"] = f"FAIL: {diagnostics}"
        return report
