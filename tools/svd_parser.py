"""
Minimal CMSIS SVD parser using only stdlib xml.etree.

Extracts peripheral base addresses, register offsets, and field bit ranges.
No required external dependencies; install defusedxml for hardened XML parsing.
"""

import copy
import json
import hashlib
import os
import re
import tempfile
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Use defusedxml when available to guard against XXE / entity expansion attacks.
# Install via: pip install defusedxml
try:
    import defusedxml.ElementTree as _ET_safe
    _SAFE_PARSE = _ET_safe.parse
except ImportError:
    _ET_safe = None
    _SAFE_PARSE = None

_MAX_DIM = 1024  # safety cap on register/cluster array expansion


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
    """Get integer content of a child element, handling hex/binary/decimal.

    Supports:
      - 0x… / 0X…  → hexadecimal
      - #…          → CMSIS-SVD binary literal (e.g. #01101001 → 105)
      - plain digits → decimal
    """
    text = _text(el, tag)
    if not text:
        return default
    text = text.strip().lower()
    try:
        if text.startswith('0x'):
            return int(text, 16)
        if text.startswith('#'):
            return int(text[1:], 2)
        return int(text, 0)
    except ValueError:
        tag_local = tag.split('}')[-1]
        raise ValueError(f"Cannot parse integer from <{tag_local}>: {text!r}")


def _parse_xml_safe(svd_path):
    """Parse SVD XML, protecting against entity expansion (XXE / Billion Laughs).

    Uses defusedxml when installed.  Falls back to stdlib after checking that
    the file does not contain a DOCTYPE or ENTITY declaration.
    """
    if _SAFE_PARSE is not None:
        return _SAFE_PARSE(svd_path).getroot()

    # Stdlib fallback: reject any file that declares a DTD/entity.
    raw = Path(svd_path).read_bytes()
    if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
        raise ValueError(
            f"SVD file '{svd_path}' contains a DOCTYPE or ENTITY declaration. "
            "Install defusedxml to parse such files safely: pip install defusedxml"
        )
    return ET.parse(svd_path).getroot()


def parse_svd(svd_path):
    """Parse an SVD file and return an SVDDevice."""
    root = _parse_xml_safe(svd_path)

    # Handle namespace if present
    ns = ''
    if root.tag.startswith('{'):
        close = root.tag.find('}')
        if close == -1:
            raise ValueError(
                f"Malformed XML namespace in root tag: {root.tag!r}"
            )
        ns = root.tag[:close + 1]

    device = SVDDevice(
        name=_text(root, f'{ns}name', 'Unknown'),
        description=_text(root, f'{ns}description'),
    )

    # Collect all peripheral elements
    peripheral_elements = {}
    for pel in root.findall(f'.//{ns}peripheral'):
        pname = _text(pel, f'{ns}name')
        if pname:
            peripheral_elements[pname] = pel

    # Process peripherals in dependency order: resolve derivedFrom even when a
    # derived peripheral appears before its parent in the XML.  Iterate until no
    # more can be resolved (handles chains: A←B←C).
    pending = dict(peripheral_elements)
    for _ in range(len(pending) + 1):
        if not pending:
            break
        resolved_this_pass = [
            pname for pname, pel in list(pending.items())
            if not pel.get('derivedFrom') or pel.get('derivedFrom') in device.peripherals
        ]
        for pname in resolved_this_pass:
            _process_peripheral(pname, pending.pop(pname), device, ns)
        if not resolved_this_pass:
            break  # no progress — remaining derivedFrom targets are missing

    # Warn and add any remaining unresolved peripherals without parent registers
    for pname, pel in pending.items():
        derived_from = pel.get('derivedFrom')
        warnings.warn(
            f"Peripheral '{pname}' derives from '{derived_from}' which was not found; "
            "its registers may be incomplete.",
            stacklevel=2,
        )
        _process_peripheral(pname, pel, device, ns)

    return device


