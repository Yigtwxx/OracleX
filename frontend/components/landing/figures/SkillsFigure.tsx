import { API, SKILLS } from '@/lib/generated/repo-facts';
import FigureFrame from './FigureFrame';

const API_SKILL = SKILLS.find((skill) => skill.generated !== null);

/**
 * How much of the API the agent skill documents, and why the rest is missing.
 *
 * One bar, because the interesting number is a ratio rather than a total: the
 * allowlist covers the operations an outside caller has a use for, and the
 * remainder is the interface talking to itself. Drawing the uncovered part as a
 * dashed outline rather than leaving it blank is what makes it read as a
 * decision instead of as a gap.
 */
export default function SkillsFigure() {
  const covered = API_SKILL?.generated;
  const share = covered ? (covered.endpoints / API.operations) * 100 : 0;

  return (
    <FigureFrame
      eyebrow="Agent skills"
      footnote={
        covered ? (
          <>
            {covered.file} · {covered.lines} lines, generated
            <br />
            the rest is the interface talking to itself
          </>
        ) : null
      }
    >
      <div className="flex h-[10px] w-full border border-dashed border-line">
        <span
          className="landing-bar block h-full bg-accent"
          style={{ '--w': `${share}%` } as React.CSSProperties}
        />
      </div>

      <p className="mt-2 font-mono text-2xs tabnum text-fg-subtle">
        {covered?.endpoints} of {API.operations} operations · {covered?.groups} groups
      </p>

      <ul className="mt-4 space-y-2">
        {SKILLS.map((skill) => (
          <li key={skill.name} className="flex items-baseline gap-2.5 font-mono text-2xs">
            <span className="flex-1 truncate text-fg">{skill.name}</span>
            <span className="tabnum text-fg-subtle">{skill.version}</span>
          </li>
        ))}
      </ul>
    </FigureFrame>
  );
}
