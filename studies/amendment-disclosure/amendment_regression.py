"""
ECON537: TWFE Event Study with Robustness Checks
amendment_regression_v2.py
==================================================
Steps:
  1. Build panel (same logic as raw-means plot, inline)
  2. Main TWFE event study
  3. Robustness 1: fund-specific linear trends (manual detrending)
  4. Robustness 2: joint pre-trend F-test
  5. Robustness 3: placebo timing test
  6. Goodman-Bacon decomposition (manual implementation)
  7. Combined event-study plot (main + trends + placebo)
  8. Simple DiD (single POST coefficient)
  9. Sample composition table

All outputs saved to output/. Regressions saved as CSVs so
plots can be regenerated without re-running regressions.
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pyfixest as pf
from pathlib import Path
from sklearn.linear_model import LinearRegression

# ── Paths ─────────────────────────────────────────────────────────
import argparse

_parser = argparse.ArgumentParser(description="Event study of 13F amendments on reported fund size.")
_parser.add_argument("data", type=Path,
                     help="manager-level quarterly value totals from the QuantKiosk API (CSV)")
_parser.add_argument("--out", type=Path, default=Path("output"), help="output folder")
_args = _parser.parse_args()
DATA_PATH, OUT_DIR = _args.data, _args.out
OUT_DIR.mkdir(parents=True, exist_ok=True)
NOTES_PATH = OUT_DIR / "regression_notes.txt"

EVENT_WINDOW = 8
notes = []

def note(msg):
    print(msg)
    notes.append(msg)

def save_notes():
    with open(NOTES_PATH, "w") as f:
        f.write("\n".join(notes))

note("=" * 60)
note("ECON537, TWFE Event Study Regression")
note("=" * 60)


# ══════════════════════════════════════════════════════════════════
# PANEL CONSTRUCTION (same logic as raw-means plot)
# ══════════════════════════════════════════════════════════════════
note("\n── Panel Construction ──")
df = pd.read_csv(DATA_PATH, low_memory=False)
df = df[df['reportingError'] == False].copy()
df['period_dt'] = pd.to_datetime(df['period'].astype(str), format='%Y%m%d')
df['quarter']   = df['period_dt'].dt.to_period('Q')
df = df.sort_values(['cik', 'quarter']).reset_index(drop=True)
df = df[df['valueTotal'] > 0].copy()

treated_ciks = set(df.loc[df['form'] == '13F-HR/A', 'cik'].unique())
control_ciks = set(df['cik'].unique()) - treated_ciks

treatment_quarters = (
    df[df['form'] == '13F-HR/A']
    .groupby('cik')['quarter'].min()
    .rename('treatment_quarter').reset_index()
)

df['size_decile'] = (
    df.groupby('quarter')['valueTotal']
    .transform(lambda x: pd.qcut(x, 10, labels=False, duplicates='drop'))
)
treated_with_size = treatment_quarters.merge(
    df[['cik', 'quarter', 'size_decile']],
    left_on=['cik', 'treatment_quarter'], right_on=['cik', 'quarter'], how='left'
).drop(columns='quarter')

control_size = (
    df[df['cik'].isin(control_ciks)]
    .groupby('cik')['size_decile']
    .agg(lambda x: x.mode().iloc[0] if len(x.mode()) > 0 else np.nan)
    .rename('size_decile').reset_index()
)

np.random.seed(537)
def assign_pseudo(row, pool):
    matches = pool[pool['size_decile'] == row['size_decile']]
    if len(matches) == 0:
        return pd.NaT
    return matches.sample(1, random_state=np.random.randint(0, 999999999))['treatment_quarter'].iloc[0]

control_size['treatment_quarter'] = control_size.apply(
    lambda r: assign_pseudo(r, treated_with_size), axis=1)
control_assigned = control_size.dropna(subset=['treatment_quarter']).copy()

treated_panel = treatment_quarters.copy(); treated_panel['treated'] = 1
control_panel = control_assigned[['cik', 'treatment_quarter']].copy(); control_panel['treated'] = 0
assignment    = pd.concat([treated_panel, control_panel], ignore_index=True)
panel         = df.merge(assignment, on='cik', how='inner')
panel['event_time'] = (panel['quarter'] - panel['treatment_quarter']).apply(lambda x: x.n)
panel         = panel[panel['event_time'].abs() <= EVENT_WINDOW].copy()

panel = panel.sort_values(['cik', 'quarter']).reset_index(drop=True)
panel['log_value']  = np.log(panel['valueTotal'])
panel['dlog_value'] = panel.groupby('cik')['log_value'].diff()
panel = panel.dropna(subset=['dlog_value'])
panel = panel[np.isfinite(panel['dlog_value'])]
p01, p99 = panel['dlog_value'].quantile([0.01, 0.99])
panel['dlog_value'] = panel['dlog_value'].clip(p01, p99)

# Integer quarter index for fixed effects
panel['quarter_int'] = panel['quarter'].apply(lambda q: q.year * 4 + q.quarter)
panel['cik_int']     = panel['cik'].astype(int)

note(f"  Panel rows       : {len(panel):,}")
note(f"  Treated funds    : {panel[panel['treated']==1]['cik'].nunique():,}")
note(f"  Control funds    : {panel[panel['treated']==0]['cik'].nunique():,}")
note(f"  Treated obs      : {(panel['treated']==1).sum():,}")
note(f"  Control obs      : {(panel['treated']==0).sum():,}")

# ── Build event-time dummies (omit k=-1 as reference) ────────────
# Use km8..km2, k0..k8 to avoid '-' being parsed as subtraction
def kname(k):
    return f'km{abs(k)}' if k < 0 else f'k{k}'

for k in range(-EVENT_WINDOW, EVENT_WINDOW + 1):
    if k == -1:
        continue
    panel[kname(k)] = ((panel['event_time'] == k) & (panel['treated'] == 1)).astype(float)

lead_lag_vars = [kname(k) for k in range(-EVENT_WINDOW, EVENT_WINDOW + 1) if k != -1]


# ══════════════════════════════════════════════════════════════════
# STEP 1: Main TWFE event study
# ══════════════════════════════════════════════════════════════════
note("\n── Step 1: Main TWFE Event Study ──")
formula_main = f"dlog_value ~ {' + '.join(lead_lag_vars)} | cik_int + quarter_int"
fit_main = pf.feols(formula_main, data=panel, vcov={'CRV1': 'cik_int'})
print("\n=== Main spec: TWFE event study ===")
print(fit_main.summary())

def extract_coefs(fit):
    """Extract tidy coefficients + CIs. tidy() returns 6 cols including CIs."""
    td = fit.tidy().copy()
    td.index.name = 'varname'
    td.columns = ['coef', 'se', 't', 'pvalue', 'ci_lo', 'ci_hi']
    return td.reset_index()

# Map back to event_time
def et_from_varname(v):
    if v.startswith('km'):
        return -int(v[2:])
    return int(v[1:])

raw_main   = extract_coefs(fit_main)
coefs_main = raw_main[raw_main['varname'].str.match(r'^km?\d+$')].copy()
coefs_main['event_time'] = coefs_main['varname'].apply(et_from_varname)
# Add reference row at k=-1
ref_row = pd.DataFrame([{'event_time': -1, 'coef': 0.0, 'se': 0.0, 'ci_lo': 0.0, 'ci_hi': 0.0}])
coefs_main = pd.concat([coefs_main[['event_time','coef','se','ci_lo','ci_hi']], ref_row],
                        ignore_index=True).sort_values('event_time').reset_index(drop=True)
coefs_main.to_csv(OUT_DIR / 'coefs_main.csv', index=False)
note(f"  Saved: coefs_main.csv")


# ══════════════════════════════════════════════════════════════════
# STEP 2: Robustness 1: Fund-specific linear trends (manual detrend)
# ══════════════════════════════════════════════════════════════════
note("\n── Step 2: Robustness 1, Fund-specific linear trends ──")

panel['t'] = panel.groupby('cik').cumcount()

def detrend_fund(group):
    if len(group) < 3:
        return pd.Series(group['dlog_value'].values, index=group.index)
    X = group['t'].values.reshape(-1, 1)
    y = group['dlog_value'].values
    lr = LinearRegression().fit(X, y)
    return pd.Series(y - lr.predict(X), index=group.index)

panel['dlog_value_dt'] = (
    panel.groupby('cik', group_keys=False).apply(detrend_fund)
)

formula_trends = f"dlog_value_dt ~ {' + '.join(lead_lag_vars)} | cik_int + quarter_int"
fit_trends = pf.feols(formula_trends, data=panel, vcov={'CRV1': 'cik_int'})
print("\n=== Robustness 1: Fund-specific linear trends (manual detrend) ===")
print(fit_trends.summary())

raw_tr   = extract_coefs(fit_trends)
coefs_tr = raw_tr[raw_tr['varname'].str.match(r'^km?\d+$')].copy()
coefs_tr['event_time'] = coefs_tr['varname'].apply(et_from_varname)
coefs_tr = pd.concat([coefs_tr[['event_time','coef','se','ci_lo','ci_hi']], ref_row],
                      ignore_index=True).sort_values('event_time').reset_index(drop=True)
coefs_tr.to_csv(OUT_DIR / 'coefs_with_trends.csv', index=False)
note(f"  Saved: coefs_with_trends.csv")

# Assess: does k=0 survive trends?
k0_main   = coefs_main[coefs_main['event_time']==0]['coef'].values[0]
k0_trends = coefs_tr[coefs_tr['event_time']==0]['coef'].values[0]
note(f"  k=0 coef, main: {k0_main:.4f}  |  with trends: {k0_trends:.4f}")
survived = "YES" if (k0_main * k0_trends > 0 and abs(k0_trends) > abs(coefs_tr[coefs_tr['event_time']==0]['se'].values[0])) else "NO"
note(f"  Spike at k=0 survives fund trends: {survived}")


# ══════════════════════════════════════════════════════════════════
# STEP 3: Robustness 2: Joint pre-trend F-test
# ══════════════════════════════════════════════════════════════════
note("\n── Step 3: Robustness 2, Joint pre-trend F-test ──")
pre_vars = [kname(k) for k in range(-EVENT_WINDOW, -1)]

try:
    wald = fit_main.wald_test(pre_vars)
    f_stat  = float(wald['statistic'].iloc[0]) if hasattr(wald['statistic'], 'iloc') else float(wald['statistic'])
    p_val   = float(wald['pvalue'].iloc[0])    if hasattr(wald['pvalue'],    'iloc') else float(wald['pvalue'])
    print(f"\n=== Robustness 2: Joint pre-trend test ===")
    print(f"H0: k={-EVENT_WINDOW} to k=-2 coefficients jointly = 0")
    print(f"F-statistic : {f_stat:.3f}")
    print(f"p-value     : {p_val:.4f}")
    pretrend_verdict = "REJECT parallel trends (p < 0.05)" if p_val < 0.05 else "FAIL TO REJECT, pre-trends statistically flat"
    note(f"  Pre-trend F-test: F={f_stat:.3f}, p={p_val:.4f}")
    note(f"  Verdict: {pretrend_verdict}")
except Exception as e:
    # Manual Wald test using VCV matrix
    note(f"  wald_test() failed ({e}), computing manually via VCV")
    coef_names = fit_main._coefnames
    pre_idx    = [i for i, n in enumerate(coef_names) if n in pre_vars]
    beta       = fit_main._beta_hat[pre_idx]
    vcv        = fit_main._vcov[np.ix_(pre_idx, pre_idx)]
    q          = len(pre_idx)
    W          = float(beta @ np.linalg.inv(vcv) @ beta / q)
    from scipy import stats
    p_val      = 1 - stats.f.cdf(W, q, panel['cik'].nunique() - 1)
    f_stat     = W
    pretrend_verdict = "REJECT parallel trends (p < 0.05)" if p_val < 0.05 else "FAIL TO REJECT, pre-trends statistically flat"
    note(f"  Pre-trend F-test (manual): F={f_stat:.3f}, p={p_val:.4f}")
    note(f"  Verdict: {pretrend_verdict}")

pd.DataFrame([{'F_stat': f_stat, 'p_value': p_val, 'df': len(pre_vars),
               'verdict': pretrend_verdict}]).to_csv(OUT_DIR / 'pretrend_test.csv', index=False)
note(f"  Saved: pretrend_test.csv")


# ══════════════════════════════════════════════════════════════════
# STEP 4: Robustness 3: Placebo timing test
# ══════════════════════════════════════════════════════════════════
note("\n── Step 4: Robustness 3, Placebo timing ──")

actual_tq    = panel.loc[panel['treated']==1, 'treatment_quarter'].drop_duplicates().values
treated_fund_ciks = panel.loc[panel['treated']==1, 'cik'].unique()

np.random.seed(537)
placebo_assign = pd.DataFrame({
    'cik': treated_fund_ciks,
    'placebo_quarter': np.random.choice(actual_tq, size=len(treated_fund_ciks), replace=True)
})

panel_pl = panel.merge(placebo_assign, on='cik', how='left')
panel_pl['et_placebo'] = np.where(
    panel_pl['treated'] == 1,
    (panel_pl['quarter'] - panel_pl['placebo_quarter']).apply(
        lambda x: x.n if hasattr(x, 'n') else np.nan),
    panel_pl['event_time']
)
panel_pl = panel_pl.dropna(subset=['et_placebo'])
panel_pl['et_placebo'] = panel_pl['et_placebo'].astype(int)
panel_pl = panel_pl[panel_pl['et_placebo'].abs() <= EVENT_WINDOW].copy()

def pkname(k):
    return f'pkm{abs(k)}' if k < 0 else f'pk{k}'

for k in range(-EVENT_WINDOW, EVENT_WINDOW + 1):
    if k == -1:
        continue
    panel_pl[pkname(k)] = ((panel_pl['et_placebo'] == k) & (panel_pl['treated'] == 1)).astype(float)

placebo_vars    = [pkname(k) for k in range(-EVENT_WINDOW, EVENT_WINDOW + 1) if k != -1]
formula_placebo = f"dlog_value ~ {' + '.join(placebo_vars)} | cik_int + quarter_int"
fit_placebo     = pf.feols(formula_placebo, data=panel_pl, vcov={'CRV1': 'cik_int'})
print("\n=== Robustness 3: Placebo timing test ===")
print(fit_placebo.summary())

def et_from_pkname(v):
    v = v[2:]  # strip 'pk'
    if v.startswith('m'):
        return -int(v[1:])
    return int(v)

raw_pl   = extract_coefs(fit_placebo)
coefs_pl = raw_pl[raw_pl['varname'].str.match(r'^pkm?\d+$')].copy()
coefs_pl['event_time'] = coefs_pl['varname'].apply(et_from_pkname)
coefs_pl = pd.concat([coefs_pl[['event_time','coef','se','ci_lo','ci_hi']], ref_row],
                      ignore_index=True).sort_values('event_time').reset_index(drop=True)
coefs_pl.to_csv(OUT_DIR / 'coefs_placebo.csv', index=False)

k0_placebo = coefs_pl[coefs_pl['event_time']==0]['coef'].values[0]
k0_se_pl   = coefs_pl[coefs_pl['event_time']==0]['se'].values[0]
note(f"  k=0 coef (placebo): {k0_placebo:.4f}  (SE={k0_se_pl:.4f})")
note(f"  k=0 coef (main)   : {k0_main:.4f}")
placebo_verdict = ("SPURIOUS, placebo also shows spike at k=0"
                   if abs(k0_placebo) > 1.96 * k0_se_pl
                   else "CLEAN, placebo k=0 is flat (main result not spurious)")
note(f"  Placebo verdict: {placebo_verdict}")
note(f"  Saved: coefs_placebo.csv")


# ══════════════════════════════════════════════════════════════════
# STEP 5: Goodman-Bacon decomposition (manual, corrected)
# ══════════════════════════════════════════════════════════════════
note("\n── Step 5: Goodman-Bacon Decomposition ──")

# Each 2x2 comparison is a difference in group means over an EVENT_WINDOW-quarter
# window around the (earlier) treatment quarter, taken from each group's raw
# quarterly series. A cohort's controls are not cut down to their own pseudo
# treatment window. Weight = number of treated funds x number of control funds.
raw = df.sort_values(['cik', 'quarter']).copy()
raw['dlog'] = np.log(raw['valueTotal'])
raw['dlog'] = raw.groupby('cik')['dlog'].diff()
raw = raw[np.isfinite(raw['dlog'])]
raw['dlog'] = raw['dlog'].clip(p01, p99)          # same bounds as the panel

treat_q = panel[panel['treated'] == 1].groupby('cik')['treatment_quarter'].first()
cohorts = sorted(treat_q.unique())
members = {g: set(treat_q[treat_q == g].index) for g in cohorts}
never   = set(control_ciks)


def window_rows(ciks, centre):
    lo, hi = centre - EVENT_WINDOW, centre + EVENT_WINDOW
    return raw[raw['cik'].isin(ciks) & (raw['quarter'] >= lo) & (raw['quarter'] <= hi)]


def two_by_two(treated_rows, control_rows, g):
    """Change in the treated group's mean growth, minus the control group's, around g."""
    means = [treated_rows[treated_rows['quarter'] < g]['dlog'].mean(),
             treated_rows[treated_rows['quarter'] >= g]['dlog'].mean(),
             control_rows[control_rows['quarter'] < g]['dlog'].mean(),
             control_rows[control_rows['quarter'] >= g]['dlog'].mean()]
    if any(pd.isna(m) for m in means):
        return None
    return (means[1] - means[0]) - (means[3] - means[2])


bacon_rows = []


def add_row(kind, label, treated_rows, control_rows, g):
    est = two_by_two(treated_rows, control_rows, g)
    if est is None:
        return
    n_t, n_c = treated_rows['cik'].nunique(), control_rows['cik'].nunique()
    bacon_rows.append({'type': kind, 'cohort': label, 'n_treated': n_t, 'n_control': n_c,
                       'weight': n_t * n_c, 'estimate': est})


for g in cohorts:                                  # cohort vs. never-treated
    add_row('Treated vs. Never-treated', str(g),
            window_rows(members[g], g), window_rows(never, g), g)

for i, g_early in enumerate(cohorts):              # every pair of cohorts, both ways
    for g_late in cohorts[i + 1:]:
        add_row('Earlier vs. Later treated', f"{g_early} vs {g_late}",
                window_rows(members[g_early], g_early), window_rows(members[g_late], g_early), g_early)
        add_row('Later vs. Earlier treated (biased)', f"{g_late} vs {g_early}",
                window_rows(members[g_late], g_late), window_rows(members[g_early], g_late), g_late)

bacon_df = pd.DataFrame(bacon_rows)

if len(bacon_df) > 0:
    total_w    = bacon_df['weight'].sum()
    bacon_df['weight_norm'] = bacon_df['weight'] / total_w
    bacon_df['weighted_est'] = bacon_df['weight_norm'] * bacon_df['estimate']

    summary = bacon_df.groupby('type').agg(
        total_weight=('weight_norm', 'sum'),
        wtd_estimate=('weighted_est', 'sum'),
        n_pairs=('estimate', 'count')
    ).reset_index()

    print("\n=== Goodman-Bacon Decomposition ===")
    print(summary.to_string(index=False))

    bacon_df.to_csv(OUT_DIR / 'bacon_decomp.csv', index=False)
    summary.to_csv(OUT_DIR / 'bacon_decomp_summary.csv', index=False)

    for _, r in summary.iterrows():
        note(f"  {r['type']}: weight={r['total_weight']:.3f}, est={r['wtd_estimate']:.4f}")

    biased_wgt = summary[summary['type'].str.contains('biased')]['total_weight'].sum()
    note(f"  Bacon weight on potentially-biased comparisons (later vs. earlier): {biased_wgt:.1%}")
    note(f"  Saved: bacon_decomp.csv, bacon_decomp_summary.csv")
else:
    note("  Bacon decomp: insufficient cohort variation to compute")
    pd.DataFrame().to_csv(OUT_DIR / 'bacon_decomp.csv', index=False)


# ══════════════════════════════════════════════════════════════════
# STEP 6: Combined event-study plot
# ══════════════════════════════════════════════════════════════════
note("\n── Step 6: Combined event-study plot ──")

n_obs   = len(panel)
n_funds = panel['cik'].nunique()

fig, ax = plt.subplots(figsize=(11, 6))
et      = range(-EVENT_WINDOW, EVENT_WINDOW + 1)

specs = [
    (coefs_main, 'Main TWFE',           '#C0392B', 'o',  '-',  True),
    (coefs_tr,   'With fund trends',    '#1A5276', 's',  '--', False),
    (coefs_pl,   'Placebo timing',      '#717D7E', 'x',  ':',  False),
]

for df_c, label, color, marker, ls, filled in specs:
    sub = df_c.sort_values('event_time')
    ax.plot(sub['event_time'], sub['coef'],
            marker=marker, linestyle=ls, color=color,
            label=label, linewidth=1.8, markersize=6,
            markerfacecolor=color if filled else 'none', zorder=3)
    ax.errorbar(sub['event_time'], sub['coef'],
                yerr=1.96 * sub['se'],
                fmt='none', color=color, alpha=0.35, linewidth=1.2, zorder=2)
    # Reference dot at k=-1
    ax.plot(-1, 0, marker=marker, color=color, markersize=7,
            markerfacecolor='white', markeredgecolor=color, zorder=4)

ax.axvline(x=0, color='gray', linestyle='--', linewidth=1.0, alpha=0.7)
ax.axhline(y=0, color='black', linewidth=0.7)
ax.set_xlabel('Event time (quarters from first amendment)', fontsize=11)
ax.set_ylabel('β̂ₖ  (Δlog fund AUM)', fontsize=11)
ax.set_title('Event-study estimates: Δlog(fund AUM) around 13F amendment, with robustness',
             fontsize=12, fontweight='bold', pad=10)
ax.set_xticks(range(-EVENT_WINDOW, EVENT_WINDOW + 1, 2))
ax.legend(frameon=False, fontsize=10, loc='upper left')
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

caption = (
    f"Coefficients from TWFE event-study regression of Δlog(fund AUM) on event-time indicators interacted with treatment status. "
    f"Sample: ever-amenders matched to never-amenders by AUM size decile, 2013–2025 "
    f"(N = {n_obs:,} fund-quarter obs across {n_funds:,} funds). "
    "All specifications include fund and calendar quarter FEs; SEs clustered at fund level. "
    "'With trends' adds fund-specific linear time trends. 'Placebo timing' shuffles treatment dates. "
    "95% CIs shown as error bars. Open circle at k=−1 is reference period (zero by construction)."
)
fig.text(0.01, -0.04, caption, fontsize=7.5, color='#444444', ha='left', va='top',
         wrap=True)

plt.tight_layout()
plt.savefig(OUT_DIR / 'fig03_es_combined.pdf', bbox_inches='tight')
plt.savefig(OUT_DIR / 'fig03_es_combined.png', dpi=300, bbox_inches='tight')
note(f"  Saved: fig03_es_combined.pdf + .png")


# ══════════════════════════════════════════════════════════════════
# STEP 7: Simple DiD (single POST coefficient)
# ══════════════════════════════════════════════════════════════════
note("\n── Step 7: Simple DiD ──")
panel['post_treated'] = ((panel['event_time'] >= 0) & (panel['treated'] == 1)).astype(float)
fit_simple = pf.feols("dlog_value ~ post_treated | cik_int + quarter_int",
                       data=panel, vcov={'CRV1': 'cik_int'})
print("\n=== Simple TWFE DiD ===")
print(fit_simple.summary())

raw_s  = extract_coefs(fit_simple)
ts     = raw_s[raw_s['varname'] == 'post_treated'].iloc[0]
simple_did = {
    'coef':   float(ts['coef']),
    'se':     float(ts['se']),
    't':      float(ts['t']),
    'pvalue': float(ts['pvalue']),
    'r2':     float(fit_simple._r2),
    'nobs':   int(fit_simple._N),
    'ci_lo':  float(ts['ci_lo']),
    'ci_hi':  float(ts['ci_hi']),
}
pd.DataFrame([simple_did]).to_csv(OUT_DIR / 'did_simple.csv', index=False)
note(f"  POST coef: {simple_did['coef']:.4f}  SE={simple_did['se']:.4f}  p={simple_did['pvalue']:.4f}")
note(f"  Saved: did_simple.csv")


# ══════════════════════════════════════════════════════════════════
# STEP 8: Sample composition
# ══════════════════════════════════════════════════════════════════
note("\n── Step 8: Sample Composition ──")
n_tr_funds = panel[panel['treated']==1]['cik'].nunique()
n_ct_funds = panel[panel['treated']==0]['cik'].nunique()
n_tr_obs   = (panel['treated']==1).sum()
n_ct_obs   = (panel['treated']==0).sum()
mean_qt_tr = panel[panel['treated']==1].groupby('cik').size().mean()
mean_qt_ct = panel[panel['treated']==0].groupby('cik').size().mean()
mean_y_tr  = panel[panel['treated']==1]['dlog_value'].mean()
mean_y_ct  = panel[panel['treated']==0]['dlog_value'].mean()
tmin = panel['quarter'].min(); tmax = panel['quarter'].max()

comp = pd.DataFrame([
    {'metric': 'N treated funds',                  'value': n_tr_funds},
    {'metric': 'N control funds',                  'value': n_ct_funds},
    {'metric': 'N fund-quarter obs (treated)',      'value': n_tr_obs},
    {'metric': 'N fund-quarter obs (control)',      'value': n_ct_obs},
    {'metric': 'N fund-quarter obs (total)',        'value': len(panel)},
    {'metric': 'Mean obs per treated fund',         'value': round(mean_qt_tr, 1)},
    {'metric': 'Mean obs per control fund',         'value': round(mean_qt_ct, 1)},
    {'metric': 'Mean dlog_value treated',           'value': round(mean_y_tr, 4)},
    {'metric': 'Mean dlog_value control',           'value': round(mean_y_ct, 4)},
    {'metric': 'Time period',                       'value': f"{tmin} to {tmax}"},
])
print("\n=== Sample Composition ===")
print(comp.to_string(index=False))
comp.to_csv(OUT_DIR / 'sample_composition.csv', index=False)
note(f"  Saved: sample_composition.csv")


# ══════════════════════════════════════════════════════════════════
# FINAL NOTES SUMMARY
# ══════════════════════════════════════════════════════════════════
note("\n" + "=" * 60)
note("SUMMARY OF FINDINGS")
note("=" * 60)
note(f"1. Spike at k=0 survives fund trends: {survived}")
note(f"2. Pre-trend F-test: F={f_stat:.3f}, p={p_val:.4f} → {pretrend_verdict}")
note(f"3. Placebo at k=0: coef={k0_placebo:.4f} → {placebo_verdict}")
if len(bacon_df) > 0:
    note(f"4. Bacon: biased comparison weight = {biased_wgt:.1%}")
else:
    note("4. Bacon: not computed (insufficient cohort variation)")
note(f"5. Simple DiD POST coef: {simple_did['coef']:.4f} (p={simple_did['pvalue']:.4f})")

save_notes()
print(f"\nAll outputs saved to: {OUT_DIR}")
print(f"Notes saved to: {NOTES_PATH.name}")
