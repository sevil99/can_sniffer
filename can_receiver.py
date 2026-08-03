from __future__ import annotations

from collections import deque
import ctypes
from datetime import datetime
import os
import queue
import random
import struct
import threading
import time
from typing import Any


CIO_CAN11 = 0x01
CIO_CAN29 = 0x02

CAN_FLAG_RTR = 0x01
CAN_FLAG_EFF = 0x04

ECIINVAL = -1
ECINODEV = -2
ECIBUSY = -3
ECIMFAULT = -4
ECISTATE = -5
ECINORES = -6

BAUD_SETTINGS = {
    10000: (0x31, 0x1C),
    20000: (0x18, 0x1C),
    50000: (0x09, 0x1C),
    100000: (0x04, 0x1C),
    125000: (0x03, 0x1C),
    250000: (0x01, 0x1C),
    500000: (0x00, 0x1C),
    800000: (0x00, 0x16),
    1000000: (0x00, 0x14),
}

READ_BATCH_SIZE = 64
IDLE_SLEEP_SECONDS = 0.002


class CANMSG_T(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("data", ctypes.c_uint8 * 8),
        ("len", ctypes.c_uint8),
        ("flags", ctypes.c_uint16),
        ("ts", ctypes.c_uint32),
    ]


class CANBOARD_T(ctypes.Structure):
    _fields_ = [
        ("brdnum", ctypes.c_uint8),
        ("hwver", ctypes.c_uint32),
        ("chip", ctypes.c_int16 * 4),
        ("name", ctypes.c_char * 64),
        ("manufacturer", ctypes.c_char * 64),
    ]


class CANMessage:
    def __init__(self, canmsg: CANMSG_T | None = None, channel: int | None = None):
        if canmsg is None:
            self.id = 0
            self.data = b""
            self.length = 0
            self.flags = 0
            self.timestamp = 0
        else:
            length = max(0, min(int(canmsg.len), 8))
            self.id = int(canmsg.id)
            self.data = bytes(canmsg.data[:length])
            self.length = length
            self.flags = int(canmsg.flags)
            self.timestamp = int(canmsg.ts)

        self.channel = channel
        self.receive_time = datetime.now()

    def msg_isrtr(self) -> bool:
        return bool(self.flags & CAN_FLAG_RTR)

    def msg_iseff(self) -> bool:
        return bool(self.flags & CAN_FLAG_EFF)

    def get_id_string(self) -> str:
        if self.msg_iseff() or self.id > 0x7FF:
            return f"0x{self.id:08X}"
        return f"0x{self.id:03X}"

    def get_data_hex(self) -> str:
        return " ".join(f"{byte:02X}" for byte in self.data)

    def get_frame_type(self) -> str:
        return "EXT" if self.msg_iseff() else "STD"

    def get_rtr_status(self) -> str:
        return "RTR" if self.msg_isrtr() else "DATA"

    def get_timestamp_ms(self) -> float:
        return self.timestamp / 1000.0

    def __str__(self) -> str:
        rtr_flag = " RTR" if self.msg_isrtr() else ""
        return f"CAN {self.get_frame_type()} ID: {self.get_id_string()}{rtr_flag} Len: {self.length} Data: {self.get_data_hex()}"


