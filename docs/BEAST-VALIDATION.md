# BEAST change-dating: independent validation

What we tested: `change_onset()` in `backend/insights/onset.py` (the "WHEN did it change?" tool), the
way the active-trend check uses it (`beast_gate` in `backend/active/engine.py`), and two simpler
methods already in the app, all on the same computer-made series. Script:
`scripts/beast_validation.py` (fixed seeds; `--quick` for a 2-minute smoke run). Study run 2026-11-15.

## Summary for students and judges

We tested the "when did it change?" tool on 3,720 computer-made monthly series where we know the
right answer. On 1,800 series that had a steady trend and **no** change, it wrongly "confirmed" a change
in 1.4% of them (95% CI 0.9-2.0%). That is below its 5% target overall. No single setting (noise level,
record length or missing-data pattern) was clearly above 5%: the highest was 7% (4 of 60, CI 2-16%). The price of that caution is that it misses many real changes: a
sudden jump of 1.5 noise standard deviations is confirmed every time when the noise has no memory, but only
10% of the time when the noise is very persistent, and a gradual change in slope is rarely confirmed
(at most 22% in our tests). So "no confirmed change" never means "no change". When it confirms a sudden
jump, the date is usually right to within a few months, but the "90% interval" contained the true date
only 68% of the time overall (about 30% for slope changes), so read it as a rough range, not a guarantee.
A much simpler method that is already in the app (PELT with its BIC check) found real changes about as
often, with a similar low false-alarm rate (3.6%); what BEAST adds is the "could this be chance?" test
and the probability ribbon, not extra detection power. In the active-trend check BEAST never backed a
wrong direction and never backed a trend in trend-free data, but it often said "cannot tell".

## Results

All rates are shown as `rate [95% CI] (count/trials)`; the CI is the exact (Clopper-Pearson) binomial
interval. phi is the true lag-1 autocorrelation (how much each month remembers the last one).
"BEAST confirmed" means an event with `status == "confirmed"`. For power, a detection counts only if its
date is within ±24 months of the true change. Dating errors are in months and use every detection, even
those more than 24 months off.

### Q1. False alarms on series with no change (target about 5%)

