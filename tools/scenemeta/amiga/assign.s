; Tiny C:Assign for KS1.2+ (68000, position independent).
; Arguments: name: path, either token optionally quoted; "" means current dir.
; No REMOVE/ADD/LATE/DEFER support. Return 0 on success, 20 on failure.
; Rebuild raw code (embedded in workbench.py):
;   vasmm68k_mot -m68000 -Fbin -o assign.bin assign.s
; V36+ uses AssignLock. Older DOS uses a DLT_DIRECTORY DosList node:
; dl_Root=34, rn_Info=24 (BPTR), di_DevInfo=4 (BPTR);
; dol_Next=0, Type=4, Task=8, Lock=12, Name=40 (BSTR), sizeof=44;
; fl_Task=12. Exec Forbid/Permit protects only lookup + publication.
; Locks/allocations are acquired before Forbid and released after Permit.
; An existing directory assign is updated in place; devices/volumes fail.
; On success DOS owns the new lock, node and BSTR. All failures release them.
        movem.l d2-d7/a2-a6,-(sp)
        move.l  a0,a2
        move.l  4.w,a6
        lea     dosname(pc),a1
        moveq   #0,d0
        jsr     -552(a6)             ; OpenLibrary
        move.l  d0,d6
        beq     bad
        move.l  d0,a6
; Parse name, strip quotes and colon; keep its length for a BCPL name.
spaces: cmp.b   #32,(a2)+
        beq.s   spaces
        subq.l  #1,a2
        moveq   #0,d4
        cmp.b   #34,(a2)
        bne.s   name_start
        moveq   #34,d4
        addq.l  #1,a2
name_start:
        move.l  a2,a3
        moveq   #0,d7
name:   moveq   #0,d0
        move.b  (a2)+,d0
        cmp.b   #58,d0
        beq.s   colon
        cmp.b   #32,d0
        bcs     close_bad
        bne.s   name_char
        tst.b   d4
        beq     close_bad
name_char:
        cmp.b   #34,d0
        beq     close_bad
        addq.w  #1,d7
        cmp.w   #255,d7
        bls.s   name
        bra     close_bad
colon:  tst.w   d7
        beq     close_bad
        clr.b   -1(a2)
        tst.b   d4
        beq.s   path_space
        cmp.b   (a2)+,d4
        bne     close_bad
path_space:
        cmp.b   #32,(a2)+
        beq.s   path_space
        subq.l  #1,a2
        cmp.b   #34,(a2)
        bne.s   bare
        addq.l  #1,a2
        move.l  a2,d1
quoted: move.b  (a2)+,d0
        cmp.b   #34,d0
        beq.s   path_end
        cmp.b   #32,d0
        bcc.s   quoted
        bra     close_bad
bare:   move.l  a2,d1
word:   cmp.b   #32,(a2)+
        bhi.s   word
path_end:
        clr.b   -1(a2)
        moveq   #-2,d2
        jsr     -84(a6)              ; Lock
        move.l  d0,d5
        beq     close_bad
        cmp.w   #36,20(a6)
        bcs.s   legacy
        move.l  a3,d1
        move.l  d5,d2
        jsr     -612(a6)             ; AssignLock
        tst.l   d0
        bne     close_ok
        bra     unlock_bad
legacy:
; Allocate node + name separately so normal DOS cleanup can free each.
        move.l  4.w,a6
        moveq   #44,d0
        move.l  #$10001,d1           ; MEMF_PUBLIC | MEMF_CLEAR
        jsr     -198(a6)             ; AllocMem
        move.l  d0,a4
        tst.l   d0
        beq     unlock_bad
        moveq   #0,d0
        move.w  d7,d0
        addq.l  #2,d0
        moveq   #1,d1                ; MEMF_PUBLIC
        jsr     -198(a6)
        move.l  d0,a5
        tst.l   d0
        beq     free_node
        move.l  a5,a0
        move.b  d7,(a0)+
        move.l  a3,a1
copy:   move.b  (a1)+,(a0)+
        bne.s   copy
        move.l  a5,d0
        lsr.l   #2,d0
        move.l  d0,40(a4)
        move.l  #1,4(a4)             ; DLT_DIRECTORY
        move.l  d5,12(a4)
        move.l  d5,d0
        lsl.l   #2,d0
        move.l  d0,a0
        move.l  12(a0),8(a4)         ; fl_Task
        jsr     -132(a6)             ; Forbid
        move.l  d6,a0
        move.l  34(a0),a0            ; dl_Root (APTR)
        move.l  24(a0),d0            ; rn_Info (BPTR)
        lsl.l   #2,d0
        move.l  d0,a2
        move.l  4(a2),d2
next:   tst.l   d2
        beq.s   publish
        move.l  d2,d0
        lsl.l   #2,d0
        move.l  d0,a0
        move.l  40(a0),d0
        lsl.l   #2,d0
        move.l  d0,a1
        cmp.b   (a1)+,d7
        bne.s   advance
        move.l  a3,a5
compare:
        move.b  (a5)+,d0
        beq.s   found
        move.b  (a1)+,d1
        bsr     fold
        cmp.b   d0,d1
        beq.s   compare
advance:
        move.l  (a0),d2
        bra.s   next
found:  cmp.l   #1,4(a0)
        bne.s   collision
        move.l  12(a0),d5            ; release previous lock after Permit
        move.l  12(a4),12(a0)
        move.l  8(a4),8(a0)
        jsr     -138(a6)             ; Permit
        bsr.s   free_alloc
        move.l  d6,a6
        move.l  d5,d1
        jsr     -90(a6)              ; UnLock old lock
        bra     close_ok
publish:
        move.l  4(a2),(a4)
        move.l  a4,d0
        lsr.l   #2,d0
        move.l  d0,4(a2)
        jsr     -138(a6)             ; Permit (DOS now owns allocations)
        bra     close_ok
collision:
        jsr     -138(a6)             ; Permit
        bsr.s   free_alloc
        bra.s   unlock_bad
; Free the unpublished node and its name (pointer recovered from node).
free_alloc:
        move.l  40(a4),d0
        lsl.l   #2,d0
        move.l  d0,a1
        moveq   #0,d0
        move.w  d7,d0
        addq.l  #2,d0
        jsr     -210(a6)             ; FreeMem name
        move.l  a4,a1
        moveq   #44,d0
        jmp     -210(a6)             ; FreeMem node
free_node:
        move.l  a4,a1
        moveq   #44,d0
        jsr     -210(a6)
unlock_bad:
        move.l  d6,a6
        move.l  d5,d1
        jsr     -90(a6)
close_bad:
        moveq   #20,d7
        bra.s   close
close_ok:
        moveq   #0,d7
close:  move.l  d6,a1
        move.l  4.w,a6
        jsr     -414(a6)             ; CloseLibrary
        move.l  d7,d0
        bra.s   done
bad:    moveq   #20,d0
done:   movem.l (sp)+,d2-d7/a2-a6
        rts
; Fold ASCII letters only; punctuation must keep its identity.
fold:   cmp.b   #97,d0
        bcs.s   fold1
        cmp.b   #122,d0
        bhi.s   fold1
        sub.b   #32,d0
fold1:  cmp.b   #97,d1
        bcs.s   folded
        cmp.b   #122,d1
        bhi.s   folded
        sub.b   #32,d1
folded: rts
 dosname: dc.b 'dos.library',0
        even
