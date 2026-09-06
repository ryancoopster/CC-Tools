# Golden device list

Curated devices and their real connectors. **Copy this to
`~/Documents/CC Tools/devices.md`** — that is where CC Tools reads it from.

## What it is for

ConnectCAD ships a database of 2,734 devices, and CC Tools falls back to it.
But that data is uneven: socket naming varies by manufacturer, and 36 rows in
it carry a double space in a socket name. This file is where you pin down how
*your* drawings represent a device, once, so every schematic that uses it comes
out the same.

**Hand the same file to Claude** alongside `JOB-SPEC.md`. Claude reads the
socket names from here and writes circuits against them; the plug-in reads the
same names and builds the sockets. One source, so the two cannot disagree —
which is the whole reason this is markdown and not JSON.

A device that is *not* in this file is exactly where a model would otherwise
invent connectors. When that happens, look the device up properly and add it
here.

## Lookup order

1. A device symbol in the open document — someone drew it, sockets placed
2. Sockets the job lists explicitly
3. **This file**
4. ConnectCAD's shipped database

Stock manufacturer symbol libraries are deliberately not searched. On this
install 345 of the 346 are undownloaded 10-byte placeholders, and the ones that
do arrive are inconsistent with each other.

## Format

A heading naming the device, then a table:

```
## Meyer Sound | TIGRA-L

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN_IN 1 | IN | LAN | EC-6A | L |
```

`Type` is `IN`, `OUT` or `IO`. `Side` is `L` or `R` — inputs conventionally
left, outputs right. Sockets stack down their edge in the order listed.

Physical properties go between the heading and the table, one per line:

```
- Width: 482.6 mm
- Height: 44.45 mm
- Depth: 262.89 mm
- Weight: 3.84 kg
- Power: 30 W
- Rack mounted: yes
- Rack U: 1
```

Write the unit — `mm` or `in`, `kg` or `lb` — because an unlabelled number is
a unit waiting to be guessed wrong. **Rack U is the device's size in rack
units, not where it sits in a rack**; that second thing belongs to an
installation, not to the product. Leave a property out if you do not know it;
do not put a plausible number in.

These map onto ConnectCAD's `EquipItem` record — `Width`/`Height`/`Depth`,
`weight`, `power`, `width_R`, `heightU` — which is where they end up when the
device is placed in a rack.

Columns are matched by **header name**, not position, so you can reorder them
or add your own. Anything that is not a heading followed by a table is ignored,
so write as much prose between entries as you like.

## Devices

Seeded from the Geffen Hall drawing. Whitespace has been normalised — a few
socket names there carried double or trailing spaces, which are invisible on
screen and break the name match.

**Physical properties are filled in only where ConnectCAD's own database had
them — 2 of the 28.** The rest are left blank on purpose rather than filled
with plausible numbers. Fill them in as you look each device up; that is what
this file is for.

### Align Array | AL3

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN_IN | IN | LAN | EC-6A | L |

### Custom | Connector Panel

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| 1-49 | IN | LINE | --- | L |
| 1-49 | OUT | LINE | XLR3F | R |

### Focusrite | REDNET-D16R AES

- Width: 482.6 mm
- Height: 44.45 mm
- Depth: 262.89 mm
- Weight: 3.84 kg
- Power: 30 W
- Rack mounted: yes

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| DANTE 1 | IO | LAN | RJ45 | R |
| DANTE 2 | IO | LAN | RJ45 | R |
| WD_CLK _N | IN | WC | BNC | L |
| WD_CLK_OUT | OUT | WC | BNC | R |
| AES_IN | IN | AES | XLR3M | L |
| AES_OUT | OUT | AES | XLR3F | R |
| SPDIF_IN | IN | AES | RCA | L |
| SPDIF_OUT | OUT | AES | RCA | R |
| AES_IN&OUT 1-8 | IO | AES | DB25M | R |
| AES_IN&OUT 9-16 | IO | AES | DB25M | R |

### Luminex | 10I 10G 2X SFP 1G x8

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN 1 | IO | LAN | RJ45 | R |
| LAN 2 | IO | LAN | RJ45 | R |
| LAN 3 | IO | LAN | RJ45 | R |
| LAN 4 | IO | LAN | RJ45 | R |
| LAN 5 | IO | LAN | RJ45 | R |
| LAN 6 | IO | LAN | RJ45 | R |
| LAN 7 | IO | LAN | RJ45 | R |
| LAN 8 | IO | LAN | RJ45 | R |
| SFP 9 | IO | OPT | LC | R |
| SMP 10 | IO | LAN | DUO-SMF | R |