| months | missing | phi | median phi-hat | BEAST confirmed | BEAST confirmed or possible | Pettitt p<0.05 | Pettitt jump flag (integrity) | PELT any break | PELT BIC-preferred |
|---|---|---|---|---|---|---|---|---|---|
| 288 | none | 0.0 | 0.01 | 0% [0-6] (0/60) | 18% [10-30] (11/60) | 95% [86-99] (57/60) | 72% [59-83] (43/60) | 18% [10-30] (11/60) | 0% [0-6] (0/60) |
| 288 | none | 0.3 | 0.28 | 5% [1-14] (3/60) | 37% [25-50] (22/60) | 92% [82-97] (55/60) | 78% [66-88] (47/60) | 18% [10-30] (11/60) | 5% [1-14] (3/60) |
| 288 | none | 0.5 | 0.49 | 2% [0-9] (1/60) | 30% [19-43] (18/60) | 65% [52-77] (39/60) | 53% [40-66] (32/60) | 12% [5-23] (7/60) | 2% [0-9] (1/60) |
| 288 | none | 0.7 | 0.67 | 5% [1-14] (3/60) | 27% [16-40] (16/60) | 38% [26-52] (23/60) | 35% [23-48] (21/60) | 17% [8-29] (10/60) | 10% [4-21] (6/60) |
| 288 | none | 0.8 | 0.79 | 0% [0-6] (0/60) | 3% [0-12] (2/60) | 13% [6-25] (8/60) | 12% [5-23] (7/60) | 8% [3-18] (5/60) | 7% [2-16] (4/60) |
| 288 | random10 | 0.0 | 0.00 | 3% [0-12] (2/60) | 15% [7-27] (9/60) | 93% [84-98] (56/60) | 70% [57-81] (42/60) | 23% [13-36] (14/60) | 0% [0-6] (0/60) |
| 288 | random10 | 0.3 | 0.26 | 3% [0-12] (2/60) | 20% [11-32] (12/60) | 83% [71-92] (50/60) | 72% [59-83] (43/60) | 27% [16-40] (16/60) | 5% [1-14] (3/60) |
| 288 | random10 | 0.5 | 0.47 | 0% [0-6] (0/60) | 23% [13-36] (14/60) | 60% [47-72] (36/60) | 53% [40-66] (32/60) | 12% [5-23] (7/60) | 2% [0-9] (1/60) |
| 288 | random10 | 0.7 | 0.65 | 2% [0-9] (1/60) | 27% [16-40] (16/60) | 42% [29-55] (25/60) | 37% [25-50] (22/60) | 12% [5-23] (7/60) | 7% [2-16] (4/60) |
| 288 | random10 | 0.8 | 0.77 | 7% [2-16] (4/60) | 17% [8-29] (10/60) | 22% [12-34] (13/60) | 20% [11-32] (12/60) | 7% [2-16] (4/60) | 5% [1-14] (3/60) |
| 288 | block36 | 0.0 | 0.00 | 0% [0-6] (0/60) | 8% [3-18] (5/60) | 95% [86-99] (57/60) | 67% [53-78] (40/60) | 20% [11-32] (12/60) | 0% [0-6] (0/60) |
| 288 | block36 | 0.3 | 0.29 | 5% [1-14] (3/60) | 25% [15-38] (15/60) | 82% [70-90] (49/60) | 67% [53-78] (40/60) | 30% [19-43] (18/60) | 5% [1-14] (3/60) |
| 288 | block36 | 0.5 | 0.50 | 0% [0-6] (0/60) | 33% [22-47] (20/60) | 57% [43-69] (34/60) | 52% [38-65] (31/60) | 15% [7-27] (9/60) | 0% [0-6] (0/60) |
| 288 | block36 | 0.7 | 0.69 | 2% [0-9] (1/60) | 8% [3-18] (5/60) | 28% [17-41] (17/60) | 27% [16-40] (16/60) | 22% [12-34] (13/60) | 8% [3-18] (5/60) |
| 288 | block36 | 0.8 | 0.79 | 0% [0-6] (0/60) | 13% [6-25] (8/60) | 30% [19-43] (18/60) | 28% [17-41] (17/60) | 13% [6-25] (8/60) | 2% [0-9] (1/60) |
| 180 | none | 0.0 | 0.01 | 0% [0-6] (0/60) | 20% [11-32] (12/60) | 65% [52-77] (39/60) | 58% [45-71] (35/60) | 25% [15-38] (15/60) | 5% [1-14] (3/60) |
| 180 | none | 0.3 | 0.28 | 0% [0-6] (0/60) | 27% [16-40] (16/60) | 40% [28-53] (24/60) | 38% [26-52] (23/60) | 18% [10-30] (11/60) | 2% [0-9] (1/60) |
| 180 | none | 0.5 | 0.48 | 0% [0-6] (0/60) | 28% [17-41] (17/60) | 20% [11-32] (12/60) | 15% [7-27] (9/60) | 17% [8-29] (10/60) | 7% [2-16] (4/60) |
| 180 | none | 0.7 | 0.68 | 0% [0-6] (0/60) | 17% [8-29] (10/60) | 15% [7-27] (9/60) | 13% [6-25] (8/60) | 3% [0-12] (2/60) | 2% [0-9] (1/60) |
| 180 | none | 0.8 | 0.79 | 0% [0-6] (0/60) | 12% [5-23] (7/60) | 5% [1-14] (3/60) | 5% [1-14] (3/60) | 8% [3-18] (5/60) | 5% [1-14] (3/60) |
| 180 | random10 | 0.0 | 0.00 | 0% [0-6] (0/60) | 10% [4-21] (6/60) | 43% [31-57] (26/60) | 42% [29-55] (25/60) | 25% [15-38] (15/60) | 2% [0-9] (1/60) |
| 180 | random10 | 0.3 | 0.28 | 2% [0-9] (1/60) | 25% [15-38] (15/60) | 37% [25-50] (22/60) | 35% [23-48] (21/60) | 20% [11-32] (12/60) | 0% [0-6] (0/60) |
| 180 | random10 | 0.5 | 0.46 | 3% [0-12] (2/60) | 35% [23-48] (21/60) | 25% [15-38] (15/60) | 25% [15-38] (15/60) | 15% [7-27] (9/60) | 5% [1-14] (3/60) |
| 180 | random10 | 0.7 | 0.66 | 0% [0-6] (0/60) | 17% [8-29] (10/60) | 7% [2-16] (4/60) | 7% [2-16] (4/60) | 12% [5-23] (7/60) | 7% [2-16] (4/60) |
| 180 | random10 | 0.8 | 0.77 | 2% [0-9] (1/60) | 13% [6-25] (8/60) | 0% [0-6] (0/60) | 0% [0-6] (0/60) | 3% [0-12] (2/60) | 2% [0-9] (1/60) |
| 180 | block36 | 0.0 | 0.00 | 0% [0-6] (0/60) | 18% [10-30] (11/60) | 60% [47-72] (36/60) | 53% [40-66] (32/60) | 22% [12-34] (13/60) | 0% [0-6] (0/60) |
| 180 | block36 | 0.3 | 0.25 | 2% [0-9] (1/60) | 52% [38-65] (31/60) | 43% [31-57] (26/60) | 40% [28-53] (24/60) | 37% [25-50] (22/60) | 3% [0-12] (2/60) |
| 180 | block36 | 0.5 | 0.47 | 0% [0-6] (0/60) | 43% [31-57] (26/60) | 23% [13-36] (14/60) | 22% [12-34] (13/60) | 25% [15-38] (15/60) | 3% [0-12] (2/60) |
| 180 | block36 | 0.7 | 0.67 | 0% [0-6] (0/60) | 25% [15-38] (15/60) | 18% [10-30] (11/60) | 15% [7-27] (9/60) | 25% [15-38] (15/60) | 3% [0-12] (2/60) |
| 180 | block36 | 0.8 | 0.75 | 0% [0-6] (0/60) | 5% [1-14] (3/60) | 13% [6-25] (8/60) | 12% [5-23] (7/60) | 23% [13-36] (14/60) | 7% [2-16] (4/60) |

