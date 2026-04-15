import re
import time
from typing import Any

from pynput.keyboard import Controller, Key
from smartcard.CardConnection import CardConnection
from smartcard.CardMonitoring import CardMonitor, CardObserver
from smartcard.Exceptions import CardConnectionException, NoCardException

ULTRALIGHT_ATR_PREFIX = "3B 8F 80 01 80 4F 0C A0 00 00 03 06"
IMGOTAG_URL_RE = re.compile(r"nfc\.imagotag\.com/([A-Za-z0-9_-]+)", re.IGNORECASE)


URI_PREFIX_MAP: dict[int, str] = {
    0x00: "",
    0x01: "http://www.",
    0x02: "https://www.",
    0x03: "http://",
    0x04: "https://",
}


def apdu_transmit(
    connection: CardConnection, apdu: list[int]
) -> tuple[list[int], int, int]:
    """Transmit an APDU command to the connected card.

    Args:
        connection: Active card connection used for APDU exchange.
        apdu: APDU bytes to send.

    Returns:
        A tuple ``(response, sw1, sw2)`` where:
        - response (list[int]): Raw response bytes.
        - sw1 (int): First status byte.
        - sw2 (int): Second status byte.
    """
    response, sw1, sw2 = connection.transmit(apdu)
    return response, sw1, sw2


def is_ultralight_or_ntag_atr(atr: list[int]) -> bool:
    """Check whether an ATR matches the expected Ultralight/NTAG pattern.

    Args:
        atr: ATR bytes returned by the reader.

    Returns:
        ``True`` if the ATR matches the configured Ultralight/NTAG prefix,
        otherwise ``False``.
    """
    atr_hex = " ".join(f"{x:02X}" for x in atr)
    return atr_hex.startswith(ULTRALIGHT_ATR_PREFIX)


def read_ultralight_window(
    connection: CardConnection, start_page: int
) -> tuple[list[int] | None, int, int]:
    """Read one Ultralight window (4 pages / 16 bytes).

    This function first tries the standard PC/SC read APDU and then falls back
    to a PN53x-style command when needed.

    Args:
        connection: Active card connection.
        start_page: First Ultralight page to read.

    Returns:
        A tuple ``(data, sw1, sw2)`` where:
        - data (list[int] | None): 16 data bytes on success, else ``None``.
        - sw1 (int): First status byte from the attempted command.
        - sw2 (int): Second status byte from the attempted command.
    """
    data, sw1, sw2 = apdu_transmit(connection, [0xFF, 0xB0, 0x00, start_page, 0x10])
    if (sw1, sw2) == (0x90, 0x00) and len(data) >= 16:
        return data[:16], sw1, sw2

    data, sw1, sw2 = apdu_transmit(
        connection, [0xFF, 0x00, 0x00, 0x00, 0x04, 0xD4, 0x42, 0x30, start_page]
    )
    if (sw1, sw2) != (0x90, 0x00):
        return None, sw1, sw2

    if len(data) >= 19 and data[:3] == [0xD5, 0x43, 0x00]:
        return data[3:19], sw1, sw2
    if len(data) >= 16:
        return data[-16:], sw1, sw2
    return None, sw1, sw2


def read_ndef_message(connection: CardConnection) -> list[int] | None:
    """Read only the bytes required to reconstruct the NDEF message.

    Args:
        connection: Active card connection.

    Returns:
        The NDEF message bytes as ``list[int]`` when successfully parsed from
        TLV data, otherwise ``None``.
    """
    raw: list[int] = []

    # Read only until we have enough bytes for the NDEF message.
    for page in range(4, 44, 4):
        data, _, _ = read_ultralight_window(connection, page)
        if data is None:
            return None
        raw.extend(data)

        ndef = extract_ndef_from_tlv(raw)
        if ndef is not None:
            return ndef

    return None


def extract_ndef_from_tlv(raw: list[int]) -> list[int] | None:
    """Extract NDEF bytes from a raw Ultralight memory snapshot.

    Args:
        raw: Raw bytes gathered from card pages.

    Returns:
        NDEF message bytes when enough TLV data is available, otherwise ``None``.
    """
    try:
        tlv_start = raw.index(0x03)
    except ValueError:
        return None

    if tlv_start + 1 >= len(raw):
        return None

    length = raw[tlv_start + 1]
    cursor = tlv_start + 2
    if length == 0xFF:
        if cursor + 1 >= len(raw):
            return None
        length = (raw[cursor] << 8) | raw[cursor + 1]
        cursor += 2

    end = cursor + length
    if len(raw) < end:
        return None
    return raw[cursor:end]


