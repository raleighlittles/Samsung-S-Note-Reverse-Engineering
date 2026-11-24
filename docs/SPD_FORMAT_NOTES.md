# Samsung S Note `.spd` format – working notes

Derived from 6 sample files (30 pages, ~7,100 strokes, 2013-12 → 2014-08).
Status legend: **[OK]** verified (parser asserts / renders correctly),
**[HYP]** hypothesis, **[?]** unknown.

All integers little-endian. "str16" = `u16 nchars` + UTF-16LE chars (no NUL).

## 1. Container **[OK]**

An `.spd` is a plain ZIP (deflate / stored), no encryption.

| member | notes |
|---|---|
| `<uuid>.page` | one per page; handwriting/objects (see §3) |
| `pageIdInfo.dat` | `u16 count`, then `count × str16` page UUIDs – **page order** |
| `note.note` | note-level metadata (§4) |
| `end_tag.bin` | trailer-ish metadata, repeats note UUID + thumbnail name (§4) |
| `media/mediaInfo.dat` | `00 00` when no media, else 34 bytes (not decoded) |
| `media/image0.png` | embedded image (template/background); stored, not deflated |
| `NN_thumbnail_<name>.png` | note thumbnail / template preview (stock image in all 6 samples) |

## 2. Page file layout **[OK]**

```
0x00 u32  objects_off     offset of the object-section header (see below)
0x04 u32  = 104           constant in all samples
0x08 u16  = 1             version?
0x0A u16  flagsA          0x03b5 / 0x0335 / 0x0334 / 0x0314 : presence bits [HYP]
0x0C u16  flagsB          0x1866 / 0x1876                    [?]
0x0E u32  page width      1504 / 1551 / 1570 px (matches note.note "PageWidth")
0x12 str16 page UUID      (36 chars)
     i64  timestamp       µs since Unix epoch (matches PAGE_LAST_EDITED_TIME)
     u32  = 20            [?]
     ...  optional fields: 4×f32 content bbox, template path (str16, e.g.
          ".../files/template_portrait/blank.spd"), pen class name
          (com.samsung.android.sdk.pen.pen.preload.InkPen), ...  [HYP: gated by flags]
     map  {Density: "2.0", PAGE_LAST_EDITED_TIME: "<µs>"}
```
Metadata map block: `u32 size; u8 type(=1); u16 count; entries…` where each entry is
`u16 keylen (incl NUL); ASCII key + NUL; str16 value`.  size counts everything after itself.

Object-section header (at `objects_off`), 24 bytes **[OK]**:
```
u32 = 1
u32 = 16                       length of the following block
u32 ptr                        = offset of the next u32 (objects_off + 20)
u8[4] 01 02 01 00              [?]
u32 = 0
u32 object_count               [OK – equals number of objects parsed]
```
Objects follow immediately and run **exactly to EOF** (verified for all 30 pages).
Empty pages end right after this header.

## 3. Objects **[OK framing]**

```
u8  kind       1 = stroke, 2 = text box (only 1 textbox in all samples)
u8  = 1, u8 = 0   [?]
u32 size       body length
body[size]
```

