"""
tacref.py -- Boss tactics, the reference: what tactics.asm decides, worked
out the same way in Python, integer for integer.  The tests hold the cart to
this, and check this against the game's own routines where it reads them.

The currency is rounds, in 256ths (8.8): the race between the party killing
the boss and the boss killing the party.  An action is worth the rounds it
buys the boss -- rounds sooner the party falls, rounds later the boss does.

    Dp      the party's damage a round to the boss, sixteenths of HP: each
            living member's best, a swing or a spell (threat)
    Rb      the rounds the boss has left, its HP over Dp
    Db      the boss's own best damage a turn, sixteenths: the most any of
            its actions is expected to take off the party
    damage  x sixteenths of HP off the party: x / Db rounds
    a kill  the HP, and Rb's growth when Dp loses that member's damage, and
            their healing over Rb rounds, and the fight if they were the last
    stun    four turns lost (a stunned player recovers one turn in four),
            sleep about one (Battle_PlayerTryWakeup), confusion two: each a
            turn of their damage and healing
    mute    a caster's spells, damage and healing, for the rest of the fight
    dark    a fighter's damage, less 40 hit; slow, less a hit multiplier
    heal    the boss's HP over Dp; FAST, the boss's own damage going up
"""
import gentactics as G

CAP = 64 * 256
HITS = G.hits()
TQ, TL = G.normal()
SLEEP = G.sleep()
DEAD, STONE, POISON, DARK, STUN, SLEEP_, MUTE, CONF = 1, 2, 4, 8, 0x10, 0x20, 0x40, 0x80
UNDEAD = 0x08                           # an enemy category bit: HARM's


def hits(h):
    return 0 if h < 0 else 255 if h >= 199 else HITS[h]


def F(k):
    """The sum over the 256 dice of die * k / 256, k 0-255."""
    if k == 0:
        return 0
    return ((k - 1) * 255 + (k & -k) - 1) // 2


def isqrt(v):
    r = 0
    for b in range(15, -1, -1):
        t = r | (1 << b)
        if t * t <= v:
            r = t
    return r