def parse_first_ndef_record(ndef: list[int]) -> tuple[int, bytes, bytes] | None:
    """Parse the first NDEF record from an NDEF message.

    Args:
        ndef: Raw NDEF message bytes.

    Returns:
        ``(tnf, record_type, payload)`` if parsing succeeds, otherwise ``None``.
        - tnf (int): Type Name Format value.
        - record_type (bytes): Record type field.
        - payload (bytes): Record payload bytes.
    """
    if len(ndef) < 3:
        return None

    header = ndef[0]
    sr = bool(header & 0x10)
    il = bool(header & 0x08)
    tnf = header & 0x07

    type_len = ndef[1]
    idx = 2

    if sr:
        if len(ndef) <= idx:
            return None
        payload_len = ndef[idx]
        idx += 1
    else:
        if len(ndef) < idx + 4:
            return None
        payload_len = (
            (ndef[idx] << 24)
            | (ndef[idx + 1] << 16)
            | (ndef[idx + 2] << 8)
            | ndef[idx + 3]
        )
        idx += 4

    id_len = 0
    if il:
        if len(ndef) <= idx:
            return None
        id_len = ndef[idx]
        idx += 1

    if len(ndef) < idx + type_len + id_len:
        return None

    record_type = bytes(ndef[idx : idx + type_len])
    idx += type_len + id_len

    if len(ndef) < idx + payload_len:
        return None

    payload = bytes(ndef[idx : idx + payload_len])
    return tnf, record_type, payload


def decode_ndef_record_to_text(
    tnf: int, record_type: bytes, payload: bytes
) -> str | None:
    """Decode an NDEF record payload to a text value.

    Supports well-known URI ("U") and Text ("T") records. For other records,
    it attempts UTF-8 decoding of the payload.

    Args:
        tnf: Type Name Format of the record.
        record_type: NDEF record type bytes.
        payload: NDEF payload bytes.

    Returns:
        Decoded string value, or ``None`` when no value can be produced.
    """
    if tnf == 0x01 and record_type == b"U" and payload:
        prefix = URI_PREFIX_MAP.get(payload[0], "")
        suffix = payload[1:].decode("utf-8", errors="replace")
        return f"{prefix}{suffix}".strip()

    if tnf == 0x01 and record_type == b"T" and payload:
        status = payload[0]
        lang_len = status & 0x3F
        text_bytes = payload[1 + lang_len :]
        return text_bytes.decode("utf-8", errors="replace").strip()

    return payload.decode("utf-8", errors="replace").strip() if payload else None


def extract_imgotag_serial(value: str) -> str | None:
    """Extract the serial from an Imagotag NFC URL.

    Args:
        value: Candidate string that should match
            ``nfc.imagotag.com/<serial>`` (with optional http/https prefix).

    Returns:
        The extracted serial when the value matches the expected format,
        otherwise ``None``.
    """
    normalized = value.strip()
    normalized = re.sub(r"^https?://", "", normalized, flags=re.IGNORECASE)
    normalized = normalized.rstrip("/")

    match = IMGOTAG_URL_RE.fullmatch(normalized)
    if not match:
        return None
    return match.group(1)


def send_serial_with_keyboard(serial: str, keyboard: Controller) -> None:
    """Type a serial value with the keyboard and press Enter.

    Args:
        serial: Serial string to type.
        keyboard: Pynput keyboard controller used to inject keystrokes.

    Returns:
        None.
    """
    keyboard.type(serial)
    keyboard.press(Key.enter)
    keyboard.release(Key.enter)


class ImgotagObserver(CardObserver):
    """Card observer that extracts and emits Imagotag serials from NFC tags."""

    def __init__(self) -> None:
        """Initialize the observer resources.

        Returns:
            None.
        """
        self.keyboard = Controller()

    def update(self, observable: Any, handlers: tuple[list[Any], list[Any]]) -> None:
        """Handle card monitor notifications.

        Args:
            observable: Event source from ``CardMonitor``.
            handlers: Tuple ``(added_cards, removed_cards)``.

        Returns:
            None.
        """
        added_cards, removed_cards = handlers

        for card in removed_cards:
            print(f"Card removed: {card}")

        for card in added_cards:
            print(f"Card detected: {card}")
            self._process_card(card)

    def _process_card(self, card: Any) -> None:
        """Process a single card to extract and send a serial.

        Args:
            card: Card object provided by pyscard.

        Returns:
            None.
        """
        connection = card.createConnection()

        try:
            connection.connect()
            atr = connection.getATR()

            if not is_ultralight_or_ntag_atr(atr):
                return

            ndef = read_ndef_message(connection)
            if not ndef:
                return

            parsed = parse_first_ndef_record(ndef)
            if parsed is None:
                return

            tnf, record_type, payload = parsed

            text_value = decode_ndef_record_to_text(tnf, record_type, payload)
            if not text_value:
                return

            serial = extract_imgotag_serial(text_value)
            if serial is None:
                print("Invalid NDEF format")
                return

            print(f"Serial: {serial}")
            try:
                send_serial_with_keyboard(serial, self.keyboard)
            except Exception as exc:
                print(f"Keyboard send error: {exc}")

        except (NoCardException, CardConnectionException) as exc:
            print(f"Card communication error: {exc}")
        except Exception as exc:
            print(f"Unexpected card processing error: {exc}")
        finally:
            try:
                connection.disconnect()
            except Exception:
                pass


def main():
    """Start NFC monitoring and attach the Imagotag observer.

    Returns:
        None.
    """
    print("Monitoring for MIFARE Ultralight/NTAG (Ctrl+C to stop)...")

    monitor = CardMonitor()
    observer = ImgotagObserver()

    try:
        monitor.addObserver(observer)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping monitor...")
    except Exception as exc:
        print(f"Fatal monitoring error: {exc}")
    finally:
        try:
            monitor.deleteObserver(observer)
        except Exception:
            pass


if __name__ == "__main__":
    main()
