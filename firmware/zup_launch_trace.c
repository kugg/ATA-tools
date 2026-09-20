/* SPDX-License-Identifier: BSD-3-Clause
 *
 * Bounded host-side semantic trace of the SIP resident launch validator,
 * setup, and dispatcher.
 *
 * Offline reference model only. It never executes firmware, never casts
 * guest values to host pointers, never makes memory executable, never
 * mutates guest memory, never decompresses, and performs no network or
 * device I/O. It reads one exact 512 KiB reconstructed bank from stdin
 * and emits fixed numeric trace lines to stdout.
 *
 * Address units (matching docs/firmware-analysis.md and the MIPS-X report):
 * - bank_offset: byte offset into the 512 KiB bank file.
 * - byte_address: absolute byte address used by firmware loads/stores.
 * - word_pc: architectural MIPS-X word address (byte address / 4).
 *   Memory pointers are byte-addressed; jspci PCs are word-addressed.
 * - Branch target formula is PC + 8 + displacement*4. Ordinary branch and
 *   jump delay slots always execute; squash-branch slots execute only
 *   when taken.
 *
 * Recovered layout:
 * - Validator source [0x7f9fc,0x7faf8) is 63 words, copied by setup to
 *   low RAM [0x0007fe00,0x0007fefc), then called via word PC 0x1ff80.
 *   Setup [0x7fccc,0x7fd20) is 21 words: it builds runtime source
 *   0x0cfff9fc (bank 0x7f9fc), destination 0x0007fe00, count 63, derives
 *   word PC 0x1ff80 as 0x7fe00 >> 2, copies, then calls with link r31
 *   while clearing r26 in the delay slot.
 * - Dispatcher [0x7fd18,0x7ff80) is 154 words; setup overlaps it at
 *   0x7fd18 and 0x7fd1c to load the selected header table pointer and
 *   count. All decode without unknown opcodes.
 * - Validator checks staged section header at bank 0x40000: magic
 *   0x12340004, stored XOR, four descriptors, seed 0xdeadbeef. Match
 *   selects runtime header 0x0cfc0100 (bank 0x40100, table 0x0cfc0110,
 *   27 records, final r10=0x100). Mismatch selects 0x0cff0000
 *   (bank 0x70000, table 0x0cff6ee0, 18 records, final r10=0).
 *   A magic mismatch takes a path that depends on incoming r10, which
 *   is not statically established; this model reports it as an explicit
 *   unsupported marker status and never guesses.
 * - The validator may perform up to two conditional stores through r27
 *   (at 0x7fa6c and 0x7faac). Those stores are not modeled here; only
 *   the header selection is traced.
 *
 * Dispatcher semantics (all directly decoded):
 * - 1: copy field3 words from field1 (runtime source) to field2 (byte
 *   destination). Handler at 0x7fddc; count zero skips the loop.
 * - 2: zero field2 words at field1 (byte destination). Handler at
 *   0x7fe30; count zero skips the loop.
 * - 3: load field1 into r13, then terminal unlinked jspci r13,+0x0,r0.
 *   All known tables end with exactly one type 3; count exhaustion
 *   would fall through into the type-1 handler with a one-past-end
 *   pointer, so the terminal is part of the table contract. The field
 *   is passed unchanged; low word-PC maps to the type-9 code start
 *   while the preserved 0x40000000 tag has unknown CPU/platform
 *   meaning and is never masked or interpreted here.
 * - 4: linked call to field1 through r13 with link r31, saving and
 *   restoring r6, r7, r10, r11, then resuming dispatch. Traced as an
 *   opaque call event; loaded registers are not claimed to survive it.
 * - 5/6/7/8/9/0xa/0xb/0xc: load field1 into
 *   r24/r25/r23/r4/r5/r28/r29/r19 in the first always-executed delay
 *   slot of the branch back to the dispatcher continuation.
 * - 0xd: read four field2-length blocks at 16-byte strides. With
 *   B=field1, L=field2, N=floor(L/16), exact read addresses are
 *   B+16*i, B+L+16*i, B+2*L+16*i, B+3*L+16*i for 0<=i<N, loaded into
 *   r0 (discarded). Purpose unknown; traced only as reads, never as a
 *   proven cache or mode operation. No known table invokes it.
 *
 * Unknowns remain explicit statuses/events, never invented behavior.
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ZLT_BANK_BYTES ((size_t)0x80000)
#define ZLT_RUNTIME_BASE_DEFAULT ((uint32_t)0x0CF80000u)
#define ZLT_RECORD_BYTES ((uint32_t)16u)
#define ZLT_MAX_RECORDS ((uint32_t)256u)
#define ZLT_SECTION_OFFSET ((uint32_t)0x40000u)
#define ZLT_SECTION_MAGIC ((uint32_t)0x12340004u)
#define ZLT_CHECKSUM_SEED ((uint32_t)0xDEADBEEFu)
#define ZLT_NUM_DESCRIPTORS ((uint32_t)4u)
#define ZLT_MAIN_HEADER_OFFSET ((uint32_t)0x40100u)
#define ZLT_MAIN_TABLE_OFFSET ((uint32_t)0x40110u)
#define ZLT_MAIN_TABLE_ADDRESS ((uint32_t)0x0CFC0110u)
#define ZLT_MAIN_HEADER_ADDRESS ((uint32_t)0x0CFC0100u)
#define ZLT_MAIN_COUNT ((uint32_t)27u)
#define ZLT_AUX_HEADER_OFFSET ((uint32_t)0x70000u)
#define ZLT_AUX_TABLE_OFFSET ((uint32_t)0x76EE0u)
#define ZLT_AUX_TABLE_ADDRESS ((uint32_t)0x0CFF6EE0u)
#define ZLT_AUX_HEADER_ADDRESS ((uint32_t)0x0CFF0000u)
#define ZLT_AUX_COUNT ((uint32_t)18u)

typedef enum {
    ZLT_OK = 0,
    ZLT_ERR_INPUT = 1,
    ZLT_ERR_BANK_SIZE = 2,
    ZLT_ERR_HEADER_OFFSET = 3,
    ZLT_ERR_TABLE_ADDRESS = 4,
    ZLT_ERR_COUNT = 5,
    ZLT_ERR_DESCRIPTOR = 6,
    ZLT_ERR_MARKER = 7,
    ZLT_ERR_UNKNOWN_TYPE = 8,
    ZLT_ERR_MISSING_TERMINAL = 9,
    ZLT_ERR_NONTERMINAL_TYPE3 = 10,
    ZLT_ERR_OVERFLOW = 11,
    ZLT_ERR_TRUNCATED = 12,
    ZLT_ERR_CALLBACK = 13,
    ZLT_ERR_ARGS = 14
} zlt_status;

typedef enum {
    ZLT_EV_VALIDATOR = 0,
    ZLT_EV_HEADER = 1,
    ZLT_EV_COPY = 2,
    ZLT_EV_ZERO = 3,
    ZLT_EV_REG = 4,
    ZLT_EV_CALL = 5,
    ZLT_EV_TYPE_D = 6,
    ZLT_EV_TERMINAL = 7
} zlt_evtype;

typedef struct {
    zlt_evtype kind;
    uint32_t index;
    uint32_t bank_offset;
    uint32_t rec_type;
    uint32_t field1;
    uint32_t field2;
    uint32_t field3;
    uint32_t reg;
    uint64_t byte_count;
    uint64_t blocks;
    uint32_t header_offset;
    uint32_t header_address;
    uint32_t table_offset;
    uint32_t table_address;
    uint32_t record_count;
    uint32_t field0;
    uint32_t header_field3;
    int selection_is_main;
    uint32_t stored;
    uint32_t calculated;
    uint32_t src_bank_offset;
    int src_mapped;
} zlt_event;

typedef int (*zlt_cb)(const zlt_event *ev, void *ctx);

static uint32_t zlt_be32(const unsigned char *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

static int zlt_read_u32(const unsigned char *bank, size_t len, uint32_t off,
                        uint32_t *out)
{
    uint64_t end;
    if (bank == NULL || out == NULL) {
        return -1;
    }
    if (len != ZLT_BANK_BYTES) {
        return -1;
    }
    if (off % 4u != 0u) {
        return -1;
    }
    end = (uint64_t)off + 4u;
    if (end > (uint64_t)len) {
        return -1;
    }
    *out = zlt_be32(bank + off);
    return 0;
}

static int zlt_addr_in_bank(uint32_t addr, uint32_t base, uint32_t *off_out)
{
    uint64_t base_end;
    if (off_out != NULL) {
        *off_out = 0u;
    }
    base_end = (uint64_t)base + (uint64_t)ZLT_BANK_BYTES;
    if ((uint64_t)addr < (uint64_t)base) {
        return 0;
    }
    if ((uint64_t)addr >= base_end) {
        return 0;
    }
    if (off_out != NULL) {
        *off_out = addr - base;
    }
    return 1;
}

static zlt_status zlt_validate_section(const unsigned char *bank, size_t len,
                                       uint32_t *stored_out,
                                       uint32_t *calc_out)
{
    uint32_t magic = 0u;
    uint32_t stored = 0u;
    uint32_t calc = ZLT_CHECKSUM_SEED;
    uint32_t i;
    if (bank == NULL || stored_out == NULL || calc_out == NULL) {
        return ZLT_ERR_INPUT;
    }
    if (len != ZLT_BANK_BYTES) {
        return ZLT_ERR_BANK_SIZE;
    }
    if (zlt_read_u32(bank, len, ZLT_SECTION_OFFSET, &magic) != 0) {
        return ZLT_ERR_DESCRIPTOR;
    }
    if (magic != ZLT_SECTION_MAGIC) {
        return ZLT_ERR_MARKER;
    }
    if (zlt_read_u32(bank, len, ZLT_SECTION_OFFSET + 4u, &stored) != 0) {
        return ZLT_ERR_DESCRIPTOR;
    }
    for (i = 0u; i < ZLT_NUM_DESCRIPTORS; i++) {
        uint32_t desc = 0u;
        uint32_t start = 0u;
        uint32_t size = 0u;
        uint64_t end = 0u;
        uint32_t off = 0u;
        if (zlt_read_u32(bank, len, ZLT_SECTION_OFFSET + 8u + i * 4u, &desc) != 0) {
            return ZLT_ERR_DESCRIPTOR;
        }
        start = (desc >> 16) << 8;
        size = (desc & 0xFFFFu) << 8;
        if (size == 0u) {
            return ZLT_ERR_DESCRIPTOR;
        }
        if (start % 4u != 0u || size % 4u != 0u) {
            return ZLT_ERR_DESCRIPTOR;
        }
        end = (uint64_t)start + (uint64_t)size;
        if (end > (uint64_t)ZLT_BANK_BYTES) {
            return ZLT_ERR_DESCRIPTOR;
        }
        for (off = start; off < start + size; off += 4u) {
            uint32_t w = 0u;
            if (zlt_read_u32(bank, len, off, &w) != 0) {
                return ZLT_ERR_DESCRIPTOR;
            }
            calc ^= w;
        }
    }
    *stored_out = stored;
    *calc_out = calc;
    return ZLT_OK;
}

static zlt_status zlt_parse_header(const unsigned char *bank, size_t len,
                                   uint32_t header_offset, uint32_t runtime_base,
                                   uint32_t *field0_out, uint32_t *table_addr_out,
                                   uint32_t *table_off_out, uint32_t *count_out,
                                   uint32_t *field3_out)
{
    uint32_t field0 = 0u;
    uint32_t table_addr = 0u;
    uint32_t count = 0u;
    uint32_t field3 = 0u;
    uint32_t table_off = 0u;
    uint64_t table_bytes = 0u;
    uint64_t table_end = 0u;
    uint64_t base_end = 0u;
    if (bank == NULL || field0_out == NULL || table_addr_out == NULL ||
        table_off_out == NULL || count_out == NULL || field3_out == NULL) {
        return ZLT_ERR_INPUT;
    }
    if (len != ZLT_BANK_BYTES) {
        return ZLT_ERR_BANK_SIZE;
    }
    if (header_offset % ZLT_RECORD_BYTES != 0u) {
        return ZLT_ERR_HEADER_OFFSET;
    }
    if ((uint64_t)header_offset + ZLT_RECORD_BYTES > (uint64_t)len) {
        return ZLT_ERR_HEADER_OFFSET;
    }
    field0 = zlt_be32(bank + header_offset);
    table_addr = zlt_be32(bank + header_offset + 4u);
    count = zlt_be32(bank + header_offset + 8u);
    field3 = zlt_be32(bank + header_offset + 12u);
    if (count == 0u || count > ZLT_MAX_RECORDS) {
        return ZLT_ERR_COUNT;
    }
    base_end = (uint64_t)runtime_base + (uint64_t)ZLT_BANK_BYTES;
    if (base_end > (uint64_t)0xFFFFFFFFu + 1u) {
        return ZLT_ERR_INPUT;
    }
    if ((uint64_t)table_addr < (uint64_t)runtime_base ||
        (uint64_t)table_addr >= base_end) {
        return ZLT_ERR_TABLE_ADDRESS;
    }
    table_off = table_addr - runtime_base;
    if (table_off % ZLT_RECORD_BYTES != 0u) {
        return ZLT_ERR_TABLE_ADDRESS;
    }
    table_bytes = (uint64_t)count * ZLT_RECORD_BYTES;
    table_end = (uint64_t)table_off + table_bytes;
    if (table_end > (uint64_t)len) {
        return ZLT_ERR_TABLE_ADDRESS;
    }
    *field0_out = field0;
    *table_addr_out = table_addr;
    *table_off_out = table_off;
    *count_out = count;
    *field3_out = field3;
    return ZLT_OK;
}

static int zlt_type_known(uint32_t t)
{
    switch (t) {
    case 1u:
    case 2u:
    case 3u:
    case 4u:
    case 5u:
    case 6u:
    case 7u:
    case 8u:
    case 9u:
    case 0xAu:
    case 0xBu:
    case 0xCu:
    case 0xDu:
        return 1;
    default:
        return 0;
    }
}

static uint32_t zlt_reg_for_type(uint32_t t)
{
    switch (t) {
    case 5u:
        return 24u;
    case 6u:
        return 25u;
    case 7u:
        return 23u;
    case 8u:
        return 4u;
    case 9u:
        return 5u;
    case 0xAu:
        return 28u;
    case 0xBu:
        return 29u;
    case 0xCu:
        return 19u;
    default:
        return 0u;
    }
}

static zlt_status zlt_preflight(const unsigned char *bank, size_t len,
                                uint32_t table_offset, uint32_t count)
{
    uint32_t i;
    uint32_t type3_pos = 0u;
    uint32_t type3_seen = 0u;
    if (bank == NULL) {
        return ZLT_ERR_INPUT;
    }
    if (len != ZLT_BANK_BYTES) {
        return ZLT_ERR_BANK_SIZE;
    }
    for (i = 0u; i < count; i++) {
        uint32_t off = table_offset + i * ZLT_RECORD_BYTES;
        uint32_t t = 0u;
        uint32_t f1 = 0u;
        uint32_t f2 = 0u;
        uint32_t f3 = 0u;
        if ((uint64_t)off + ZLT_RECORD_BYTES > (uint64_t)len) {
            return ZLT_ERR_TABLE_ADDRESS;
        }
        t = zlt_be32(bank + off);
        f1 = zlt_be32(bank + off + 4u);
        f2 = zlt_be32(bank + off + 8u);
        f3 = zlt_be32(bank + off + 12u);
        if (!zlt_type_known(t)) {
            return ZLT_ERR_UNKNOWN_TYPE;
        }
        if (t == 3u) {
            type3_seen++;
            type3_pos = i;
            /* Type 3 carries an unchanged PC value; only require that its
             * low word part is plausible? No: preserve 0x40000000 tag
             * verbatim and do not invent a range check. Only structural
             * terminal position is enforced. */
            (void)f1;
            (void)f2;
            (void)f3;
            continue;
        }
        if (t == 1u) {
            uint64_t bytes = (uint64_t)f3 * 4u;
            uint64_t dst_end = 0u;
            if (f3 > 0x3FFFFFFFu) {
                return ZLT_ERR_OVERFLOW;
            }
            dst_end = (uint64_t)f2 + bytes;
            if (dst_end > (uint64_t)0xFFFFFFFFu) {
                return ZLT_ERR_OVERFLOW;
            }
        } else if (t == 2u) {
            uint64_t bytes = (uint64_t)f2 * 4u;
            uint64_t dst_end = 0u;
            if (f2 > 0x3FFFFFFFu) {
                return ZLT_ERR_OVERFLOW;
            }
            dst_end = (uint64_t)f1 + bytes;
            if (dst_end > (uint64_t)0xFFFFFFFFu) {
                return ZLT_ERR_OVERFLOW;
            }
        } else if (t == 0xDu) {
            uint64_t blocks = (uint64_t)f2 / 16u;
            uint64_t b = (uint64_t)f1;
            uint64_t l = (uint64_t)f2;
            uint64_t last = 0u;
            /* Four ranges: B+16*i, B+L+16*i, B+2L+16*i, B+3L+16*i.
             * Check the maximal address without iterating N times. */
            if (blocks == 0u) {
                continue;
            }
            if (l > (uint64_t)0xFFFFFFFFu) {
                return ZLT_ERR_OVERFLOW;
            }
            /* 3*L must fit, plus stride tail. */
            if (l > ((uint64_t)0xFFFFFFFFu - 16u * (blocks - 1u)) / 3u &&
                blocks > 0u) {
                /* Compute conservatively with 64-bit and bound. */
                last = b + 3u * l + 16u * (blocks - 1u);
                if (last > (uint64_t)0xFFFFFFFFu) {
                    return ZLT_ERR_OVERFLOW;
                }
            } else {
                last = b + 3u * l + 16u * (blocks - 1u);
                if (last > (uint64_t)0xFFFFFFFFu) {
                    return ZLT_ERR_OVERFLOW;
                }
            }
            if (b + l > (uint64_t)0xFFFFFFFFu) {
                return ZLT_ERR_OVERFLOW;
            }
        } else {
            (void)f1;
            (void)f2;
            (void)f3;
        }
    }
    if (type3_seen == 0u) {
        return ZLT_ERR_MISSING_TERMINAL;
    }
    if (type3_seen != 1u || type3_pos != count - 1u) {
        return ZLT_ERR_NONTERMINAL_TYPE3;
    }
    return ZLT_OK;
}

