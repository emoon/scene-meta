/*
* Local patch: headless batch debug protocol (--dbg). See dbgproto.h.
*
* Design notes:
*  - Everything runs on the emulation thread. The initial dispatch happens
*    from the per-instruction hook before the first instruction executes, so
*    breakpoints / loads are in place before the ROM runs. After that,
*    dispatch resumes whenever the active `run` command's stop condition
*    fires (frame countdown at vsync, breakpoint at the instruction hook,
*    audio-DMA at the DMACON write).
*  - The dispatcher always leaves either an active `run` or quits, so the
*    machine never free-runs past the batch.
*  - NDJSON goes straight to stdout with fprintf; Amiberry's own logging is
*    silent by default and routes to stderr/SDL_Log when enabled, so stdout
*    stays parseable (do not pass --log / --cli).
*/

#include "sysconfig.h"
#include "sysdeps.h"

#include <algorithm>
#include <vector>
#include <string>

#include "options.h"
#include "uae.h"
#include "memory.h"
#include "custom.h"
#include "newcpu.h"
#include "disk.h"
#include "gui.h"
#include "inputdevice.h"
#include "dbgproto.h"
#include "osdep/target.h"
#include "osdep/amiberry_gfx.h"

int dbgproto_active = 0;
int dbgproto_instr_gate = 0;
int dbgproto_exit_code = 0;
int dbgproto_warp_until_audio = 0;

extern void warpmode(int mode);          /* inputdevice.cpp */
extern bool create_screenshot(void);     /* osdep/amiberry_gfx.cpp */
extern int save_thumb_if_new(const std::string &path, int permille, int *changed);
extern int save_thumb(const std::string &path);
extern int screenshot_box(int *w, int *h, int box[4]);
extern bool render_screen(int monid, int mode, bool immediate);

static std::vector<std::string> commands;
static size_t next_cmd = 0;
static int seq = 0;
static bool started = false;      /* initial dispatch done */
static bool finished = false;     /* batch exhausted, quit requested */
static bool halted_emitted = false;

static long frame_counter = 0;    /* vsync count since power-on */

/* RESET instructions executed. An Amiga reboots by executing RESET and jumping
 * back into the ROM — $FC00D0 in kick1.3 is the scan idiom's landing pad, one
 * word before its cold entry at $FC00D2. Such a reboot never reaches
 * m68k_go's reset loop: hooked there instead, a disk that visibly rebooted
 * three times counted 0. Neither ROM executes RESET on its own account, so on
 * the disks measured so far the count moves only when the disk restarts the
 * machine — but it counts RESET instructions, not reboots, and a program is
 * free to execute one for its own reasons. */
static int reset_counter = 0;

/* Active run command state. */
enum run_mode { RUN_NONE, RUN_FRAMES, RUN_BP, RUN_AUDIO, RUN_WATCH };
static run_mode run_active = RUN_NONE;
static long run_elapsed = 0;      /* frames elapsed in this run */
static long run_max = 0;          /* frame budget (always finite) */
static std::string run_cmd;       /* verbatim cmd for the result line */
static int run_seq = 0;

#define DBG_MAX_BP 16
static uaecptr bps[DBG_MAX_BP];
static int bp_count = 0;

/* Write watchpoint: a snapshot of the watched bytes re-compared from the
 * per-instruction hook the breakpoints already run under, rather than a hook
 * in the memory banks. That costs nothing when disarmed and needs no CPU-core
 * patch, at the price of reporting the instruction AFTER the store — which is
 * what "who clobbered this address" wants anyway. */
#define DBG_MAX_WATCH 64
static uaecptr watch_addr = 0;
static int watch_size = 0;                  /* 0 = disarmed */
static uae_u8 watch_snap[DBG_MAX_WATCH];

/* ---- swap-wait detector / autoswap --------------------------------- */
/* A demo waiting for the next disk polls CIA-A PRA /CHNG with a drive
 * selected while disk DMA is idle (five wait styles surveyed in
 * docs/demo-tricks.md, "disk-swap sample sweep"). disk.cpp notes every
 * selected-drive PRA read, step pulse and DMA start; this state machine
 * turns a sustained poll window into a `swap-poll` NDJSON event and — when
 * armed via `disk autoswap on|click` — inserts the next `-diskswapper=`
 * list entry, with an optional one-shot LMB click fallback for
 * Odyssey-style "insert disk and press left mouse button" prompts. */
static int autoswap_mode = 0;        /* 0=off 1=insert 2=insert+click */
static int swapslot = 0;             /* next dfxlist entry (shared with
                                        `disk swap-next`) */
static long chng_polls_frame = 0;    /* selected-drive PRA reads, this frame */
static long total_rom_polls = 0;
static bool autoswap_ram_polls = false; /* rampolls: ignore ROM polls */
static long steps_frame = 0;         /* step pulses, this frame */
static long last_dma_frame = -1;     /* frame of last disk DMA start (any) */
static long last_stream_frame = -1;  /* frame of last DMA start at cyl >=
                                        SWAP_STREAM_CYL (real streaming, not
                                        an ID re-read at track 0/1) */
static int max_dma_cyl = -1;         /* highest cyl seen at any DMA start;
                                        arming guard: no trigger before real
                                        streaming progress */
static long window_start = -1;       /* first frame of current poll window */
static long last_poll_frame = -1;    /* last frame with >=1 poll */
static long window_reads = 0, window_steps = 0;
static long window_poll_frames = 0;  /* distinct frames with polls */
static bool swap_event_emitted = false; /* one event per quiet period */
static long autoswap_insert_frame = -1; /* when autoswap inserted */
static bool swap_pending_verify = false; /* inserted, awaiting acceptance */
static char swap_prev_disk[600];     /* disk to restore on rollback */
static long swap_retry_after = -1;   /* no fire before this frame (set on
                                        rollback) */
static int click_state = 0;          /* 0=idle 1=armed 2=LMB held
                                        3=RMB armed 4=RMB held */
static long click_down_frame = -1;
static long autoswap_idle_frames = 0; /* idle=N trigger, 0=disabled */
static bool autoswap_idle_anycyl = false; /* idle trigger ignores head position */
static int autoswap_unit = 0;        /* unit=N: the drive swaps go into */
static bool autoswap_reread = false;   /* reread trigger enabled */
static bool autoswap_idle_static = false; /* idle needs a still screen */
static uint32_t screen_hash = 0;
static long screen_change_frame = -1;  /* last frame the display changed */
#define SCREEN_SAMPLE_FRAMES 25
/* Reread trigger state: when each cylinder last had a DMA start, the last
 * DMA start at a cylinder not read within SWAP_REREAD_FORGET, and the DMA
 * starts since then. A demo waiting for its next disk by re-reading the
 * same track(s) keeps DMA going without ever reaching a new cylinder. */
#define REREAD_CYLS 84
static long cyl_last_dma[REREAD_CYLS];
static long reread_progress_frame = -1;
static long reread_dmas = 0;
static void reread_reset(void);
static long autoswap_tail_frames = 0; /* tail=N: end the batch N frames after the last disk */
static long autoswap_stop_frame = -1; /* frame the tail runs out, -1 = none */
static long autoswap_dead_frames = 0;  /* dead=N: end the batch after N frames
                                          with no display change, audio DMA
                                          or disk DMA */
static long last_audio_frame = -1;
static long total_polls = 0, total_steps = 0; /* since power-on (debug) */

#define SWAP_POLL_GAP    60   /* max frames between polls inside a window
                                 (The Last Drop polls every ~35-50 frames
                                 parked); kick13's trackdisk housekeeping
                                 polls every ~2.5 s (125 frames), so the OS
                                 never sustains a window */
#define SWAP_WAIT_CONFIRM 500 /* a window must sustain ~10 s with no
                                 streaming DMA before it counts as a swap
                                 wait. Loaders emit poll bursts of every
                                 density mid-disk (The Last Drop: nine
                                 false windows, 20-14000 reads each;
                                 Odyssey: step+poll disk verifications) but
                                 all die when streaming resumes within a
                                 few hundred frames — only a real wait
                                 sustains this long. */