def _process_peripheral(pname, pel, device, ns):
    """Build one SVDPeripheral from its XML element and add it to device."""
    derived_from = pel.get('derivedFrom')
    periph = SVDPeripheral(
        name=pname,
        base_address=_int(pel, f'{ns}baseAddress'),
        description=_text(pel, f'{ns}description'),
        group_name=_text(pel, f'{ns}groupName'),
    )

    if derived_from and derived_from in device.peripherals:
        parent = device.peripherals[derived_from]
        periph.registers = copy.deepcopy(parent.registers)
        if not periph.description:
            periph.description = parent.description

    _parse_registers(pel, periph, ns)
    device.peripherals[pname] = periph


def _parse_registers(pel, periph, ns, base_offset=0):
    """Parse registers from a peripheral element (finds <registers> wrapper)."""
    registers_el = pel.find(f'{ns}registers')
    if registers_el is None:
        return
    _parse_register_block(registers_el, periph, ns, base_offset, "")


def _parse_register_block(block_el, periph, ns, base_offset, name_prefix):
    """Parse <register> and <cluster> children directly from block_el."""
    for reg_el in block_el.findall(f'{ns}register'):
        for reg in _instantiate_registers(reg_el, ns, base_offset, name_prefix):
            if reg.name in periph.registers:
                warnings.warn(
                    f"Duplicate register name '{reg.name}' in peripheral "
                    f"'{periph.name}'; later definition overwrites earlier.",
                    stacklevel=2,
                )
            periph.registers[reg.name] = reg

    for cluster_el in block_el.findall(f'{ns}cluster'):
        _instantiate_clusters(cluster_el, periph, ns, base_offset, name_prefix)


def _instantiate_clusters(cluster_el, periph, ns, base_offset, name_prefix):
    """Instantiate a cluster, handling dim arrays and recursive nesting."""
    cluster_name = _text(cluster_el, f'{ns}name')
    cluster_offset = _int(cluster_el, f'{ns}addressOffset')
    dim = _int(cluster_el, f'{ns}dim', 0)

    if dim > 0:
        if dim > _MAX_DIM:
            raise ValueError(
                f"Cluster '{cluster_name}' <dim> {dim} exceeds safety limit {_MAX_DIM}"
            )
        dim_increment = _int(cluster_el, f'{ns}dimIncrement', 0)
        if dim_increment <= 0:
            raise ValueError(
                f"Cluster '{cluster_name}' has dim={dim} but dimIncrement={dim_increment}; "
                "all instances would share the same address"
            )
        indices = _expand_dim_indices(_text(cluster_el, f'{ns}dimIndex'), dim)
        for i, idx in enumerate(indices):
            inst_name = cluster_name.replace('%s', idx)
            if inst_name == cluster_name:
                inst_name = f"{cluster_name}{idx}"
            full_prefix = f"{name_prefix}_{inst_name}" if name_prefix else inst_name
            inst_offset = base_offset + cluster_offset + i * dim_increment
            _parse_register_block(cluster_el, periph, ns, inst_offset, full_prefix)
    else:
        full_prefix = f"{name_prefix}_{cluster_name}" if name_prefix else cluster_name
        _parse_register_block(cluster_el, periph, ns,
                              base_offset + cluster_offset, full_prefix)


def _compute_width(field_el, ns):
    """Compute bit width from bitRange or lsb/msb if bitWidth not given."""
    # Try bitRange format: [msb:lsb]
    bit_range = _text(field_el, f'{ns}bitRange')
    if bit_range:
        bit_range = bit_range.strip('[]')
        parts = bit_range.split(':')
        if len(parts) != 2:
            raise ValueError(f"Malformed <bitRange>: {bit_range!r}")
        msb, lsb = int(parts[0].strip()), int(parts[1].strip())
        if msb < lsb:
            raise ValueError(f"<bitRange> has msb ({msb}) < lsb ({lsb})")
        return msb - lsb + 1

    # Try msb/lsb
    msb_text = _text(field_el, f'{ns}msb')
    lsb_text = _text(field_el, f'{ns}lsb')
    if msb_text and lsb_text:
        msb, lsb = int(msb_text), int(lsb_text)
        if msb < lsb:
            raise ValueError(f"<msb> ({msb}) < <lsb> ({lsb})")
        return msb - lsb + 1

    return 1  # default to single bit