Pooled BEAST false-alarm rate by missing-data pattern: none: 1% [0-2] (7/600); random10: 2% [1-4] (13/600); block36: 1% [0-2] (5/600)

Pooled by phi (both lengths, all missing patterns), BEAST confirmed vs PELT BIC-preferred: phi 0.0: 1% [0-2] (2/360) vs 1% [0-3] (4/360); phi 0.3: 3% [1-5] (10/360) vs 3% [2-6] (12/360); phi 0.5: 1% [0-2] (3/360) vs 3% [2-5] (11/360); phi 0.7: 1% [0-3] (5/360) vs 6% [4-9] (22/360); phi 0.8: 1% [0-3] (5/360) vs 4% [3-7] (16/360)

All 1800 no-change series: BEAST confirmed 1% [1-2] (25/1800); BEAST confirmed or possible 22% [20-24] (391/1800); PELT BIC-preferred 4% [3-5] (65/1800); PELT any break 18% [16-20] (319/1800); Pettitt jump flag 37% [35-40] (673/1800).

### Q2-Q3. Power (detection within +/-24 months of the true date) and dating error

Effect sizes in noise-SD units (jump) and noise-SD per decade (slope change); 288 months; break month uniform in [60, 228].

| change | jump | slope chg | phi | BEAST power | PELT power (BIC-preferred) | PELT power (any break) | Pettitt power (p<0.05) | Pettitt power (jump flag) | BEAST abs err median/P90 (mo) | Pettitt err med/P90 | PELT err med/P90 | interval90 coverage |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| slope | 0.0 | 0.5 | 0.0 | 2% [0-13] (1/40) | 2% [0-13] (1/40) | 15% [6-30] (6/40) | 40% [25-57] (16/40) | 28% [15-44] (11/40) | 36/59 | 37/73 | 31/75 | 50% [1-99] (1/2) |
| slope | 0.0 | 0.5 | 0.3 | 2% [0-13] (1/40) | 2% [0-13] (1/40) | 8% [2-20] (3/40) | 15% [6-30] (6/40) | 10% [3-24] (4/40) | 34/88 | 46/88 | 29/73 | 33% [1-91] (1/3) |
| slope | 0.0 | 0.5 | 0.5 | 0% [0-9] (0/40) | 0% [0-9] (0/40) | 8% [2-20] (3/40) | 28% [15-44] (11/40) | 20% [9-36] (8/40) | 33/33 | 33/92 | 41/99 | 0% [0-98] (0/1) |
| slope | 0.0 | 0.5 | 0.7 | 0% [0-9] (0/40) | 0% [0-9] (0/40) | 2% [0-13] (1/40) | 25% [13-41] (10/40) | 18% [7-33] (7/40) | 79/103 | 44/84 | 74/106 | 0% [0-84] (0/2) |
| slope | 0.0 | 0.5 | 0.8 | 0% [0-9] (0/40) | 0% [0-9] (0/40) | 0% [0-9] (0/40) | 15% [6-30] (6/40) | 12% [4-27] (5/40) | 96/115 | 41/98 | 71/71 | 0% [0-84] (0/2) |
| slope | 0.0 | 1.0 | 0.0 | 0% [0-9] (0/40) | 8% [2-20] (3/40) | 18% [7-33] (7/40) | 25% [13-41] (10/40) | 15% [6-30] (6/40) | 39/77 | 39/78 | 44/75 | 0% [0-52] (0/5) |
| slope | 0.0 | 1.0 | 0.3 | 8% [2-20] (3/40) | 8% [2-20] (3/40) | 10% [3-24] (4/40) | 35% [21-52] (14/40) | 20% [9-36] (8/40) | 28/71 | 31/88 | 33/64 | 33% [4-78] (2/6) |
| slope | 0.0 | 1.0 | 0.5 | 5% [1-17] (2/40) | 2% [0-13] (1/40) | 5% [1-17] (2/40) | 28% [15-44] (11/40) | 10% [3-24] (4/40) | 50/89 | 39/82 | 76/153 | 25% [1-81] (1/4) |
| slope | 0.0 | 1.0 | 0.7 | 0% [0-9] (0/40) | 2% [0-13] (1/40) | 2% [0-13] (1/40) | 8% [2-20] (3/40) | 8% [2-20] (3/40) | 139/149 | 55/86 | 49/142 | 0% [0-71] (0/3) |
| slope | 0.0 | 1.0 | 0.8 | 2% [0-13] (1/40) | 0% [0-9] (0/40) | 0% [0-9] (0/40) | 15% [6-30] (6/40) | 12% [4-27] (5/40) | 30/44 | 54/85 | 57/65 | 0% [0-84] (0/2) |
| slope | 0.0 | 2.0 | 0.0 | 22% [11-38] (9/40) | 35% [21-52] (14/40) | 38% [23-54] (15/40) | 52% [36-68] (21/40) | 18% [7-33] (7/40) | 21/32 | 22/73 | 32/62 | 33% [12-62] (5/15) |
| slope | 0.0 | 2.0 | 0.3 | 22% [11-38] (9/40) | 22% [11-38] (9/40) | 30% [17-47] (12/40) | 45% [29-62] (18/40) | 25% [13-41] (10/40) | 22/148 | 30/86 | 33/76 | 35% [14-62] (6/17) |
| slope | 0.0 | 2.0 | 0.5 | 15% [6-30] (6/40) | 22% [11-38] (9/40) | 25% [13-41] (10/40) | 32% [19-49] (13/40) | 20% [9-36] (8/40) | 32/63 | 42/71 | 32/94 | 23% [5-54] (3/13) |
| slope | 0.0 | 2.0 | 0.7 | 10% [3-24] (4/40) | 12% [4-27] (5/40) | 12% [4-27] (5/40) | 40% [25-57] (16/40) | 12% [4-27] (5/40) | 40/135 | 37/82 | 45/64 | 25% [5-57] (3/12) |
| slope | 0.0 | 2.0 | 0.8 | 5% [1-17] (2/40) | 8% [2-20] (3/40) | 12% [4-27] (5/40) | 40% [25-57] (16/40) | 20% [9-36] (8/40) | 27/141 | 28/66 | 23/61 | 0% [0-52] (0/5) |
| jump | 0.5 | 0.0 | 0.0 | 10% [3-24] (4/40) | 10% [3-24] (4/40) | 30% [17-47] (12/40) | 75% [59-87] (30/40) | 48% [32-64] (19/40) | 6/86 | 14/52 | 8/118 | 80% [28-99] (4/5) |
| jump | 0.5 | 0.0 | 0.3 | 10% [3-24] (4/40) | 10% [3-24] (4/40) | 12% [4-27] (5/40) | 68% [51-81] (27/40) | 45% [29-62] (18/40) | 2/25 | 15/79 | 34/123 | 60% [15-95] (3/5) |
| jump | 0.5 | 0.0 | 0.5 | 0% [0-9] (0/40) | 0% [0-9] (0/40) | 2% [0-13] (1/40) | 58% [41-73] (23/40) | 52% [36-68] (21/40) | -/- | 18/60 | 66/116 | n/a |
| jump | 0.5 | 0.0 | 0.7 | 5% [1-17] (2/40) | 8% [2-20] (3/40) | 8% [2-20] (3/40) | 22% [11-38] (9/40) | 22% [11-38] (9/40) | 10/16 | 32/83 | 24/119 | 50% [1-99] (1/2) |
| jump | 0.5 | 0.0 | 0.8 | 0% [0-9] (0/40) | 0% [0-9] (0/40) | 5% [1-17] (2/40) | 40% [25-57] (16/40) | 38% [23-54] (15/40) | 25/25 | 13/71 | 2/3 | 0% [0-98] (0/1) |
| jump | 1.0 | 0.0 | 0.0 | 70% [53-83] (28/40) | 62% [46-77] (25/40) | 80% [64-91] (32/40) | 90% [76-97] (36/40) | 58% [41-73] (23/40) | 2/6 | 3/21 | 2/16 | 90% [73-98] (26/29) |
| jump | 1.0 | 0.0 | 0.3 | 52% [36-68] (21/40) | 50% [34-66] (20/40) | 58% [41-73] (23/40) | 90% [76-97] (36/40) | 78% [62-89] (31/40) | 2/90 | 2/25 | 4/59 | 84% [64-95] (21/25) |
| jump | 1.0 | 0.0 | 0.5 | 25% [13-41] (10/40) | 32% [19-49] (13/40) | 45% [29-62] (18/40) | 80% [64-91] (32/40) | 72% [56-85] (29/40) | 2/6 | 4/40 | 4/45 | 80% [44-97] (8/10) |
| jump | 1.0 | 0.0 | 0.7 | 8% [2-20] (3/40) | 5% [1-17] (2/40) | 10% [3-24] (4/40) | 80% [64-91] (32/40) | 68% [51-81] (27/40) | 6/124 | 6/34 | 24/113 | 60% [15-95] (3/5) |
| jump | 1.0 | 0.0 | 0.8 | 5% [1-17] (2/40) | 5% [1-17] (2/40) | 5% [1-17] (2/40) | 52% [36-68] (21/40) | 48% [32-64] (19/40) | 30/115 | 8/59 | 32/58 | 33% [4-78] (2/6) |
| jump | 1.5 | 0.0 | 0.0 | 100% [91-100] (40/40) | 100% [91-100] (40/40) | 100% [91-100] (40/40) | 92% [80-98] (37/40) | 68% [51-81] (27/40) | 0/3 | 3/18 | 1/5 | 100% [91-100] (40/40) |
| jump | 1.5 | 0.0 | 0.3 | 92% [80-98] (37/40) | 98% [87-100] (39/40) | 100% [91-100] (40/40) | 90% [76-97] (36/40) | 70% [53-83] (28/40) | 2/9 | 4/19 | 2/8 | 89% [75-97] (34/38) |
| jump | 1.5 | 0.0 | 0.5 | 58% [41-73] (23/40) | 52% [36-68] (21/40) | 60% [43-75] (24/40) | 92% [80-98] (37/40) | 78% [62-89] (31/40) | 2/13 | 5/19 | 3/38 | 92% [73-99] (22/24) |
| jump | 1.5 | 0.0 | 0.7 | 35% [21-52] (14/40) | 28% [15-44] (11/40) | 30% [17-47] (12/40) | 78% [62-89] (31/40) | 70% [53-83] (28/40) | 4/13 | 6/36 | 7/94 | 80% [52-96] (12/15) |
| jump | 1.5 | 0.0 | 0.8 | 10% [3-24] (4/40) | 2% [0-13] (1/40) | 2% [0-13] (1/40) | 58% [41-73] (23/40) | 50% [34-66] (20/40) | 11/36 | 7/53 | 32/34 | 43% [10-82] (3/7) |
| both | 0.5 | 0.5 | 0.0 | 15% [6-30] (6/40) | 18% [7-33] (7/40) | 32% [19-49] (13/40) | 55% [38-71] (22/40) | 20% [9-36] (8/40) | 3/26 | 22/63 | 12/85 | 86% [42-100] (6/7) |
| both | 0.5 | 0.5 | 0.3 | 5% [1-17] (2/40) | 2% [0-13] (1/40) | 22% [11-38] (9/40) | 52% [36-68] (21/40) | 25% [13-41] (10/40) | 5/7 | 22/76 | 17/97 | 100% [16-100] (2/2) |
| both | 0.5 | 0.5 | 0.5 | 5% [1-17] (2/40) | 5% [1-17] (2/40) | 8% [2-20] (3/40) | 60% [43-75] (24/40) | 30% [17-47] (12/40) | 30/87 | 21/68 | 30/103 | 40% [5-85] (2/5) |
| both | 0.5 | 0.5 | 0.7 | 0% [0-9] (0/40) | 5% [1-17] (2/40) | 5% [1-17] (2/40) | 55% [38-71] (22/40) | 42% [27-59] (17/40) | 56/56 | 16/65 | 9/47 | 0% [0-98] (0/1) |
| both | 0.5 | 0.5 | 0.8 | 0% [0-9] (0/40) | 0% [0-9] (0/40) | 0% [0-9] (0/40) | 28% [15-44] (11/40) | 25% [13-41] (10/40) | -/- | 42/74 | 48/51 | n/a |
| both | 1.0 | 1.0 | 0.0 | 70% [53-83] (28/40) | 80% [64-91] (32/40) | 85% [70-94] (34/40) | 60% [43-75] (24/40) | 10% [3-24] (4/40) | 3/16 | 18/66 | 4/18 | 90% [73-98] (26/29) |
| both | 1.0 | 1.0 | 0.3 | 45% [29-62] (18/40) | 42% [27-59] (17/40) | 62% [46-77] (25/40) | 68% [51-81] (27/40) | 20% [9-36] (8/40) | 5/19 | 10/60 | 9/50 | 74% [49-91] (14/19) |
| both | 1.0 | 1.0 | 0.5 | 32% [19-49] (13/40) | 30% [17-47] (12/40) | 35% [21-52] (14/40) | 70% [53-83] (28/40) | 40% [25-57] (16/40) | 4/69 | 10/55 | 20/68 | 67% [41-87] (12/18) |
| both | 1.0 | 1.0 | 0.7 | 15% [6-30] (6/40) | 12% [4-27] (5/40) | 12% [4-27] (5/40) | 62% [46-77] (25/40) | 30% [17-47] (12/40) | 5/54 | 14/62 | 35/106 | 44% [14-79] (4/9) |
| both | 1.0 | 1.0 | 0.8 | 2% [0-13] (1/40) | 2% [0-13] (1/40) | 2% [0-13] (1/40) | 55% [38-71] (22/40) | 40% [25-57] (16/40) | 0/0 | 18/68 | 0/0 | 100% [2-100] (1/1) |