#define SWAP_MIN_POLL_FRAMES 8 /* window needs polls in >=8 frames */
#define SWAP_STREAM_CYL  2    /* DMA at cyl >= 2 is streaming (resets the
                                 window); DMA at cyl 0/1 is an ID re-read —
                                 9 Fingers re-reads track 0 every ~100
                                 frames while waiting and must not reset */
#define SWAP_MIN_STREAM_CYL 15 /* no trigger before a DMA start with the
                                  head past cyl 15 (early-boot /CHNG
                                  interrogation looks like a swap wait);
                                  re-armed per disk: reset on every
                                  autoswap insert */
#define SWAP_DMA_QUIET   25   /* frames since last DMA start before polls
                                 count (motor-spinup /RDY loops and seek
                                 /TK0 loops around a load stay vetoed) */
#define SWAP_CLICK_DELAY 250  /* no streaming ~5 s after insert -> LMB
                                 fallback */
#define SWAP_CLICK_HOLD  10   /* frames to hold the button */
#define SWAP_REJECT_FRAMES 1000 /* rejection = after an insert, a poll
                                   window REFORMS and sustains ~20 s with no
                                   streaming (the demo ID-checked the disk
                                   once and went back to polling for the old
                                   one) -> roll back. Poll detection cannot
                                   distinguish "waiting for the next disk"
                                   from "monitoring that the current disk is
                                   still in" (The Last Drop presence-polls
                                   at cyl 22 while its voxel part plays from
                                   RAM — same drive signature as its real
                                   wait), so a swap is a hypothesis to
                                   verify. Acceptance may be lazy — the
                                   same demo ID-checks a correct disk, then
                                   plays from RAM for thousands of frames
                                   (quiet, no polls) before streaming it —
                                   which is why the criterion is a sustained
                                   post-insert window, not wall-clock. */
#define SWAP_REREAD_CONFIRM 750 /* ~15 s of DMA without a new cylinder */
#define SWAP_REREAD_FORGET 1500  /* a cylinder unread for ~30 s is new again */
#define SWAP_REREAD_MIN_DMAS 8   /* ...with at least this many DMA starts */
#define SWAP_RETRY_DELAY 2500 /* after a rollback, no re-fire for ~50 s (the
                                 monitor phase that fooled us usually ends in
                                 streaming well before that; a real wait
                                 mistakenly rolled back retries after it) */

/* ---- JSON output helpers ------------------------------------------- */

static void json_escape(const char *s, char *out, size_t outsize)
{
	size_t o = 0;
	for (; *s && o + 6 < outsize; s++) {
		unsigned char c = (unsigned char)*s;
		if (c == '"' || c == '\\') {
			out[o++] = '\\';
			out[o++] = c;
		} else if (c < 0x20) {
			o += snprintf(out + o, outsize - o, "\\u%04x", c);
		} else {
			out[o++] = c;
		}
	}
	out[o] = 0;
}

/* Emit one NDJSON result line; body is the JSON object text for "result". */
static void emit(int s, const std::string &cmd, const char *body)
{
	char esc[1024];
	json_escape(cmd.c_str(), esc, sizeof esc);
	fprintf(stdout, "{\"seq\":%d,\"cmd\":\"%s\",\"result\":%s}\n", s, esc, body);
	fflush(stdout);
}

static void emit_error(int s, const std::string &cmd, const char *msg)
{
	char buf[256];
	snprintf(buf, sizeof buf, "{\"error\":\"%s\"}", msg);
	emit(s, cmd, buf);
}

/* ---- display measure -------------------------------------------------- */
/* Where a run shows bitplanes, by the registers (custom.cpp notes each shown
 * line): per line and per column, in how many frames, apart for each mode:
 * a resolution, interlaced or not, and whether the copper list was the
 * system's (COP1LC as Kickstart sets it: AmigaDOS's own screen, or a
 * production that draws through the system). A frame is of the finest its
 * lines had, and the system's when every line was. */
int dbgproto_display_on = 0;

#define DISP_MAX 1024       /* lines of a frame; lores columns of a line */
#define DISP_MAX_DIW 32
#define DISP_MODES 12       /* resolution, + 3 interlaced, + 6 the system's */

struct disp_diw { uae_u16 strt, stop; long lines; };

static struct {
	struct {
		long frames;                /* frames that showed a line */
		long rows[DISP_MAX], cols[DISP_MAX];
	} mode[DISP_MODES];
	uae_u32 os_cop;                 /* the system's COP1LC; 0: not told */
	std::vector<disp_diw> diw;      /* DIWSTRT/DIWSTOP of the shown lines */
	bool more_diw;                  /* and others, not kept */
	/* the frame being drawn */
	bool row[DISP_MAX];
	int x0, y0, x1, y1, res;
	bool lace, os;
} disp;

static void disp_new_frame(void)
{
	disp.x0 = disp.y0 = DISP_MAX;
	disp.x1 = disp.y1 = 0;
	disp.res = 0;
	disp.lace = false;
	disp.os = disp.os_cop != 0;
}

void dbgproto_display_line(int line, int x0, int x1, int res, bool lace,
	uae_u32 cop1lc, uae_u16 diwstrt, uae_u16 diwstop)
{
	if (line < 0 || line >= DISP_MAX || x0 < 0 || x1 > DISP_MAX
		|| res < 0 || res > 2)
		return;
	disp.row[line] = true;
	disp.x0 = std::min(disp.x0, x0);
	disp.x1 = std::max(disp.x1, x1);
	disp.y0 = std::min(disp.y0, line);
	disp.y1 = std::max(disp.y1, line + 1);
	disp.res = std::max(disp.res, res);
	disp.lace |= lace;
	disp.os &= cop1lc == disp.os_cop;
	for (auto &d : disp.diw) {
		if (d.strt == diwstrt && d.stop == diwstop) {
			d.lines++;
			return;
		}
	}
	if (disp.diw.size() < DISP_MAX_DIW)
		disp.diw.push_back({ diwstrt, diwstop, 1 });
	else
		disp.more_diw = true;
}

static void disp_vsync(void)
{
	if (disp.x1 > disp.x0) {
		auto &m = disp.mode[disp.res + (disp.lace ? 3 : 0) + (disp.os ? 6 : 0)];
		m.frames++;
		for (int y = disp.y0; y < disp.y1; y++) {
			m.rows[y] += disp.row[y];
			disp.row[y] = false;
		}
		for (int x = disp.x0; x < disp.x1; x++)
			m.cols[x]++;
	}
	disp_new_frame();
}

/* ``counts`` as [[from, to, count], ...]: each stretch with one count that is
 * not zero, ``to`` not included. */
static std::string disp_runs(const long *counts)
{
	std::string out = "[";
	char buf[64];
	for (int i = 0; i < DISP_MAX;) {
		int j = i;
		while (j < DISP_MAX && counts[j] == counts[i])
			j++;
		if (counts[i]) {
			snprintf(buf, sizeof buf, "%s[%d,%d,%ld]", out.size() > 1 ? "," : "",
				i, j, counts[i]);
			out += buf;
		}
		i = j;
	}
	return out + "]";
}

/* ---- small parsing helpers ------------------------------------------ */

static std::vector<std::string> tokenize(const std::string &s)
{
	std::vector<std::string> t;
	size_t i = 0;
	while (i < s.size()) {
		while (i < s.size() && s[i] == ' ')
			i++;
		size_t j = i;
		while (j < s.size() && s[j] != ' ')
			j++;
		if (j > i)
			t.push_back(s.substr(i, j - i));
		i = j;
	}
	return t;
}

/* addresses are hex (bare or 0x-prefixed); counts/sizes are decimal */
static uaecptr parse_addr(const std::string &s)
{
	return (uaecptr)strtoul(s.c_str(), nullptr, 16);
}

static long parse_num(const std::string &s)
{
	return strtol(s.c_str(), nullptr, 10);
}

/* value of "key=..." in a token list, or empty */
static std::string kv(const std::vector<std::string> &t, const char *key)
{
	std::string prefix = std::string(key) + "=";
	for (const auto &tok : t)
		if (tok.compare(0, prefix.size(), prefix) == 0)
			return tok.substr(prefix.size());
	return "";
}

/* ---- command implementations ---------------------------------------- */

static void quit_batch(void)
{
	finished = true;
	dbgproto_instr_gate = 0;
	uae_quit();
	/* make the CPU inner loop yield promptly */
	set_special(SPCFLAG_BRK | SPCFLAG_MODE_CHANGE);
}

