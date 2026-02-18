export type SimInput = {
  // Applicants by BP level for the chosen choice
  applicantsByBP: Array<{ bp: number; applicants: number }>;
  quota: number;          // tags available
  myBP: number;           // your BP
  runs: number;           // e.g. 10000
  seed?: number;          // optional
};

export type SimResult = {
  runs: number;
  wins: number;
  winRate: number;        // 0..1
};

// Simple seeded RNG so results are repeatable if you want
function mulberry32(seed: number) {
  return function () {
    let t = (seed += 0x6D2B79F5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Nevada mechanic: each application gets k = bp^2 + 1 random numbers; lowest wins
function nevadaScore(bp: number, rand: () => number) {
  const k = bp * bp + 1;
  let best = 1;
  for (let i = 0; i < k; i++) {
    const r = rand();
    if (r < best) best = r;
  }
  return best;
}

export function simulateNevadaDraw(input: SimInput): SimResult {
  const { applicantsByBP, quota, myBP, runs, seed } = input;

  // Build a compact “pool” representation: counts per BP
  const pool = applicantsByBP
    .filter((x) => x.applicants > 0)
    .map((x) => ({ bp: x.bp, n: Math.floor(x.applicants) }));

  const totalApplicants = pool.reduce((sum, x) => sum + x.n, 0);

  if (runs <= 0) return { runs: 0, wins: 0, winRate: 0 };
  if (quota <= 0 || totalApplicants <= 0) return { runs, wins: 0, winRate: 0 };
  if (quota >= totalApplicants) return { runs, wins: runs, winRate: 1 };

  const rand = seed != null ? mulberry32(seed) : Math.random;

  let wins = 0;

  // For each run:
  // - generate scores for all applicants (by bp counts)
  // - generate your score
  // - winners are the lowest scores, quota count
  //
  // Optimization: We don’t need to store all scores as objects; store as number array.
  for (let r = 0; r < runs; r++) {
    const scores: number[] = [];
    scores.length = totalApplicants;

    let idx = 0;
    for (const group of pool) {
      for (let i = 0; i < group.n; i++) {
        scores[idx++] = nevadaScore(group.bp, rand);
      }
    }

    const myScore = nevadaScore(myBP, rand);

    // Find cutoff score for quota-th smallest.
    // Easiest: sort. (fine for moderate pools; we can optimize later)
    scores.sort((a, b) => a - b);
    const cutoff = scores[quota - 1];

    // If your score is strictly less than cutoff => guaranteed win
    // If equal to cutoff => tie-break is random among equals; approximate by chance.
    if (myScore < cutoff) {
      wins++;
    } else if (myScore === cutoff) {
      // Tie handling:
      // Count how many scores are < cutoff and how many == cutoff
      let less = 0;
      let eq = 0;
      for (let i = 0; i < scores.length; i++) {
        if (scores[i] < cutoff) less++;
        else if (scores[i] === cutoff) eq++;
        else break; // sorted
      }
      const slotsLeft = quota - less;
      // Chance you get one of the remaining slots among eq+1 (include you)
      const chance = slotsLeft / (eq + 1);
      if (rand() < chance) wins++;
    }
  }

  return { runs, wins, winRate: wins / runs };
}