### Stroke body (kind 1)
```
0x00 u32 = 30                  [?] (0x1e in every sample inspected)
0x04 u32 = 0                   [?]
0x08 u8[5] 01 ae 02 00 00      flags [?]
0x0D f32×4 rect                (left, top, right, bottom) – bbox in page px  [OK]
0x1D u8[5] 01 00 00 00 00      [?]
0x22 u32 plen                  = 8*N + 54  (overstates real payload by 26/22 B)
0x26 payload:
   u8[4] 01 01 01 0b|0f        0x0b = 4 B shorter variant; 0x0f carries an extra u32 (ff ff ff ff) before the final f32 [HYP: colour?]
   u16   N                     number of points                              [OK]
   f32,f32  x0, y0             first point, page px                          [OK]
   (N-1) × (s16 dx, s16 dy)    deltas in 1/32 px, **sign-magnitude** (bit15=sign) [OK]
   f32                          e.g. 0.0997, 0.1326…  [?] (per-stroke scalar; maybe avg speed/pressure)
   (N-1) × s16                  sign-magnitude, smooth, multiples of 4, 0 at duplicate samples [?]
                                (looks like a time delta or pressure-delta series)
   N × u16                      mostly ≈75 (74–82) interleaved with 32-bit-looking
                                pairs (U,V) where U ≡ 75−V (mod 65536)       [?]
   tail: 08 00 | 02 00 00 00 | 00 00 | 01 00 00 00 | f32 (pen size?)         [HYP]
         (0x0f variant: `07 00 …` and an extra `ff ff ff ff` before the f32)
```
Reconstruction: `x_i = x0 + Σ dx/32`, `y_i = y0 + Σ dy/32`. Rendering every stroke as a
black polyline reproduces the handwriting faithfully (see `renders/`).

Observations worth knowing:
* About every 5.33rd sample is a **duplicate point** (dx=dy=0). The (U,V) pairs in the
  last array sit at a constant offset after those duplicates – looks like a resync /
  timestamp marker, but not confirmed.
* Minimum N seen is 6.

### Text box (kind 2) **[partial]**
Only one text box exists in the samples (page 1 of `Note_301213_183101`), 330-byte body:
```
0x00 u32 = 0x54, u32 = 0x1e     [?]  (stroke bodies start 0x1e, 0)
0x08 u8[5] 01 ae 02 20 00       same flag bytes as a stroke, but 0x20 instead of 0x00 [?]
0x0D f32x4 rect                 (36.0, 145.0, 1468.0, 351.0)   [OK - same position/format as strokes]
0x1D u8[5] 01 00 00 00 00       same as strokes
0x22 int map: u8 type=2, u16 count=3, then entries
        (u16 keylen incl NUL, ASCII key + NUL, u32 value)       [OK]
        MainTextbox=1, ModifiedTextbox=1, Type=17
     u32 = 103                  [?] looks like a length, but does not land on an obvious boundary
     ...  four f32 = 5.0 (margins/padding? [HYP]), then a series of attribute records
          (pattern `02 00 01 00 00 00 <4-byte value> 18 00 00 00 <u32 id>`) [?]
     font name: u16 len incl NUL (15) + ASCII "Roboto-Regular" + NUL      [OK]
     tail: ... f32 1.3 (line spacing? [HYP]) ...
```
No text characters appear anywhere in the body (UTF-16 or ASCII), so this looks like an
**empty** text box. Whether text would be stored here, and how, is unknown.

## 4. note.note / end_tag.bin **[partial]**
Both are length-prefixed structures containing: the note UUID (str16), the page-width key
`PageWidth` = `1504`, `NOTE_LAST_INPUT_MODE_KEY`, `NOTE_OPEN_STATE_CHECK_KEY`, template path,
thumbnail file name, and the string `Document for SAMSUNG S-Pen SDK`. Several u32/u64
fields (timestamps in µs, flags) are not yet mapped.

## 5. Open questions (good next steps)
1. Meaning of the `(N-1)×s16` array and the `N×u16` array (timestamps? pressure? tilt?).
   Strategy: find strokes where these differ visibly (pressure-sensitive lines, fast vs.
   slow writing) and correlate with the geometry.
2. Pen type / colour / width: only two variants (0x0b, 0x0f) appear; every stroke renders
   black in the source? Need a sample with coloured/different pens to confirm.
3. Page header flag bits (flagsA/flagsB) and the optional-field gating.
4. Text box & image objects (need samples with images/text of various styles).
5. `media/mediaInfo.dat` and how pages reference `media/image0.png`.

## References

Anthropic. (2026). *Claude* (Sonnet 4.5) [Large language model]. https://claude.ai

