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


def _extract_phone_from_any(obj) -> Optional[str]:
    """Robustly extract phone number from JID, Device, PairStatus or any object."""
    if not obj:
        return None
    # 1. Direct User / user attribute (e.g. JID.User)
    for attr in ("User", "user"):
        val = getattr(obj, attr, None)
        if val:
            return str(val)

    # 2. Nested JID (e.g. Device.JID, client.me.JID)
    for parent_attr in ("JID", "jid", "ID", "id"):
        parent = getattr(obj, parent_attr, None)
        if parent:
            for attr in ("User", "user"):
                val = getattr(parent, attr, None)
                if val:
                    return str(val)

    return None


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
        on_logged_out: Optional[Callable] = None,
        phone_number: Optional[str] = None,
    ):
        self.account_id = account_id
        self.session_name = session_name
        self.on_qr = on_qr
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected
        self.on_message = on_message
        self.on_logged_out = on_logged_out or on_disconnected
        self.loop = loop
        self.client = None
        self.connected = False
        self.phone_number: Optional[str] = phone_number
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
                PairStatus as PairStatusEv,
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

            # ── PairStatus event (triggers when QR is scanned & authenticated) ──
            @client.event(PairStatusEv)
            def on_pair_status_ev(c, event: PairStatusEv):
                logger.info(f"PairStatusEv received for account {self.account_id}")
                self.connected = True
                phone = (
                    _extract_phone_from_any(event)
                    or _extract_phone_from_any(getattr(c, "me", None))
                    or self.phone_number
                )
                if phone:
                    self.phone_number = phone
                logger.info(f"Account {self.account_id} paired successfully! Phone: {self.phone_number or phone}")
                _safe_schedule(self.on_connected(self.account_id, self.phone_number or phone))

            # ── Connected event (triggers on socket connection) ─────────────
            @client.event(ConnectedEv)
            def on_connected_ev(c, event: ConnectedEv):
                logger.info(f"ConnectedEv received for account {self.account_id}")
                phone = _extract_phone_from_any(getattr(c, "me", None)) or self.phone_number

                # Check if client is already paired/authenticated
                is_logged_in = False
                if getattr(c, "me", None) is not None:
                    is_logged_in = True
                elif getattr(c, "is_logged_in", None) and callable(c.is_logged_in):
                    try:
                        is_logged_in = c.is_logged_in()
                    except Exception:
                        pass
                elif phone:
                    is_logged_in = True

                if is_logged_in:
                    self.connected = True
                    if phone:
                        self.phone_number = phone
                    logger.info(f"Account {self.account_id} connected and logged in! Phone: {self.phone_number or phone}")
                    _safe_schedule(self.on_connected(self.account_id, self.phone_number or phone))
                else:
                    logger.info(f"Account {self.account_id} ConnectedEv before pairing (waiting for QR scan)")

            # ── Disconnected event (socket temporary drop) ───────────────
            @client.event(DisconnectedEv)
            def on_disconnected_ev(c, event: DisconnectedEv):
                self.connected = False
                logger.warning(f"DisconnectedEv: WhatsApp socket dropped for {self.account_id}")
                _safe_schedule(self.on_disconnected(self.account_id))

            # ── LoggedOut event (device revoked on phone) ─────────────────
            @client.event(LoggedOutEv)
            def on_logged_out(c, event: LoggedOutEv):
                self.connected = False
                logger.warning(f"LoggedOutEv: Account {self.account_id} was permanently logged out on phone")
                _safe_schedule(self.on_logged_out(self.account_id))

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
                    has_sticker = False
                    try:
                        has_image = msg.HasField("imageMessage")
                    except Exception:
                        has_image = bool(getattr(msg, "imageMessage", None) and (getattr(msg.imageMessage, "url", None) or getattr(msg.imageMessage, "directPath", None)))

                    try:
                        has_audio = msg.HasField("audioMessage")
                    except Exception:
                        has_audio = bool(getattr(msg, "audioMessage", None) and (getattr(msg.audioMessage, "url", None) or getattr(msg.audioMessage, "directPath", None)))

                    try:
                        has_sticker = msg.HasField("stickerMessage")
                    except Exception:
                        has_sticker = bool(getattr(msg, "stickerMessage", None))

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
                    elif has_sticker:
                        media_type = "image"
                        mime_type = "image/webp"
                        content = "[Sticker]"
                        try:
                            media_bytes = None
                            try:
                                media_bytes = c.download_any(msg)
                            except Exception:
                                pass
                            if not media_bytes and hasattr(msg, "stickerMessage"):
                                try:
                                    media_bytes = c.download_any(msg.stickerMessage)
                                except Exception:
                                    pass

                            if media_bytes:
                                import os
                                from app.config import settings
                                media_dir = os.path.join(settings.media_dir, self.account_id)
                                os.makedirs(media_dir, exist_ok=True)
                                filename = f"{message_id or 'sticker'}.webp"
                                media_path = os.path.join(media_dir, filename)
                                with open(media_path, 'wb') as f:
                                    f.write(media_bytes)
                                logger.info(f"Downloaded sticker: {media_path} ({len(media_bytes)} bytes)")
                        except Exception as e:
                            logger.error(f"Failed to download sticker: {e}")
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

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
            raise ValueError(f"Audio file not found or empty: {audio_path}")

        try:
            from neonize.client import build_jid
            from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import AudioMessage, Message
            from neonize.utils.enum import MediaType
            import math

            abs_path = os.path.abspath(audio_path)
            clean_phone = "".join(c for c in phone if c.isdigit())
            jid = build_jid(clean_phone, "s.whatsapp.net")

            # Try to resolve phone to LID for routing in modern WhatsApp clients
            try:
                lid_jid = self.client.get_lid_from_pn(jid)
                if lid_jid and lid_jid.User:
                    logger.info(f"Resolved phone {clean_phone} -> LID {lid_jid.User} for audio delivery")
                    jid = lid_jid
            except Exception as lid_err:
                logger.debug(f"LID resolution skipped for {clean_phone}: {lid_err}")

            with open(abs_path, "rb") as f:
                audio_bytes = f.read()

            # Upload audio to WhatsApp media servers
            upload = self.client.upload(audio_bytes, MediaType.MediaAudio)

            # Extract duration safely via ffprobe or default
            duration = 2
            try:
                from neonize.utils.ffmpeg import FFmpeg
                with FFmpeg(audio_bytes) as ffmpeg:
                    info = ffmpeg.extract_info()
                    if info and info.format and info.format.duration:
                        duration = max(1, int(float(info.format.duration)))
            except Exception as dur_err:
                logger.debug(f"Duration probe failed ({dur_err}), defaulting to 2s")

            # WhatsApp Mobile Voice Note requires a 64-byte waveform amplitude array (values 0-100)
            waveform = bytes([
                min(100, max(12, int(45 + 35 * math.sin(i / 2.8) + (i % 6) * 4)))
                for i in range(64)
            ])

            # WhatsApp mobile (iOS & Android) strictly requires "audio/ogg; codecs=opus" for PTT playback
            mimetype = "audio/ogg; codecs=opus" if is_ptt else "audio/ogg"

            audio_msg = AudioMessage(
                URL=upload.url,
                directPath=upload.DirectPath,
                mediaKey=upload.MediaKey,
                fileSHA256=upload.FileSHA256,
                fileEncSHA256=upload.FileEncSHA256,
                fileLength=upload.FileLength,
                seconds=duration,
                mimetype=mimetype,
                PTT=is_ptt,
                waveform=waveform if is_ptt else None,
            )
            msg_envelope = Message(audioMessage=audio_msg)

            # Send via client.send_message
            self.client.send_message(jid, msg_envelope)
            logger.info(f"Voice note ({len(audio_bytes)} bytes, {duration}s, mime: {mimetype}) sent to {clean_phone}")
            return True

        except Exception as e:
            logger.error(f"Failed to send voice note to {phone}: {e}", exc_info=True)
            # Fallback to neonize built-in send_audio if direct protobuf failed
            try:
                from neonize.client import build_jid
                jid = build_jid("".join(c for c in phone if c.isdigit()), "s.whatsapp.net")
                if hasattr(self.client, "send_audio"):
                    self.client.send_audio(jid, os.path.abspath(audio_path), ptt=is_ptt)
                    logger.info(f"Voice note sent via fallback send_audio to {phone}")
                    return True
            except Exception as fb_err:
                logger.error(f"Fallback send_audio also failed: {fb_err}")
            raise

    def send_sticker(self, phone: str, image_path: str) -> bool:
        """Convert image to 512x512 WebP sticker and send synchronously."""
        if not self.client or not self.connected:
            raise RuntimeError(f"WhatsApp not connected for account {self.account_id}")

        if not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
            raise ValueError(f"Image file not found or empty: {image_path}")

        try:
            from PIL import Image
            from neonize.client import build_jid
            import io

            clean_phone = "".join(c for c in phone if c.isdigit())
            jid = build_jid(clean_phone, "s.whatsapp.net")

            try:
                lid_jid = self.client.get_lid_from_pn(jid)
                if lid_jid and lid_jid.User:
                    jid = lid_jid
            except Exception:
                pass

            # Prepare 512x512 WebP sticker file
            webp_path = os.path.splitext(image_path)[0] + "_sticker.webp"
            if not os.path.exists(webp_path):
                with Image.open(image_path) as img:
                    img = img.convert("RGBA")
                    img.thumbnail((512, 512), Image.Resampling.LANCZOS)
                    canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
                    offset = ((512 - img.width) // 2, (512 - img.height) // 2)
                    canvas.paste(img, offset)
                    canvas.save(webp_path, format="WEBP", quality=90)

            abs_webp = os.path.abspath(webp_path)
            # Try client.send_sticker first
            if hasattr(self.client, "send_sticker"):
                try:
                    self.client.send_sticker(jid, abs_webp)
                    logger.info(f"Sticker sent via send_sticker to {clean_phone}")
                    return True
                except Exception as sticker_err:
                    logger.warning(f"send_sticker method call failed ({sticker_err}), falling back to direct protobuf")

            # Fallback to direct protobuf upload
            from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import StickerMessage, Message
            from neonize.utils.enum import MediaType

            with open(abs_webp, "rb") as f:
                sticker_bytes = f.read()

            upload = self.client.upload(sticker_bytes, MediaType.MediaImage)
            sticker_msg = StickerMessage(
                URL=upload.url,
                directPath=upload.DirectPath,
                mediaKey=upload.MediaKey,
                fileSHA256=upload.FileSHA256,
                fileEncSHA256=upload.FileEncSHA256,
                fileLength=upload.FileLength,
                mimetype="image/webp",
            )
            self.client.send_message(jid, Message(stickerMessage=sticker_msg))
            logger.info(f"Sticker sent via protobuf to {clean_phone}")
            return True
        except Exception as e:
            logger.error(f"Failed to send sticker to {phone}: {e}", exc_info=True)
            raise

    def stop(self):
        """Stop the session."""
        self._stopped = True
        self.connected = False
        if self.client:
            try:
                if hasattr(self.client, "disconnect"):
                    self.client.disconnect()
                elif hasattr(self.client, "stop"):
                    self.client.stop()
            except Exception as e:
                logger.warning(f"Could not disconnect client: {e}")
            try:
                from neonize._binder import gocode
                if hasattr(self.client, "uuid"):
                    gocode.Stop(self.client.uuid)
            except Exception as e:
                logger.debug(f"gocode.Stop note: {e}")
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)