def udiv(n, d):
    """n / d, at most 65535: the cart's division."""
    return min(0xFFFF, n // d)


# --- a hit's damage --------------------------------------------------------
def dice(B, a):
    """Over the 256 dice of a swing's damage roll, RandAX(0, B) + B to at most
    255 (B 255 rolls 255: the range wraps), and what gets past absorb a,
    at least 1: the sums of y, v, y*y, v*v, y*v."""
    k = (B + 1) & 0xFF
    s = [0] * 5
    for b in range(256):
        v = min(255, B + ((b * k) >> 8))
        y = max(1, v - a)
        s[0] += y; s[1] += v; s[2] += y * y; s[3] += v * v; s[4] += y * v
    return s


def swing(B0, hr, cr, numhits, mult, att_ail, def_ail, evade, bonus=False, elemdmg=0):
    """DoPhysicalAttack's numbers against one defender: (H, C, B, N)."""
    H = 168 - (40 if att_ail & DARK else 0) + (40 if def_ail & DARK else 0)
    B = B0
    if bonus:
        H = min(255, H + 40)
        B = min(255, B + elemdmg)
    if def_ail & (STUN | SLEEP_):
        B = min(255, B + (B >> 2))
    else:
        H = max(0, min(255, H + hr) - evade)
    H = H or 1
    C = min(cr, H)
    N = (numhits * mult) & 0xFF or 1
    return H, C, B, N


def hit_mean(H, C, B, a):
    """A hit's expected damage, sixteenths."""
    s = dice(B, a)
    return (hits(H) * s[0] + hits(C) * s[1]) >> 12


def hit_moments(H, C, B, a):
    """(mean, sixteenths; mean square, HP squared)."""
    s = dice(B, a)
    ch, cc = hits(H), hits(C)
    m16 = (ch * s[0] + cc * s[1]) >> 12
    m2 = (ch * (s[2] >> 8) + cc * ((2 * s[4] + s[3]) >> 8)) >> 8
    return m16, m2


def var_of(m16, m2):
    return max(0, m2 - ((m16 * m16) >> 8))


def spell_moments(E, cc):
    """A damage spell's roll, E + RandAX(0, E low byte), doubled on cc dice
    of 256: (mean, sixteenths; variance, HP squared).  The roll's square is
    summed as if each share held 256/k dice."""
    k = ((E & 0xFF) + 1) & 0xFF
    f = F(k)
    g2 = (256 * (k - 1) * (2 * k - 1)) // 6 if k else 0
    sd1 = 256 * E + f
    sd2 = 256 * E * E + 2 * E * f + g2
    m16 = (sd1 * (256 + cc)) >> 12
    m2 = ((sd2 >> 8) * (256 + 3 * cc)) >> 8
    return m16, var_of(m16, m2)


HPCAP = 4095                            # so sixteenths of HP stay in a word


def tail(M16, V, hp):
    """(sixteenths of HP expected to come off, short of overkill; the chance
    of a kill, 256ths), from a mean and variance by the normal tail."""
    hp = max(1, min(hp, HPCAP))
    t = 16 * hp - 8
    s = isqrt(V)
    if s == 0:
        return min(M16, 16 * hp), (256 if M16 >= t else 0)
    diff = t - M16
    q = min(64, abs(diff) // s)
    j = 64 + (q if diff >= 0 else -q)
    ex = (s * TL[j]) >> 4
    return max(0, min(16 * hp, M16 - ex)), TQ[j]


# --- the state -------------------------------------------------------------
class Member:
    """A party slot.  spells: 32 bytes, 4 a level, each a spell id + 1 or 0;
    mp: 8, the current MP a level."""
    def __init__(self, **k):
        self.cls = k.get("cls", 0); self.ail = k.get("ail", 0)
        self.hp = k.get("hp", 100); self.maxhp = k.get("maxhp", self.hp)
        self.dmg = k.get("dmg", 20); self.hitrate = k.get("hitrate", 20)
        self.numhits = k.get("numhits", 1); self.mult = k.get("mult", 1)
        self.crit = k.get("crit", 5); self.evade = k.get("evade", 20)
        self.absorb = k.get("absorb", 10); self.magdef = k.get("magdef", 30)
        self.res = k.get("res", 0); self.wcat = k.get("wcat", 0); self.welem = k.get("welem", 0)
        self.spells = list(k.get("spells", [0] * 32)); self.mp = list(k.get("mp", [0] * 8))

    @property
    def alive(self):
        return not self.ail & (DEAD | STONE)


class Boss:
    def __init__(self, **k):
        self.hp = k.get("hp", 1000); self.maxhp = k.get("maxhp", self.hp)
        self.ail = k.get("ail", 0); self.mult = k.get("mult", 1)
        self.strength = k.get("strength", 50); self.hitrate = k.get("hitrate", 50)
        self.numhits = k.get("numhits", 1); self.crit = k.get("crit", 1)
        self.evade = k.get("evade", 20); self.absorb = k.get("absorb", 20)
        self.magdef = k.get("magdef", 100); self.cat = k.get("cat", 0)
        self.weak = k.get("weak", 0); self.res = k.get("res", 0)


class Spell:
    def __init__(self, rec):
        self.hitrate, self.eff, self.elem, self.target, self.effect = rec[:5]


# --- threat ----------------------------------------------------------------
def member_phys(m, b, elemdmg, dark=False, slow=False):
    bonus = bool((m.wcat & b.cat) or (m.welem & b.weak))
    mult = max(0, m.mult - 1) if slow else m.mult
    H, C, B, N = swing(m.dmg, m.hitrate, m.crit, m.numhits, mult, m.ail | (DARK if dark else 0),
                       b.ail, b.evade, bonus, elemdmg)
    return min(0xFFFF, N * hit_mean(H, C, B, b.absorb))


def castable(m, spellrec):
    """(spell id, record) for each spell m knows and has the MP for."""
    if m.ail & MUTE:
        return
    for lv in range(8):
        if not m.mp[lv]:
            continue
        for sl in range(4):
            sb = m.spells[lv * 4 + sl]
            if sb:
                yield sb - 1, Spell(spellrec(sb - 1))


WM, WW = 4, 10


def member_mag(m, b, spellrec, wmharm=False):
    best = 0
    for sid, sp in castable(m, spellrec):
        if sp.target not in (0x01, 0x02):
            continue
        if sp.effect == 0x01:
            E, base = sp.eff, 148
            if b.res & sp.elem:
                E, base = E >> 1, 0
            if b.weak & sp.elem:
                E, base = E + (E >> 1), base + 40
        elif sp.effect == 0x02 and (b.cat & UNDEAD or (wmharm and m.cls in (WM, WW))):
            E, base = sp.eff, 148
        else:
            continue
        cc = hits(max(0, base + sp.hitrate - b.magdef))
        k = ((E & 0xFF) + 1) & 0xFF
        best = max(best, min(0xFFFF, ((256 * E + F(k)) * (256 + cc)) >> 12))
    return best


def member_heal(m, party, spellrec):
    alive = [p for p in party if p.alive]
    best = 0
    for sid, sp in castable(m, spellrec):
        if sp.target not in (0x08, 0x10):
            continue
        if sp.effect in (0x06, 0x07):       # RecoverHP, both its entries
            k = (sp.eff + 1) & 0xFF
            amt = min(4080, 16 * sp.eff + (F(k) >> 4))
            if sp.target == 0x08:
                amt *= len(alive)
        elif sp.effect == 0x0F:
            miss = max(0, max(p.maxhp - p.hp for p in alive))
            amt = 0xFFFF if miss > HPCAP else 16 * miss
        else:
            continue
        best = max(best, min(0xFFFF, amt))
    return best


# --- the decision ----------------------------------------------------------
DECK_TURNS = 8                          # a pass through the script's slots


class Mind:
    """One boss turn's thinking.  script: (magic rate, skill rate, 8 spells,
    4 skills).  spellrec(id): the record the battle casts, five bytes.  deck:
    the enemy's two rotation bytes as Boss tactics keeps them -- the spell
    slots played this pass, a bit each; the skill slots in the low nibble,
    the pass's turns so far in the high.  Each slot plays once a pass; a
    pass is DECK_TURNS of the boss's turns."""

    def __init__(self, party, boss, script, spellrec, elemdmg=0, wmharm=False, deck=(0, 0)):
        self.p, self.b, self.script, self.rec = party, boss, script, spellrec
        self.spent, self.skspent, self.turns = deck[0], deck[1] & 0x0F, deck[1] >> 4
        if self.turns >= DECK_TURNS:
            self.spent = self.skspent = self.turns = 0
        self.alive = [m.alive for m in party]
        self.nalive = sum(self.alive)
        self.phys = [member_phys(m, boss, elemdmg) if a else 0 for m, a in zip(party, self.alive)]
        self.pdark = [(self.phys[i] if party[i].ail & DARK else member_phys(party[i], boss, elemdmg, dark=True))
                      if self.alive[i] else 0 for i in range(4)]
        self.pslow = [(self.phys[i] if party[i].mult == 0 else member_phys(party[i], boss, elemdmg, slow=True))
                      if self.alive[i] else 0 for i in range(4)]
        self.mag = [member_mag(m, boss, spellrec, wmharm) if a else 0 for m, a in zip(party, self.alive)]
        self.heal = [member_heal(m, party, spellrec) if a else 0 for m, a in zip(party, self.alive)]
        self.d = [max(self.phys[i], self.mag[i]) for i in range(4)]
        self.Dp = max(16, min(0xFFFF, sum(self.d)))
        self.Rb = min(CAP, udiv(boss.hp * 4096, self.Dp))
        self.hpp16 = min(0xFFFF, 16 * sum(min(m.hp, HPCAP) for m, a in zip(party, self.alive) if a))
        self.actions()

    def Rg(self, delta):
        if delta <= 0:
            return 0
        rest = self.Dp - delta
        if rest < 16:
            return CAP - self.Rb
        return min(CAP, udiv(self.b.hp * 4096, rest)) - self.Rb

    # A swing, a spell: each target's (sixteenths off, kill chance).
    def swing_at(self, i, mult=None):
        b, m = self.b, self.p[i]
        H, C, B, N = swing(b.strength, b.hitrate, b.crit, b.numhits, b.mult if mult is None else mult,
                           b.ail, m.ail, m.evade)
        m16, m2 = hit_moments(H, C, B, m.absorb)
        return tail(min(0xFFFFFFFF, N * m16), N * var_of(m16, m2), m.hp)

    def spell_at(self, i, sp):
        m = self.p[i]
        resisted = m.res & sp.elem
        E = sp.eff >> 1 if resisted else sp.eff
        cc = hits(max(0, (0 if resisted else 148) + sp.hitrate - m.magdef))
        m16, v = spell_moments(E, cc)
        return tail(m16, v, m.hp)

    def candidates(self):
        """(attack id or None for a swing, record): the swing, then each
        spell and each skill of the script once, in its order."""
        out = [(None, None)]
        seen = set()
        for j, s in enumerate(self.script[2:10]):
            if s != 0xFF and not self.spent & (1 << j) and s not in seen:
                seen.add(s); out.append((s, Spell(self.rec(s))))
        for j, s in enumerate(self.script[10:14]):
            if s != 0xFF and not self.skspent & (1 << j) and s + 0x42 not in seen:
                seen.add(s + 0x42); out.append((s + 0x42, Spell(self.rec(s + 0x42))))
        return out

    def after(self, aid):
        """The two rotation bytes once the boss has done aid: its first slot
        still in the deck played, and a turn of the pass gone."""
        spent, skspent = self.spent, self.skspent
        if aid is not None and aid < 0x42:
            j = next(j for j, s in enumerate(self.script[2:10]) if s == aid and not spent & (1 << j))
            spent |= 1 << j
        elif aid is not None:
            j = next(j for j, s in enumerate(self.script[10:14]) if s + 0x42 == aid and not skspent & (1 << j))
            skspent |= 1 << j
        return spent, skspent | ((self.turns + 1) << 4)

    def actions(self):
        live = [i for i in range(4) if self.alive[i]]
        self.cands = self.candidates()
        # Pass 1: what each damaging action takes off, for Db.
        self.swings = {i: self.swing_at(i) for i in live}
        best = max((self.swings[i][0] for i in live), default=0)
        self.spellhits = {}
        for aid, sp in self.cands[1:]:
            if sp.effect != 0x01 or sp.target not in (0x01, 0x02):
                continue
            em = {i: self.spell_at(i, sp) for i in live}
            self.spellhits[aid] = em
            if sp.target == 0x01:
                best = max(best, min(0xFFFF, sum(e[0] for e in em.values())))
            else:
                best = max(best, max((e[0] for e in em.values()), default=0))
        self.Db = max(16, min(0xFFFF, best))
        self.KG = [0] * 4
        self.DG = [0] * 4
        for i in live:
            win = CAP if self.nalive == 1 else 0
            self.KG[i] = min(CAP, self.Rg(self.d[i]) + udiv(self.Rb * self.heal[i], self.Db) + win)
            self.DG[i] = min(CAP, udiv(self.d[i] * 256, self.Dp) + udiv(self.heal[i] * 256, self.Db))
        # Pass 2: each action's worth, and its target.
        self.value = []
        for aid, sp in self.cands:
            self.value.append(self.worth(aid, sp, live))

    def dmgval(self, i, e):
        return min(CAP, udiv(e[0] * 256, self.Db) + ((e[1] * self.KG[i]) >> 8))

    def status(self, i, new):
        m = self.p[i]
        if new & (DEAD | STONE):
            return min(CAP, udiv(16 * min(m.hp, HPCAP) * 256, self.Db) + self.KG[i])
        g = 0
        out = m.ail & (STUN | SLEEP_)
        if new & STUN and not out:
            g += 4 * self.DG[i]
        if new & SLEEP_ and not out:
            g += ((SLEEP[m.maxhp] if m.maxhp < 81 else 256) * self.DG[i]) >> 8
        if new & CONF and not out:
            g += 2 * self.DG[i]
        if new & MUTE:
            g += self.Rg(self.d[i] - self.phys[i]) + udiv(self.Rb * self.heal[i], self.Db)
        if new & DARK:
            g += self.Rg(self.d[i] - max(self.pdark[i], self.mag[i]))
        if new & POISON:
            g += udiv(self.Rb * 32, self.Db)
        return min(CAP, g)

    def per_target(self, aid, sp, i):
        m = self.p[i]
        resisted = m.res & sp.elem
        if sp.effect == 0x01:
            return self.dmgval(i, self.spellhits[aid][i])
        land = hits(max(0, (0 if resisted else 148) + sp.hitrate - m.magdef))
        if sp.effect == 0x03:
            new = sp.eff & ~m.ail & 0xFF
            return (land * self.status(i, new)) >> 8 if new else 0
        if sp.effect == 0x04:
            if m.mult == 0:
                return 0
            return (land * self.Rg(self.d[i] - max(self.pslow[i], self.mag[i]))) >> 8
        if sp.effect == 0x12:
            new = sp.eff & ~m.ail & 0xFF
            return self.status(i, new) if (not resisted and new and m.hp <= 300) else 0
        return 0

    def worth(self, aid, sp, live):
        """(value, target or None)."""
        if aid is None:
            best, at = -1, None
            for i in live:
                v = self.dmgval(i, self.swings[i])
                if v > best:
                    best, at = v, i
            return max(0, best), at
        if self.b.ail & MUTE:
            return 0, None
        if sp.target in (0x01, 0x02):
            vals = [(self.per_target(aid, sp, i), i) for i in live]
            if sp.target == 0x01:
                return min(CAP, sum(v for v, _ in vals)), None
            best, at = -1, None
            for v, i in vals:
                if v > best:
                    best, at = v, i
            return max(0, best), at
        b = self.b
        if sp.effect in (0x06, 0x07):
            k = (sp.eff + 1) & 0xFF
            amt = min(16 * max(0, b.maxhp - b.hp), min(4080, 16 * sp.eff + (F(k) >> 4)))
            return min(CAP, udiv(amt * 256, self.Dp)), None
        if sp.effect == 0x0F:
            return min(CAP, udiv(16 * max(0, b.maxhp - b.hp) * 256, self.Dp)), None
        if sp.effect == 0x0C:
            if b.mult >= 2:
                return 0, None
            fast = max((self.swing_at(i, b.mult + 1)[0] for i in live), default=0)
            db2 = max(self.Db, fast)
            return min(CAP, udiv(self.hpp16 * 256, self.Db) - udiv(self.hpp16 * 256, db2)), None
        return 0, None

    def choose(self, mode, rng=None):
        """(attack id or None, target or None, dice used).  rng: the battle's
        next dice, for Clever's rolls of the script's rates."""
        vals = [v for v, _ in self.value]
        if mode == 2:
            k = max(range(len(vals)), key=lambda n: (vals[n], -n))
            return self.cands[k][0], self.value[k][1], 0
        used, kind = 0, "swing"
        r = (rng[0] * 129) >> 8
        used = 1
        if r < self.script[0]:
            kind = "spell"
        else:
            r = (rng[1] * 129) >> 8
            used = 2
            if r < self.script[1]:
                kind = "skill"
        if kind != "swing":
            idx = [n for n, (aid, _) in enumerate(self.cands)
                   if aid is not None and (aid >= 0x42) == (kind == "skill")]
            if idx:
                k = max(idx, key=lambda n: (vals[n], -n))
                if vals[k] > 0:
                    return self.cands[k][0], self.value[k][1], used
        return None, self.value[0][1], used