Pooled over all power cells (every detection, not only those within 24 months): BEAST |error| median 4, P90 65 months (n=395); Pettitt 19/71 (n=1482); PELT nearest break 12/81 (n=639). interval90 coverage pooled: 68% [63-72] (268/395).

### Q4. Active-trend detect + beast_gate end to end (288 months, change 120 months before the end)

| scenario | true recent dir. | phi | detect active | detect dir. correct | gate agrees | gate disagrees | gate uncertain | active AND agrees AND dir. correct | active AND agrees AND dir. wrong |
|---|---|---|---|---|---|---|---|---|---|
| steady_rise | rising | 0.3 | 50% [34-66] (20/40) | 95% [83-99] (38/40) | 60% [43-75] (24/40) | 0% [0-9] (0/40) | 40% [25-57] (16/40) | 40% [25-57] (16/40) | 0% [0-9] (0/40) |
| steady_rise | rising | 0.7 | 22% [11-38] (9/40) | 90% [76-97] (36/40) | 20% [9-36] (8/40) | 0% [0-9] (0/40) | 80% [64-91] (32/40) | 10% [3-24] (4/40) | 0% [0-9] (0/40) |
| recent_reversal | falling | 0.3 | 88% [73-96] (35/40) | 98% [87-100] (39/40) | 45% [29-62] (18/40) | 2% [0-13] (1/40) | 52% [36-68] (21/40) | 42% [27-59] (17/40) | 0% [0-9] (0/40) |
| recent_reversal | falling | 0.7 | 52% [36-68] (21/40) | 92% [80-98] (37/40) | 5% [1-17] (2/40) | 2% [0-13] (1/40) | 92% [80-98] (37/40) | 5% [1-17] (2/40) | 0% [0-9] (0/40) |
| recent_acceleration | rising | 0.3 | 100% [91-100] (40/40) | 100% [91-100] (40/40) | 60% [43-75] (24/40) | 5% [1-17] (2/40) | 35% [21-52] (14/40) | 60% [43-75] (24/40) | 0% [0-9] (0/40) |
| recent_acceleration | rising | 0.7 | 60% [43-75] (24/40) | 98% [87-100] (39/40) | 35% [21-52] (14/40) | 0% [0-9] (0/40) | 65% [48-79] (26/40) | 32% [19-49] (13/40) | 0% [0-9] (0/40) |
| no_trend | none | 0.3 | 15% [6-30] (6/40) | n/a | 0% [0-9] (0/40) | 0% [0-9] (0/40) | 100% [91-100] (40/40) | 0% [0-9] (0/40) | 0% [0-9] (0/40) |
| no_trend | none | 0.7 | 5% [1-17] (2/40) | n/a | 0% [0-9] (0/40) | 0% [0-9] (0/40) | 100% [91-100] (40/40) | 0% [0-9] (0/40) | 0% [0-9] (0/40) |

