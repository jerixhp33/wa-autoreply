"""
Neonize WhatsApp Service

Manages WhatsApp sessions using Neonize 0.4.x.
Each account gets its own NewClient with persistent session storage.

Key API notes (v0.4.x):
  - NewClient(name, jid=None) — name is used as the session identifier/path
  - client.qr(callback) — sets QR callback(client, qr_bytes)
  - client.event(EventClass)(callback) — registers event handlers
  - client.connect() — SYNCHRONOUS blocking call, runs on a thread
  - client.send_message(jid, Message | str) — send text
"""
import asyncio
import logging
import os
import io
import base64
import threading
from typing import Dict, Optional, Callable, Any

logger = logging.getLogger(__name__)


class WhatsAppSession:
    """Represents a single WhatsApp account session."""

    def __init__(
        self,
        account_id: str,
        session_name: str,
        on_qr: Callable,
        on_connected: Callable,
        on_disconnected: Callable,
        on_message: Callable,
        loop: asyncio.AbstractEventLoop,
    ):
        self.account_id = account_id
        self.session_name = session_name
        self.on_qr = on_qr
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected
        self.on_message = on_message
        self.loop = loop
        self.client = None
        self.connected = False
        self.phone_number: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._stopped = False

    def _run_sync(self):
        """Called in a background thread to run the Neonize session."""
        try:
            from neonize.client import NewClient
            from neonize.proto.Neonize_pb2 import (
                Message as MessageEv,
                Connected as ConnectedEv,
                Disconnected as DisconnectedEv,
                LoggedOut as LoggedOutEv,
            )

            logger.info(f"Starting Neonize session: {self.session_name}")
            client = NewClient(self.session_name)
            self.client = client

            # ── QR callback ───────────────────────────────────────────────
            def _safe_schedule(coro):
                """Schedule a coroutine on the event loop from a thread."""
                try:
                    if not self.loop.is_closed():
                        asyncio.run_coroutine_threadsafe(coro, self.loop)
                    else:
                        logger.debug("Event loop closed, skipping callback")
                except Exception as e:
                    logger.debug(f"Could not schedule callback: {e}")

            @client.qr
            def on_qr_bytes(c, qr_bytes: bytes):
                """Called when QR code data is available."""
                try:
                    import qrcode
                    qr_str = qr_bytes.decode("utf-8") if isinstance(qr_bytes, bytes) else qr_bytes
                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=10,
                        border=4,
                    )
                    qr.add_data(qr_str)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    buf.seek(0)
                    qr_data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
                except Exception as e:
                    logger.warning(f"QR image generation failed: {e}, using raw bytes")
                    qr_data_uri = qr_bytes.decode("utf-8") if isinstance(qr_bytes, bytes) else str(qr_bytes)

                _safe_schedule(self.on_qr(self.account_id, qr_data_uri))

            # ── Connected event ───────────────────────────────────────────
            @client.event(ConnectedEv)
            def on_connected_ev(c, event: ConnectedEv):
                self.connected = True
                phone = None
                try:
                    if c.me:
                        phone = str(c.me.ID.User) if hasattr(c.me, 'ID') else None
                except Exception:
                    pass
                self.phone_number = phone
                _safe_schedule(self.on_connected(self.account_id, phone))

            # ── Disconnected event ────────────────────────────────────────
            @client.event(DisconnectedEv)
            def on_disconnected_ev(c, event: DisconnectedEv):
                self.connected = False
                _safe_schedule(self.on_disconnected(self.account_id))

            # ── LoggedOut event ───────────────────────────────────────────
            @client.event(LoggedOutEv)
            def on_logged_out(c, event: LoggedOutEv):
                self.connected = False
                logger.warning(f"Account {self.account_id} was logged out")
                _safe_schedule(self.on_disconnected(self.account_id))

            # ── Message event ─────────────────────────────────────────────
            @client.event(MessageEv)
            def on_message_ev(c, event: MessageEv):
                try:
                    info = event.Info

                    # Skip outgoing messages
                    if info.MessageSource.IsFromMe:
                        return

                    is_group = info.MessageSource.IsGroup
                    message_id = info.ID

                    # Extract message content (text, image, or audio)
                    content = None
                    media_path = None
                    media_type = "text"
                    mime_type = None
                    caption = None
                    msg = event.Message

                    # Unwrap any container wrappers (ephemeral, viewOnce, etc.)
                    for _ in range(5):
                        try:
                            if hasattr(msg, "ephemeralMessage") and msg.HasField("ephemeralMessage") and msg.ephemeralMessage.message:
                                msg = msg.ephemeralMessage.message
                            elif hasattr(msg, "viewOnceMessage") and msg.HasField("viewOnceMessage") and msg.viewOnceMessage.message:
                                msg = msg.viewOnceMessage.message
                            elif hasattr(msg, "viewOnceMessageV2") and msg.HasField("viewOnceMessageV2") and msg.viewOnceMessageV2.message:
                                msg = msg.viewOnceMessageV2.message
                            elif hasattr(msg, "documentWithCaptionMessage") and msg.HasField("documentWithCaptionMessage") and msg.documentWithCaptionMessage.message:
                                msg = msg.documentWithCaptionMessage.message
                            else:
                                break
                        except Exception:
                            break

                    # Check protobuf HasField for accurate media type detection
                    has_image = False
                    has_audio = False
                    try:
                        has_image = msg.HasField("imageMessage")
                    except Exception:
                        has_image = bool(getattr(msg, "imageMessage", None) and (getattr(msg.imageMessage, "url", None) or getattr(msg.imageMessage, "directPath", None)))

                    try:
                        has_audio = msg.HasField("audioMessage")
                    except Exception:
                        has_audio = bool(getattr(msg, "audioMessage", None) and (getattr(msg.audioMessage, "url", None) or getattr(msg.audioMessage, "directPath", None)))

                    if msg.conversation:
                        content = msg.conversation
                    elif msg.extendedTextMessage and msg.extendedTextMessage.text:
                        content = msg.extendedTextMessage.text
                    elif has_image:
                        media_type = "image"
                        mime_type = msg.imageMessage.mimetype or "image/jpeg"
                        caption = msg.imageMessage.caption or None
                        content = caption or "[Image]"
                        # Download image
                        try:
                            media_bytes = None
                            try:
                                media_bytes = c.download_any(msg)
                            except Exception:
                                pass
                            if not media_bytes and hasattr(msg, "imageMessage"):
                                try:
                                    media_bytes = c.download_any(msg.imageMessage)
                                except Exception:
                                    pass

                            if media_bytes:
                                import os
                                from app.config import settings
                                ext = mime_type.split('/')[-1].split(';')[0]
                                media_dir = os.path.join(settings.media_dir, self.account_id)
                                os.makedirs(media_dir, exist_ok=True)
                                filename = f"{message_id or 'img'}.{ext}"
                                media_path = os.path.join(media_dir, filename)
                                with open(media_path, 'wb') as f:
                                    f.write(media_bytes)
                                logger.info(f"Downloaded image: {media_path} ({len(media_bytes)} bytes)")
                        except Exception as e:
                            logger.error(f"Failed to download image: {e}")
                    elif has_audio:
                        media_type = "audio"
                        mime_type = msg.audioMessage.mimetype or "audio/ogg; codecs=opus"
                        content = "[Voice Note]"
                        # Download audio
                        try:
                            media_bytes = None
                            try:
                                media_bytes = c.download_any(msg)
                            except Exception:
                                pass
                            if not media_bytes and hasattr(msg, "audioMessage"):
                                try:
                                    media_bytes = c.download_any(msg.audioMessage)
                                except Exception:
                                    pass

                            if media_bytes:
                                import os
                                from app.config import settings
                                ext = "ogg"
                                media_dir = os.path.join(settings.media_dir, self.account_id)
                                os.makedirs(media_dir, exist_ok=True)
                                filename = f"{message_id or 'audio'}.{ext}"
                                media_path = os.path.join(media_dir, filename)
                                with open(media_path, 'wb') as f:
                                    f.write(media_bytes)
                                logger.info(f"Downloaded audio: {media_path} ({len(media_bytes)} bytes)")
                        except Exception as e:
                            logger.error(f"Failed to download audio: {e}")
                    else:
                        return  # Skip unsupported message types

                    if not content and not media_path:
                        return  # Nothing to process

                    sender_jid = info.MessageSource.Sender
                    chat_jid = info.MessageSource.Chat

                    logger.info(
                        f"Message received - "
                        f"Sender: {sender_jid.User}@{sender_jid.Server}, "
                        f"Chat: {chat_jid.User}@{chat_jid.Server}, "
                        f"IsGroup: {is_group}"
                    )

                    # Resolve LID to real phone number
                    # WhatsApp LIDs use "lid" as the Server field
                    phone_number = None
                    raw_jid = chat_jid if not is_group else sender_jid

                    if raw_jid.Server == "lid":
                        # This is a LID — try to resolve to real phone number
                        try:
                            resolved = c.get_pn_from_lid(raw_jid)
                            if resolved and resolved.User:
                                phone_number = str(resolved.User)
                                logger.info(
                                    f"Resolved LID {raw_jid.User} -> phone {phone_number}"
                                )
                        except Exception as e:
                            logger.warning(
                                f"Could not resolve LID {raw_jid.User}: {e}"
                            )

                    # Fallback: use the raw User field
                    if not phone_number:
                        phone_number = str(raw_jid.User)
                        logger.info(f"Using raw JID user as phone: {phone_number}")

                    _safe_schedule(self.on_message(
                        account_id=self.account_id,
                        sender=phone_number,
                        content=content,
                        is_group=is_group,
                        message_id=message_id,
                        media_path=media_path,
                        media_type=media_type,
                        mime_type=mime_type,
                        caption=caption,
                    ))
                except Exception as e:
                    logger.error(f"Error processing message event: {e}", exc_info=True)

            # ── Connect (blocking) ────────────────────────────────────────
            logger.info(f"Calling client.connect() for {self.account_id}")
            client.connect()

        except Exception as e:
            if not self._stopped:
                logger.error(f"Session error for {self.account_id}: {e}", exc_info=True)
            self.connected = False
            try:
                if not self.loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        self.on_disconnected(self.account_id),
                        self.loop
                    )
            except Exception as cb_err:
                logger.debug(f"Disconnect callback error (loop may be closed): {cb_err}")

    def start(self):
        """Start the session in a background daemon thread."""
        self._stopped = False
        self._thread = threading.Thread(
            target=self._run_sync,
            name=f"wa-session-{self.account_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"Session thread started for {self.account_id}")

    def send_message(self, phone: str, text: str) -> bool:
        """Send a text message synchronously (callable from any thread)."""
        if not self.client or not self.connected:
            raise RuntimeError(f"WhatsApp not connected for account {self.account_id}")

        try:
            from neonize.client import JID, build_jid

            # Build JID from phone number
            jid = build_jid(phone, "s.whatsapp.net")

            # Try to resolve phone number to LID for sending
            # WhatsApp may require LID JIDs for delivery
            try:
                lid_jid = self.client.get_lid_from_pn(jid)
                if lid_jid and lid_jid.User:
                    logger.info(f"Resolved phone {phone} -> LID {lid_jid.User} for sending")
                    jid = lid_jid
            except Exception:
                pass  # Use phone JID if LID resolution fails

            self.client.send_message(jid, text)
            logger.info(f"Message sent to {phone}")
            return True
        except Exception as e:
            logger.error(f"Failed to send message to {phone}: {e}")
            raise

    def send_audio(self, phone: str, audio_path: str, is_ptt: bool = True) -> bool:
        """Send an audio/voice note message synchronously."""
        if not self.client or not self.connected:
            raise RuntimeError(f"WhatsApp not connected for account {self.account_id}")

        try:
            from neonize.client import build_jid

            jid = build_jid(phone, "s.whatsapp.net")
            try:
                lid_jid = self.client.get_lid_from_pn(jid)
                if lid_jid and lid_jid.User:
                    jid = lid_jid
            except Exception:
                pass

            if hasattr(self.client, "send_audio"):
                try:
                    self.client.send_audio(jid, audio_path, ptt=is_ptt)
                    logger.info(f"Voice note sent to {phone} via send_audio")
                    return True
                except Exception as sa_err:
                    logger.warning(f"send_audio failed: {sa_err}, attempting direct upload fallback")

            # Fallback direct upload if send_audio failed or doesn't exist
            with open(audio_path, "rb") as f:
                audio_bytes = f.read()
            upload_res = self.client.upload(audio_bytes)
            import magic
            from neonize.proto.Neonize_pb2 import Message, AudioMessage
            mime = "audio/ogg; codecs=opus" if is_ptt else (magic.from_buffer(audio_bytes, mime=True) or "audio/ogg")
            audio_msg = AudioMessage(
                URL=getattr(upload_res, "url", getattr(upload_res, "URL", "")),
                seconds=5,
                directPath=getattr(upload_res, "DirectPath", getattr(upload_res, "directPath", "")),
                fileEncSHA256=getattr(upload_res, "FileEncSHA256", getattr(upload_res, "fileEncSHA256", b"")),
                fileLength=len(audio_bytes),
                fileSHA256=getattr(upload_res, "FileSHA256", getattr(upload_res, "fileSHA256", b"")),
                mediaKey=getattr(upload_res, "MediaKey", getattr(upload_res, "mediaKey", b"")),
                mimetype=mime,
                PTT=is_ptt,
            )
            self.client.send_message(jid, Message(audioMessage=audio_msg))
            logger.info(f"Voice note sent to {phone} via manual upload fallback")
            return True
        except Exception as e:
            logger.error(f"Failed to send voice note to {phone}: {e}")
            raise

    def stop(self):
        """Stop the session."""
        self._stopped = True
        self.connected = False
        if self.client:
            try:
                from neonize.client import stop_event
                stop_event.set()
            except Exception as e:
                logger.warning(f"Could not set stop_event: {e}")
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)