static zlt_status zlt_trace_bank(const unsigned char *bank, size_t len,
                                 uint32_t header_offset, uint32_t runtime_base,
                                 int use_validator,
                                 uint32_t *selected_header_offset_out,
                                 zlt_cb cb, void *ctx)
{
    uint32_t sel_header_off = 0u;
    uint32_t sel_header_addr = 0u;
    uint32_t sel_table_addr = 0u;
    uint32_t sel_table_off = 0u;
    uint32_t sel_count = 0u;
    uint32_t field0 = 0u;
    uint32_t field3 = 0u;
    uint32_t stored = 0u;
    uint32_t calc = 0u;
    int is_main = 0;
    zlt_status st;
    uint32_t i;
    zlt_event ev;

    if (bank == NULL || cb == NULL) {
        return ZLT_ERR_INPUT;
    }
    if (len != ZLT_BANK_BYTES) {
        return ZLT_ERR_BANK_SIZE;
    }
    if (selected_header_offset_out != NULL) {
        *selected_header_offset_out = 0u;
    }
    if (use_validator) {
        st = zlt_validate_section(bank, len, &stored, &calc);
        if (st != ZLT_OK) {
            return st;
        }
        if (calc == stored) {
            is_main = 1;
            sel_header_off = ZLT_MAIN_HEADER_OFFSET;
            sel_header_addr = ZLT_MAIN_HEADER_ADDRESS;
            sel_table_addr = ZLT_MAIN_TABLE_ADDRESS;
            sel_table_off = ZLT_MAIN_TABLE_OFFSET;
            sel_count = ZLT_MAIN_COUNT;
        } else {
            is_main = 0;
            sel_header_off = ZLT_AUX_HEADER_OFFSET;
            sel_header_addr = ZLT_AUX_HEADER_ADDRESS;
            sel_table_addr = ZLT_AUX_TABLE_ADDRESS;
            sel_table_off = ZLT_AUX_TABLE_OFFSET;
            sel_count = ZLT_AUX_COUNT;
        }
        st = zlt_parse_header(bank, len, sel_header_off, runtime_base, &field0,
                              &sel_table_addr, &sel_table_off, &sel_count,
                              &field3);
        if (st != ZLT_OK) {
            return st;
        }
        /* Cross-check validator selection against the parsed header. */
        if (is_main) {
            if (runtime_base + sel_header_off != ZLT_MAIN_HEADER_ADDRESS ||
                sel_table_addr != ZLT_MAIN_TABLE_ADDRESS ||
                sel_count != ZLT_MAIN_COUNT) {
                return ZLT_ERR_TABLE_ADDRESS;
            }
        } else {
            if (runtime_base + sel_header_off != ZLT_AUX_HEADER_ADDRESS ||
                sel_table_addr != ZLT_AUX_TABLE_ADDRESS ||
                sel_count != ZLT_AUX_COUNT) {
                return ZLT_ERR_TABLE_ADDRESS;
            }
        }
        st = zlt_preflight(bank, len, sel_table_off, sel_count);
        if (st != ZLT_OK) {
            return st;
        }
        if (selected_header_offset_out != NULL) {
            *selected_header_offset_out = sel_header_off;
        }
        memset(&ev, 0, sizeof(ev));
        ev.kind = ZLT_EV_VALIDATOR;
        ev.selection_is_main = is_main;
        ev.stored = stored;
        ev.calculated = calc;
        ev.header_offset = sel_header_off;
        ev.header_address = sel_header_addr;
        ev.table_offset = sel_table_off;
        ev.table_address = sel_table_addr;
        ev.record_count = sel_count;
        if (cb(&ev, ctx) != 0) {
            return ZLT_ERR_CALLBACK;
        }
    } else {
        sel_header_off = header_offset;
        st = zlt_parse_header(bank, len, sel_header_off, runtime_base, &field0,
                              &sel_table_addr, &sel_table_off, &sel_count,
                              &field3);
        if (st != ZLT_OK) {
            return st;
        }
        st = zlt_preflight(bank, len, sel_table_off, sel_count);
        if (st != ZLT_OK) {
            return st;
        }
        if (selected_header_offset_out != NULL) {
            *selected_header_offset_out = sel_header_off;
        }
        sel_header_addr = runtime_base + sel_header_off;
    }

    memset(&ev, 0, sizeof(ev));
    ev.kind = ZLT_EV_HEADER;
    ev.header_offset = sel_header_off;
    ev.header_address = sel_header_addr;
    ev.table_offset = sel_table_off;
    ev.table_address = sel_table_addr;
    ev.record_count = sel_count;
    ev.field0 = field0;
    ev.header_field3 = field3;
    if (cb(&ev, ctx) != 0) {
        return ZLT_ERR_CALLBACK;
    }

    for (i = 0u; i < sel_count; i++) {
        uint32_t off = sel_table_off + i * ZLT_RECORD_BYTES;
        uint32_t t = zlt_be32(bank + off);
        uint32_t f1 = zlt_be32(bank + off + 4u);
        uint32_t f2 = zlt_be32(bank + off + 8u);
        uint32_t f3 = zlt_be32(bank + off + 12u);
        memset(&ev, 0, sizeof(ev));
        ev.index = i;
        ev.bank_offset = off;
        ev.rec_type = t;
        ev.field1 = f1;
        ev.field2 = f2;
        ev.field3 = f3;
        ev.header_offset = sel_header_off;
        ev.table_offset = sel_table_off;
        ev.record_count = sel_count;
        if (t == 1u) {
            uint32_t mapped = 0u;
            ev.kind = ZLT_EV_COPY;
            ev.byte_count = (uint64_t)f3 * 4u;
            ev.src_mapped = zlt_addr_in_bank(f1, runtime_base, &mapped);
            ev.src_bank_offset = mapped;
        } else if (t == 2u) {
            ev.kind = ZLT_EV_ZERO;
            ev.byte_count = (uint64_t)f2 * 4u;
        } else if (t == 3u) {
            ev.kind = ZLT_EV_TERMINAL;
        } else if (t == 4u) {
            ev.kind = ZLT_EV_CALL;
        } else if (t == 0xDu) {
            ev.kind = ZLT_EV_TYPE_D;
            ev.blocks = (uint64_t)f2 / 16u;
        } else {
            ev.kind = ZLT_EV_REG;
            ev.reg = zlt_reg_for_type(t);
        }
        if (cb(&ev, ctx) != 0) {
            return ZLT_ERR_CALLBACK;
        }
    }
    return ZLT_OK;
}