### Luminex | 10T-IP

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN 8 | IO | LAN | EC-6A | R |
| LAN 6 | IO | LAN | EC-6A | R |
| LAN 5 | IO | LAN | EC-6A | R |
| LAN 4 | IO | LAN | EC-6A | R |
| LAN 3 | IO | LAN | EC-6A | R |
| LAN 2 | IO | LAN | EC-6A | R |
| LAN 7 | IO | LAN | EC-6A | R |
| LAN 1 | IO | LAN | EC-6A | R |

### Luminex | 16I 10G

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN 1 | IO | LAN | RJ45 | R |
| LAN 2 | IO | LAN | RJ45 | R |
| LAN 3 | IO | LAN | RJ45 | R |
| LAN 4 | IO | LAN | RJ45 | R |
| LAN 5 | IO | LAN | RJ45 | R |
| LAN 6 | IO | LAN | RJ45 | R |
| LAN 7 | IO | LAN | RJ45 | R |
| LAN 8 | IO | LAN | RJ45 | R |
| LAN 9 | IO | LAN | RJ45 | R |
| LAN 10 | IO | LAN | RJ45 | R |
| LAN 11 | IO | LAN | RJ45 | R |
| LAN 12 | IO | LAN | RJ45 | R |
| SFP 13 | IO | OPT | DUO-SMF | R |
| SFP 14 | IO | OPT | DUO-SMF | R |
| SFP 15 | IO | OPT | DUO-SMF | R |
| SFP 16 | IO | OPT | DUO-SMF | R |

### Luminex | 30i 10G POE

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN 1 | IO | LAN | RJ45 | R |
| LAN 2 | IO | LAN | RJ45 | R |
| LAN 3 | IO | LAN | RJ45 | R |
| LAN 4 | IO | LAN | RJ45 | R |
| LAN 5 | IO | LAN | RJ45 | R |
| LAN 6 | IO | LAN | RJ45 | R |
| LAN 7 | IO | LAN | RJ45 | R |
| LAN 8 | IO | LAN | RJ45 | R |
| LAN 9 | IO | LAN | RJ45 | R |
| LAN 10 | IO | LAN | RJ45 | R |
| LAN 11 | IO | LAN | RJ45 | R |
| LAN 12 | IO | LAN | RJ45 | R |
| LAN 13 | IO | LAN | RJ45 | R |
| LAN 14 | IO | LAN | RJ45 | R |
| LAN 15 | IO | LAN | RJ45 | R |
| LAN 16 | IO | LAN | RJ45 | R |
| LAN 17 | IO | LAN | RJ45 | R |
| LAN 18 | IO | LAN | RJ45 | R |
| LAN 19 | IO | LAN | RJ45 | R |
| LAN 20 | IO | LAN | RJ45 | R |
| LAN 21 | IO | LAN | RJ45 | R |
| LAN 22 | IO | LAN | RJ45 | R |
| LAN 23 | IO | LAN | RJ45 | R |
| LAN 24 | IO | LAN | RJ45 | R |
| SFP 25 | IO | OPT | LC | R |
| SFP 26 | IO | LAN | SFP | R |
| SFP 27 | IO | LAN | SFP | R |
| SFP 28 | IO | LAN | SFP | R |
| SFP 29 | IO | LAN | SFP | R |
| SFP 30 | IO | LAN | SFP | R |

### Meyer Sound | 2100-LFC

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LINE_IN | IN | LINE | XLR3M | L |
| LINE_THRU | OUT | LINE | XLR3F | R |
| LAN | IN | LAN | EC-6A | L |

### Meyer Sound | Galaxy 408

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| AES_IN A/B | IN | LINE | XLR3M | L |
| LINE_IN B | IN | LINE | XLR3M | L |
| AES_IN C/D | IN | LINE | XLR3M | L |
| LINE_IN D | IN | LINE | XLR3M | L |
| L Sub Top OUT 1 | OUT | LINE | XLR3F | R |
| L Sub Middle OUT 2 | OUT | LINE | XLR3F | R |
| L SUb Bottom OUT 3 | OUT | LINE | XLR3F | R |
| R Sub Top OUT 4 | OUT | LINE | XLR3F | R |
| R Sub Middle OUT 5 | OUT | LINE | XLR3F | R |
| R Sun Bottom OUT 6 | OUT | LINE | XLR3F | R |
| LINE_ OUT 7 | OUT | LINE | XLR3F | R |
| LINE_ OUT 8 | OUT | LINE | XLR3F | R |
| LAN 1 | IO | LAN | RJ45 | R |
| LAN 2 | IO | LAN | RJ45 | R |

