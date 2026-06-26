import random
import uuid
import string
from dataclasses import dataclass
from hardware import HardwareProfile


@dataclass
class SMBIOSData:
    model: str
    serial: str
    board_serial: str   # MLB
    system_uuid: str
    rom: str            # 6-byte MAC-like value for ROM


# ─── Serial number tables ─────────────────────────────────────────────────────
# Format: LLLYYWWSSSCC
#   LLL = factory location
#   YY  = year
#   WW  = week
#   SSS = unique identifier
#   CC  = model check digits

FACTORIES = [
    "C02",  # Cork, Ireland (most common MBP)
    "C1C",  # Cork
    "C17",  # Cork
    "F17",  # Foxconn
    "W88",  # Shanghai
    "YM0",  # Hon Hai
    "G8W",  # Quanta Computer
    "C3K",  # Cork
    "C3Q",  # Cork
]

# Valid year/week chars for post-2010 Macs
# Format: year digit + week digits
# Year: C=2010, D=2011, F=2012, G=2013, H=2014, J=2015, K=2016, L=2017, M=2018, N=2019, P=2020, Q=2021, R=2022, S=2023
YEAR_CODES = {
    2010: "C", 2011: "D", 2012: "F", 2013: "G", 2014: "H",
    2015: "J", 2016: "K", 2017: "L", 2018: "M", 2019: "N",
    2020: "P", 2021: "Q", 2022: "R", 2023: "S", 2024: "T",
}

# Week codes (1-52 encoded as base-36 style pairs)
WEEK_CODES = [
    "10","11","12","13","14","15","16","17","18","19",
    "20","21","22","23","24","25","26","27","28","29",
    "30","31","32","33","34","35","36","37","38","39",
    "40","41","42","43","44","45","46","47","48","49",
]

# Check digit suffixes per SMBIOS model
# These are real check digit pairs used by Apple
MODEL_SUFFIXES: dict[str, list[str]] = {
    "MacBookPro8,1":  ["DH2", "DH3", "DH4", "DH5", "DH6", "DN3", "DN4"],
    "MacBookPro9,2":  ["DRV", "DRW", "DRX", "DVH", "DVJ"],
    "MacBookPro11,1": ["FGP", "FGQ", "FGR", "FGS", "FGT", "FH0"],
    "MacBookPro12,1": ["GF1", "GF2", "GF3", "GF4", "GF5", "GF6"],
    "MacBookPro13,1": ["H3Q", "H3R", "H3S", "H3P", "H6L", "H6M"],
    "MacBookPro13,2": ["H3Q", "H3R", "H6L", "H6M", "H6N"],
    "MacBookPro14,1": ["J1G", "J1H", "J1J", "J1K", "J2K"],
    "MacBookPro14,2": ["J1G", "J1H", "J2K", "J2L"],
    "MacBookPro15,1": ["K05", "K06", "K07", "K08", "K09"],
    "MacBookPro15,2": ["K05", "K06", "K07", "K08", "KD9", "KDC"],
    "MacBookPro15,4": ["K05", "K06", "KDC"],
    "MacBookPro16,1": ["N0P", "N0Q", "N0R", "N0S"],
    "MacBookPro16,2": ["N0P", "N0Q", "N0R", "N0S"],
    "MacBookPro18,1": ["P0J", "P0K", "P0L", "P0M"],
    "MacBookPro18,3": ["P0J", "P0K", "P0L", "P0M"],
    "MacBookAir8,1":  ["K05", "K06", "K07", "K08"],
    "MacBookAir8,2":  ["K05", "K06", "KDC"],
    "MacBookAir9,1":  ["N0P", "N0Q", "N0R"],
    "MacBook8,1":     ["G8W", "G8X", "G8Y"],
    "MacBook9,1":     ["H1A", "H1B", "H1C"],
    "iMac17,1":       ["GG7", "GG8", "GG9"],
    "iMac18,3":       ["H0P", "H0Q", "H0R"],
    "iMac19,1":       ["J480","J481","J482"],
    "iMac20,1":       ["N5R", "N5S", "N5T"],
    "iMac21,1":       ["P0J", "P0K"],
    "iMacPro1,1":     ["J174","J175","J176"],
    "MacPro7,1":      ["J172","J173"],
    "Macmini8,1":     ["K0F", "K0G", "K0H"],
    "Macmini9,1":     ["N0R", "N0S"],
}

