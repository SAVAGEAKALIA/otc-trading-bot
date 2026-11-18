# 400-case agent panel: pre-registered plan (2026-11-18)

- **Cases:** 400 moments drawn at random from 2026-03-30 to 07-27, each on a 10-minute boundary. Each is at least 1 day from the 80 earlier panel moments and at least 1 hour from every other case. The answers are held outside the agents' folders (sha256 `ae4a7d16...`).
- **Agents:** the same 5 per-case forecasters and the same judge as the 40-case round, working from the same brief.
- **Primary test:** the judge's final calls. CERTIFIED requires all of:
  - at least 30 non-tie calls;
  - a one-sided 95% Clopper-Pearson lower bound on the win rate above its break-even (54.35% at 2/5 min, 53.76% at 10 min, averaged over its calls);
  - positive units won.
- **Secondary:** each forecaster, under the same rule at one-sided 99% (0.05 / 5).
- **One look:** all calls are frozen in git before `score.py` runs, and it refuses to run twice.
