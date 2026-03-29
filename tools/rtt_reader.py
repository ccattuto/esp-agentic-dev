#!/usr/bin/env python3
"""
rtt_reader.py — SEGGER RTT reader over OpenOCD Tcl interface.

Discovers the RTT control block in target SRAM, then polls the
ring buffers and streams output to stdout or a log file.

Uses mdw/mww commands over the Tcl port — works with any OpenOCD
build, including Espressif's fork which lacks native RTT support.

Runs as a long-lived daemon alongside OpenOCD.

Usage:
    python3 rtt_reader.py [options]
    python3 rtt_reader.py --output .esp-agent/rtt.log
    python3 rtt_reader.py --elf build/project.elf --output .esp-agent/rtt.log
"""

import socket
import struct
import time
import sys
import json
import argparse
import signal
import subprocess
from pathlib import Path


class OpenOCDError(Exception):
    pass


class OpenOCDConnection:
    """Persistent Tcl connection to OpenOCD."""

    TCL_DELIMITER = b'\x1a'

    def __init__(self, host='localhost', port=6666, timeout=30):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
        self.sock = socket.create_connection(
            (self.host, self.port), timeout=self.timeout
        )
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    def command(self, cmd):
        self.sock.sendall((cmd + '\x1a').encode())
        buf = b''
        while not buf.endswith(self.TCL_DELIMITER):
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OpenOCDError("Connection closed")
            buf += chunk
        return buf[:-1].decode(errors='replace').strip()

    def read_memory(self, addr, count):
        """Read count 32-bit words, return list of ints.
        Breaks large reads into batches to avoid Tcl response issues."""
        MAX_WORDS_PER_READ = 64  # 256 bytes per read — benchmark sweet spot
        values = []
        remaining = count
        cur_addr = addr
        while remaining > 0:
            n = min(remaining, MAX_WORDS_PER_READ)
            resp = self.command(f'mdw {cur_addr:#x} {n}')
            for line in resp.splitlines():
                if ':' in line:
                    hex_part = line.split(':', 1)[1].strip()
                    for token in hex_part.split():
                        try:
                            values.append(int(token, 16))
                        except ValueError:
                            pass
            cur_addr += n * 4
            remaining -= n
        return values

    def read_bytes(self, addr, nbytes):
        """Read raw bytes from target memory."""
        # Read word-aligned, then slice
        word_addr = addr & ~3
        prefix = addr - word_addr
        nwords = (prefix + nbytes + 3) // 4
        words = self.read_memory(word_addr, nwords)
        raw = struct.pack(f'<{len(words)}I', *words)
        return raw[prefix:prefix + nbytes]

    def write_u32(self, addr, value):
        self.command(f'mww {addr:#x} {value:#x}')


# ── RTT control block structures ──────────────────────

RTT_MAGIC = b'SEGGER RTT\x00\x00\x00\x00\x00\x00'  # 16 bytes, null-padded
RTT_CB_HEADER_SIZE = 24  # 16 magic + 4 MaxNumUpBuffers + 4 MaxNumDownBuffers
RTT_BUFFER_DESC_SIZE = 24  # name_ptr(4) + buf_ptr(4) + size(4) + WrOff(4) + RdOff(4) + flags(4)


class RTTChannel:
    """Represents one RTT up-channel (target → host)."""

    def __init__(self, index, desc_addr, name_ptr, buf_ptr, buf_size, wr_off, rd_off, flags):
        self.index = index
        self.desc_addr = desc_addr
        self.name_ptr = name_ptr
        self.buf_ptr = buf_ptr
        self.buf_size = buf_size
        self.wr_off = wr_off
        self.rd_off = rd_off
        self.flags = flags
        self.name = None  # resolved later

    def __repr__(self):
        name = self.name or f"ch{self.index}"
        return f"RTTChannel({name}, buf={self.buf_ptr:#x}, size={self.buf_size}, wr={self.wr_off}, rd={self.rd_off})"


