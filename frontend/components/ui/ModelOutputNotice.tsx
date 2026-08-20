/**
 * The standing caveat under anything a language model wrote.
 *
 * The prompts already tell the model to describe its own output as research
 * commentary — `prompts/chat/system.md`, `prompts/analysis/stage2_report.md`
 * and `prompts/news/system_sentiment.md` all carry the line. But an instruction
 * is not a guarantee: a model that omits it, or a fallback provider that
 * phrases it away, leaves the screen with no caveat at all. Rendering it from
 * the client makes it independent of what the model chose to say.
 *
 * Deliberately not a band in `ClientShell`. That shell is a fixed-height,
 * non-scrolling layout, so a permanent row there would cost height on all
 * thirteen routes — including the heatmap and the live feed, which show no
 * model output to caveat. This attaches to the surfaces that carry it instead.
 *
 * The border and spacing are left to the caller: the report footer wants a rule
 * above it, the chat composer already sits under one.
 */
export default function ModelOutputNotice({ className = '' }: { className?: string }) {
  return (
    <p className={`text-2xs text-fg-subtle ${className}`.trim()}>
      Model-generated and can be wrong — verify anything you act on. Research commentary, not
      personalised investment advice.
    </p>
  );
}