change_onset wall time per call: median 5.0 s (n=3400).


### How to read the gate table

`agrees` / `disagrees` / `uncertain` is what `beast_gate` returned. "detect active" is
`detect().state` in active / accelerating / emerging / reversed; in the app the gate only runs on those
candidates. The last two columns are the outcomes that matter for a `VERIFIED` label: BEAST backing the
right direction, or backing a wrong one. Across 320 runs BEAST never backed a wrong direction and never
agreed with a direction in trend-free data, but it returned `uncertain` in 35-92% of runs that had a real
recent trend. With persistent noise (phi 0.7) it backed a real recent reversal only 5% of the time.
In practice, `VERIFIED` is hard to reach for persistent variables, so `PROBABLE` will be the common label
there. That is conservative, not wrong.

## One calibration table (replaces the two that disagree)

The docstring in `onset.py` and `docs/STATISTICS.md` give different numbers for the same design. We
re-ran the original design, `python scripts/onset_calibration.py --trials 25`, on the current code.
The design: 288 months, seasonal cycle, noise 0.4 × AR(1); the true break at month 144 is a 0.6 jump plus a
0.1/yr slope change; a hit is a confirmed change within ±24 months:

| phi | raw BEAST false alarms | calibrated false alarms | calibrated power |
|---|---|---|---|
| 0.0 | 0/25 | 0/25 | 25/25 |
| 0.5 | 24/25 | 0/25 | 19/25 |
| 0.7 | 25/25 | 1/25 | 6/25 |
| 0.8 | 25/25 | 0/25 | 2/25 |