def _collect_field_templates(reg_el, ns, default_access):
    """Collect field definitions so we can clone them per register instance."""
    templates = []
    seen_names = set()
    fields_el = reg_el.find(f'{ns}fields')
    if fields_el is None:
        return templates
    for field_el in fields_el.findall(f'{ns}field'):
        fname = _text(field_el, f'{ns}name')
        if fname in seen_names:
            warnings.warn(
                f"Duplicate field name '{fname}' in register; "
                "later definition overwrites earlier.",
                stacklevel=2,
            )
        seen_names.add(fname)
        lsb = _int(field_el, f'{ns}lsb', None)
        bit_offset = _int(field_el, f'{ns}bitOffset', lsb if lsb is not None else 0)
        bit_width = _int(field_el, f'{ns}bitWidth', _compute_width(field_el, ns))
        if bit_width <= 0:
            raise ValueError(
                f"Field '{fname}' has invalid bit_width={bit_width}"
            )
        templates.append({
            'name': fname,
            'bit_offset': bit_offset,
            'bit_width': bit_width,
            'description': _text(field_el, f'{ns}description'),
            'access': _text(field_el, f'{ns}access', default_access),
        })
    return templates


def _expand_dim_indices(index_text, dim):
    """Expand dimIndex text (e.g. '0-3' or 'CH0,CH1') into a list."""
    if not index_text:
        return [str(i) for i in range(dim)]

    indices = []
    for token in index_text.replace(' ', '').split(','):
        if not token:
            continue
        # Use regex to correctly match ranges including negative starts (e.g. "-2-3").
        m = re.match(r'^(-?\d+)-(-?\d+)$', token)
        if m:
            start_i = int(m.group(1))
            end_i = int(m.group(2))
            step = 1 if end_i >= start_i else -1
            for val in range(start_i, end_i + step, step):
                indices.append(str(val))
        else:
            indices.append(token)

    if len(indices) != dim:
        return [str(i) for i in range(dim)]
    return indices


def _instantiate_registers(reg_el, ns, base_offset, name_prefix=""):
    """Instantiate a register element, expanding any dim/dimIndex entries."""
    base_name = _text(reg_el, f'{ns}name')
    description = _text(reg_el, f'{ns}description')
    size = _int(reg_el, f'{ns}size', 32)
    access = _text(reg_el, f'{ns}access', 'read-write')
    reset_value = _int(reg_el, f'{ns}resetValue')
    base_addr = base_offset + _int(reg_el, f'{ns}addressOffset')

    field_templates = _collect_field_templates(reg_el, ns, access)
    dim = _int(reg_el, f'{ns}dim', 0)

    if dim > 0:
        if dim > _MAX_DIM:
            raise ValueError(
                f"Register '{base_name}' <dim> {dim} exceeds safety limit {_MAX_DIM}"
            )
        default_increment = size // 8 if size > 0 else 4
        dim_increment = _int(reg_el, f'{ns}dimIncrement', default_increment)
        if dim_increment <= 0:
            raise ValueError(
                f"Register '{base_name}' has dim={dim} but dimIncrement={dim_increment}; "
                "all instances would share the same address"
            )
        indices = _expand_dim_indices(_text(reg_el, f'{ns}dimIndex'), dim)
        registers = []
        for i, idx in enumerate(indices):
            name = base_name.replace('%s', idx)
            if name == base_name:
                name = f"{base_name}{idx}"
            if name_prefix:
                name = f"{name_prefix}_{name}"
            desc = description.replace('%s', idx) if description else ""
            reg = SVDRegister(
                name=name,
                offset=base_addr + i * dim_increment,
                size=size,
                description=desc,
                access=access,
                reset_value=reset_value,
            )
            for tmpl in field_templates:
                reg.fields[tmpl['name']] = SVDField(**tmpl)
            registers.append(reg)
        return registers

    # Non-dim register
    name = base_name
    if name_prefix:
        name = f"{name_prefix}_{name}"
    reg = SVDRegister(
        name=name,
        offset=base_addr,
        size=size,
        description=description,
        access=access,
        reset_value=reset_value,
    )
    for tmpl in field_templates:
        reg.fields[tmpl['name']] = SVDField(**tmpl)
    return [reg]


