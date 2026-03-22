"""
Minimal CMSIS SVD parser using only stdlib xml.etree.

Extracts peripheral base addresses, register offsets, and field bit ranges.
No external dependencies.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json
import hashlib


@dataclass
class SVDField:
    name: str
    bit_offset: int
    bit_width: int
    description: str = ""
    access: str = "read-write"

    @property
    def mask(self):
        return ((1 << self.bit_width) - 1) << self.bit_offset

    def extract(self, value):
        """Extract this field's value from a register value."""
        return (value & self.mask) >> self.bit_offset

    def format(self, value):
        """Format the extracted field value with context."""
        v = self.extract(value)
        if self.bit_width == 1:
            return f"{self.name}: {v} ({'set' if v else 'clear'})"
        elif self.bit_width <= 4:
            return f"{self.name}: {v:#x} (bits [{self.bit_offset + self.bit_width - 1}:{self.bit_offset}])"
        else:
            return f"{self.name}: {v:#x} ({v}) (bits [{self.bit_offset + self.bit_width - 1}:{self.bit_offset}])"


@dataclass
class SVDRegister:
    name: str
    offset: int
    size: int = 32
    description: str = ""
    access: str = "read-write"
    reset_value: int = 0
    fields: dict = field(default_factory=dict)  # name -> SVDField

    def decode(self, value):
        """Decode a register value into named fields."""
        result = {}
        for fname, f in self.fields.items():
            result[fname] = {
                'value': f.extract(value),
                'bits': f"{f.bit_offset + f.bit_width - 1}:{f.bit_offset}",
                'description': f.description,
            }
        return result

    def format(self, value):
        """Human-readable decode of a register value."""
        lines = [f"{self.name} = {value:#010x}"]
        if self.description:
            lines[0] += f"  ({self.description})"
        for f in sorted(self.fields.values(), key=lambda f: f.bit_offset):
            lines.append(f"  {f.format(value)}")
        return '\n'.join(lines)


@dataclass
class SVDPeripheral:
    name: str
    base_address: int
    description: str = ""
    group_name: str = ""
    registers: dict = field(default_factory=dict)  # name -> SVDRegister

    def register_address(self, reg_name):
        """Absolute address of a register."""
        reg = self.registers.get(reg_name)
        if reg is None:
            raise KeyError(f"No register '{reg_name}' in peripheral '{self.name}'. "
                           f"Available: {', '.join(sorted(self.registers.keys()))}")
        return self.base_address + reg.offset


@dataclass
class SVDDevice:
    name: str
    description: str = ""
    peripherals: dict = field(default_factory=dict)  # name -> SVDPeripheral

    def lookup(self, path):
        """Lookup by dot-notation: 'GPIO.OUT' or 'GPIO.OUT.field_name'."""
        parts = path.split('.')
        if len(parts) < 2:
            raise ValueError(f"Use PERIPHERAL.REGISTER[.FIELD] notation, got '{path}'")

        periph_name = parts[0].upper()
        reg_name = parts[1].upper()

        periph = self.peripherals.get(periph_name)
        if periph is None:
            # Try case-insensitive
            for k, v in self.peripherals.items():
                if k.upper() == periph_name:
                    periph = v
                    break
            if periph is None:
                raise KeyError(f"No peripheral '{periph_name}'. "
                               f"Available: {', '.join(sorted(self.peripherals.keys()))}")

        reg = periph.registers.get(reg_name)
        if reg is None:
            for k, v in periph.registers.items():
                if k.upper() == reg_name:
                    reg = v
                    break
            if reg is None:
                raise KeyError(f"No register '{reg_name}' in '{periph.name}'. "
                               f"Available: {', '.join(sorted(periph.registers.keys()))}")

        addr = periph.base_address + reg.offset

        if len(parts) == 3:
            field_name = parts[2].upper()
            fld = reg.fields.get(field_name)
            if fld is None:
                for k, v in reg.fields.items():
                    if k.upper() == field_name:
                        fld = v
                        break
                if fld is None:
                    raise KeyError(f"No field '{field_name}' in '{periph.name}.{reg.name}'. "
                                   f"Available: {', '.join(sorted(reg.fields.keys()))}")
            return periph, reg, fld, addr

        return periph, reg, None, addr

    def list_peripherals(self):
        """List all peripherals with base addresses."""
        result = []
        for name, p in sorted(self.peripherals.items()):
            result.append({
                'name': p.name,
                'base': f"{p.base_address:#010x}",
                'description': p.description,
                'registers': len(p.registers),
            })
        return result

    def list_registers(self, peripheral_name):
        """List all registers in a peripheral."""
        periph = self.peripherals.get(peripheral_name)
        if periph is None:
            for k, v in self.peripherals.items():
                if k.upper() == peripheral_name.upper():
                    periph = v
                    break
        if periph is None:
            raise KeyError(f"No peripheral '{peripheral_name}'")

        result = []
        for name, r in sorted(periph.registers.items(), key=lambda x: x[1].offset):
            result.append({
                'name': r.name,
                'offset': f"{r.offset:#06x}",
                'address': f"{periph.base_address + r.offset:#010x}",
                'access': r.access,
                'fields': len(r.fields),
                'description': r.description,
            })
        return result