class CHAIReceiver:
    def __init__(self, dll_path: str | None = None):
        self.dll_path = dll_path or os.environ.get("CHAI_DLL", "chai.dll")
        self.chai: Any | None = None
        self.is_loaded = False
        self.is_connected = False
        self.channel: int | None = None
        self.stop_event = threading.Event()
        self.message_count = 0
        self.last_error = ""
        self._initialized = False
        self._pending: deque[CANMessage] = deque()
        self._last_read_error: tuple[int, float] | None = None
        self._single_read_mode = False
        self._debug = os.environ.get("CAN_RECEIVER_DEBUG", "").lower() in {"1", "true", "yes"}

        try:
            self.chai = ctypes.WinDLL(self.dll_path)
            self._setup_prototypes()
            self.is_loaded = True
        except Exception as error:
            self.last_error = f"Cannot load {self.dll_path}: {error}"

    def _setup_prototypes(self) -> None:
        if self.chai is None:
            return

        self.chai.CiInit.argtypes = []
        self.chai.CiInit.restype = ctypes.c_int16
        self.chai.CiBoardInfo.argtypes = [ctypes.POINTER(CANBOARD_T)]
        self.chai.CiBoardInfo.restype = ctypes.c_int16
        self.chai.CiOpen.argtypes = [ctypes.c_uint8, ctypes.c_uint8]
        self.chai.CiOpen.restype = ctypes.c_int16
        self.chai.CiClose.argtypes = [ctypes.c_uint8]
        self.chai.CiClose.restype = ctypes.c_int16
        self.chai.CiSetBaud.argtypes = [ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint8]
        self.chai.CiSetBaud.restype = ctypes.c_int16
        self.chai.CiSetFilter.argtypes = [ctypes.c_uint8, ctypes.c_uint32, ctypes.c_uint32]
        self.chai.CiSetFilter.restype = ctypes.c_int16
        self.chai.CiStart.argtypes = [ctypes.c_uint8]
        self.chai.CiStart.restype = ctypes.c_int16
        self.chai.CiStop.argtypes = [ctypes.c_uint8]
        self.chai.CiStop.restype = ctypes.c_int16
        self.chai.CiRead.argtypes = [ctypes.c_uint8, ctypes.POINTER(CANMSG_T), ctypes.c_int16]
        self.chai.CiRead.restype = ctypes.c_int16

    def scan_devices(self) -> list[int]:
        if not self.is_loaded or self.chai is None:
            return []

        try:
            self._initialize_library()
            board_info = CANBOARD_T()
            board_info.brdnum = 0
            result = self.chai.CiBoardInfo(ctypes.byref(board_info))
            if result < 0:
                return []
            return [int(chip) for chip in board_info.chip if int(chip) >= 0]
        except Exception as error:
            self.last_error = str(error)
            return []

    def connect(self, channel: int = 0, baud_rate: int = 500000) -> bool:
        if not self.is_loaded or self.chai is None:
            return False

        try:
            if self.is_connected:
                self.disconnect()

            selected_channel = int(channel)
            btr0, btr1 = self._baud_settings(int(baud_rate))

            self._initialize_library()
            self._open_channel(selected_channel)
            self._check(self.chai.CiSetBaud(selected_channel, btr0, btr1), "CiSetBaud")
            self._check(self.chai.CiSetFilter(selected_channel, 0, 0), "CiSetFilter")
            self._check(self.chai.CiStart(selected_channel), "CiStart")

            self.channel = selected_channel
            self.is_connected = True
            self.stop_event.clear()
            self.message_count = 0
            self._pending.clear()
            self._last_read_error = None
            self._single_read_mode = False
            self.last_error = ""
            return True
        except Exception as error:
            self.last_error = str(error)
            self.disconnect()
            return False

    def disconnect(self) -> None:
        self.stop_event.set()
        channel = self.channel
        self.is_connected = False
        self.channel = None
        self._pending.clear()

        if self.chai is None or channel is None:
            return

        try:
            self.chai.CiStop(channel)
        except Exception:
            pass
        try:
            self.chai.CiClose(channel)
        except Exception:
            pass

    def get_message(self, timeout: float = 0.1) -> CANMessage | None:
        deadline = time.monotonic() + max(0.0, float(timeout))

        while not self.stop_event.is_set() and self.is_connected:
            if self._pending:
                return self._pending.popleft()

            self._read_once()
            if self._pending:
                return self._pending.popleft()

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(IDLE_SLEEP_SECONDS, remaining))

        return None

    def _initialize_library(self) -> None:
        if self._initialized:
            return
        if self.chai is None:
            raise RuntimeError("CHAI library is not loaded")
        self._check(self.chai.CiInit(), "CiInit")
        self._initialized = True

    def _open_channel(self, channel: int) -> None:
        if self.chai is None:
            raise RuntimeError("CHAI library is not loaded")

        modes = (CIO_CAN11, CIO_CAN11 | CIO_CAN29) if channel == 1 else (CIO_CAN11 | CIO_CAN29, CIO_CAN11)
        last_result = 0
        for mode in modes:
            result = self.chai.CiOpen(channel, mode)
            if result >= 0:
                return
            last_result = int(result)

        raise RuntimeError(f"CiOpen failed for CH{channel}: {last_result}")

    def _read_once(self) -> int:
        if self.chai is None or self.channel is None:
            return 0

        if self._single_read_mode:
            return self._read_single_message()

        buffer = (CANMSG_T * READ_BATCH_SIZE)()
        try:
            result = int(self.chai.CiRead(self.channel, buffer, READ_BATCH_SIZE))
        except Exception as error:
            self.last_error = f"CiRead exception: {error}"
            return 0

        if result > 0:
            count = min(result, READ_BATCH_SIZE)
            for index in range(count):
                self._remember_message(CANMessage(buffer[index], channel=self.channel))
            return count

        if result == 0:
            return 0

        if result == ECIINVAL:
            self._single_read_mode = True
            return self._read_single_message()

        self._remember_read_error(result)
        return 0

    def _read_single_message(self) -> int:
        if self.chai is None or self.channel is None:
            return 0

        message = CANMSG_T()
        try:
            result = int(self.chai.CiRead(self.channel, ctypes.byref(message), 1))
        except Exception as error:
            self.last_error = f"CiRead single exception: {error}"
            return 0

        if result == 1:
            self._remember_message(CANMessage(message, channel=self.channel))
            return 1
        if result < 0 and result != ECIINVAL:
            self._remember_read_error(result)
        return 0

    def _remember_message(self, message: CANMessage) -> None:
        self.message_count += 1
        self._pending.append(message)
        if self._debug and (self.message_count <= 5 or self.message_count % 1000 == 0):
            print(
                f"RX CH{message.channel} {self.message_count:08d} {message.get_frame_type()} "
                f"{message.get_id_string().upper()} {message.length} HEX {message.get_data_hex()} {message.timestamp:010d}"
            )

    def _remember_read_error(self, result: int) -> None:
        now = time.monotonic()
        if self._last_read_error is None or self._last_read_error[0] != result or now - self._last_read_error[1] > 2.0:
            self.last_error = f"CiRead failed: {result}"
            if self._debug:
                print(self.last_error)
            self._last_read_error = (result, now)

    @staticmethod
    def _baud_settings(baud_rate: int) -> tuple[int, int]:
        if baud_rate in BAUD_SETTINGS:
            return BAUD_SETTINGS[baud_rate]
        closest_rate = min(BAUD_SETTINGS, key=lambda rate: abs(rate - baud_rate))
        return BAUD_SETTINGS[closest_rate]

    @staticmethod
    def _check(result: int, action: str) -> None:
        if int(result) < 0:
            raise RuntimeError(f"{action} failed: {int(result)}")