This matches `docs/STATISTICS.md` to within one series per cell (STATISTICS.md has 24/25 power at phi 0
and 25/25 raw false alarms at phi 0.5). The docstring table (1, 2, 1 false alarms; power 20, 10, 4)
does not match the current code; it looks like it was left over from an earlier version. With 25 trials
a 0/25 false-alarm count still has a 95% CI of 0-14%, so the larger study above is the one to quote:

| phi | false alarms, no-change series (this study, 360 per phi) | power, 1.0 SD jump | power, 1.0 SD jump + 1.0 SD/decade slope change |
|---|---|---|---|
| 0.0 | 1% [0-2] (2/360) | 70% [53-83] | 70% [53-83] |
| 0.3 | 3% [1-5] (10/360) | 52% [36-68] | 45% [29-62] |
| 0.5 | 1% [0-2] (3/360) | 25% [13-41] | 32% [19-49] |
| 0.7 | 1% [0-3] (5/360) | 8% [2-20] | 15% [6-30] |
| 0.8 | 1% [0-3] (5/360) | 5% [1-17] | 2% [0-13] |

## Is BEAST worth it compared with the baselines?

- **False alarms.** BEAST confirmed 1.4% [0.9-2.0] of 1,800 no-change series. PELT's BIC-preferred rule
  found a break in 3.6% [2.8-4.6], rising to 6% [4-9] at phi 0.7. PELT's "any break" (shown with a
  "weak evidence" note when BIC disagrees) fired on 18%. Pettitt is a test for a shift in level, so a
  steady trend breaks its assumption: it rejected on 95% of steady-trend series at phi 0 and 288 months.
  The integrity "single jump" flag built on it fired on 37% of all no-change series (see Issues).
