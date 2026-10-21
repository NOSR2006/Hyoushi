"""Replay the live corrector over every round that recorded its probe frames.

research/runs/dets_*.json carries the note-blob frames a round's probe thread saw, plus the t0 and
offset its corrector ran under -- so LiveCorrector can be run again over exactly the evidence it saw
live. This is how VOTE_MARGIN was picked: replayed over all 26 dumps, margin 2 drops g239's poisoned
-45 ms commit and moves nothing else but g228 (whose last two steps were themselves one-vote pairs).
A vote rule cannot be argued about, only replayed, and this is the replay.

2026-10-07 moved the rule again, and the same replay is why. Margin 2 still let g458 through: a
window on 0056_03's 41-52 s stretch -- a 157 ms-spaced tap staircase where the tap mask sees two or
three blobs a frame -- agreed on -163 ms with 12 votes against a runner-up of 9, committed the full
-45 ms step, and the remaining 204 judged objects all landed GREAT-FAST. So the shipped rules are now a two-tier
margin (VOTE_MARGIN = 2 for a move up to SMALL_MOVE_MS = 15, VOTE_MARGIN_BIG = 4 past it) plus
CORR_TRUST_MS = 50 (see player.py for the corpus numbers behind all three).

The verdict is a regression with its own counterfactual, and it is relative to the corpus rather
than to a hard-coded count: every dump is replayed twice -- once under the shipped rails and once
under the pre-2026-10-07 rules (a flat margin 2, no drift rail) -- and the rounds that commit must differ by
exactly the two alias rounds, with no round *gaining* a commit and no round ending further than the
trusted drift from its nominal clock. On this corpus the margin is what catches both aliases; the
drift rail never fires here and is the second belt, exercised synthetically by pushcap.py PART 12.
`--teeth` runs only the reverted pair and requires the two alias rounds to commit again, which is
the same counterfactual stated as a check. A fresh clone has no dumps, and then this prints so and
passes.

2026-10-08 added the 多人 half. The first two rounds played through `run.py --multi` both locked a
clock tens to 155 ms out, and the shipped rails refused every claim that could have fixed it
(0056_03's -155 ms plateau ran for twelve votes from chart +33 s) -- so both played out on a raw
clock and both result pages read SLOW. `LiveCorrector(..., open_trust=True)` is what run.py now asks
for on a 多人 round, and this probe states both halves: with the flag off those two dumps must
commit nothing (the single-player contract above is measured with them skipped, so it stays exactly
the contract the corpus calibrated), and with it on each must commit with a *negative* first step --
earlier, the side both result pages named.

2026-10-09: the stamp `play()` writes into every dump (`open_trust`) made this section catch 多人
rounds by itself, and the 多人 rounds played since all read ALL PERFECT -- their locks needed no
fixing, so `open_trust=True` commits nothing on them and the old wording ("each must commit") was
unsatisfiable. The two shapes are told apart by the round's own evidence rather than by its tag: a
dump whose rails refused a claim past the trusted drift (`refused > 0`, i.e. the opening lock was
doubted) is the mp3/mp4/mp5 shape and must be fixed by the window; a dump with `refused == 0` has
nothing to doubt and there the flag must be *inert* -- same commits, same steps. Both shapes carry
the side rule: no step may move the clock the other way.

The cap each round ran under comes from its record's cfg when the round recorded one (run.py's own
自记) and from player.LIVE_PUSH_MS otherwise -- the panel's rounds do not carry cfg, and the printed
source says which was used, because a cap of 0 and a cap of 10 replay very differently.

From the repo root:

    python tools/probes/votereplay.py            # one line per dump, then the verdict
    python tools/probes/votereplay.py --votes    # ... and every branch line the corrector printed
    python tools/probes/votereplay.py --teeth    # the reverted rails only; must FAIL
"""
import argparse
import glob
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import player  # noqa: E402
import rlog  # noqa: E402

