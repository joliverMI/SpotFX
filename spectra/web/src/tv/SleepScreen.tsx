/** THE SLEEP SCREEN (data/tv-display-plan/plan.html PR 1.5, §2.1):
 * "true black after 10 minutes with no night and no music" — OLED
 * pixels fully off. No readable content (nothing here needs the text-
 * size floors the other screens carry), and nothing to drift: a pure
 * black frame is, by construction, never a burn-in risk — the plan's
 * own reasoning for choosing black over "a still card" in the first
 * place. */
export default function SleepScreen() {
  return <div className="tv-sleep" aria-hidden="true" />;
}