#ifndef ZUP_LAUNCH_TRACE_NO_MAIN

struct out_ctx {
    FILE *out;
    int failed;
};

static int stdout_cb(const zlt_event *ev, void *ctx)
{
    struct out_ctx *o = (struct out_ctx *)ctx;
    int r = 0;
    if (ev == NULL || o == NULL || o->out == NULL) {
        return -1;
    }
    switch (ev->kind) {
    case ZLT_EV_VALIDATOR:
        r = fprintf(o->out,
                    "validator magic=0x%08x stored=0x%08x calculated=0x%08x "
                    "selection=%s header_byte_address=0x%08x "
                    "header_bank_offset=0x%x table_byte_address=0x%08x "
                    "table_bank_offset=0x%x records=%u\n",
                    ZLT_SECTION_MAGIC, ev->stored, ev->calculated,
                    ev->selection_is_main ? "main" : "auxiliary",
                    ev->header_address, ev->header_offset, ev->table_address,
                    ev->table_offset, ev->record_count);
        break;
    case ZLT_EV_HEADER:
        r = fprintf(o->out,
                    "header bank_offset=0x%x field0=0x%08x "
                    "table_byte_address=0x%08x table_bank_offset=0x%x "
                    "records=%u field3=0x%08x\n",
                    ev->header_offset, ev->field0, ev->table_address,
                    ev->table_offset, ev->record_count, ev->header_field3);
        break;
    case ZLT_EV_COPY:
        if (ev->src_mapped) {
            r = fprintf(o->out,
                        "copy index=%u bank_offset=0x%x "
                        "src_byte_address=0x%08x src_bank_offset=0x%x "
                        "dst_byte_address=0x%08x word_count=%u byte_count=%llu\n",
                        ev->index, ev->bank_offset, ev->field1,
                        ev->src_bank_offset, ev->field2, ev->field3,
                        (unsigned long long)ev->byte_count);
        } else {
            r = fprintf(o->out,
                        "copy index=%u bank_offset=0x%x "
                        "src_byte_address=0x%08x src_unmapped=true "
                        "dst_byte_address=0x%08x word_count=%u byte_count=%llu\n",
                        ev->index, ev->bank_offset, ev->field1, ev->field2,
                        ev->field3,
                        (unsigned long long)ev->byte_count);
        }
        break;
    case ZLT_EV_ZERO:
        r = fprintf(o->out,
                    "zero index=%u bank_offset=0x%x "
                    "dst_byte_address=0x%08x word_count=%u byte_count=%llu\n",
                    ev->index, ev->bank_offset, ev->field1, ev->field2,
                    (unsigned long long)ev->byte_count);
        break;
    case ZLT_EV_REG:
        r = fprintf(o->out,
                    "reg index=%u bank_offset=0x%x reg=r%u value=0x%08x\n",
                    ev->index, ev->bank_offset, ev->reg, ev->field1);
        break;
    case ZLT_EV_CALL:
        r = fprintf(o->out, "call index=%u bank_offset=0x%x target=0x%08x\n",
                    ev->index, ev->bank_offset, ev->field1);
        break;
    case ZLT_EV_TYPE_D:
        r = fprintf(o->out,
                    "type_d index=%u bank_offset=0x%x base=0x%08x length=0x%08x "
                    "blocks=%llu\n",
                    ev->index, ev->bank_offset, ev->field1, ev->field2,
                    (unsigned long long)ev->blocks);
        break;
    case ZLT_EV_TERMINAL:
        r = fprintf(o->out,
                    "terminal index=%u bank_offset=0x%x target=0x%08x\n",
                    ev->index, ev->bank_offset, ev->field1);
        break;
    default:
        return -1;
    }
    if (r < 0) {
        o->failed = 1;
        return -1;
    }
    return 0;
}