# The two rounds whose second halves an alias ate, and the reason the margin moved to 4: both are
# 0056_03, both agreed ~160 ms away from the truth on the same 157 ms staircase.
ALIASED = ("g454", "g458")
# The 多人 rounds of 2026-10-08 (the first three ever played through `run.py --multi`; mp5 is the one
# that ran with the opening window in place). `play()` now stamps `open_trust` into every dump, so a
# new 多人 round identifies itself; this list is the fallback for the dumps written before that stamp
# existed. Either way they are kept out of the single-player comparison above and replayed in their
# own section, because the shipped rails *must* refuse their opening claims (0056_03: a -120 ms pair
# from a lock 155 ms out) -- that refusal is exactly why run.py asks for `open_trust=True` on a 多人
# round and why this probe has to state both halves of the contract. With the window in place each of
# them must commit, and no commit may move the clock the other way: all three result pages read SLOW.
MULTI = ("mp3", "mp4", "mp5")
# The pre-2026-10-07 rules, i.e. the mutation `--teeth` applies and the counterfactual sweep uses:
# a flat margin of 2 for every pair, and no trusted drift. (VOTE_MARGIN, VOTE_MARGIN_BIG, trust ms)
OLD_RAILS = (2, 2, 1e9)
# Two rounds whose *old-rule* commit was a net 0 ms step: a no-op, the clock did not move, and the
# trusted band simply declines to call that a commit. Same clock either way, so they are not a loss.
# (kdt35c and kt31 both appeared when the corpus grew past the aliases; the old criterion pinned the
# count of committing rounds instead, which tracks the corpus rather than the change, and went red
# for exactly these two no-ops.)
NOOP_LOST = ("kdt35c", "kt31")
# The single-player corpus must not shrink into passing: a prune that quietly eats the dumps would
# otherwise turn every set comparison below into a comparison of nothing. 164 on 2026-10-09.
CORPUS_FLOOR = 150


def caps():
    """tag -> (push cap in ms, where it came from)."""
    out = {}
    try:
        lines = io.open(rlog.HISTORY_FULL, encoding="utf-8")
    except OSError:
        return out
    for line in lines:
        if not line.strip():
            continue
        rec = json.loads(line)
        push = (rec.get("cfg") or {}).get("push")
        if push is not None:
            out[rec.get("tag")] = (float(push), "自记")
    return out


def replay(path, cap):
    d = json.load(io.open(path, encoding="utf-8"))
    ref = d["t0"] + d["offset"] / 1000.0
    lines = []
    lc = player.LiveCorrector([tuple(n) for n in d["notes"]], ref, lines.append,
                              max_corr_up=cap / 1000.0)
    for t, blobs in d["probes"]:
        lc.feed(t, [(y, x) for y, x in blobs])
    return lc, lines


