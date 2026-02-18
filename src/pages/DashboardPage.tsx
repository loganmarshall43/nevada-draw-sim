import { useEffect, useMemo, useState } from "react";
import { signOut } from "firebase/auth";
import { auth } from "../firebase/firebase";
import { useAuth } from "../features/auth/AuthProvider";
import type { SpeciesKey } from "../features/profile/userProfile";
import { getUserProfile, setBonusPoints } from "../features/profile/userProfile";
import { simulateNevadaDraw } from "../features/simulator/nevadaSim";

import ndowBlocks from "../data/nv_bonuspoints_2025.json";

type NdowRow = {
  bp: number;
  successfulByChoice: number[]; // length 5
  totalByChoice: number[]; // length 5
  totalApplicants: number;
};

type NdowBlock = {
  state: "NV";
  year: number;
  residency: "R" | "NR" | null;
  species: string; // e.g., elk, deer, antelope, sheep, goat, moose, bear
  title: string;
  units: string | null;
  season: string | null;
  quota: number | null;
  weapon: string | null;
  rows: NdowRow[];
  sourceUrl?: string;
  sourceFile?: string;
  startPage?: number;
  endPage?: number;
};

type ResidencyFilter = "ALL" | "R" | "NR";

function normalizeSpeciesKey(s: string): string {
  return (s || "").toLowerCase().trim();
}

function toSpeciesKeyForProfile(s: string): SpeciesKey {
  // Your Firestore profile only tracks these; map others into closest bucket.
  const v = normalizeSpeciesKey(s);
  if (v === "elk") return "elk";
  if (v === "deer") return "deer";
  if (v === "antelope") return "antelope";
  if (v === "sheep") return "sheep";
  if (v === "goat") return "goat";
  // fallback so UI still works even on moose/bear datasets
  return "elk";
}

