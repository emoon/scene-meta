/*
* Local patch: headless batch debug protocol (--dbg), used by the Demokick
* test harness (tools/runner.py). See ../../SNAPSHOT.md and the repo's
* protocol design (vamiga_demo_rom issue #77).
*
* Commands arrive as repeated `--dbg "<cmd>"` argv entries and execute in
* order; each emits one NDJSON line on stdout:
*   {"seq":N,"cmd":"<verbatim>","result":{...}}
* A CPU halt mid-batch emits {"event":"halt",...} and exits non-zero.
*/

#ifndef UAE_DBGPROTO_H
#define UAE_DBGPROTO_H

#include "uae/types.h"

/* Non-zero once at least one --dbg command was collected. */
extern int dbgproto_active;
/* Fast gate for the per-instruction CPU-loop hook (initial dispatch +
 * breakpoint scan). Checked inline in the m68k run loops. */
extern int dbgproto_instr_gate;
/* Exit code for the process; set to 2 by a halt event. */
extern int dbgproto_exit_code;
/* --warp-until-audio-dma: warp from reset until audio DMA first becomes
 * effective (interactive fast-forward through boot/decrunch to the music).
 * One-shot: cleared by the DMACON hook when it releases warp. Independent
 * of dbgproto_active — usable without any --dbg command. */
extern int dbgproto_warp_until_audio;

void dbgproto_add_command(const char *cmd);   /* from --dbg argv parsing */
void dbgproto_instr(uaecptr pc);              /* per instruction when gated */
void dbgproto_vsync(void);                    /* once per emulated frame */
void dbgproto_audio_dma(void);                /* audio DMA channel enabled */
void dbgproto_halt(int id);                   /* from cpu_halt() */
void dbgproto_note_audio_reg(int nr, int reg, unsigned v);   /* PROTOTYPE */
void dbgproto_note_audio_sample(int nr, int sample, int vol); /* PROTOTYPE */
void dbgproto_note_cpu_reset(void);           /* from cpureset(), the RESET op */

/* Swap-wait detector notes, called from disk.cpp (cheap counters; the
 * heuristic itself runs in dbgproto_vsync). A demo waiting for a disk swap
 * polls CIA-A PRA /CHNG with a drive selected while disk DMA is idle —
 * see docs/demo-tricks.md ("disk-swap sample sweep") in the repo root. */
void dbgproto_note_chng_poll(uae_u32 pc);     /* PRA read, >=1 drive selected */
void dbgproto_note_disk_step(void);           /* head step pulse */
void dbgproto_note_disk_dma(int cyl);         /* disk DMA started; cyl = highest
                                                 selected-drive cylinder, -1 if
                                                 none selected */

/* Implemented in custom.cpp (needs its file-static chipset state). */
struct dbgproto_custom_state {
	uae_u16 dmacon, intena, intreq, bplcon0;
	int ddfstrt, ddfstop, diwstrt, diwstop;
	uae_u32 coppc;
	int vpos;
};
void dbgproto_custom_status(struct dbgproto_custom_state *out);

#endif /* UAE_DBGPROTO_H */