static void update_instr_gate(void)
{
	dbgproto_instr_gate = dbgproto_active &&
		(!started || (run_active == RUN_BP && bp_count > 0)
		 || (run_active == RUN_WATCH && watch_size > 0));
}

static void start_run(run_mode mode, long max, const std::string &cmd, int s)
{
	run_active = mode;
	run_elapsed = 0;
	run_max = max > 0 ? max : 1;
	run_cmd = cmd;
	run_seq = s;
	update_instr_gate();
}

static void finish_run(const char *stopped)
{
	char body[192];
	snprintf(body, sizeof body,
		"{\"stopped\":\"%s\",\"frame\":%ld,\"elapsed\":%ld,\"pc\":\"%x\","
		"\"hit\":%s}",
		stopped, frame_counter, run_elapsed, m68k_getpc(),
		strcmp(stopped, "bp") == 0 || strcmp(stopped, "watch") == 0
			? "true" : "false");
	run_active = RUN_NONE;
	emit(run_seq, run_cmd, body);
	update_instr_gate();
}

static void cmd_regs(int s, const std::string &cmd)
{
	MakeSR();
	char body[512];
	int n = snprintf(body, sizeof body,
		"{\"pc\":\"%x\",\"sr\":%u,\"usp\":\"%x\",\"isp\":\"%x\","
		"\"cacr\":\"%x\",\"caar\":\"%x\",\"d\":[",
		m68k_getpc(), (unsigned)regs.sr, (unsigned)regs.usp,
		(unsigned)regs.isp, (unsigned)regs.cacr, (unsigned)regs.caar);
	for (int i = 0; i < 8; i++)
		n += snprintf(body + n, sizeof body - n, "\"%x\"%s",
			(unsigned)m68k_dreg(regs, i), i < 7 ? "," : "],\"a\":[");
	for (int i = 0; i < 8; i++)
		n += snprintf(body + n, sizeof body - n, "\"%x\"%s",
			(unsigned)m68k_areg(regs, i), i < 7 ? "," : "]}");
	emit(s, cmd, body);
}

static void cmd_peek(int s, const std::string &cmd, uaecptr addr, long size)
{
	if (size < 1 || size > 0x100000) {
		emit_error(s, cmd, "size out of range (1..1048576)");
		return;
	}
	std::string body;
	body.reserve((size_t)size * 2 + 64);
	char head[64];
	snprintf(head, sizeof head, "{\"addr\":\"%x\",\"size\":%ld,\"hex\":\"",
		addr, size);
	body = head;
	static const char hexd[] = "0123456789abcdef";
	for (long i = 0; i < size; i++) {
		uae_u8 b = (uae_u8)get_byte(addr + (uaecptr)i);
		body += hexd[b >> 4];
		body += hexd[b & 15];
	}
	body += "\"}";
	emit(s, cmd, body.c_str());
}

static void cmd_disasm(int s, const std::string &cmd, uaecptr addr, long n)
{
	/* Amiberry-Lite ships no disassembler (debug.cpp is a stub), so this
	 * returns raw big-endian opcode words; disassemble host-side
	 * (tools use capstone on `peek` output for real mnemonics). */
	if (n < 1 || n > 256)
		n = 16;
	std::string body;
	char head[48];
	snprintf(head, sizeof head, "{\"addr\":\"%x\",\"words\":[", addr);
	body = head;
	for (long i = 0; i < n; i++) {
		char w[16];
		snprintf(w, sizeof w, "\"%04x\"%s",
			(unsigned)get_word(addr + (uaecptr)(i * 2)),
			i < n - 1 ? "," : "");
		body += w;
	}
	body += "]}";
	emit(s, cmd, body.c_str());
}

static void cmd_status(int s, const std::string &cmd)
{
	struct dbgproto_custom_state cs;
	dbgproto_custom_status(&cs);
	const struct gui_info_drive *d0 = &gui_data.drives[0];
	char df0[512];
	json_escape(d0->df, df0, sizeof df0);
	char body[1024];
	snprintf(body, sizeof body,
		"{\"frame\":%ld,\"pc\":\"%x\",\"halt\":%d,\"stopped\":%d,"
		"\"dmacon\":%u,\"intena\":%u,\"intreq\":%u,\"bplcon0\":%u,"
		"\"ddfstrt\":%u,\"ddfstop\":%u,\"diwstrt\":%u,\"diwstop\":%u,"
		"\"coppc\":\"%x\",\"cop1lc\":\"%x\",\"vpos\":%d,"
		"\"motor\":%d,\"cyl\":%d,\"df0\":\"%s\",\"warp\":%d,"
		"\"resets\":%d}",
		frame_counter, m68k_getpc(), regs.halted, regs.stopped ? 1 : 0,
		(unsigned)cs.dmacon, (unsigned)cs.intena, (unsigned)cs.intreq,
		(unsigned)cs.bplcon0, (unsigned)cs.ddfstrt, (unsigned)cs.ddfstop,
		(unsigned)cs.diwstrt, (unsigned)cs.diwstop, cs.coppc, cs.cop1lc, cs.vpos,
		d0->drive_motor ? 1 : 0, d0->drive_track, df0,
		currprefs.turbo_emulation ? 1 : 0,
		reset_counter);
	emit(s, cmd, body);
}

static void cmd_screenshot(int s, const std::string &cmd, const std::string &path)
{
	/* Re-render so the surface reflects the current chipset state (in warp
	 * mode frames may have skipped rendering). */
	render_screen(0, 1, true);
	bool ok = create_screenshot();
	if (ok)
		ok = save_thumb(path) != 0;
	char esc[600];
	json_escape(path.c_str(), esc, sizeof esc);
	char body[700];
	snprintf(body, sizeof body, "{\"ok\":%s,\"path\":\"%s\"}",
		ok ? "true" : "false", esc);
	emit(s, cmd, body);
}

/* shot-new PERMILLE PATH: a screenshot, kept only when more than PERMILLE of
 * every thousand pixels differ from the last one this command kept. */
static void cmd_shot_new(int s, const std::string &cmd, int permille,
	const std::string &path)
{
	render_screen(0, 1, true);
	int changed = 0;
	int kept = create_screenshot() ? save_thumb_if_new(path, permille, &changed) : -1;
	char esc[600];
	json_escape(path.c_str(), esc, sizeof esc);
	char body[700];
	snprintf(body, sizeof body,
		"{\"ok\":%s,\"kept\":%s,\"changed\":%d,\"path\":\"%s\"}",
		kept >= 0 ? "true" : "false", kept > 0 ? "true" : "false", changed, esc);
	emit(s, cmd, body);
}

/* display measure on [os=ADDR] | off: start (from nothing) or stop the
 * measure; ADDR is the system's COP1LC, in hex.
 * display status: what it holds and, of the picture a screenshot would give
 * now, the box of the pixels that are not the border's (``screen``), to set
 * against it. */
static void cmd_display(int s, const std::string &cmd,
	const std::vector<std::string> &t)
{
	if (t.size() >= 3 && t[1] == "measure" && (t[2] == "on" || t[2] == "off")) {
		if (t[2] == "on") {
			disp = {};
			std::string os = kv(t, "os");
			disp.os_cop = os.empty() ? 0 : parse_addr(os);
			disp_new_frame();
		}
		dbgproto_display_on = t[2] == "on";
		emit(s, cmd, "{\"ok\":true}");
		return;
	}
	if (t.size() < 2 || t[1] != "status") {
		emit_error(s, cmd, "usage: display measure on [os=ADDR] | off | status");
		return;
	}
	char buf[256];
	std::string body = dbgproto_display_on ? "{\"on\":true" : "{\"on\":false";
	body += ",\"modes\":[";
	bool first = true;
	for (int i = 0; i < DISP_MODES; i++) {
		const auto &m = disp.mode[i];
		if (!m.frames)
			continue;
		snprintf(buf, sizeof buf, "%s{\"res\":%d,\"lace\":%s,\"os\":%s,"
			"\"frames\":%ld,\"rows\":", first ? "" : ",", i % 3,
			i % 6 >= 3 ? "true" : "false", i >= 6 ? "true" : "false", m.frames);
		body += buf + disp_runs(m.rows) + ",\"cols\":" + disp_runs(m.cols) + "}";
		first = false;
	}
	body += "],\"diw\":[";
	for (size_t i = 0; i < disp.diw.size(); i++) {
		snprintf(buf, sizeof buf, "%s[%u,%u,%ld]", i ? "," : "",
			(unsigned)disp.diw[i].strt, (unsigned)disp.diw[i].stop,
			disp.diw[i].lines);
		body += buf;
	}
	body += disp.more_diw ? "],\"more_diw\":true" : "]";
	render_screen(0, 1, true);
	int w, h, box[4];
	int found = create_screenshot() ? screenshot_box(&w, &h, box) : -1;
	if (found >= 0) {
		snprintf(buf, sizeof buf, ",\"screen\":{\"w\":%d,\"h\":%d", w, h);
		body += buf;
		if (found) {
			snprintf(buf, sizeof buf, ",\"box\":[%d,%d,%d,%d]", box[0], box[1],
				box[2], box[3]);
			body += buf;
		}
		body += "}";
	}
	body += "}";
	emit(s, cmd, body.c_str());
}