class NeonizeManager:
    """Manages multiple WhatsApp sessions."""

    def __init__(self):
        self.sessions: Dict[str, WhatsAppSession] = {}
        self._callbacks: Dict[str, Dict[str, Callable]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
        return self._loop

    def register_callbacks(
        self,
        account_id: str,
        on_qr: Callable,
        on_connected: Callable,
        on_disconnected: Callable,
        on_message: Callable,
    ):
        """Register event callbacks for an account."""
        self._callbacks[account_id] = {
            "on_qr": on_qr,
            "on_connected": on_connected,
            "on_disconnected": on_disconnected,
            "on_message": on_message,
        }

    async def start_session(self, account_id: str, session_name: str) -> WhatsAppSession:
        """Start a WhatsApp session for an account."""
        # Stop existing session if any
        if account_id in self.sessions:
            existing = self.sessions[account_id]
            if existing.connected:
                return existing
            existing.stop()
            del self.sessions[account_id]

        callbacks = self._callbacks.get(account_id, {})
        loop = asyncio.get_running_loop()

        session = WhatsAppSession(
            account_id=account_id,
            session_name=session_name,
            on_qr=callbacks.get("on_qr", self._noop),
            on_connected=callbacks.get("on_connected", self._noop),
            on_disconnected=callbacks.get("on_disconnected", self._noop),
            on_message=callbacks.get("on_message", self._noop),
            loop=loop,
        )

        self.sessions[account_id] = session
        session.start()
        return session

    async def stop_session(self, account_id: str):
        """Stop a WhatsApp session."""
        if account_id in self.sessions:
            session = self.sessions.pop(account_id)
            await asyncio.get_event_loop().run_in_executor(None, session.stop)

    async def send_message(self, account_id: str, phone: str, text: str) -> bool:
        """Send a message from a specific account (async wrapper)."""
        session = self.sessions.get(account_id)
        if not session:
            raise RuntimeError(f"No active session for account {account_id}")
        # Run blocking send in executor
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, session.send_message, phone, text)

    async def send_audio(self, account_id: str, phone: str, audio_path: str, is_ptt: bool = True) -> bool:
        """Send a voice note from a specific account (async wrapper)."""
        session = self.sessions.get(account_id)
        if not session:
            raise RuntimeError(f"No active session for account {account_id}")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, session.send_audio, phone, audio_path, is_ptt)

    def get_session(self, account_id: str) -> Optional[WhatsAppSession]:
        return self.sessions.get(account_id)

    def is_connected(self, account_id: str) -> bool:
        session = self.sessions.get(account_id)
        return session is not None and session.connected

    @staticmethod
    async def _noop(*args, **kwargs):
        pass


# Global manager instance
neonize_manager = NeonizeManager()