- **Power.** BEAST and PELT (BIC-preferred) have about the same power in every cell. Their CIs overlap
  everywhere, and neither is consistently ahead. Pettitt's higher "power" is not a fair comparison,
  because it fires just as often without any change.
- **Dating.** When BEAST confirms a 1.5 SD jump with phi ≤ 0.5, the median error is 0-2 months and the
  90th percentile is 3-13 months, a little better than Pettitt and PELT on the same series. For 1.0 SD
  jumps the median is still about 2 months, but the 90th percentile reaches 90 months at phi 0.3,
  because sometimes the wrong event is confirmed (Issue 1). For slope changes all three methods are
  poor (median errors mostly 20-80 months), because a gradual bend has no sharp date.
- **Cost.** BEAST takes about 5 s per series (49 surrogates); PELT takes milliseconds.
- **Verdict.** BEAST is not a better detector than the PELT already in the app. Its value is the
  calibrated "could this be chance?" p-value, which PELT does not have, the probability ribbon for
  students, and slightly sharper dates for sudden jumps. Using both, and treating agreement
  (`agrees_with_pelt`) as the stronger statement, is reasonable. Presenting BEAST as more powerful would be
  an overclaim.

## Issues found (not fixed here; for the backend owner)

1. **The confirmed change can be the wrong one.** Only the event with the highest *window
   probability* can be confirmed. Its F statistic can still be large because a broken line fitted at
   the wrong date partly absorbs a real change somewhere else. Failing case: the `power|jump|jump=1.0|dslope=0.0|phi=0.3`
   cell, trial 4 (true 1.0 SD jump at 2014-05). `change_onset` confirms **2005-02**
   (probability 100%, F = 18.8, p = 0.02, interval 2003-03 to 2005-07). The event nearer the truth, 2013-01
   (F = 21.1, p = 0.02), is shown only as "possible". Smallest fix: confirm the candidate with the
   largest F, and make the null use the same rule. In `_top_change_stat`, take the maximum F over the
   same up-to-3 greedy windows (zeroing ±2 windows after each, as the main loop does). In `change_onset`, replace the
   `for e in events[1:]` demotion with "demote every confirmed event except `max(events, key=f_stat)`".
   We tested this on a patched copy, re-running 8 cells (380 trials). The failing case then confirms
   2013-01, and false alarms in the three null cells tried were unchanged (3/60, 3/60, 2/60). Power for
   1.0 SD jumps changed from 70/52/25% to 72/58/28% (phi 0/0.3/0.5), and the 90th-percentile dating error
   at phi 0.3 fell from 90 to 42 months. These gains are inside the CIs, so the fix is a correctness
   improvement, not a proven power gain.
2. **`interval90` is too narrow.** Pooled coverage is 68% [63-72] (268/395 confirmed events), against
   a nominal 90%. It is about right for sudden jumps with low persistence (80-100%) and far too low for
   slope changes (0-35%). The quantiles are taken only from posterior mass inside ±1 year of the peak,
   so the interval can never be wider than about 2 years plus one block. It is often only 11-28 months
   wide, while slope-change dating errors are mostly 20-80 months. Smallest honest fix: call it "BEAST's
   range around its peak", not a 90% interval. A real fix would compute the quantiles over a wider
   span, or from the F-statistic profile, and would need re-validating with this script.
3. **The integrity "single jump" flag fires on steady trends** (`backend/novelty/integrity.py:
   trend_or_jump`). This affects F1 and the active-trend integrity check, not BEAST, and was found
   through the Pettitt baseline. The flag (`best_model == "jump"` and Pettitt p < 0.05) fired on 37%
   [35-40] of the 1,800 no-change series, and on 72% at phi 0 with 288 months. Failing case: the
   `null|n=288|miss=none|phi=0.0` cell, trial 0 (a pure 0.3 SD/decade trend with white noise) gives
   "A single jump around 2010-03 explains the data better than a steady trend". Here BIC is trend −20.5 and
   jump −23.5. Cause: the jump date is chosen by searching every month, but BIC does not count that
   search as a parameter. Smallest fix: add `log(neff)` to the BIC of the `jump` and
   `trend_plus_jump` models. In a scratch test on the same 60 series this cut the flag from 43/60 to
   12/60. That is still high, so a calibrated test (for example the surrogate approach `onset.py` already
   uses) is the proper fix. Effect today: clean steady trends often get an integrity `warn` (badge CAUTION),
   and the label rules do not allow `VERIFIED` when there is an integrity warning.