static void cmd_load(int s, const std::string &cmd, uaecptr addr,
	const std::string &path)
{
	FILE *f = fopen(path.c_str(), "rb");
	if (!f) {
		emit_error(s, cmd, "cannot open file");
		return;
	}
	long n = 0;
	int c;
	while ((c = fgetc(f)) != EOF) {
		put_byte(addr + (uaecptr)n, (uae_u8)c);
		n++;
	}
	fclose(f);
	char body[96];
	snprintf(body, sizeof body, "{\"ok\":true,\"addr\":\"%x\",\"size\":%ld}",
		addr, n);
	emit(s, cmd, body);
}

static void cmd_disk(int s, const std::string &cmd,
	const std::vector<std::string> &t)
{
	/* swapslot is file-static: `disk swap-next` and autoswap share it */
	if (t.size() >= 2 && t[1] == "swap-next") {
		if (swapslot >= MAX_SPARE_DRIVES || currprefs.dfxlist[swapslot][0] == 0) {
			emit_error(s, cmd, "swap list exhausted");
			return;
		}
		disk_insert(0, currprefs.dfxlist[swapslot]);
		char esc[600];
		json_escape(currprefs.dfxlist[swapslot], esc, sizeof esc);
		swapslot++;
		char body[700];
		snprintf(body, sizeof body,
			"{\"ok\":true,\"unit\":0,\"inserted\":\"%s\"}", esc);
		emit(s, cmd, body);
	} else if (t.size() >= 4 && t[1] == "insert") {
		int unit = (int)parse_num(t[2]);
		/* path is everything after the unit token, spaces preserved */
		size_t pos = cmd.find(t[2]);
		std::string path = cmd.substr(pos + t[2].size() + 1);
		if (unit < 0 || unit > 3) {
			emit_error(s, cmd, "unit out of range");
			return;
		}
		disk_insert(unit, path.c_str());
		char esc[600];
		json_escape(path.c_str(), esc, sizeof esc);
		char body[700];
		snprintf(body, sizeof body,
			"{\"ok\":true,\"unit\":%d,\"inserted\":\"%s\"}", unit, esc);
		emit(s, cmd, body);
	} else if (t.size() >= 2 && t[1] == "status") {
		std::string body = "{\"units\":[";
		for (int i = 0; i < 4; i++) {
			const struct gui_info_drive *d = &gui_data.drives[i];
			char esc[600];
			json_escape(d->df, esc, sizeof esc);
			char one[700];
			snprintf(one, sizeof one,
				"{\"df\":\"%s\",\"motor\":%d,\"cyl\":%d,\"inserted\":%d}%s",
				esc, d->drive_motor ? 1 : 0, d->drive_track,
				d->floppy_inserted ? 1 : 0, i < 3 ? "," : "");
			body += one;
		}
		body += "]}";
		emit(s, cmd, body.c_str());
	} else if (t.size() >= 3 && t[1] == "autoswap") {
		/* disk autoswap on|click|off|status [idle=SECONDS] — arm the
		 * swap-wait detector to auto-insert the next -diskswapper=
		 * entry; "click" adds the one-shot LMB fallback for
		 * insert-and-confirm prompts; idle=N adds the opt-in
		 * drive-idle trigger (Odyssey-class prompts that never touch
		 * the drive); "anycyl" drops that trigger's head-at-cyl-0 gate
		 * (Soul Kitchen parks at cyl 75 behind its LMB prompt);
		 * "static" additionally holds the idle trigger until the display
		 * has not changed for the whole idle period (a prompt is a still
		 * picture, a part playing from RAM animates);
		 * "reread" adds a trigger for waits that re-read the same
		 * track(s) instead of polling (Iso, Big Time Sensuality);
		 * tail=N ends the batch N frames after the last swap-list disk
		 * went in (a sweep need not run out its whole budget);
		 * dead=N ends the batch once nothing has happened for N frames
		 * (no display change, audio or disk DMA): a crash or a frozen
		 * screen need not run out the budget;
		 * "rampolls" ignores /CHNG polls made from Kickstart ROM: the OS's
		 * own trackdisk polling while a DOS-loaded demo plays from RAM
		 * otherwise looks like a wait (Dark Ages, the AMOS megademos);
		 * unit=N swaps into DFN instead of DF0 (Soho wants disks 2 and
		 * 3 in an external drive);
		 * "status" dumps the detector window. */
		if (t[2] == "on")
			autoswap_mode = 1;
		else if (t[2] == "click")
			autoswap_mode = 2;
		else if (t[2] == "off") {
			autoswap_mode = 0;
			autoswap_idle_frames = 0;
			autoswap_idle_anycyl = false;
			autoswap_tail_frames = 0;
			autoswap_reread = false;
			autoswap_idle_static = false;
			autoswap_unit = 0;
			autoswap_ram_polls = false;
			autoswap_dead_frames = 0;
		} else if (t[2] == "status") {
			char body[400];
			snprintf(body, sizeof body,
				"{\"mode\":%d,\"slot\":%d,\"frame\":%ld,"
				"\"window_start\":%ld,\"last_poll\":%ld,\"last_dma\":%ld,"
				"\"window_reads\":%ld,\"window_steps\":%ld,"
				"\"max_dma_cyl\":%d,"
				"\"total_polls\":%ld,\"rom_polls\":%ld,"
				"\"total_steps\":%ld}",
				autoswap_mode, swapslot, frame_counter,
				window_start, last_poll_frame, last_dma_frame,
				window_reads, window_steps, max_dma_cyl,
				total_polls, total_rom_polls, total_steps);
			emit(s, cmd, body);
			return;
		} else {
			emit_error(s, cmd,
				"usage: disk autoswap on|click|off|status [idle=SECONDS]");
			return;
		}
		for (size_t i = 3; i < t.size(); i++) {
			if (t[i].compare(0, 5, "idle=") == 0)
				autoswap_idle_frames = 50 * parse_num(t[i].substr(5));
			else if (t[i] == "anycyl")
				autoswap_idle_anycyl = true;
			else if (t[i] == "static")
				autoswap_idle_static = true;
			else if (t[i] == "reread") {
				autoswap_reread = true;
				reread_reset();
			}
			else if (t[i].compare(0, 5, "tail=") == 0)
				autoswap_tail_frames = parse_num(t[i].substr(5));
			else if (t[i].compare(0, 5, "dead=") == 0)
				autoswap_dead_frames = parse_num(t[i].substr(5));
			else if (t[i] == "rampolls")
				autoswap_ram_polls = true;
			else if (t[i].compare(0, 5, "unit=") == 0) {
				long u = parse_num(t[i].substr(5));
				autoswap_unit = u >= 0 && u <= 3 ? (int)u : 0;
			}
		}
		char body[128];
		snprintf(body, sizeof body,
			"{\"ok\":true,\"autoswap\":%d,\"click\":%d,\"slot\":%d,"
			"\"idle_frames\":%ld}",
			autoswap_mode != 0, autoswap_mode == 2, swapslot,
			autoswap_idle_frames);
		emit(s, cmd, body);
	} else {
		emit_error(s, cmd,
			"usage: disk swap-next | insert UNIT PATH | status | autoswap on|click|off");
	}
}