static void print_usage(void)
{
    fprintf(stderr,
            "usage: zup_launch_trace [--header-offset OFFSET] "
            "[--runtime-base ADDRESS]\n");
}

static int parse_u32_arg(const char *text, uint32_t *out)
{
    char *end = NULL;
    unsigned long v = 0ul;
    if (text == NULL || out == NULL || text[0] == '\0') {
        return -1;
    }
    v = strtoul(text, &end, 0);
    if (end == NULL || *end != '\0') {
        return -1;
    }
    if (v > 0xFFFFFFFFul) {
        return -1;
    }
    *out = (uint32_t)v;
    return 0;
}

int main(int argc, char **argv)
{
    uint32_t header_offset = 0u;
    uint32_t runtime_base = ZLT_RUNTIME_BASE_DEFAULT;
    int use_validator = 1;
    int have_header = 0;
    int i = 1;
    unsigned char *bank = NULL;
    size_t got = 0u;
    size_t n = 0u;
    zlt_status st;
    struct out_ctx ctx;

    while (i < argc) {
        if (strcmp(argv[i], "--header-offset") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "error: invalid arguments\n");
                return 2;
            }
            if (parse_u32_arg(argv[i + 1], &header_offset) != 0) {
                fprintf(stderr, "error: invalid arguments\n");
                return 2;
            }
            use_validator = 0;
            have_header = 1;
            i += 2;
        } else if (strcmp(argv[i], "--runtime-base") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "error: invalid arguments\n");
                return 2;
            }
            if (parse_u32_arg(argv[i + 1], &runtime_base) != 0) {
                fprintf(stderr, "error: invalid arguments\n");
                return 2;
            }
            i += 2;
        } else if (strcmp(argv[i], "--help") == 0 ||
                   strcmp(argv[i], "-h") == 0) {
            print_usage();
            return 0;
        } else {
            fprintf(stderr, "error: invalid arguments\n");
            return 2;
        }
    }
    if (have_header && use_validator) {
        fprintf(stderr, "error: invalid arguments\n");
        return 2;
    }
    if (runtime_base > 0xFFFFFFFFu - (uint32_t)ZLT_BANK_BYTES) {
        fprintf(stderr, "error: invalid arguments\n");
        return 2;
    }

    bank = (unsigned char *)malloc(ZLT_BANK_BYTES + 1u);
    if (bank == NULL) {
        fprintf(stderr, "error: launch trace failed closed\n");
        return 1;
    }
    got = 0u;
    while (got < ZLT_BANK_BYTES) {
        n = fread(bank + got, 1u, ZLT_BANK_BYTES - got, stdin);
        if (n == 0u) {
            if (feof(stdin)) {
                break;
            }
            if (ferror(stdin)) {
                fprintf(stderr, "error: launch trace failed closed\n");
                free(bank);
                return 1;
            }
        }
        got += n;
    }
    if (got != ZLT_BANK_BYTES) {
        fprintf(stderr, "error: launch trace failed closed\n");
        free(bank);
        return 1;
    }
    /* Reject trailing bytes without echoing input. */
    {
        unsigned char extra = 0u;
        if (fread(&extra, 1u, 1u, stdin) != 0u) {
            fprintf(stderr, "error: launch trace failed closed\n");
            free(bank);
            return 1;
        }
    }

    ctx.out = stdout;
    ctx.failed = 0;
    st = zlt_trace_bank(bank, ZLT_BANK_BYTES, header_offset, runtime_base,
                        use_validator, NULL, stdout_cb, &ctx);
    free(bank);
    if (fflush(stdout) != 0) {
        fprintf(stderr, "error: launch trace failed closed\n");
        return 1;
    }
    if (ctx.failed) {
        fprintf(stderr, "error: launch trace failed closed\n");
        return 1;
    }
    if (st != ZLT_OK) {
        /* Fixed diagnostic; never reflects guest bytes. */
        if (st == ZLT_ERR_MARKER) {
            fprintf(stderr, "error: unsupported marker mismatch\n");
        } else {
            fprintf(stderr, "error: launch trace failed closed\n");
        }
        return 1;
    }
    return 0;
}

#endif /* ZUP_LAUNCH_TRACE_NO_MAIN */