def load_svd_cached(svd_path, cache_dir=None):
    """Load SVD with optional JSON cache for faster subsequent loads.

    SVD files can be large and slow to parse. This caches the parsed
    result as JSON keyed by the file's hash.
    """
    svd_path = Path(svd_path)
    if cache_dir is None:
        cache_dir = svd_path.parent / '.svd_cache'

    # Bump cache_version whenever the serialised format changes so that stale
    # caches are automatically invalidated.
    cache_version = "v3"
    file_hash = hashlib.md5(svd_path.read_bytes()).hexdigest()[:12]
    cache_file = Path(cache_dir) / f"{svd_path.stem}_{cache_version}_{file_hash}.json"

    if cache_file.exists():
        try:
            return _load_from_cache(cache_file)
        except (ValueError, KeyError, TypeError) as e:
            warnings.warn(
                f"SVD cache '{cache_file}' is corrupt and will be regenerated: {e}",
                stacklevel=2,
            )
            cache_file.unlink(missing_ok=True)

    device = parse_svd(svd_path)
    _save_to_cache(device, cache_file)
    return device


def _save_to_cache(device, cache_file):
    """Serialize device to JSON cache (written atomically)."""
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

    # Atomic write: temp file in same directory + rename.
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=cache_file.parent, prefix='.svd_cache_tmp_', suffix='.json'
    )
    try:
        with os.fdopen(tmp_fd, 'w') as f:
            json.dump(data, f)
        Path(tmp_path).replace(cache_file)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_from_cache(cache_file):
    """Deserialize device from JSON cache with type validation."""
    try:
        data = json.loads(cache_file.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"Unreadable SVD cache: {e}") from e

    if not isinstance(data, dict) or 'name' not in data or 'peripherals' not in data:
        raise ValueError("Invalid SVD cache structure")

    device = SVDDevice(
        name=str(data['name']),
        description=str(data.get('description', '')),
    )

    for pname, pdata in data['peripherals'].items():
        base_address = pdata['base_address']
        if not isinstance(base_address, int):
            raise TypeError(
                f"Cache: peripheral '{pname}' base_address must be int, got {base_address!r}"
            )
        periph = SVDPeripheral(
            name=str(pname),
            base_address=base_address,
            description=str(pdata.get('description', '')),
        )
        for rname, rdata in pdata.get('registers', {}).items():
            offset = rdata['offset']
            if not isinstance(offset, int):
                raise TypeError(
                    f"Cache: register '{rname}' offset must be int, got {offset!r}"
                )
            reg = SVDRegister(
                name=str(rname),
                offset=offset,
                size=int(rdata.get('size', 32)),
                description=str(rdata.get('description', '')),
                access=str(rdata.get('access', 'read-write')),
                reset_value=int(rdata.get('reset_value', 0)),
            )
            for fname, fdata in rdata.get('fields', {}).items():
                bit_offset = fdata['bit_offset']
                bit_width = fdata['bit_width']
                if not isinstance(bit_offset, int) or bit_offset < 0:
                    raise TypeError(
                        f"Cache: field '{fname}' bit_offset must be a non-negative int"
                    )
                if not isinstance(bit_width, int) or bit_width <= 0:
                    raise TypeError(
                        f"Cache: field '{fname}' bit_width must be a positive int"
                    )
                reg.fields[fname] = SVDField(
                    name=str(fname),
                    bit_offset=bit_offset,
                    bit_width=bit_width,
                    description=str(fdata.get('description', '')),
                    access=str(fdata.get('access', 'read-write')),
                )
            periph.registers[rname] = reg
        device.peripherals[pname] = periph

    return device