### Meyer Sound | Galaxy 816

- Width: 483 mm
- Height: 88 mm
- Depth: 410 mm
- Weight: 7.6 kg
- Rack mounted: yes

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| AES_IN A/B | IN | AES | XLR3M | L |
| LINE_IN B | IN | LINE | XLR3M | L |
| AES_IN C/D | IN | AES | XLR3M | L |
| LINE_IN D | IN | LINE | XLR3M | L |
| AES_IN E/F | IN | AES | XLR3M | L |
| LINE_IN F | IN | LINE | XLR3M | L |
| AES_IN G/H | IN | AES | XLR3M | L |
| LINE_IN H | IN | LINE | XLR3M | L |
| LINE_OUT 1 | OUT | LINE | XLR3F | R |
| LINE_OUT 2 | OUT | LINE | XLR3F | R |
| LINE_OUT 3 | OUT | LINE | XLR3F | R |
| LINE_OUT 4 | OUT | LINE | XLR3F | R |
| LINE_OUT 5 | OUT | LINE | XLR3F | R |
| LINE_OUT 6 | OUT | LINE | XLR3F | R |
| LINE_OUT 7 | OUT | LINE | XLR3F | R |
| LINE_OUT 8 | OUT | LINE | XLR3F | R |
| LINE_OUT 9 | OUT | LINE | XLR3F | R |
| LINE_OUT 10 | OUT | LINE | XLR3F | R |
| LINE_OUT 11 | OUT | LINE | XLR3F | R |
| LINE_OUT 12 | OUT | LINE | XLR3F | R |
| LINE_OUT 13 | OUT | LINE | XLR3F | R |
| LINE_OUT 14 | OUT | LINE | XLR3F | R |
| LINE_OUT 15 | OUT | LINE | XLR3F | R |
| LINE_OUT 16 | OUT | LINE | XLR3F | R |
| LAN 1 | IO | LAN | RJ45 | R |
| LAN 2 | IO | LAN | RJ45 | R |

### Meyer Sound | MPS-488X

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LINE_IN 1 | IN | LINE | XLR3M | L |
| LINE_IN 2 | IN | LINE | XLR3M | L |
| LINE_IN 3 | IN | LINE | XLR3M | L |
| LINE_IN 4 | IN | LINE | XLR3M | L |
| LINE_IN 5 | IN | LINE | XLR3M | L |
| LINE_IN 6 | IN | LINE | XLR3M | L |
| LINE_IN 7 | IN | LINE | XLR3M | L |
| LINE_IN 8 | IN | LINE | XLR3M | L |
| MIDC_OUT 1 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 2 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 3 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 4 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 5 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 6 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 7 | OUT | MIDC | TBLK-5 | R |
| MIDC_OUT 8 | OUT | MIDC | TBLK-5 | R |
| LAN | IO | LAN | RJ45 | R |

### Meyer Sound | TIGRA-L

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN_IN 1 | IN | LAN | EC-6A | L |
| LAN_IN 2 | IN | LAN | EC-6A | L |
| LINE_IN | IN | LINE | XLR3M | L |
| LINE_THRU | OUT | LINE | XLR3F | R |

### Meyer Sound | TIGRA-W

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| Power In | IN | PWR | powerCON TRUE 1 F | L |
| Power Thru | OUT | PWR | powerCon TRUE1 M | R |

### Meyer Sound | ULTRA-X22

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LINE_IN | IN | LINE | XLR3M | L |
| LINE_THRU | OUT | LINE | XLR3M | R |

### Meyer Sound | ULTRA-X40

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LINE_IN | IN | LINE | XLR3M | L |
| LINE_THRU | OUT | LINE | XLR3M | R |

### Meyer Sound | ULTRA-X42

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LINE_IN | IN | LINE | XLR3M | L |
| LINE_THRU | OUT | LINE | XLR3M | R |

### Meyer Sound | UP-4slim

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| MIDC_IN | IN | MIDC | TBLK-5 | L |

### Middle Atlantic | EB1

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| ? | IO | MILAN PRI | EC-6A | R |
| ? | IO | MILAN SEC | EC-6A | R |
| ? | IO | CTL | EC-6A | R |
| ? | IO | MILAN PRI | EC-6A | R |
| ? | IO | MILAN SEC | EC-6A | R |