def _text(el, tag, default=""):
    """Get text content of a child element."""
    child = el.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return default


def _int(el, tag, default=0):
    """Get integer content of a child element, handling hex."""
    text = _text(el, tag)
    if not text:
        return default
    text = text.strip().lower()
    if text.startswith('0x') or text.startswith('#'):
        text = text.replace('#', '0x')
        return int(text, 16)
    return int(text)


def parse_svd(svd_path):
    """Parse an SVD file and return an SVDDevice."""
    tree = ET.parse(svd_path)
    root = tree.getroot()

    # Handle namespace if present
    ns = ''
    if root.tag.startswith('{'):
        ns = root.tag.split('}')[0] + '}'

    device = SVDDevice(
        name=_text(root, f'{ns}name', 'Unknown'),
        description=_text(root, f'{ns}description'),
    )

    # Collect all peripherals first for derivedFrom resolution
    peripheral_elements = {}
    for pel in root.findall(f'.//{ns}peripheral'):
        pname = _text(pel, f'{ns}name')
        if pname:
            peripheral_elements[pname] = pel

    # Parse peripherals
    for pname, pel in peripheral_elements.items():
        derived_from = pel.get('derivedFrom')

        periph = SVDPeripheral(
            name=pname,
            base_address=_int(pel, f'{ns}baseAddress'),
            description=_text(pel, f'{ns}description'),
            group_name=_text(pel, f'{ns}groupName'),
        )

        # If derived, copy registers from parent first
        if derived_from and derived_from in device.peripherals:
            parent = device.peripherals[derived_from]
            import copy
            periph.registers = copy.deepcopy(parent.registers)
            if not periph.description:
                periph.description = parent.description

        # Parse registers (may override derived ones)
        _parse_registers(pel, periph, ns)

        device.peripherals[pname] = periph

    return device


def _parse_registers(pel, periph, ns, base_offset=0):
    """Parse registers from a peripheral or cluster element."""
    registers_el = pel.find(f'{ns}registers')
    if registers_el is None:
        return

    for reg_el in registers_el.findall(f'{ns}register'):
        reg = SVDRegister(
            name=_text(reg_el, f'{ns}name'),
            offset=base_offset + _int(reg_el, f'{ns}addressOffset'),
            size=_int(reg_el, f'{ns}size', 32),
            description=_text(reg_el, f'{ns}description'),
            access=_text(reg_el, f'{ns}access', 'read-write'),
            reset_value=_int(reg_el, f'{ns}resetValue'),
        )

        # Parse fields
        fields_el = reg_el.find(f'{ns}fields')
        if fields_el is not None:
            for field_el in fields_el.findall(f'{ns}field'):
                fld = SVDField(
                    name=_text(field_el, f'{ns}name'),
                    bit_offset=_int(field_el, f'{ns}bitOffset',
                                    _int(field_el, f'{ns}lsb')),
                    bit_width=_int(field_el, f'{ns}bitWidth',
                                   _compute_width(field_el, ns)),
                    description=_text(field_el, f'{ns}description'),
                    access=_text(field_el, f'{ns}access', reg.access),
                )
                reg.fields[fld.name] = fld

        periph.registers[reg.name] = reg

    # Handle clusters (register groups with a shared offset)
    for cluster_el in registers_el.findall(f'{ns}cluster'):
        cluster_offset = base_offset + _int(cluster_el, f'{ns}addressOffset')
        cluster_prefix = _text(cluster_el, f'{ns}name', '')

        for reg_el in cluster_el.findall(f'{ns}register'):
            reg = SVDRegister(
                name=f"{cluster_prefix}_{_text(reg_el, f'{ns}name')}" if cluster_prefix else _text(reg_el, f'{ns}name'),
                offset=cluster_offset + _int(reg_el, f'{ns}addressOffset'),
                size=_int(reg_el, f'{ns}size', 32),
                description=_text(reg_el, f'{ns}description'),
                access=_text(reg_el, f'{ns}access', 'read-write'),
                reset_value=_int(reg_el, f'{ns}resetValue'),
            )

            fields_el = reg_el.find(f'{ns}fields')
            if fields_el is not None:
                for field_el in fields_el.findall(f'{ns}field'):
                    fld = SVDField(
                        name=_text(field_el, f'{ns}name'),
                        bit_offset=_int(field_el, f'{ns}bitOffset',
                                        _int(field_el, f'{ns}lsb')),
                        bit_width=_int(field_el, f'{ns}bitWidth',
                                       _compute_width(field_el, ns)),
                        description=_text(field_el, f'{ns}description'),
                        access=_text(field_el, f'{ns}access', reg.access),
                    )
                    reg.fields[fld.name] = fld

            periph.registers[reg.name] = reg