4. **Minor.** The docstring says a block counts "only if half its months are valid", but the code uses
   `L // 2` (for example 1 of 3 months, 2 of 5). Missing months make the memory estimate in
   `_line_and_memory` slightly low, because it computes lag-1 on the series with the gaps closed up (it
   pairs months across a gap). The measured effect was small: median phi-hat 0.65 vs 0.67 at phi 0.7, and
   no rise in false alarms beyond the CI.
5. **About "possible" events.** 22% [20-24] of no-change series show at least one "possible" change.
   The app is right not to present "possible" as a finding. The UI should show "possible" with its
   `plain_language` ("not stronger than what persistent noise produces"), never as a result.

## Methods

- **Series.** Monthly, starting 2001-01, 288 months (24 years) or 180 months (15 years). Value =
  1.5·sin(2π·t) seasonal cycle + a 0.3 SD/decade linear trend + Gaussian AR(1) noise scaled to unit
  marginal SD, so every effect size is in noise-SD units whatever phi is. phi ∈ {0, 0.3, 0.5, 0.7, 0.8}.
- **Missing data (null only).** `none`; `random10`: each month missing with probability 0.10;
  `block36`: 36 consecutive missing months starting at a random month in [24, n−60). Missing months
  are NaN and never filled.
- **Changes (power, 288 months, no missing data).** The break month is uniform in [60, 228]. `slope`:
  slope change of 0.5 / 1 / 2 SD per decade; `jump`: level jump of 0.5 / 1 / 1.5 SD; `both`:
  0.5 + 0.5 and 1 + 1.
- **Trials.** 60 per null cell (30 cells, 1,800 series), 40 per power cell (40 cells, 1,600 series),
  40 per gate cell (8 cells, 320 series); 3,720 in total.
- **Method under test.** `change_onset(ms, n_surrogates=49)` with all other API defaults (seed 2026,
  alpha 0.05, max_events 3, min_event_prob 0.5), exactly as `runner.py` calls it.
- **Baselines on the same series.** (a) `trend_or_jump(t, a, time)` on the STL anomalies, as
  `integrity_audit` does, using its AR(1)-corrected Pettitt p. "Pettitt p<0.05" is the raw test; "jump flag"
  adds `best_model == "jump"`, which is the rule that raises the F1 / active-trend warning.
  (b) `detect_trend_breaks(time, t, a, min_segment_years=4)` on the STL anomalies, as
  `backend/insights/engine.py` calls it. "any break" = at least one break; "BIC-preferred" = also
  `segmented_preferred`. The PELT dating error uses the break nearest the truth, which favours PELT
  slightly.
- **Gate scenarios.** 288 months, slope changes 120 months before the end (the start of
  `detect()`'s recent window): steady rise 0.8 SD/decade; reversal +0.8 → −1.5; acceleration
  0.3 → 1.5; no trend. phi 0.3 and 0.7. Each series goes through `detect(ms)`, `change_onset(ms)` and then
  `beast_gate(onset, det)`.
- **Reproducibility.** Each trial's data come from
  `numpy.random.default_rng([crc32(cell name), trial])`, so any one trial can be rebuilt alone (the
  issue examples above were rebuilt this way). Run: `python scripts/beast_validation.py --out results.json`
  (32.7 min on 10 processes; median 5.0 s per `change_onset` call). Re-print the tables without
  simulating: `--summarize results.json`. Smoke test: `--quick` (128 trials, about 1 min).
  It uses a process pool, because Rbeast holds the Python GIL.

## Honest limits of this study

- The noise is Gaussian AR(1). Real anomalies can have heavier tails, memory that lasts longer than
  AR(1) allows, a seasonal cycle that changes over time, and changing variance. False-alarm rates on
  real data could be higher than shown here.
- Every changed series has exactly one change, placed at least 5 years from either end. Changes very
  near the end of the record (the "is it changing now?" case) were tested only through the gate
  scenarios, not for dating.
- Missing data was tested only for false alarms, not for power or dating.
- 40-60 trials per cell give wide CIs (about ±10-15 points). Use the pooled rates for overall
  statements and the cells only for patterns.
- The MCMC seed is fixed at 2026, as in production. Results with other seeds would differ slightly.
- Dating errors and coverage are measured only on series where a method detected something, so they
  are conditional and not comparable as unconditional accuracy.
- The proposed fixes in "Issues found" were checked only on a subset of cells, in a scratch copy.
  After any change to `onset.py`, re-run this script and replace the tables.
