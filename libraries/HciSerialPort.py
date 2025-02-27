import time
import serial
import threading
import queue
import io
import zlib
import hci
import hci.command
import hci.event
import logging


class HciSerialPort():
    """Serial port implementation to communicate with Infineon Bluetooth HCI devices
    """
    ROBOT_LIBRARY_SCOPE = 'TEST SUITE'

    CLEAR_QUEUE_TIMEOUT = 0.1
    WRITE_RAM_MAX_SIZE = 240

    OPCODE_DOWNLOAD_MINIDRIVER = 0xFC2E
    OPCODE_WRITE_RAM = 0xFC4C
    OPCODE_LAUNCH_RAM = 0xFC4E
    OPCODE_UPDATE_BAUDRATE = 0xFC18
    OPCODE_CHIP_ERASE = 0xFFCE
    OPCODE_VERIFY_CRC = 0xFCCC

    ERASE_ALL_FLASH_MAGIC = 0xFCBEEEEF
    LITTLE_ENDIAN = 'little'
    LAUNCH_RAM_DELAY = 0.2
    FLASH_PAD = 0xFF
    RAM_PAD = 0x00

    SERIAL_PORT_RX_TIMEOUT_SECS = 0.0006076 # Based on 7 bytes at 115200 baud (a full HCI command complete event)
    SERIAL_PORT_RX_SIZE_BYTES = 1024

    def __init__(self):
        self.port = None
        self.rx_bytes = []
        self.rx_queue = None
        self.stop_threads = False
        self.queue_monitor_event = threading.Event()

    def __queue_monitor(self):
        last_len = 0
        curr_len = 0
        if not self.rx_queue:
            raise Exception('RX queue is NULL')
        while True:
            if self.stop_threads:
                break
            self.queue_monitor_event.wait()
            if not self.rx_queue.empty():
                curr_len = self.rx_queue.qsize()
                if curr_len == last_len:
                    logging.debug(
                        f'Clear RX queue ({curr_len})')
                    res = True
                    while res:
                        try:
                            # TODO: Instead of clearing the queue, see if a packet can be parsed and fire an event
                            res = self.rx_queue.get(False)
                            logging.debug(
                                f'Unhandled pkt: {res.binary.hex(",")}')
                        except:
                            break
                    self.clear_rx_queue()

                else:
                    logging.debug(f'RX queue len: {curr_len}')
                last_len = curr_len
            time.sleep(self.CLEAR_QUEUE_TIMEOUT)

    def __pause_queue_monitor(self):
        self.queue_monitor_event.clear()

    def __resume_queue_monitor(self):
        self.queue_monitor_event.set()

    def __serial_port_rx_thread(self):
        self.rx_bytes.clear()
        if not self.rx_queue or not self.port:
            raise Exception('Null object')
        while True:
            if self.stop_threads:
                break
            try:
                self.rx_bytes.extend(self.port.read(
                    self.SERIAL_PORT_RX_SIZE_BYTES))
                packets, unprocessed = hci.from_binary(
                    bytearray(self.rx_bytes))
                if len(packets) > 0 and len(unprocessed) > 0:
                    self.rx_bytes.clear()
                    self.rx_bytes.extend(unprocessed)
                for pkt in packets:
                    logging.debug(f'RX {pkt.binary.hex(",")}')
                    self.rx_queue.put(pkt)
                    self.rx_bytes.clear()
            except Exception as e:
                # logging.warning(str(e))
                if len(self.rx_bytes) > 0:
                    logging.debug(
                        f'Unhandled HCI bytes: {bytearray(self.rx_bytes).hex(",")}')
                    self.rx_bytes.pop(0)
                pass

    def send_command_wait_response(self, packet: hci.command.CommandPacket, timeout: float = 1, tries: int = 1) -> tuple:
        if self.port == None or not self.port.is_open:
            raise Exception('Port is not open')
        success = False
        resp_payload = None
        while not success and tries > 0:
            tries -= 1
            self.__pause_queue_monitor()
            self.clear_rx_queue()
            logging.debug(f'TX {packet.binary.hex(",")}')
            self.port.write(packet.binary)
            try:
                resp_pkt = self.rx_queue.get(True, timeout)
                if resp_pkt.status != hci.event.HCI_CommandComplete.Status.HCI_SUCCESS \
                        or packet.opcode != resp_pkt.opcode:
                    success = False
                    try:
                        logging.warning(
                            f'Invalid response\n{resp_pkt}')
                    except:
                        pass
                else:
                    success = True
            except:
                success = False
            self.__resume_queue_monitor()
        if success:
            resp_len = resp_pkt.binary[2:3]
            resp_len = int.from_bytes(resp_len, self.LITTLE_ENDIAN)
            if (resp_len > 4):
                resp_payload = resp_pkt.binary[7:]
        return (success, resp_payload)

    def __verify_crc(self, address: int, length: int) -> int:
        """Verify CRC command (Infineon Vendor Specific HCI command)

        Args:
            address (int): Start address
            length (int): Length of data to verify from start address

        Returns:
            int: CRC value
        """
        payload = []
        payload.extend(address.to_bytes(4, self.LITTLE_ENDIAN))
        payload.extend(length.to_bytes(4, self.LITTLE_ENDIAN))
        (success, payload) = self.send_command_wait_response(hci.command.CommandPacket(
            self.OPCODE_VERIFY_CRC, bytearray(payload)))
        if not success:
            raise Exception('Failed to verify CRC')
        return int.from_bytes(payload, self.LITTLE_ENDIAN)

    def open(self, portName: str, baud: int, flow_control: bool = True) -> object:
        """Open the serial port

        Args:
            portName (str): COM port name or device
            baud (int): baud rate
            flow_control (bool): enable RTS/CTS flow control

        Returns:
            object: Serial port object
        """

        # if the port is already open just return
        if self.port and self.port.is_open:
            return

        self.port = serial.Serial(portName, baud, rtscts=flow_control)
        self.port.timeout = self.SERIAL_PORT_RX_TIMEOUT_SECS
        self.port.reset_input_buffer()
        self.port.reset_output_buffer()
        self.rx_queue = queue.Queue()
        self.stop_threads = False
        # The serial port RX thread reads all bytes received and places them in a queue
        threading.Thread(target=self.__serial_port_rx_thread,
                         daemon=True).start()
        # The queue monitor thread clears stray HCI messages if they are not processed for
        # CLEAR_QUEUE_TIMEOUT amount of time
        threading.Thread(target=self.__queue_monitor, daemon=True).start()
        return self.port

    def clear_rx_queue(self):
        """Clear all received HCI messages from the queue
        """
        if self.rx_queue == None:
            return
        with self.rx_queue.mutex:
            self.rx_queue.queue.clear()
            self.rx_bytes.clear()

    def send_hci_reset(self):
        """Send HCI reset and wait for response

        Raises:
            Exception: raise exception if no response
        """
        (success, _) = self.send_command_wait_response(hci.command.HCI_Reset())
        if not success:
            raise Exception('Failed HCI reset')

    def send_download_minidriver(self):
        """Download minidriver command (Infineon Vendor Specific HCI command)

        Raises:
            Exception: raise exception if no response
        """
        (success, _) = self.send_command_wait_response(
            hci.command.CommandPacket(self.OPCODE_DOWNLOAD_MINIDRIVER, bytes()))
        if not success:
            raise Exception('Failed download minidriver')

    def write_ram(self, address: int, data: io.BytesIO, pad: int = FLASH_PAD, verify: bool = False):
        """Write RAM command (Infineon Vendor Specific HCI command)

        Args:
            address (int): Address to write to
            data (io.BytesIO): All bytes to write
            pad (int, optional): Pad byte value. If a write buffer contains all pad bytes,
              it isn't written. Defaults to FLASH_PAD.

        Raises:
            Exception: raise exception if no response
        """
        all_data = list(data.getvalue())
        total_bytes = bytes_left = len(all_data)
        addr = address
        write_len = self.WRITE_RAM_MAX_SIZE
        bytes_written = 0
        while bytes_left > 0:
            if bytes_left > self.WRITE_RAM_MAX_SIZE:
                write_len = self.WRITE_RAM_MAX_SIZE
            else:
                write_len = bytes_left

            write_data = all_data[0:write_len]
            # Check if all bytes are pad bytes, if they are, we dont need to write them
            no_write = write_data.count(pad) == len(write_data)
            success = False
            if no_write:
                success = True
                logging.debug('Pad bytes, dont write')
            else:
                payload = bytearray(addr.to_bytes(4, self.LITTLE_ENDIAN))
                payload.extend(write_data)
                (success, _) = self.send_command_wait_response(
                    hci.command.CommandPacket(self.OPCODE_WRITE_RAM, payload))
            if success:
                if not no_write and verify:
                    # Verify CRC
                    data_crc = zlib.crc32(bytearray(write_data))
                    logging.debug(f'Data CRC: {hex(data_crc)}')
                    read_crc = self.__verify_crc(addr, write_len)
                    logging.debug(f'Read CRC: {hex(read_crc)}')
                    if data_crc != read_crc:
                        raise Exception(
                            f'Write verification failed. {hex(read_crc)} != {hex(data_crc)}')

                all_data = all_data[write_len:]
                bytes_written += write_len
                addr += write_len
                bytes_left -= write_len
                logging.debug(
                    f'write_ram {bytes_written}/{total_bytes} ({round(bytes_written/total_bytes*100, 1)}%)')
            else:
                raise Exception(f'Failed to write to address {hex(addr)}')

    def send_launch_ram(self, address: int):
        """Launch RAM command (Infineon Vendor Specific HCI command)

        Args:
            address (int): address to launch

        Raises:
            Exception: raise exception if no response
        """
        logging.debug(f'Launch RAM {hex(address)}')
        (success, _) = self.send_command_wait_response(hci.command.CommandPacket(
            self.OPCODE_LAUNCH_RAM, address.to_bytes(4, self.LITTLE_ENDIAN)))
        if not success:
            raise Exception('Failed launch RAM')
        time.sleep(self.LAUNCH_RAM_DELAY)

    def send_chip_erase(self, timeout: int = 1):
        """Chip erase command (Infineon Vendor Specific HCI command)

        Args:
            timeout (int, optional): Time to wait for response in seconds. Defaults to 1.

        Raises:
            Exception: raise exception if no response
        """
        (success, _) = self.send_command_wait_response(hci.command.CommandPacket(
            self.OPCODE_CHIP_ERASE, self.ERASE_ALL_FLASH_MAGIC.to_bytes(4, self.LITTLE_ENDIAN)), timeout)
        if not success:
            raise Exception('Failed chip erase')

    def change_baud_rate(self, baud: int):
        """Change device baud rate (Infineon Vendor Specific HCI command)

        Args:
            baud (int): baud rate to change to
        """
        payload = [0, 0]
        payload.extend(baud.to_bytes(4, self.LITTLE_ENDIAN))
        (success, _) = self.send_command_wait_response(hci.command.CommandPacket(
            self.OPCODE_UPDATE_BAUDRATE, bytearray(payload)))
        if not success:
            raise Exception('Failed to update baud rate')
        self.port.baudrate = baud

    def close(self):
        """Close the serial port.
        """
        self.stop_threads = True
        if self.port and self.port.is_open:
            self.port.close()