class RTTReader:
    """Discovers and polls RTT channels over OpenOCD."""

    def __init__(self, ocd, search_start, search_size,
                 block_id="SEGGER RTT", poll_interval=0.05):
        self.ocd = ocd
        self.search_start = search_start
        self.search_size = search_size
        self.block_id = block_id
        self.poll_interval = poll_interval
        self.cb_addr = None
        self.up_channels = []
        self.down_channels = []

    def find_control_block(self):
        """Scan SRAM for the RTT control block magic signature."""
        magic = self.block_id.encode('ascii')
        # Pad to 16 bytes
        magic = magic + b'\x00' * (16 - len(magic))

        addr = self.search_start
        end = self.search_start + self.search_size
        chunk_words = 256  # 1KB per chunk
        chunk_bytes = chunk_words * 4
        overlap = 16  # overlap to catch magic spanning chunks
        total = end - addr
        last_pct_reported = -10

        log(f"Scanning for RTT control block '{self.block_id}' "
            f"in {self.search_start:#x}–{end:#x} ({total // 1024}KB)...")

        while addr < end:
            nwords = min(chunk_words, (end - addr + 3) // 4)
            try:
                words = self.ocd.read_memory(addr, nwords)
            except OpenOCDError as e:
                log(f"  Read error at {addr:#x}: {e}")
                addr += chunk_bytes - overlap
                continue

            data = struct.pack(f'<{len(words)}I', *words)
            idx = data.find(magic)
            if idx >= 0:
                self.cb_addr = addr + idx
                log(f"  Found control block at {self.cb_addr:#x}")
                return self.cb_addr

            addr += chunk_bytes - overlap
            pct = (addr - self.search_start) * 100 // total
            if pct >= last_pct_reported + 10:
                last_pct_reported = pct
                log(f"  {pct}% scanned...")

        log("  Control block not found.")
        return None

    def read_channel_descriptors(self):
        """Parse the control block header and channel descriptors."""
        if self.cb_addr is None:
            raise OpenOCDError("Control block not found")

        # Read header: 16 bytes magic + MaxNumUpBuffers(4) + MaxNumDownBuffers(4)
        header_words = self.ocd.read_memory(self.cb_addr + 16, 2)
        num_up = header_words[0]
        num_down = header_words[1]

        log(f"  Up channels: {num_up}, Down channels: {num_down}")

        # Parse up-channel descriptors
        self.up_channels = []
        desc_base = self.cb_addr + RTT_CB_HEADER_SIZE

        for i in range(num_up):
            desc_addr = desc_base + i * RTT_BUFFER_DESC_SIZE
            words = self.ocd.read_memory(desc_addr, 6)
            ch = RTTChannel(
                index=i,
                desc_addr=desc_addr,
                name_ptr=words[0],
                buf_ptr=words[1],
                buf_size=words[2],
                wr_off=words[3],
                rd_off=words[4],
                flags=words[5],
            )
            # Try to read channel name
            if ch.name_ptr != 0:
                try:
                    name_bytes = self.ocd.read_bytes(ch.name_ptr, 32)
                    null_idx = name_bytes.find(b'\x00')
                    if null_idx >= 0:
                        name_bytes = name_bytes[:null_idx]
                    ch.name = name_bytes.decode('ascii', errors='replace')
                except OpenOCDError:
                    ch.name = f"ch{i}"
            log(f"  Up[{i}]: {ch}")
            self.up_channels.append(ch)

        # Parse down-channel descriptors (after up channels)
        self.down_channels = []
        desc_base = self.cb_addr + RTT_CB_HEADER_SIZE + num_up * RTT_BUFFER_DESC_SIZE

        for i in range(num_down):
            desc_addr = desc_base + i * RTT_BUFFER_DESC_SIZE
            words = self.ocd.read_memory(desc_addr, 6)
            ch = RTTChannel(
                index=i,
                desc_addr=desc_addr,
                name_ptr=words[0],
                buf_ptr=words[1],
                buf_size=words[2],
                wr_off=words[3],
                rd_off=words[4],
                flags=words[5],
            )
            self.down_channels.append(ch)

        return self.up_channels

    def poll_channel(self, channel):
        """Read new data from an up-channel. Returns bytes."""
        # Re-read the write offset from target (it changes as firmware writes)
        wr_off_addr = channel.desc_addr + 12  # offset of WrOff in descriptor
        wr_words = self.ocd.read_memory(wr_off_addr, 1)
        wr_off = wr_words[0]

        rd_off = channel.rd_off

        if wr_off == rd_off:
            return b''

        # Calculate how much data to read
        if wr_off > rd_off:
            # Contiguous region
            nbytes = wr_off - rd_off
            data = self.ocd.read_bytes(channel.buf_ptr + rd_off, nbytes)
        else:
            # Wrapped: read tail, then head
            tail_len = channel.buf_size - rd_off
            head_len = wr_off
            data = b''
            if tail_len > 0:
                data += self.ocd.read_bytes(channel.buf_ptr + rd_off, tail_len)
            if head_len > 0:
                data += self.ocd.read_bytes(channel.buf_ptr, head_len)

        # Update read offset on the target so firmware knows space is free
        rd_off_addr = channel.desc_addr + 16  # offset of RdOff in descriptor
        self.ocd.write_u32(rd_off_addr, wr_off)
        channel.rd_off = wr_off

        return data

    def stream(self, channel_index=0, output=None):
        """Continuously poll a channel and write output.

        output: file-like object (default: sys.stdout.buffer)
        """
        if channel_index >= len(self.up_channels):
            raise OpenOCDError(
                f"Channel {channel_index} not available "
                f"(only {len(self.up_channels)} up-channels)"
            )

        ch = self.up_channels[channel_index]
        out = output or sys.stdout.buffer

        log(f"Streaming channel {channel_index} ({ch.name or 'unnamed'}), "
            f"poll interval {self.poll_interval * 1000:.0f}ms")

        # Sync: set our local rd_off to the current target value
        rd_words = self.ocd.read_memory(ch.desc_addr + 16, 1)
        ch.rd_off = rd_words[0]

        while True:
            try:
                data = self.poll_channel(ch)
                if data:
                    out.write(data)
                    out.flush()
                else:
                    time.sleep(self.poll_interval)
            except OpenOCDError as e:
                log(f"Connection error: {e}, reconnecting...")
                time.sleep(1)
                try:
                    self.ocd.close()
                    self.ocd.connect()
                    log("Reconnected.")
                except Exception:
                    log("Reconnect failed, retrying...")
                    time.sleep(2)
            except KeyboardInterrupt:
                log("Stopped.")
                break


def log(msg):
    print(f"[rtt] {msg}", file=sys.stderr)


def address_from_elf(elf_path):
    """Extract _SEGGER_RTT symbol address from an ELF file using nm."""
    # Try common toolchain prefixes
    for prefix in ['riscv32-esp-elf-', 'xtensa-esp32-elf-', 'arm-none-eabi-', '']:
        nm = f'{prefix}nm'
        try:
            result = subprocess.run(
                [nm, elf_path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 3 and '_SEGGER_RTT' in parts[2]:
                        return int(parts[0], 16)
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            continue
    return None


def main():
    parser = argparse.ArgumentParser(
        description='RTT reader over OpenOCD Tcl interface',
    )
    parser.add_argument('--host', default='localhost',
                        help='OpenOCD host (default: localhost)')
    parser.add_argument('--port', type=int, default=None,
                        help='OpenOCD Tcl port (default: from config or 6666)')
    parser.add_argument('--channel', type=int, default=0,
                        help='RTT up-channel index (default: 0)')
    parser.add_argument('--poll', type=float, default=0.05,
                        help='Poll interval in seconds (default: 0.05)')
    parser.add_argument('--output', '-o',
                        help='Output file (default: stdout)')
    parser.add_argument('--config',
                        help='Project config JSON (default: esp_target_config.json)')
    parser.add_argument('--search-start', type=lambda x: int(x, 0),
                        default=None,
                        help='SRAM start address for control block search')
    parser.add_argument('--search-size', type=lambda x: int(x, 0),
                        default=None,
                        help='Search range size in bytes')
    parser.add_argument('--block-id', default='SEGGER RTT',
                        help='RTT control block ID string')
    parser.add_argument('--address', '-a', type=lambda x: int(x, 0),
                        default=None,
                        help='Known control block address (skips scan)')
    parser.add_argument('--elf', '-e',
                        help='ELF file to extract control block address from (skips scan)')
    parser.add_argument('--scan-only', action='store_true',
                        help='Find control block and print info, then exit')

    args = parser.parse_args()

    # Resolve config
    search_start = args.search_start
    search_size = args.search_size
    tcl_port = args.port

    # Try to load esp_target_config.json
    config_path = args.config
    if config_path is None:
        for d in [Path('.'), Path(__file__).parent]:
            p = d / 'esp_target_config.json'
            if p.exists():
                config_path = str(p)
                break

    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            project_cfg = json.load(f)

        # Resolve chip config for SRAM range
        config_dir = Path(config_path).parent
        chip_path = config_dir / project_cfg.get('chip', '')
        if chip_path.exists():
            with open(chip_path) as f:
                chip = json.load(f)
            sram = chip.get('memory', {}).get('sram', {})
            if search_start is None and sram:
                search_start = int(sram.get('start', '0x20000000'), 0)
            if search_size is None and sram:
                search_size = int(sram.get('size', '0x10000'), 0)

        if tcl_port is None:
            tcl_port = project_cfg.get('openocd', {}).get('tcl_port', 6666)

        log(f"Config: {config_path}")
    else:
        if args.config:
            log(f"Warning: config not found: {args.config}")


    if search_start is None:
        search_start = 0x20000000  # generic default
    if search_size is None:
        search_size = 0x10000
    if tcl_port is None:
        tcl_port = 6666

    # Connect to OpenOCD
    ocd = OpenOCDConnection(host=args.host, port=tcl_port)
    try:
        ocd.connect()
    except Exception as e:
        log(f"Cannot connect to OpenOCD at {args.host}:{tcl_port}: {e}")
        sys.exit(1)

    log(f"Connected to OpenOCD at {args.host}:{tcl_port}")

    # Create reader
    reader = RTTReader(
        ocd,
        search_start=search_start,
        search_size=search_size,
        block_id=args.block_id,
        poll_interval=args.poll,
    )

    # Find control block
    if args.address is not None:
        reader.cb_addr = args.address
        log(f"Using provided control block address: {args.address:#x}")
    elif args.elf:
        addr = address_from_elf(args.elf)
        if addr is None:
            log(f"Could not find _SEGGER_RTT symbol in {args.elf}")
            ocd.close()
            sys.exit(1)
        reader.cb_addr = addr
        log(f"Control block address from ELF: {addr:#x}")
    else:
        cb_addr = reader.find_control_block()
        if cb_addr is None:
            log("RTT control block not found. Is the firmware running with RTT initialized?")
            log("Hint: use --elf build/project.elf or --address 0x... to skip scanning.")
            ocd.close()
            sys.exit(1)

    # Parse channels
    reader.read_channel_descriptors()

    if args.scan_only:
        log("Scan complete.")
        ocd.close()
        return

    # Open output
    output = None
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            mtime = output_path.stat().st_mtime
            ts = time.strftime('%Y-%m-%dT%H-%M-%S', time.localtime(mtime))
            rotated = output_path.with_name(
                f"{output_path.stem}.{ts}{output_path.suffix}"
            )
            output_path.rename(rotated)
            log(f"Rotated previous log to {rotated.name}")
        output = open(output_path, 'wb')
        log(f"Writing to {output_path}")

    # Handle SIGTERM gracefully
    def handle_signal(signum, frame):
        log("Terminated.")
        if output:
            output.close()
        ocd.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)

    # Stream
    try:
        reader.stream(channel_index=args.channel, output=output)
    finally:
        if output:
            output.close()
        ocd.close()


if __name__ == '__main__':
    main()