### Middle Atlantic | UPS-S1000R

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| PWR_IN | IN | PWR | NEMA 5-15P | L |
| PWR_OUT 1 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 2 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 3 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 4 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 5 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 6 | OUT | PWR | NEMA 5-15P | R |

### Radial | POWER-2

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| PWR_IN | IN | PWR | NEMA 5-15P | L |
| PWR_OUT 1 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 2 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 3 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 4 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 5 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 6 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 7 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT 8 | OUT | PWR | NEMA 5-15R | R |
| PWR_OUT Front | OUT | PWR | NEMA 5-15R | R |

### SAI | DB25 to AES XLR B/O

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| AES_I/O | IN | AES | Built In | L |
| AES_IN 1-2 | IN | AES | Built In | L |
| AES_IN 1-2 | IN | AES | Built In | L |
| AES_IN 3-4 | IN | AES | Built In | L |
| AES_IN 3-4 | IN | AES | Built In | L |
| AES_OUT 1-2 | OUT | AES | Built In | R |
| AES_OUT 3-4 | OUT | AES | Built In | R |
| AES_OUT 5-6 | OUT | AES | Built In | R |
| AES_OUT 7-8 | OUT | AES | Built In | R |

### SAI | Powercon "Y"

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| ? | IN | PWR | pCON-W | L |
| ? | OUT | PWR | pCON-B | R |
| ? | OUT | PWR | pCON-B | R |

### Ubiquiti | Cloud Gateway Ultra

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| WAN | IO | LAN | RJ45 | R |
| LAN 1 | IO | LAN | RJ45 | R |
| LAN 2 | IO | LAN | RJ45 | R |
| LAN 3 | IO | LAN | RJ45 | R |
| LAN 4 | IO | LAN | RJ45 | R |

### Ubiquiti | U6 Mesh

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| LAN_IN | IO | LAN | RJ45 | R |

### theatrixx | 5-L21-30 distro

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| L21-30_IN 1 | IN | PWR | L21/30 F | L |
| L21-30_IN 2 | IN | PWR | L21/30 F | L |
| L21-30_IN 3 | IN | PWR | L21/30 F | L |
| L21-30_IN 4 | IN | PWR | L21/30 F | L |
| L21-30_IN 5 | IN | PWR | L21/30 F | L |
| 20A 208v_OUT 1 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 2 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 3 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 4 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 5 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 6 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 7 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 9 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 10 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 11 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 208v_OUT 12 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 120v_OUT 13 | OUT | PWR | pCON grey | R |
| 20A 120v_OUT 14 | OUT | PWR | pCON grey | R |
| 20A 120v_OUT 15 | OUT | PWR | pCON grey | R |
| 20A 208v_OUT 8 | OUT | PWR | powerCON TRUE 1 F | R |
| 20A 120v_OUT 16 | OUT | PWR | pCON grey | R |
| 20A 120v_OUT 17 | OUT | PWR | pCON grey | R |
| 20A 120v_OUT 18 | OUT | PWR | pCON grey | R |

### theatrixx | DGH 21-30 breakout

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| L21-30_IN | IN | PWR | L21/30 F | L |
| 20A 208v_OUT 1 | OUT | PWR | powerCon TRUE1 M | R |
| 20A 208v_OUT 2 | OUT | PWR | powerCon TRUE1 M | R |
| 20A 120v_OUT 1 | OUT | PWR | pCON grey | R |
| 20A 120v_OUT 2 | OUT | PWR | NEMA 5-20R | R |

### theatrixx | L21-30 PD

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| L21-30_IN | IN | PWR | L21/30 F | L |
| 20A 120v_OUT 1A | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 1B | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 2A | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 2B | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 3A | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 3B | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 4A | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 4B | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 5A | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 5B | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 6A | OUT | PWR | NEMA L5-20P | R |
| 20A 120v_OUT 6B | OUT | PWR | NEMA L5-20P | R |

### theatrixx | PB-11

- Width:
- Height:
- Depth:
- Weight:
- Power:
- Rack mounted:
- Rack U:

| Socket | Type | Signal | Connector | Side |
|---|---|---|---|---|
| PWR_IN | IN | PWR | pCON blue | L |
| PWR_OUT 1 | OUT | PWR | pCON | R |
| PWR_OUT 2 | OUT | PWR | pCON | R |
| PWR_OUT 1 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 2 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 3 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 4 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 5 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 6 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 7 | OUT | PWR | NEMA 5-15P | R |
| PWR_OUT 8 | OUT | PWR | NEMA 5-15P | R |