/* ---- pointer / click sequencer -------------------------------------- */
/* The Amiga mouse is a delta device: JOY0DAT counts quadrature steps and the
 * pointer sits wherever the OS accumulated them, so there is no position to
 * write. `input mouse move X Y` therefore slams the pointer into the
 * top-left corner (a delta wider than any Amiga screen — Intuition clamps at
 * the edge) and walks out to X,Y from there.
 *
 * Motion has to be paced: inputdevice.cpp's mouseupdate moves the emulated
 * counters at most 120 units per frame and DISCARDS the rest (a 240-unit
 * delta arrives as 120), and a reader sees an 8-bit signed difference
 * anyway, so a step injects at most MOUSE_STEP per frame and spreads the
 * rest over following frames. Frames only elapse inside a `run`, so pointer
 * motion and the click helpers queue here and advance one vsync at a time;
 * each command answers with the frames its queue still needs, which is what
 * to hand the `run frames=` that follows. */
#define MOUSE_STEP  100    /* counter units injected per frame (mouseupdate
                              discards anything past 120) */
#define MOUSE_HOME  2048   /* slam distance: past the widest Amiga screen */
#define MOUSE_SETTLE 2     /* frames for the last counts to be read */
#define CLICK_HOLD  6      /* frames a click holds the button down */
#define CLICK_GAP   6      /* frames between the clicks of a double-click;
                              both land well inside Intuition's half-second
                              double-click window */
#define DBG_MAX_ACT 16

enum act_op { ACT_MOVE, ACT_BTN };
struct dbg_act {
	act_op op;
	int a, b;      /* MOVE: dx, dy still to inject.  BTN: button, down */
	long after;    /* frames to idle after the step, before the next one */
};
static dbg_act acts[DBG_MAX_ACT];
static int act_count = 0;      /* steps pushed */
static int act_next = 0;       /* next step to take */
static long act_wait = 0;      /* frames left before that step */

static int act_chunk(int d)
{
	if (d > MOUSE_STEP)
		return MOUSE_STEP;
	if (d < -MOUSE_STEP)
		return -MOUSE_STEP;
	return d;
}

/* Frames a move of dx,dy occupies at MOUSE_STEP per frame. */
static long move_frames(int dx, int dy)
{
	int ax = dx < 0 ? -dx : dx, ay = dy < 0 ? -dy : dy;
	int m = ax > ay ? ax : ay;
	return m > 0 ? (m + MOUSE_STEP - 1) / MOUSE_STEP : 1;
}

/* Room for a command's steps, which are pushed all or nothing: half an
 * absolute move would leave the pointer slammed into the corner. A drained
 * queue is reclaimed here rather than in act_vsync, because a caller that
 * runs exactly the frames a command asked for drains it on the run's last
 * frame — there is no later vsync to notice, and the slots would leak until
 * the queue read as full. Only command context reaches this, between runs,
 * where act_next == act_count means fully drained. */
static bool act_reserve(int steps)
{
	if (act_next >= act_count)
		act_next = act_count = 0;
	return act_count + steps <= DBG_MAX_ACT;
}

static void act_push(act_op op, int a, int b, long after)
{
	acts[act_count].op = op;
	acts[act_count].a = a;
	acts[act_count].b = b;
	acts[act_count].after = after;
	act_count++;
}

/* Frames until the queue is empty — what to hand the next `run frames=`. */
static long act_pending(void)
{
	long n = act_wait;
	for (int i = act_next; i < act_count; i++)
		n += acts[i].after + (acts[i].op == ACT_MOVE
			? move_frames(acts[i].a, acts[i].b) : 1);
	return n;
}

static void act_vsync(void)
{
	if (act_wait > 0) {
		act_wait--;
		return;
	}
	if (act_next >= act_count) {
		act_next = act_count = 0;
		return;
	}
	struct dbg_act *a = &acts[act_next];
	if (a->op == ACT_MOVE) {
		/* Same rule as `joy`: the abstract event path drives the
		 * emulated port, setmousestate() indexes host mouse devices a
		 * headless run does not have. */
		int dx = act_chunk(a->a), dy = act_chunk(a->b);
		send_input_event(INPUTEVENT_MOUSE1_HORIZ, dx, 0, 0);
		send_input_event(INPUTEVENT_MOUSE1_VERT, dy, 0, 0);
		a->a -= dx;
		a->b -= dy;
		if (a->a || a->b)
			return;
	} else {
		setmousebuttonstate(0, a->a, a->b);
	}
	act_next++;
	act_wait = a->after;
}

static void cmd_input(int s, const std::string &cmd,
	const std::vector<std::string> &t)
{
	/* input mouse BTN down|up   — BTN 0=left 1=right 2=middle
	 * input mouse move X Y      — absolute, in pointer units (mouse counter
	 *                             steps: a hires Workbench screen is 1:1
	 *                             across and 2:1 down)
	 * input mouse rel DX DY     — relative
	 * input mouse click BTN     — a press/release pair
	 * input mouse doubleclick BTN
	 * input joy PORT BTN down|up
	 * input key CODE down|up    — CODE is an Amiga rawkey code
	 * Button and key state changes land on the emulated hardware
	 * immediately; sequence them around `run frames=N` commands to model
	 * press durations. Pointer motion and the click helpers queue instead
	 * (see the sequencer above) and report the frames they need. */
	auto is_down = [](const std::string &w) { return w == "down"; };
	if (t.size() >= 4 && t[1] == "mouse" &&
			(t[2] == "move" || t[2] == "rel")) {
		if (t.size() < 5) {
			emit_error(s, cmd, "usage: input mouse move|rel X Y");
			return;
		}
		int x = (int)parse_num(t[3]), y = (int)parse_num(t[4]);
		bool absolute = t[2] == "move";
		if (absolute && (x < 0 || y < 0)) {
			emit_error(s, cmd, "move: X and Y must be >= 0");
			return;
		}
		if (!act_reserve(absolute ? 2 : 1)) {
			emit_error(s, cmd, "input queue full");
			return;
		}
		if (absolute)
			act_push(ACT_MOVE, -MOUSE_HOME, -MOUSE_HOME, 0);
		act_push(ACT_MOVE, x, y, MOUSE_SETTLE);
		char body[96];
		snprintf(body, sizeof body,
			"{\"ok\":true,\"%s\":[%d,%d],\"frames\":%ld}",
			t[2].c_str(), x, y, act_pending());
		emit(s, cmd, body);
	} else if (t.size() >= 3 && t[1] == "mouse" &&
			(t[2] == "click" || t[2] == "doubleclick")) {
		int btn = t.size() >= 4 ? (int)parse_num(t[3]) : 0;
		int clicks = t[2] == "click" ? 1 : 2;
		if (!act_reserve(2 * clicks)) {
			emit_error(s, cmd, "input queue full");
			return;
		}
		for (int i = 0; i < clicks; i++) {
			act_push(ACT_BTN, btn, 1, CLICK_HOLD);
			act_push(ACT_BTN, btn, 0, CLICK_GAP);
		}
		char body[96];
		snprintf(body, sizeof body,
			"{\"ok\":true,\"%s\":%d,\"frames\":%ld}",
			t[2].c_str(), btn, act_pending());
		emit(s, cmd, body);
	} else if (t.size() >= 4 && t[1] == "mouse") {
		int btn = (int)parse_num(t[2]);
		setmousebuttonstate(0, btn, is_down(t[3]) ? 1 : 0);
		char body[64];
		snprintf(body, sizeof body,
			"{\"ok\":true,\"mouse\":%d,\"down\":%d}", btn, is_down(t[3]));
		emit(s, cmd, body);
	} else if (t.size() >= 5 && t[1] == "joy") {
		/* Inject through the abstract INPUTEVENT_JOYn_* events, not
		 * setjoybuttonstate(): that call indexes HOST joystick devices,
		 * and a headless run has none, so it was a silent no-op. The
		 * event path drives the emulated gameport directly. BTN is a
		 * number (0=fire 1=2nd 2=3rd) or one of
		 * fire|2nd|3rd|up|down|left|right. */
		int port = (int)parse_num(t[2]);
		const std::string &b = t[3];
		static const int ev1[] = { INPUTEVENT_JOY1_FIRE_BUTTON,
			INPUTEVENT_JOY1_2ND_BUTTON, INPUTEVENT_JOY1_3RD_BUTTON,
			INPUTEVENT_JOY1_UP, INPUTEVENT_JOY1_DOWN,
			INPUTEVENT_JOY1_LEFT, INPUTEVENT_JOY1_RIGHT };
		static const int ev2[] = { INPUTEVENT_JOY2_FIRE_BUTTON,
			INPUTEVENT_JOY2_2ND_BUTTON, INPUTEVENT_JOY2_3RD_BUTTON,
			INPUTEVENT_JOY2_UP, INPUTEVENT_JOY2_DOWN,
			INPUTEVENT_JOY2_LEFT, INPUTEVENT_JOY2_RIGHT };
		int idx;
		if (b == "fire") idx = 0;
		else if (b == "2nd") idx = 1;
		else if (b == "3rd") idx = 2;
		else if (b == "up") idx = 3;
		else if (b == "down") idx = 4;
		else if (b == "left") idx = 5;
		else if (b == "right") idx = 6;
		else idx = (int)parse_num(b);
		if (port < 0 || port > 1 || idx < 0 || idx > 6) {
			emit_error(s, cmd, "joy: PORT is 0|1, BTN is 0-2 or fire|2nd|3rd|up|down|left|right");
			return;
		}
		send_input_event((port == 0 ? ev1 : ev2)[idx],
			is_down(t[4]) ? 1 : 0, 1, 0);
		char body[96];
		snprintf(body, sizeof body,
			"{\"ok\":true,\"joy\":%d,\"button\":\"%s\",\"down\":%d}",
			port, b.c_str(), is_down(t[4]));
		emit(s, cmd, body);
	} else if (t.size() >= 4 && t[1] == "key") {
		int code = (int)parse_num(t[2]);
		inputdevice_do_keyboard(code, is_down(t[3]) ? 1 : 0);
		char body[64];
		snprintf(body, sizeof body,
			"{\"ok\":true,\"key\":%d,\"down\":%d}", code, is_down(t[3]));
		emit(s, cmd, body);
	} else {
		emit_error(s, cmd,
			"usage: input mouse BTN down|up | mouse move|rel X Y | "
			"mouse click|doubleclick [BTN] | joy PORT BTN down|up | "
			"key CODE down|up");
	}
}