def sweep(paths, known, votes=False):
    """Replay every single-player dump once, under whatever rails player.py currently carries."""
    seen, hits, commits, refused = {}, 0, 0, 0
    for p in paths:
        try:
            d = json.load(io.open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not (isinstance(d, dict) and d.get("probes") and d.get("t0")):
            continue
        if is_multi(p, d):
            continue
        tag = os.path.basename(p)[len("dets_"):-len(".json")].split("-")[0]
        hits += 1
        cap, src = known.get(tag, (player.LIVE_PUSH_MS, "默认"))
        lc, lines = replay(p, cap)
        commits += lc.committed
        refused += lc.refused
        seen[tag] = (lc.committed, lc.corr, lc.refused)
        if votes:
            print("%-26s cap=%3.0f(%s) commits=%d corr=%+7.1f ms refused=%d probes=%3d"
                  % (os.path.basename(p), cap, src, lc.committed, lc.corr * 1000, lc.refused,
                     len(d["probes"])))
            for l in lines:
                print("    " + l.strip())
    return seen, hits, commits, refused


def is_multi(path, d=None):
    """Is this dump a 多人 round? Dumps written since 2026-10-08 say so themselves.

    `play()` stamps `open_trust` into the dump, so a new 多人 round cannot be mistaken for a
    single-player one -- before that, every new 多人 round made this probe fail until its tag was
    added to MULTI by hand (mp5 did exactly that). The tag list stays as the fallback for the older
    dumps, which were written before the stamp existed.
    """
    if isinstance(d, dict) and "open_trust" in d:
        return bool(d["open_trust"])
    tag = os.path.basename(path)[len("dets_"):-len(".json")].split("-")[0]
    return tag in MULTI


def commit_ms(lines):
    """Every correction this replay committed, in order, in ms."""
    out = []
    for l in lines:
        if "two votes agree -> correction" in l:
            out.append(float(l.split("correction", 1)[1].split("ms", 1)[0]))
    return out


def multi_contract(paths, known, votes=False):
    """The 多人 half of the contract: the shipped rails refuse, `open_trust` corrects.

    Both halves matter. With the rails as shipped a multi round must commit *nothing* -- that is the
    refusal the live rounds actually hit, and it is why run.py passes open_trust on 多人. With
    open_trust=True the same dump must commit, its *first* commit must be negative, and **no commit
    may ever move the clock the other way**: the rounds' own result pages said the misses were SLOW,
    so every step is earlier, and mp4's later +139 ms plateau (which the old window committed, undoing
    the -45 ms it had just taken) is the shape this rules out. A positive step here would be either
    the +154 ms echo 0056_03 opened with or that undo.
    """
    ok = True
    for p in paths:
        try:
            d = json.load(io.open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not (isinstance(d, dict) and d.get("probes") and d.get("t0")):
            continue
        if not is_multi(p, d):
            continue
        tag = os.path.basename(p)[len("dets_"):-len(".json")].split("-")[0]
        cap, src = known.get(tag, (player.LIVE_PUSH_MS, "默认"))
        out = {}
        for flag in (False, True):
            lines = []
            lc = player.LiveCorrector([tuple(n) for n in d["notes"]],
                                      d["t0"] + d["offset"] / 1000.0, lines.append,
                                      max_corr_up=cap / 1000.0, open_trust=flag)
            for t, blobs in d["probes"]:
                lc.feed(t, [(y, x) for y, x in blobs])
            out[flag] = (lc.committed, lc.corr * 1000.0, lc.refused, commit_ms(lines))
            if votes:
                print("  %s open_trust=%s commits=%d corr=%+.1f ms refused=%d steps=%s"
                      % (tag, flag, lc.committed, lc.corr * 1000.0, lc.refused,
                         ["%+.0f" % s for s in out[flag][3]]))
        shut, open_ = out[False], out[True]
        steps = open_[3]
        # A 多人 dump comes in two shapes, and the stamp (`is_multi` above) cannot tell them apart,
        # so the contract has to. The shape the window was written for is a round whose *opening
        # lock was doubted*: the shipped rails refused a claim past CORR_TRUST_MS (mp3/mp4/mp5 all
        # show refused=1 and commits=0). There the rails must stay shut and the window must fix it
        # with a negative first step. Every 多人 round played since (mp9/mp10/mp14..mp18) locked a
        # clock that needed no fixing -- refused=0, and the rails already commit 0 or a few ms of
        # their own -- and requiring a commit from those would be requiring the window to *invent*
        # a correction on a round that read ALL PERFECT. What must hold there is the opposite, and
        # it is a check the corpus could not make before: with nothing to doubt, the flag is inert,
        # byte for byte. Both shapes share the side rule: no step may ever move the clock the other
        # way (that is mp4's +139 ms plateau undoing the -45 ms it had just taken).
        if shut[2] > 0:
            good = (shut[0] == 0 and open_[0] > 0 and steps and steps[0] < 0
                    and all(s <= 0 for s in steps))
            want = "要 闸关 0 次 / 闸开 >0、首步 <0、其余不回头"
        else:
            good = (open_[0] == shut[0] and steps == shut[3]
                    and all(s <= 0 for s in steps))
            want = "要 闸开与闸关逐字相同（开局锁定没被怀疑，没什么可修）、其余不回头"
        ok = ok and good
        print("  多人 %-4s cap=%3.0f(%s) 闸关：提交 %d 次 refused=%d；闸开：提交 %d 次、步 %s"
              "（%s）%s"
              % (tag, cap, src, shut[0], shut[2], open_[0],
                 ["%+.0f" % s for s in steps] or "-", want,
                 "" if good else "  <-- 不合契约"))
    return ok


def _present(paths):
    """`dets_<tag>.json` -> the tags this corpus actually still has."""
    return {os.path.basename(p)[len("dets_"):-len(".json")] for p in paths}


def _alias_synthetic():
    """The alias shape without depending on two particular dumps.

    g454 / g458 were the two rounds an alias ate (`ALIASED`), and on 2026-10-19 their dumps were no
    longer in `research/runs/` -- the corpus floor (`CORPUS_FLOOR`, "the corpus must not be quietly
    eaten") counts *how many* dumps there are and cannot notice that two specific ones went. The
    guard must not go vacuous with them, so the shape is synthesised: every vote reads ~160 ms away
    from the truth on one side, which the old rails (two-tier margin, no trusted drift) spend as a
    whole step and the shipped rails refuse because it is past the 50 ms trust band.

    Returns (old rules took a whole >=40 ms step, shipped rules committed nothing). One commit caps
    at `max_step` (45 ms), so the old rules' answer here is a single -45 ms step -- which is exactly
    the shape `ALIASED` recorded: a whole step, not a nudge.
    """
    import pushcap                       # same directory: its synthetic field is the fixture
    real = (player.VOTE_MARGIN, player.VOTE_MARGIN_BIG, player.CORR_TRUST_MS)
    try:
        player.VOTE_MARGIN, player.VOTE_MARGIN_BIG, player.CORR_TRUST_MS = OLD_RAILS
        old, _ = pushcap.run([(-0.160, 24)], 0.0)
    finally:
        player.VOTE_MARGIN, player.VOTE_MARGIN_BIG, player.CORR_TRUST_MS = real
    new, lines = pushcap.run([(-0.160, 24)], 0.0)
    return (old.committed > 0 and old.corr * 1000.0 <= -40.0,
            new.committed == 0 and new.refused > 0
            and any("past the trusted drift" in l for l in lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dumps", nargs="*", help="default: every dets_*.json under research/runs")
    ap.add_argument("--votes", action="store_true",
                    help="print one line per dump and every branch line the corrector printed")
    ap.add_argument("--teeth", action="store_true",
                    help="revert the two rails (margin 2, no trusted drift) -- the check must go red")
    args = ap.parse_args()

    known = caps()
    paths = args.dumps or sorted(glob.glob(os.path.join(rlog.RUNS, "dets_*.json")))
    if args.teeth:
        player.VOTE_MARGIN, player.VOTE_MARGIN_BIG, player.CORR_TRUST_MS = OLD_RAILS
        print(f"牙：把 margin 退回 {OLD_RAILS[0]}（两档一样）、可信带拆掉（2026-10-07 之前的规则）")

    seen, hits, commits, refused = sweep(paths, known, votes=args.votes or not args.teeth)
    if not hits:
        print("没有可重放的 dump（新克隆里 research/ 是空的）—— 这一项跳过")
        return 0

    if args.teeth:
        have = _present(paths)
        eaten = sorted(t for t in ALIASED if t in have and seen.get(t, (0,))[0] > 0)
        # 那两份 dump 不在了，牙也得照样咬得住：同一个形状用合成场喂进旧规则，必须被吞。
        syn_eaten, _ = _alias_synthetic()
        # The 多人 half has to go red as well: with the rails gone the shipped-rule replay of a
        # multi round commits instead of refusing, so the contract's "闸关：提交 0 次" no longer
        # holds. Both halves being load-bearing is the point of the teeth.
        multi_ok = multi_contract(paths, known)
        ok = (len(eaten) == len(set(ALIASED) & have) and syn_eaten and not multi_ok)
        print(f"退回旧规则后仍然提交的别名局：{eaten or '一个都没有'}"
              f"（语料里现存 {sorted(set(ALIASED) & have) or '一份都没有'}）")
        print(f"  合成别名（不依赖那两份 dump）：旧规则提交 -160 ms = {syn_eaten}（要 True）")
        print(f"  多人契约在旧规则下：{'仍然成立（牙没咬到）' if multi_ok else '不成立（牙咬到了）'}"
              f"（要不成立）")
        print("VOTEREPLAY " + ("PASS" if ok else "FAIL"))
        return 0 if ok else 1

    real = (player.VOTE_MARGIN, player.VOTE_MARGIN_BIG, player.CORR_TRUST_MS)
    try:
        player.VOTE_MARGIN, player.VOTE_MARGIN_BIG, player.CORR_TRUST_MS = OLD_RAILS
        before, _, bcommits, _ = sweep(paths, known)
    finally:
        player.VOTE_MARGIN, player.VOTE_MARGIN_BIG, player.CORR_TRUST_MS = real

    now = {t for t, v in seen.items() if v[0] > 0}
    then = {t for t, v in before.items() if v[0] > 0}
    lost = sorted(then - now)
    gained = sorted(now - then)
    over = [(t, round(v[1] * 1000, 1)) for t, v in sorted(seen.items())
            if abs(v[1]) * 1000 > player.CORR_TRUST_MS]
    big = [(t, round(before[t][1] * 1000)) for t in lost]
    small = max((abs(v[1]) * 1000 for t, v in seen.items() if v[0] > 0), default=0.0)
    # What the narrowing is allowed to remove, and nothing else:
    #   * the two aliases -- rounds whose second half an alias ate; their old-rule commit was a whole
    #     >= 40 ms step, and refusing it is the point of the trusted band;
    #   * NOOP_LOST -- rounds where the old rules committed a net 0 ms step (the clock did not move)
    #     and the new rules decline to call that a commit.
    # Anything else leaving the committing set, anything joining it, and any commit moving the clock
    # past the trusted band is a regression. The set is pinned rather than the count, because the
    # count tracks the corpus (which grows as rounds are played and shrinks when it is pruned).
    have = _present(paths)
    aliases = [t for t in lost if t in ALIASED]
    noops = [t for t in lost if t in NOOP_LOST]
    unknown = [t for t in lost if t not in ALIASED and t not in NOOP_LOST]
    # 两份别名 dump 可以在语料清理里消失（2026-10-19 就已经不在了），判据不能跟着失效：
    # 语料里还留着的那几份照旧要挡，另外**永远**拿合成场把同一个形状喂一遍。
    syn_alias, syn_refused = _alias_synthetic()
    alias_ok = (sorted(aliases) == sorted(set(ALIASED) & have)
                and all(abs(before[t][1]) * 1000 >= 40 for t in aliases)
                and syn_alias and syn_refused)
    noop_ok = all(abs(before[t][1]) * 1000 == 0 for t in noops)
    ok = (not unknown and not gained and not over and alias_ok and noop_ok and small <= 25
          and hits >= CORPUS_FLOOR)
    print(f"{hits} 份可重放的 dump（单人；多人 {len(MULTI)} 份另算）；"
          f"现规则（margin={real[0]}/{real[1]}、可信带 {real[2]:.0f} ms）"
          f"提交 {commits} 次、不采 {refused} 次；旧规则提交 {bcommits} 次")
    print(f"  旧规则提交、现规则不提交的：{big or '无'}"
          f"（只许是别名 {list(ALIASED)} 的整步 >= 40 ms、或 {list(NOOP_LOST)} 那种净 0 的空步）")
    print(f"  认不出来的丢失（一个都不该有）：{unknown or '无'}")
    print(f"  别名（语料现存 {sorted(set(ALIASED) & have) or '无'}）都在丢失名单里、且都是一整步 >= 40 ms："
          f"{alias_ok}")
    print(f"  合成别名（不依赖 dump）：旧规则花掉一整步（<= -40 ms）={syn_alias}、现规则不采={syn_refused}")
    print(f"  净 0 空步那几局的旧规则步长确实是 0：{noop_ok}")
    print(f"  现规则新提交的（不该有）：{gained or '无'}")
    print(f"  现规则下最大的提交：{small:.1f} ms（要 <= 25：语料里有用的一律 <= 23）")
    print(f"  末值超出可信带的 dump：{over or '无'}")
    print(f"  语料规模：{hits} 份（下限 {CORPUS_FLOOR}：语料不许被清理悄悄吃掉）")
    # 牙：把可信带掐到 1 ms，大量 dump 会从「提交」变成「不采」——判据必须因此变红，而且红在
    # 「认不出来的丢失」那一条上（证明这一条真的在咬，不是摆设）。
    real_trust = player.CORR_TRUST_MS
    try:
        player.CORR_TRUST_MS = 1.0
        squeezed, _, _, _ = sweep(paths, known)
    finally:
        player.CORR_TRUST_MS = real_trust
    tooth_lost = sorted({t for t, v in before.items() if v[0] > 0}
                        - {t for t, v in squeezed.items() if v[0] > 0})
    tooth_unknown = [t for t in tooth_lost if t not in ALIASED and t not in NOOP_LOST]
    tooth_ok = bool(tooth_unknown)
    print(f"  牙：可信带掐到 1 ms 之后，丢失名单里多出 {len(tooth_unknown)} 局认不出来的"
          f"（{'咬到了' if tooth_ok else '没咬到'}）")
    ok = tooth_ok and ok
    ok = multi_contract(paths, known, votes=args.votes) and ok
    print("VOTEREPLAY " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