# MLB (board serial) prefixes per model
MLB_PREFIXES: dict[str, list[str]] = {
    "MacBookPro15,2": ["C02845301GUH", "C028453014NH", "C02V5450HACD"],
    "MacBookPro16,1": ["C02C20470GUH", "C02C20470H8H"],
    "MacBookPro16,2": ["C02C20470GUH", "C02C20470H8H"],
    "MacBookPro18,1": ["C02D50680GUH", "C02D50680H8H"],
    "MacBookPro18,3": ["C02D50680GUH", "C02D50680H8H"],
    "iMac18,3":       ["C02T2500HACD", "C02T2500J9J3"],
    "iMac19,1":       ["C02X2500J9J3", "C02X2500HACD"],
    "iMac20,1":       ["C02Y2500J9J3", "C02Y2500HACD"],
    "iMacPro1,1":     ["C02849302GUH", "C02849302NH3"],
    "MacPro7,1":      ["F5K2500HACD",  "F5K2500J9J3"],
    "Macmini8,1":     ["C07K2500J9J3", "C07K2500HACD"],
}


def _rand_hex(n: int) -> str:
    return "".join(random.choices("0123456789ABCDEF", k=n))


def _rand_upper(n: int) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


def generate_serial(model: str) -> str:
    factory = random.choice(FACTORIES)

    # pick year/week that makes sense for this model generation
    year = random.choice([2018, 2019, 2020, 2021, 2022])
    year_code = YEAR_CODES.get(year, "M")
    week = random.choice(WEEK_CODES)

    unique = _rand_upper(3)

    suffixes = MODEL_SUFFIXES.get(model, ["DH2", "GF1", "K05"])
    suffix = random.choice(suffixes)

    return f"{factory}{year_code}{week}{unique}{suffix}"


def generate_mlb(model: str) -> str:
    prefixes = MLB_PREFIXES.get(model)
    if prefixes:
        prefix = random.choice(prefixes)
        tail = _rand_upper(4)
        return f"{prefix}{tail}"

    # generic fallback: real MLBs are 17 chars
    return f"C02{_rand_upper(8)}HACD{_rand_upper(2)}"


def generate_uuid() -> str:
    return str(uuid.uuid4()).upper()


def generate_rom() -> str:
    # ROM is 6 bytes shown as 12 hex chars, must look like a real MAC
    # First byte must have bit 1 unset (unicast) and bit 0 unset (OUI)
    # Use Apple OUIs: 00:17:f2, 28:cf:e9, 3c:07:54, 8c:85:90, ac:de:48
    apple_ouis = ["0017F2", "28CFE9", "3C0754", "8C8590", "ACDE48", "F0DBE2"]
    oui = random.choice(apple_ouis)
    nic = _rand_hex(6)
    return oui + nic


def generate(profile: HardwareProfile) -> SMBIOSData:
    model = profile.smbios_model or "MacBookPro15,2"
    return SMBIOSData(
        model=model,
        serial=generate_serial(model),
        board_serial=generate_mlb(model),
        system_uuid=generate_uuid(),
        rom=generate_rom(),
    )


if __name__ == "__main__":
    from hardware import scan
    profile = scan()
    data = generate(profile)

    print(f"\n{'─'*55}")
    print(f"  HackMate SMBIOS Generator")
    print(f"{'─'*55}")
    print(f"  Model:        {data.model}")
    print(f"  Serial:       {data.serial}")
    print(f"  Board Serial: {data.board_serial}")
    print(f"  System UUID:  {data.system_uuid}")
    print(f"  ROM:          {data.rom}")
    print(f"{'─'*55}")
    print(f"\n  Paste into config.plist → PlatformInfo → Generic:")
    print(f"    SystemProductName  = {data.model}")
    print(f"    SystemSerialNumber = {data.serial}")
    print(f"    MLB                = {data.board_serial}")
    print(f"    SystemUUID         = {data.system_uuid}")
    print(f"    ROM                = {data.rom}")
    print()