static void cmd_bp(int s, const std::string &cmd,
	const std::vector<std::string> &t)
{
	if (t.size() >= 3 && t[1] == "set") {
		if (bp_count >= DBG_MAX_BP) {
			emit_error(s, cmd, "too many breakpoints");
			return;
		}
		bps[bp_count++] = parse_addr(t[2]);
		char body[64];
		snprintf(body, sizeof body, "{\"ok\":true,\"addr\":\"%x\"}",
			bps[bp_count - 1]);
		emit(s, cmd, body);
	} else if (t.size() >= 3 && t[1] == "clear") {
		uaecptr a = parse_addr(t[2]);
		int found = 0;
		for (int i = 0; i < bp_count; i++) {
			if (bps[i] == a) {
				bps[i] = bps[--bp_count];
				found = 1;
				break;
			}
		}
		char body[80];
		snprintf(body, sizeof body, "{\"ok\":%s,\"addr\":\"%x\"}",
			found ? "true" : "false", a);
		emit(s, cmd, body);
	} else {
		emit_error(s, cmd, "usage: bp set|clear ADDR");
	}
	update_instr_gate();
}

static void watch_capture(void)
{
	for (int i = 0; i < watch_size; i++)
		watch_snap[i] = (uae_u8)get_byte(watch_addr + (uaecptr)i);
}

static void cmd_watch(int s, const std::string &cmd,
	const std::vector<std::string> &t)
{
	if (t.size() >= 4 && t[1] == "set") {
		long size = parse_num(t[3]);
		if (size < 1 || size > DBG_MAX_WATCH) {
			char msg[64];
			snprintf(msg, sizeof msg, "size out of range (1..%d)",
				DBG_MAX_WATCH);
			emit_error(s, cmd, msg);
			return;
		}
		watch_addr = parse_addr(t[2]);
		watch_size = (int)size;
		watch_capture();
		char body[80];
		snprintf(body, sizeof body,
			"{\"ok\":true,\"addr\":\"%x\",\"size\":%d}",
			watch_addr, watch_size);
		emit(s, cmd, body);
	} else if (t.size() >= 2 && t[1] == "clear") {
		watch_size = 0;
		emit(s, cmd, "{\"ok\":true}");
	} else {
		emit_error(s, cmd, "usage: watch set ADDR SIZE | watch clear");
	}
	update_instr_gate();
}

/* ---- the dispatcher -------------------------------------------------- */

/* Process commands until a `run` starts or the batch ends. Called from the
 * instruction hook (initial dispatch, breakpoint hit) and from the vsync
 * hook (frame countdown / audio-dma / run budget exhausted). */
static void dispatch(void)
{
	while (run_active == RUN_NONE && !finished) {
		if (next_cmd >= commands.size()) {
			quit_batch();
			return;
		}
		const std::string cmd = commands[next_cmd++];
		const int s = ++seq;
		std::vector<std::string> t = tokenize(cmd);
		if (t.empty()) {
			emit_error(s, cmd, "empty command");
		} else if (t[0] == "warp") {
			int on = t.size() >= 2 && t[1] == "on" ? 1 : 0;
			warpmode(on);
			char body[32];
			snprintf(body, sizeof body, "{\"warp\":%d}", on);
			emit(s, cmd, body);
		} else if (t[0] == "run") {
			std::string until = kv(t, "until");
			std::string frames = kv(t, "frames");
			std::string max = kv(t, "max");
			if (!frames.empty()) {
				start_run(RUN_FRAMES, parse_num(frames), cmd, s);
			} else if (until == "bp") {
				long m = max.empty() ? 60000 : parse_num(max);
				start_run(RUN_BP, m, cmd, s);
			} else if (until == "audio-dma") {
				long m = max.empty() ? 60000 : parse_num(max);
				start_run(RUN_AUDIO, m, cmd, s);
			} else if (until == "watch") {
				long m = max.empty() ? 60000 : parse_num(max);
				watch_capture();  /* ignore changes made before the run */
				start_run(RUN_WATCH, m, cmd, s);
			} else {
				emit_error(s, cmd,
					"usage: run frames=N | until=bp|audio-dma|watch max=N");
			}
		} else if (t[0] == "peek" && t.size() >= 3) {
			cmd_peek(s, cmd, parse_addr(t[1]), parse_num(t[2]));
		} else if (t[0] == "regs") {
			cmd_regs(s, cmd);
		} else if (t[0] == "status") {
			cmd_status(s, cmd);
		} else if (t[0] == "screenshot" && t.size() >= 2) {
			cmd_screenshot(s, cmd, cmd.substr(cmd.find(' ') + 1));
		} else if (t[0] == "shot-new" && t.size() >= 3) {
			size_t p = cmd.find(t[1]) + t[1].size() + 1;
			cmd_shot_new(s, cmd, (int)parse_num(t[1]), cmd.substr(p));
		} else if (t[0] == "bp") {
			cmd_bp(s, cmd, t);
		} else if (t[0] == "watch") {
			cmd_watch(s, cmd, t);
		} else if (t[0] == "disasm" && t.size() >= 2) {
			cmd_disasm(s, cmd, parse_addr(t[1]),
				t.size() >= 3 ? parse_num(t[2]) : 16);
		} else if (t[0] == "load" && t.size() >= 3) {
			/* load ADDR PATH — path is the remainder, spaces preserved */
			size_t p = cmd.find(t[1]) + t[1].size() + 1;
			cmd_load(s, cmd, parse_addr(t[1]), cmd.substr(p));
		} else if (t[0] == "disk") {
			cmd_disk(s, cmd, t);
		} else if (t[0] == "display") {
			cmd_display(s, cmd, t);
		} else if (t[0] == "input") {
			cmd_input(s, cmd, t);
		} else {
			emit_error(s, cmd, "unknown command");
		}
	}
}

/* ---- hooks ------------------------------------------------------------ */