export default function DashboardPage() {
  const { user } = useAuth();
  const blocksAll = ndowBlocks as unknown as NdowBlock[];

  // Simulation state
  const [runs, setRuns] = useState<number>(10000);
  const [simBusy, setSimBusy] = useState(false);
  const [simResult, setSimResult] = useState<{ winRate: number; wins: number; runs: number } | null>(null);

  // Filters
  const speciesOptions = useMemo(() => {
    const set = new Set<string>();
    for (const b of blocksAll) set.add(normalizeSpeciesKey(b.species));
    return Array.from(set).sort();
  }, [blocksAll]);

  const [speciesFilter, setSpeciesFilter] = useState<string>(() => speciesOptions[0] ?? "elk");
  const [residencyFilter, setResidencyFilter] = useState<ResidencyFilter>("ALL");
  const [search, setSearch] = useState<string>("");

  // This is the species bucket for saving BP in Firestore
  const profileSpecies: SpeciesKey = useMemo(() => toSpeciesKeyForProfile(speciesFilter), [speciesFilter]);

  const [choice, setChoice] = useState<1 | 2 | 3 | 4 | 5>(1);
  const [blockIdx, setBlockIdx] = useState(0);

  const [myBP, setMyBP] = useState<number>(0);
  const [saving, setSaving] = useState(false);

  // Filter blocks based on current filters
  const filteredBlocks = useMemo(() => {
    const s = normalizeSpeciesKey(speciesFilter);
    const q = search.trim().toLowerCase();

    return blocksAll.filter((b) => {
      if (normalizeSpeciesKey(b.species) !== s) return false;

      if (residencyFilter !== "ALL") {
        if ((b.residency ?? null) !== residencyFilter) return false;
      }

      if (q) {
        const hay = [b.title, b.units, b.season, b.weapon, b.sourceFile]
          .filter(Boolean)
          .join(" • ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }

      return true;
    });
  }, [blocksAll, speciesFilter, residencyFilter, search]);

  // Keep selected block index valid + clear sim when filters change
  useEffect(() => {
    setBlockIdx(0);
    setSimResult(null);
  }, [speciesFilter, residencyFilter, search]);

  // Also clear sim when choice changes or myBP changes (keeps display honest)
  useEffect(() => {
    setSimResult(null);
  }, [choice, myBP]);

  const active = filteredBlocks[blockIdx] ?? filteredBlocks[0] ?? null;

  // Load saved BP for the selected species bucket
  useEffect(() => {
    if (!user) return;
    (async () => {
      const profile = await getUserProfile(user.uid);
      const v = profile?.bonusPoints?.[profileSpecies] ?? 0;
      setMyBP(v);
    })().catch(console.error);
  }, [user, profileSpecies]);

  // Compute table for active block + choice (historical table view)
  const table = useMemo(() => {
    if (!active) return [];
    const c = choice - 1;

    return active.rows
      .map((r) => {
        const apps = r.totalByChoice?.[c] ?? 0;
        const succ = r.successfulByChoice?.[c] ?? 0;
        const pct = apps > 0 ? (succ / apps) * 100 : 0;
        return { bp: r.bp, apps, succ, pct };
      })
      .sort((a, b) => a.bp - b.bp);
  }, [active, choice]);

  // Applicant pool for simulation (use totals-by-choice as pool size per BP)
  const applicantsByBP = useMemo(() => {
    if (!active) return [];
    const c = choice - 1;

    return active.rows.map((r) => ({
      bp: r.bp,
      applicants: r.totalByChoice?.[c] ?? 0,
    }));
  }, [active, choice]);

  async function saveBP() {
    if (!user) return;
    const val = Number.isFinite(myBP) ? Math.max(0, Math.floor(myBP)) : 0;
    setSaving(true);
    try {
      await setBonusPoints(user.uid, profileSpecies, val);
    } finally {
      setSaving(false);
    }
  }

  async function runSim() {
    if (!active) return;

    const quota = active.quota ?? 0;
    const nRuns = Math.max(1000, Math.min(200000, Math.floor(runs || 10000)));

    setSimBusy(true);
    setSimResult(null);

    // allow UI to paint "Running..."
    await new Promise((res) => setTimeout(res, 0));

    try {
      const result = simulateNevadaDraw({
        applicantsByBP,
        quota,
        myBP,
        runs: nRuns,
      });
      setSimResult(result);
    } catch (e) {
      console.error("Simulation failed:", e);
      setSimResult(null);
    } finally {
      setSimBusy(false);
    }
  }

  async function logout() {
    await signOut(auth);
  }

  const blockLabel = (b: NdowBlock, idx: number) => {
    const units = b.units ?? "Units ?";
    const season = b.season ?? "Season ?";
    const quota = b.quota ?? "?";
    const res = b.residency ?? "—";
    return `${idx + 1}. [${res}] Units ${units} • ${season} • Quota ${quota}`;
  };

  const quotaDisabled = !active || (active.quota ?? 0) <= 0;

  return (
    <div style={{ maxWidth: 1200, margin: "24px auto", padding: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0 }}>Nevada Draw Simulator</h1>
          <div style={{ marginTop: 6 }}>
            Logged in as: <b>{user?.email}</b>
          </div>
        </div>

        <button onClick={logout} style={{ padding: 10, height: 42 }}>
          Logout
        </button>
      </div>

      <hr style={{ margin: "20px 0" }} />

      {/* FILTERS */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "end" }}>
        <div>
          <label>
            Species
            <select
              value={speciesFilter}
              onChange={(e) => setSpeciesFilter(e.target.value)}
              style={{ display: "block", padding: 10, marginTop: 6, minWidth: 180 }}
            >
              {speciesOptions.map((s) => (
                <option key={s} value={s}>
                  {s.toUpperCase()}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div>
          <label>
            Residency
            <select
              value={residencyFilter}
              onChange={(e) => setResidencyFilter(e.target.value as ResidencyFilter)}
              style={{ display: "block", padding: 10, marginTop: 6, minWidth: 150 }}
            >
              <option value="ALL">All</option>
              <option value="R">Resident</option>
              <option value="NR">Nonresident</option>
            </select>
          </label>
        </div>

        <div style={{ minWidth: 260 }}>
          <label>
            Search (units / season / weapon)
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="ex: 061, archery, Oct"
              style={{ display: "block", padding: 10, marginTop: 6, width: "100%" }}
            />
          </label>
        </div>

        <div>
          <label>
            Choice
            <select
              value={choice}
              onChange={(e) => setChoice(parseInt(e.target.value, 10) as 1 | 2 | 3 | 4 | 5)}
              style={{ display: "block", padding: 10, marginTop: 6, minWidth: 130 }}
            >
              <option value={1}>1st</option>
              <option value={2}>2nd</option>
              <option value={3}>3rd</option>
              <option value={4}>4th</option>
              <option value={5}>5th</option>
            </select>
          </label>
        </div>

        <div>
          <label>
            Points
            <input
              type="number"
              min={0}
              value={myBP}
              onChange={(e) => setMyBP(parseInt(e.target.value || "0", 10))}
              style={{ display: "block", padding: 10, marginTop: 6, width: 190 }}
            />
          </label>
        </div>

        <button onClick={saveBP} disabled={saving} style={{ padding: "10px 16px", height: 42 }}>
          {saving ? "Saving..." : "Save"}
        </button>
      </div>

      {/* BLOCK PICKER */}
      <div style={{ marginTop: 16 }}>
        <div style={{ marginBottom: 6, opacity: 0.85 }}>
          Showing <b>{filteredBlocks.length}</b> blocks for <b>{speciesFilter.toUpperCase()}</b>
          {residencyFilter !== "ALL" ? ` (${residencyFilter})` : ""}.
        </div>

        <label>
          Hunt block
          <select
            value={blockIdx}
            onChange={(e) => setBlockIdx(parseInt(e.target.value, 10))}
            style={{ display: "block", padding: 10, marginTop: 6, width: "100%" }}
          >
            {filteredBlocks.map((b, idx) => (
              <option key={`${b.sourceFile}-${idx}`} value={idx}>
                {blockLabel(b, idx)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* ACTIVE INFO */}
      {active && (
        <div style={{ marginTop: 16, padding: 14, border: "1px solid #ddd", borderRadius: 10 }}>
          <div style={{ fontWeight: 800 }}>
            {active.year} {active.title} — Units {active.units} — Quota {active.quota ?? "?"}
          </div>
          <div style={{ marginTop: 6 }}>
            <b>Season:</b> {active.season ?? "?"} &nbsp; | &nbsp; <b>Weapon:</b> {active.weapon ?? "?"}
          </div>
          {active.sourceUrl && (
            <div style={{ marginTop: 6, fontSize: 13, opacity: 0.85 }}>
              Source PDF:{" "}
              <a href={active.sourceUrl} target="_blank" rel="noreferrer">
                {active.sourceFile ?? "NDOW report"}
              </a>
            </div>
          )}
        </div>
      )}

      {/* SIMULATION */}
      {active && (
        <div style={{ marginTop: 16, padding: 14, border: "1px solid #ddd", borderRadius: 10 }}>
          <div style={{ fontWeight: 800, marginBottom: 10 }}>Simulation (Nevada bonus-point lottery)</div>

          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "end" }}>
            <div>
              <label>
                Runs
                <input
                  type="number"
                  min={1000}
                  step={1000}
                  value={runs}
                  onChange={(e) => setRuns(parseInt(e.target.value || "10000", 10))}
                  style={{ display: "block", padding: 10, marginTop: 6, width: 160 }}
                />
              </label>
            </div>

            <button
              onClick={runSim}
              disabled={simBusy || quotaDisabled}
              style={{ padding: "10px 16px", height: 42 }}
            >
              {simBusy ? "Running..." : "Run Simulation"}
            </button>

            <div style={{ opacity: 0.85 }}>
              Uses quota <b>{active.quota ?? "?"}</b> and the applicant pool for <b>Choice {choice}</b>.
            </div>
          </div>

          {quotaDisabled && (
            <div style={{ marginTop: 10, opacity: 0.85 }}>
              No quota found for this block, so simulation is disabled.
            </div>
          )}

          {simResult && (
            <div style={{ marginTop: 12, padding: 12, border: "1px solid #eee", borderRadius: 10 }}>
              <div>
                Estimated win rate: <b>{(simResult.winRate * 100).toFixed(2)}%</b>
              </div>
              <div style={{ marginTop: 4, opacity: 0.85 }}>
                Wins: {simResult.wins} / {simResult.runs}
              </div>
            </div>
          )}
        </div>
      )}

      {/* TABLE */}
      <div style={{ marginTop: 18, overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={th}>Bonus Pts</th>
              <th style={th}>Applicants (Choice {choice})</th>
              <th style={th}>Successful (Choice {choice})</th>
              <th style={th}>Success %</th>
            </tr>
          </thead>
          <tbody>
            {table.map((r) => {
              const isMine = r.bp === myBP;
              return (
                <tr key={r.bp} style={isMine ? { background: "#fff7cc" } : undefined}>
                  <td style={isMine ? { ...td, color: "#000", fontWeight: 700 } : td}>{r.bp}</td>
                  <td style={isMine ? { ...td, color: "#000", fontWeight: 700 } : td}>{r.apps}</td>
                  <td style={isMine ? { ...td, color: "#000", fontWeight: 700 } : td}>{r.succ}</td>
                  <td style={isMine ? { ...td, color: "#000", fontWeight: 700 } : td}>{r.pct.toFixed(2)}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {!active && (
        <div style={{ marginTop: 16, padding: 12, border: "1px solid #ddd", borderRadius: 10 }}>
          No blocks match your filters. Try clearing search or switching residency/species.
        </div>
      )}
    </div>
  );
}

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "10px 8px",
  borderBottom: "2px solid #ddd",
  whiteSpace: "nowrap",
};
const td: React.CSSProperties = {
  padding: "10px 8px",
  borderBottom: "1px solid #eee",
  whiteSpace: "nowrap",
};