class NeonizeManager:
    """Manages multiple WhatsApp sessions."""

    def __init__(self):
        self.sessions: Dict[str, WhatsAppSession] = {}
        self._callbacks: Dict[str, Dict[str, Callable]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._start_lock = asyncio.Lock()

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
        on_logged_out: Optional[Callable] = None,
    ):
        """Register event callbacks for an account."""
        self._callbacks[account_id] = {
            "on_qr": on_qr,
            "on_connected": on_connected,
            "on_disconnected": on_disconnected,
            "on_message": on_message,
            "on_logged_out": on_logged_out or on_disconnected,
        }

    async def start_session(
        self, account_id: str, session_name: str, phone_number: Optional[str] = None
    ) -> WhatsAppSession:
        """Start a WhatsApp session for an account (serialized to protect Go C-FFI runtime)."""
        async with self._start_lock:
            # Stop existing session if any without blocking the event loop
            if account_id in self.sessions:
                existing = self.sessions[account_id]
                if existing.connected:
                    return existing
                await asyncio.get_event_loop().run_in_executor(None, existing.stop)
                self.sessions.pop(account_id, None)
                # Wait 1.5s for OS file lock and Go C-FFI runtime to completely release SQLite handles
                await asyncio.sleep(1.5)

            callbacks = self._callbacks.get(account_id, {})
            loop = asyncio.get_running_loop()

            session = WhatsAppSession(
                account_id=account_id,
                session_name=session_name,
                on_qr=callbacks.get("on_qr", self._noop),
                on_connected=callbacks.get("on_connected", self._noop),
                on_disconnected=callbacks.get("on_disconnected", self._noop),
                on_message=callbacks.get("on_message", self._noop),
                on_logged_out=callbacks.get("on_logged_out", self._noop),
                loop=loop,
                phone_number=phone_number,
            )

            self.sessions[account_id] = session
            session.start()
            # Stagger startup so Go runtime registers client in its global map safely
            await asyncio.sleep(3)
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

    async def send_sticker(self, account_id: str, phone: str, image_path: str) -> bool:
        """Send a sticker from a specific account (async wrapper)."""
        session = self.sessions.get(account_id)
        if not session:
            raise RuntimeError(f"No active session for account {account_id}")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, session.send_sticker, phone, image_path)

    def get_session(self, account_id: str) -> Optional[WhatsAppSession]:
        return self.sessions.get(account_id)

    def is_connected(self, account_id: str) -> bool:
        session = self.sessions.get(account_id)
        if not session:
            return False
        if session.connected:
            return True
        if session.client and getattr(session.client, "connected", False):
            if getattr(session.client, "me", None) is not None or session.phone_number:
                session.connected = True
                return True
        return False

    @staticmethod
    async def _noop(*args, **kwargs):
        pass


# Global manager instance
neonize_manager = NeonizeManager()