void dbgproto_add_command(const char *cmd)
{
	commands.push_back(cmd);
	dbgproto_active = 1;
	dbgproto_instr_gate = 1; /* force initial dispatch at first instruction */
}

void dbgproto_instr(uaecptr pc)
{
	if (!started) {
		started = true;
		dispatch();
		return;
	}
	if (run_active == RUN_BP) {
		for (int i = 0; i < bp_count; i++) {
			if (bps[i] == pc) {
				finish_run("bp");
				dispatch();
				return;
			}
		}
	} else if (run_active == RUN_WATCH) {
		uae_u8 now[DBG_MAX_WATCH];
		for (int i = 0; i < watch_size; i++)
			now[i] = (uae_u8)get_byte(watch_addr + (uaecptr)i);
		if (memcmp(now, watch_snap, (size_t)watch_size) == 0)
			return;
		std::string was, is;
		static const char hexd[] = "0123456789abcdef";
		for (int i = 0; i < watch_size; i++) {
			was += hexd[watch_snap[i] >> 4];
			was += hexd[watch_snap[i] & 15];
			is += hexd[now[i] >> 4];
			is += hexd[now[i] & 15];
		}
		memcpy(watch_snap, now, (size_t)watch_size);
		/* pc is the instruction about to run, i.e. the one after the store */
		fprintf(stdout,
			"{\"event\":\"watch\",\"frame\":%ld,\"addr\":\"%x\","
			"\"pc\":\"%x\",\"was\":\"%s\",\"is\":\"%s\"}\n",
			frame_counter, watch_addr, pc, was.c_str(), is.c_str());
		fflush(stdout);
		finish_run("watch");
		dispatch();
		return;
	}
}

/* ---- swap-wait detector (see state block at top) -------------------- */

/* Kickstart ROM (and the extended ROM area): a poll from here is
 * trackdisk.device, which checks for disk changes every ~2 s on its own
 * whenever the OS runs. A trackloader polls from its own code in RAM. */
static bool pc_in_rom(uae_u32 pc)
{
	return pc >= 0xe00000 && pc < 0x1000000;
}

void dbgproto_note_chng_poll(uae_u32 pc)
{
	total_polls++;
	if (pc_in_rom(pc)) {
		total_rom_polls++;
		if (autoswap_ram_polls)
			return;
	}
	chng_polls_frame++;
}

void dbgproto_note_disk_step(void)
{
	steps_frame++;
	total_steps++;
}

static void reread_reset(void)
{
	for (int i = 0; i < REREAD_CYLS; i++)
		cyl_last_dma[i] = -1;
	reread_progress_frame = frame_counter;
	reread_dmas = 0;
}

void dbgproto_note_disk_dma(int cyl)
{
	if (cyl >= 0 && cyl < REREAD_CYLS) {
		if (cyl_last_dma[cyl] < 0 ||
				frame_counter - cyl_last_dma[cyl] > SWAP_REREAD_FORGET) {
			reread_progress_frame = frame_counter;
			reread_dmas = 0;
		} else {
			reread_dmas++;
		}
		cyl_last_dma[cyl] = frame_counter;
	}
	last_dma_frame = frame_counter;
	if (cyl >= SWAP_STREAM_CYL)
		last_stream_frame = frame_counter;
	if (cyl > max_dma_cyl)
		max_dma_cyl = cyl;
}

static void swap_emit_event(const char *name, const char *extra)
{
	fprintf(stdout,
		"{\"event\":\"%s\",\"frame\":%ld,\"reads\":%ld,\"steps\":%ld%s}\n",
		name, frame_counter, window_reads, window_steps,
		extra ? extra : "");
	fflush(stdout);
}

static void swap_do_autoswap(void)
{
	if (swapslot >= MAX_SPARE_DRIVES ||
			currprefs.dfxlist[swapslot][0] == 0) {
		/* one-shot: after the last disk is in, its own presence-monitor
		 * phases keep firing the detector (The Last Drop disk 3: a
		 * window every ~2000 frames of playback) — reporting the empty
		 * list once is enough */
		static bool exhausted_emitted = false;
		if (!exhausted_emitted) {
			exhausted_emitted = true;
			swap_emit_event("autoswap-exhausted", NULL);
		}
		return;
	}
	_tcsncpy(swap_prev_disk, currprefs.floppyslots[autoswap_unit].df,
		sizeof swap_prev_disk - 1);
	disk_insert(autoswap_unit, currprefs.dfxlist[swapslot]);
	char esc[600], extra[700];
	json_escape(currprefs.dfxlist[swapslot], esc, sizeof esc);
	snprintf(extra, sizeof extra,
		",\"inserted\":\"%s\",\"slot\":%d", esc, swapslot);
	swapslot++;
	swap_emit_event("autoswap", extra);
	if (autoswap_tail_frames > 0 && (swapslot >= MAX_SPARE_DRIVES ||
			currprefs.dfxlist[swapslot][0] == 0))
		autoswap_stop_frame = frame_counter + autoswap_tail_frames;
	autoswap_insert_frame = frame_counter;
	swap_pending_verify = true;
	reread_reset();
	/* the pre-insert window belongs to the old disk's wait; reset so any
	 * window that reforms is post-insert evidence (see the rollback) */
	window_start = -1;
	window_reads = window_steps = 0;
	window_poll_frames = 0;
	/* Disarm until the NEW disk has streamed past SWAP_MIN_STREAM_CYL.
	 * Accepting a swap involves a step-and-poll latch-clear burst plus a
	 * cyl-0 ID read with long DMA-quiet gaps — without this the detector
	 * re-fired ~500 frames after an insert and burned the rest of the
	 * swap list (The Last Drop, Odyssey). */
	max_dma_cyl = -1;
	if (autoswap_mode == 2)
		click_state = 1;
}

/* Sparse hash of the emulated display (every 4th row, every 8th pixel). */
static uint32_t display_hash(void)
{
	SDL_Surface *sf = get_amiga_surface(0);
	if (!sf || !sf->pixels)
		return 0;
	uint32_t h = 2166136261u;
	const int bpp = SDL_BYTESPERPIXEL(sf->format);
	for (int y = 0; y < sf->h; y += 4) {
		const uint8_t *row = (const uint8_t *)sf->pixels + (size_t)y * sf->pitch;
		for (int x = 0; x < sf->w; x += 8) {
			for (int b = 0; b < bpp; b++)
				h = (h ^ row[x * bpp + b]) * 16777619u;
		}
	}
	return h;
}