class DemoReceiver:
    def __init__(self):
        self.is_loaded = True
        self.is_connected = False
        self.channel: int | None = None
        self.stop_event = threading.Event()
        self.message_queue: queue.Queue[CANMessage] = queue.Queue(maxsize=1000)
        self.message_count = 0
        self.demo_thread: threading.Thread | None = None

    def scan_devices(self) -> list[int]:
        return [0, 1]

    def connect(self, channel: int = 0, baud_rate: int = 500000) -> bool:
        if self.is_connected:
            self.disconnect()

        self.channel = int(channel)
        self.is_connected = True
        self.stop_event.clear()
        self.message_count = 0
        self.demo_thread = threading.Thread(target=self._demo_loop, daemon=True)
        self.demo_thread.start()
        return True

    def disconnect(self) -> None:
        self.is_connected = False
        self.stop_event.set()
        if self.demo_thread and self.demo_thread.is_alive():
            self.demo_thread.join(timeout=1.0)
        self._clear_queue()

    def get_message(self, timeout: float = 0.1) -> CANMessage | None:
        try:
            return self.message_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _demo_loop(self) -> None:
        while not self.stop_event.is_set() and self.is_connected:
            self._put_demo_message()
            time.sleep(0.02)

    def _put_demo_message(self) -> None:
        channel = 0 if self.channel is None else self.channel
        message_id, payload = random.choice(self._demo_frames())
        canmsg = CANMSG_T()
        canmsg.id = message_id
        canmsg.len = len(payload)
        canmsg.flags = 0
        canmsg.ts = int((time.monotonic() * 1000) % 0xFFFFFFFF)
        for index, byte in enumerate(payload):
            canmsg.data[index] = byte

        message = CANMessage(canmsg, channel=channel)
        self.message_count += 1
        try:
            self.message_queue.put_nowait(message)
        except queue.Full:
            pass

    @staticmethod
    def _demo_frames() -> list[tuple[int, list[int]]]:
        gas_value = random.uniform(0.0, 100.0)
        gas_payload = [0x27, 0x00, 0x27, 0x00, *list(struct.pack("<f", gas_value))]

        knock_value = random.uniform(0.0, 5.0)
        knock_payload = [0x03, 0x00, 0x03, 0x00, *list(struct.pack("<f", knock_value))]

        return [
            (0x001, gas_payload),
            (0x10F, knock_payload),
            (0x100, [0x06, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00]),
            (0x000, [0x0D, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
        ]

    def _clear_queue(self) -> None:
        while True:
            try:
                self.message_queue.get_nowait()
            except queue.Empty:
                return


def create_receiver() -> CHAIReceiver | DemoReceiver:
    if os.environ.get("CAN_RECEIVER_DEMO", "").lower() in {"1", "true", "yes"}:
        return DemoReceiver()

    receiver = CHAIReceiver()
    if receiver.is_loaded:
        return receiver
    return DemoReceiver()
