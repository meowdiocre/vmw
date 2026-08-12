#!/usr/bin/env python3

from pathlib import Path
from uuid import UUID
import argparse, os

parser = argparse.ArgumentParser()
parser.add_argument("-o", "--output", default="smbios.bin")
args = parser.parse_args()

def get_bytes(path):
	try: return Path(path).read_bytes()
	except OSError: return b""

# 1. Table concatenation
data = get_bytes("/sys/firmware/dmi/tables/smbios_entry_point") + get_bytes("/sys/firmware/dmi/tables/DMI")

# 2. Overwrite UUID bytes
# System — UUID - https://www.dmtf.org/sites/default/files/standards/documents/DSP0134_3.9.0.pdf#%5B%7B%22num%22%3A249%2C%22gen%22%3A0%7D%2C%7B%22name%22%3A%22XYZ%22%7D%2C70%2C214%2C0%5D
# - Quote: "If the value is all FFh, the ID is not currently present in the system, but it can be set. If the value is all 00h, the ID is not present in the system."
if raw := get_bytes("/sys/class/dmi/id/product_uuid").strip():
	data = data.replace(UUID(raw.decode()).bytes_le, os.urandom(16)) # ????????-????-????-????-????????????
	#data = data.replace(UUID(raw.decode()).bytes_le, b"\xFF" * 16) # FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF
	#data = data.replace(UUID(raw.decode()).bytes_le, b"\x00" * 16) # 00000000-0000-0000-0000-000000000000

# 3. Overwrite SN strings
for attr in ("board_serial", "chassis_serial", "product_serial"):
	if val := get_bytes(f"/sys/class/dmi/id/{attr}").strip():
		data = data.replace(val, b"To be filled by O.E.M.")

for entry in Path("/sys/firmware/dmi/entries/").glob("17-*/raw"):
	for token in get_bytes(entry)[2:].split(b'\x00'):
		if len(token) == 8 and token.isalnum():
			data = data.replace(token.lower(), b"00000000").replace(token.upper(), b"00000000")

if data:
	Path(args.output).write_bytes(data)