static void swap_vsync(void)
{
	if ((autoswap_idle_static || autoswap_dead_frames > 0) &&
			frame_counter % SCREEN_SAMPLE_FRAMES == 0) {
		uint32_t h = display_hash();
		if (h != screen_hash || screen_change_frame < 0) {
			screen_hash = h;
			screen_change_frame = frame_counter;
		}
	}
	bool dma_quiet = !(last_dma_frame >= 0 &&
		frame_counter - last_dma_frame < SWAP_DMA_QUIET);
	bool stream_quiet = !(last_stream_frame >= 0 &&
		frame_counter - last_stream_frame < SWAP_DMA_QUIET);
	bool armed = max_dma_cyl >= SWAP_MIN_STREAM_CYL;

	/* Insert verification: accepted = the demo streamed the new disk;
	 * no streaming for SWAP_REJECT_FRAMES = rejected (it ID-checked once
	 * and went back to polling for the old disk — The Last Drop's in-play
	 * presence monitor) -> restore the old disk and roll the slot back;
	 * the demo re-accepts it on its own and the wait, if it was real,
	 * re-fires after SWAP_RETRY_DELAY. */
	if (swap_pending_verify) {
		if (last_stream_frame > autoswap_insert_frame) {
			swap_pending_verify = false;
		} else if (window_start > autoswap_insert_frame &&
				frame_counter - last_poll_frame <= SWAP_POLL_GAP &&
				frame_counter - window_start >= SWAP_REJECT_FRAMES) {
			swap_pending_verify = false;
			swapslot--;
			autoswap_stop_frame = -1;
			disk_insert(autoswap_unit, swap_prev_disk);
			swap_retry_after = frame_counter + SWAP_RETRY_DELAY;
			swap_event_emitted = false;
			click_state = 0;
			/* we were armed when we fired; restore that, or a real
			 * wait mistakenly rolled back (no streaming ever again)
			 * could never re-fire */
			max_dma_cyl = SWAP_MIN_STREAM_CYL;
			/* restore churns the latch too; start clean */
			window_start = -1;
			window_reads = window_steps = 0;
			window_poll_frames = 0;
			char esc[600], extra[700];
			json_escape(swap_prev_disk, esc, sizeof esc);
			snprintf(extra, sizeof extra,
				",\"restored\":\"%s\",\"slot\":%d", esc, swapslot);
			swap_emit_event("autoswap-rollback", extra);
		}
	}

	/* A pending click is only cancelled once the inserted disk actually
	 * streams (re-arms) — an ID-check DMA burst at cyl 0 must not
	 * suppress the confirm press (Odyssey reads the new disk's ID but
	 * still waits for LMB). */
	if ((click_state == 1 || click_state == 3) && armed)
		click_state = 0;

	if (!stream_quiet) {
		/* loading: reset the window and rearm for the next swap. Only
		 * streaming DMA (cyl >= SWAP_STREAM_CYL) resets — 9 Fingers
		 * re-reads track 0 every ~100 frames while waiting, and that
		 * must not restart the confirmation clock. */
		window_start = -1;
		window_reads = window_steps = 0;
		window_poll_frames = 0;
		swap_event_emitted = false;
	} else {
		if (chng_polls_frame > 0) {
			if (window_start < 0 ||
					frame_counter - last_poll_frame > SWAP_POLL_GAP) {
				window_start = frame_counter;
				window_reads = window_steps = 0;
				window_poll_frames = 0;
			}
			last_poll_frame = frame_counter;
			window_poll_frames++;
			window_reads += chng_polls_frame;
		}
		if (window_start >= 0)
			window_steps += steps_frame;
	}

	/* A swap wait is a poll window (max gap SWAP_POLL_GAP) sustained for
	 * SWAP_WAIT_CONFIRM frames with no streaming DMA. Poll density and
	 * head steps discriminate nothing: loaders emit mid-disk bursts of
	 * every shape (The Last Drop, Odyssey disk checks), but those always
	 * die when streaming resumes — only a real wait outlives 10 s. */
	bool window_live = window_start >= 0 &&
		frame_counter - last_poll_frame <= SWAP_POLL_GAP;
	bool poll_hit = armed && window_live &&
		frame_counter - window_start >= SWAP_WAIT_CONFIRM &&
		window_poll_frames >= SWAP_MIN_POLL_FRAMES;

	/* Opt-in idle trigger (`disk autoswap ... idle=SECONDS`) for demos
	 * that show a prompt without touching the drive at all — Odyssey
	 * waits for LMB and only then interrogates the disk. Riskier than
	 * poll detection (Odyssey's disk A has 60 s mid-disk lulls with the
	 * head parked at cyl 8/49), hence opt-in AND further gated on the
	 * prompt signature: df0 retracted to cyl 0, motor off. */
	const struct gui_info_drive *gd0 = &gui_data.drives[autoswap_unit];
	long last_activity = last_dma_frame > last_poll_frame
		? last_dma_frame : last_poll_frame;
	bool idle_hit = autoswap_idle_frames > 0 && armed &&
		dma_quiet && last_activity >= 0 &&
		frame_counter - last_activity >= autoswap_idle_frames &&
		(gd0->drive_track == 0 || autoswap_idle_anycyl) &&
		!gd0->drive_motor &&
		(!autoswap_idle_static ||
		 frame_counter - screen_change_frame >= autoswap_idle_frames);

	/* Opt-in reread trigger: DMA keeps going (last start within the poll
	 * gap) for SWAP_REREAD_CONFIRM frames without touching a cylinder that
	 * was not read recently. Streaming always reaches new cylinders. */
	bool reread_hit = autoswap_reread && armed &&
		reread_progress_frame >= 0 &&
		frame_counter - reread_progress_frame >= SWAP_REREAD_CONFIRM &&
		frame_counter - last_dma_frame <= SWAP_POLL_GAP &&
		reread_dmas >= SWAP_REREAD_MIN_DMAS;

	if (!swap_event_emitted && !swap_pending_verify &&
			frame_counter >= swap_retry_after &&
			(poll_hit || idle_hit || reread_hit)) {
		swap_event_emitted = true;
		swap_emit_event(poll_hit ? "swap-poll" : idle_hit ? "swap-idle"
			: "swap-reread", NULL);
		if (autoswap_mode)
			swap_do_autoswap();
	}

	/* LMB fallback: the insert did not lead to streaming (an ID check at
	 * cyl 0 alone does not count — max_dma_cyl was reset at insert), so
	 * the demo is presumably an insert-and-confirm prompt (Odyssey). One
	 * press per swap, then one RMB press if that did not do it either
	 * (Lethal Dose 2 confirms its disk on the right button). */
	if (click_state == 1 && autoswap_insert_frame >= 0 &&
			frame_counter - autoswap_insert_frame >= SWAP_CLICK_DELAY &&
			!armed) {
		setmousebuttonstate(0, 0, 1);
		click_state = 2;
		click_down_frame = frame_counter;
	} else if (click_state == 2 &&
			frame_counter - click_down_frame >= SWAP_CLICK_HOLD) {
		setmousebuttonstate(0, 0, 0);
		click_state = 3;
		swap_emit_event("autoswap-click", NULL);
	} else if (click_state == 3 &&
			frame_counter - autoswap_insert_frame >= 2 * SWAP_CLICK_DELAY &&
			!armed) {
		setmousebuttonstate(0, 1, 1);
		click_state = 4;
		click_down_frame = frame_counter;
	} else if (click_state == 4 &&
			frame_counter - click_down_frame >= SWAP_CLICK_HOLD) {
		setmousebuttonstate(0, 1, 0);
		click_state = 0;
		swap_emit_event("autoswap-click-right", NULL);
	}

	chng_polls_frame = 0;
	steps_frame = 0;
}

void dbgproto_note_cpu_reset(void)
{
	reset_counter++;
}

/* dead=N: true (batch ended) once the display, audio DMA and disk DMA
 * have all been still for N frames. Sampled with the screen hash. */
static bool dead_end(void)
{
	if (autoswap_dead_frames <= 0 || frame_counter % SCREEN_SAMPLE_FRAMES)
		return false;
	struct dbgproto_custom_state cs;
	dbgproto_custom_status(&cs);
	if ((cs.dmacon & 0x200) && (cs.dmacon & 0x00f))
		last_audio_frame = frame_counter;
	long last = screen_change_frame;
	if (last_dma_frame > last)
		last = last_dma_frame;
	if (last_audio_frame > last)
		last = last_audio_frame;
	if (last < 0 || frame_counter - last < autoswap_dead_frames)
		return false;
	swap_emit_event("dead-end", NULL);
	quit_batch();
	return true;
}

void dbgproto_vsync(void)
{
	if (!dbgproto_active || finished)
		return;
	frame_counter++;
	if (dbgproto_display_on)
		disp_vsync();
	act_vsync();
	swap_vsync();
	if (dead_end())
		return;
	if (autoswap_stop_frame >= 0 && frame_counter >= autoswap_stop_frame) {
		autoswap_stop_frame = -1;
		swap_emit_event("autoswap-tail-end", NULL);
		quit_batch();
		return;
	}
	if (run_active == RUN_NONE)
		return;
	run_elapsed++;
	if (run_active == RUN_FRAMES && run_elapsed >= run_max) {
		finish_run("frames");
		dispatch();
	} else if (run_elapsed >= run_max) {
		/* until=bp / until=audio-dma budget exhausted */
		finish_run("frames");
		dispatch();
	}
}

void dbgproto_audio_dma(void)
{
	if (run_active == RUN_AUDIO) {
		finish_run("audio-dma");
		dispatch();
	}
}

void dbgproto_halt(int id)
{
	if (!dbgproto_active || halted_emitted)
		return;
	halted_emitted = true;
	fprintf(stdout,
		"{\"event\":\"halt\",\"reason\":%d,\"pc\":\"%x\",\"frame\":%ld}\n",
		id, m68k_getpc(), frame_counter);
	fflush(stdout);
	dbgproto_exit_code = 2;
	quit_batch();
}
