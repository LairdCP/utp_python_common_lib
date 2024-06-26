import serial
import threading
import logging
import time


class SerialPort():
    """Base serial port implementation.
    Receives bytes from the serial port and places them in a queue.
    The queue is cleared after if the bytes remain in the queue for
    _clear_queue_timeout_sec amount of time.
    """
    ROBOT_LIBRARY_SCOPE = 'TEST SUITE'
    CLEAR_QUEUE_TIMEOUT_DEFAULT = 5
    SERIAL_PORT_RX_TIMEOUT_SECS = 0.000003 # Based on 1 byte at 3000000 baud
    SERIAL_PORT_RX_SIZE_BYTES = 1024 * 1024

    def __init__(self):
        self._port = None
        self._rx_queue = []
        self._stop_threads = False
        self._clear_queue_timeout_sec = SerialPort.CLEAR_QUEUE_TIMEOUT_DEFAULT
        self._queue_monitor_event = threading.Event()
        self._bytes_received = threading.Event()
        self._monitor_rx_queue = False
        self._enable_queue_monitor = False

    def __queue_monitor_timer_expired(self):
        self._queue_monitor_event.set()

    def __queue_monitor(self):
        while not self._stop_threads:
            self._queue_monitor_event.wait()
            self._queue_monitor_event.clear()
            size = len(self._rx_queue)
            if size > 0:
                logging.debug(f'Clear RX queue ({size})')
                self.clear_rx_queue()

    def pause_queue_monitor(self):
        if self._enable_queue_monitor:
            self._monitor_rx_queue = False
            self._queue_monitor_timer.cancel()

    def resume_queue_monitor(self):
        if self._enable_queue_monitor:
            self._monitor_rx_queue = True
            self._queue_monitor_timer = threading.Timer(
                interval=self._clear_queue_timeout_sec,
                function=self.__queue_monitor_timer_expired)
            self._queue_monitor_timer.daemon = True
            self._queue_monitor_timer.start()

    def __serial_port_rx_thread(self):
        while not self._stop_threads:
            try:
                bytes = self._port.read(self.SERIAL_PORT_RX_SIZE_BYTES)
                if len(bytes) > 0:
                    self._rx_queue.extend(list(bytes))
                    self._bytes_received.set()
                    if self._monitor_rx_queue and not self._queue_monitor_timer.is_alive():
                        self.resume_queue_monitor()
            except:
                pass

    def set_queue_timeout(self, timeout_sec: float):
        """Set the RX byte queue cleanup timeout

        Args:
            timeout_sec (float): Time in seconds
        """
        self._clear_queue_timeout_sec = timeout_sec
        self.pause_queue_monitor()
        self.resume_queue_monitor()

    def open(self, portName: str, baud: int, rtsCts: bool = False):
        """Open the serial port and start processing threads

        Args:
            portName (str): COM port name or device
            baud (int): baud rate
            rtsCts (bool, optional): Enable RTS/CTS flow control. Defaults to False.
        """
        if self._port and self._port.is_open:
            return

        self._port = serial.Serial(portName, baud, rtscts=rtsCts)
        self._port.timeout = self.SERIAL_PORT_RX_TIMEOUT_SECS
        self._port.reset_input_buffer()
        self._port.reset_output_buffer()
        self.clear_rx_queue()
        self.signal_bytes_received()
        self._stop_threads = False
        self.resume_queue_monitor()
        # The serial port RX thread reads all bytes received and places them in a queue
        self._rx_thread = threading.Thread(target=self.__serial_port_rx_thread,
                         daemon=True)
        self._rx_thread.start()
        # The queue monitor thread clears stray RX bytes if they are not processed for
        # clear_queue_timeout_sec amount of time
        self._q_mon_thread = threading.Thread(target=self.__queue_monitor, daemon=True)
        self._q_mon_thread.start()

    def clear_rx_queue(self):
        """Clear all received bytes from the queue
        """
        self._rx_queue.clear()
        self.signal_bytes_received()

    def send(self, data: bytes) -> int | None:
        """Send bytes out the serial port

        Args:
            data (bytes): data to send
        """
        self.pause_queue_monitor()
        if isinstance(data, str):
            data = bytes(data, 'utf-8')
        elif not isinstance(data, bytes):
            data = bytes(data)
        logging.debug(f'[{self._port.name}] TX: {data}')
        res = self._port.write(data)
        self.resume_queue_monitor()
        return res

    def close(self):
        """Close the serial port and stop all threads
        """
        self._stop_threads = True
        self.pause_queue_monitor()
        self._queue_monitor_event.set()
        self._bytes_received.set()
        if self._port and self._port.is_open:
            self._port.close()
            logging.debug(f'closed {self._port.name}')
        self.clear_rx_queue()
        while self._rx_thread.is_alive() or self._q_mon_thread.is_alive():
            time.sleep(0.1)

    def get_rx_queue(self):
        return self._rx_queue

    def is_queue_empty(self):
        if len(self._rx_queue) > 0:
            return False
        else:
            True

    def wait_for_bytes_received(self, timeout_sec: float = None):
        """Wait for bytes to be received on the serial port

        Args:
            timeout_sec (float, optional): Time in seconds to wait. Defaults to None.

        Returns:
            _type_: True if signaled, False if timed out
        """
        return self._bytes_received.wait(timeout_sec)

    def signal_bytes_received(self):
        """Signal that bytes have been received
        """
        self._bytes_received.clear()

    @property
    def port(self):
        """Serial port object"""
        return self._port

    def read(self) -> bytes:
        """Read bytes from the serial port

        Returns:
            bytes: bytes read from the serial port
        """
        self.pause_queue_monitor()
        num_bytes = len(self._rx_queue)
        rx = bytes(self._rx_queue[:num_bytes])
        del self._rx_queue[:num_bytes]
        self.resume_queue_monitor()

        return rx

    def enable_rx_queue_monitor(self, enable: bool):
        """Enable RX queue monitor. When the monitor is enabled, the rx byte
        queue is cleared if bytes are not received for clear_queue_timeout_sec amount of time.

        Args:
            enable (bool): True to enable, False to disable
        """
        self._enable_queue_monitor = enable
        if enable:
            self.resume_queue_monitor()
        else:
            self.pause_queue_monitor()