def _compute_width(field_el, ns):
    """Compute bit width from bitRange or lsb/msb if bitWidth not given."""
    # Try bitRange format: [msb:lsb]
    bit_range = _text(field_el, f'{ns}bitRange')
    if bit_range:
        bit_range = bit_range.strip('[]')
        msb, lsb = bit_range.split(':')
        return int(msb) - int(lsb) + 1

    # Try msb/lsb
    msb = _text(field_el, f'{ns}msb')
    lsb = _text(field_el, f'{ns}lsb')
    if msb and lsb:
        return int(msb) - int(lsb) + 1

    return 1  # default to single bit


def load_svd_cached(svd_path, cache_dir=None):
    """Load SVD with optional JSON cache for faster subsequent loads.

    SVD files can be large and slow to parse. This caches the parsed
    result as JSON keyed by the file's hash.
    """
    svd_path = Path(svd_path)
    if cache_dir is None:
        cache_dir = svd_path.parent / '.svd_cache'

    # Check cache
    file_hash = hashlib.md5(svd_path.read_bytes()).hexdigest()[:12]
    cache_file = Path(cache_dir) / f"{svd_path.stem}_{file_hash}.json"

    if cache_file.exists():
        return _load_from_cache(cache_file)

    # Parse and cache
    device = parse_svd(svd_path)
    _save_to_cache(device, cache_file)
    return device


def _save_to_cache(device, cache_file):
    """Serialize device to JSON cache."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    data = {
        'name': device.name,
        'description': device.description,
        'peripherals': {}
    }
    for pname, periph in device.peripherals.items():
        pdata = {
            'base_address': periph.base_address,
            'description': periph.description,
            'registers': {}
        }
        for rname, reg in periph.registers.items():
            rdata = {
                'offset': reg.offset,
                'size': reg.size,
                'description': reg.description,
                'access': reg.access,
                'reset_value': reg.reset_value,
                'fields': {}
            }
            for fname, fld in reg.fields.items():
                rdata['fields'][fname] = {
                    'bit_offset': fld.bit_offset,
                    'bit_width': fld.bit_width,
                    'description': fld.description,
                    'access': fld.access,
                }
            pdata['registers'][rname] = rdata
        data['peripherals'][pname] = pdata

    cache_file.write_text(json.dumps(data))


def _load_from_cache(cache_file):
    """Deserialize device from JSON cache."""
    data = json.loads(cache_file.read_text())

    device = SVDDevice(name=data['name'], description=data.get('description', ''))

    for pname, pdata in data['peripherals'].items():
        periph = SVDPeripheral(
            name=pname,
            base_address=pdata['base_address'],
            description=pdata.get('description', ''),
        )
        for rname, rdata in pdata.get('registers', {}).items():
            reg = SVDRegister(
                name=rname,
                offset=rdata['offset'],
                size=rdata.get('size', 32),
                description=rdata.get('description', ''),
                access=rdata.get('access', 'read-write'),
                reset_value=rdata.get('reset_value', 0),
            )
            for fname, fdata in rdata.get('fields', {}).items():
                reg.fields[fname] = SVDField(
                    name=fname,
                    bit_offset=fdata['bit_offset'],
                    bit_width=fdata['bit_width'],
                    description=fdata.get('description', ''),
                    access=fdata.get('access', 'read-write'),
                )
            periph.registers[rname] = reg
        device.peripherals[pname] = periph

    return device
