/**
 * The developers page, as content.
 *
 * One rule governs everything here and it is enforced by `sections.test.ts`:
 * **the prose carries no digits.** Every number on that page comes from
 * `lib/generated/repo-facts`, which is regenerated from the sources and checked
 * in CI. A sentence that says "thirty tools" is a claim that ages silently; a
 * figure that reads the count is a claim that fails the build when it stops
 * being true. Keeping the two apart is the only reason the page can be trusted
 * about the thing it is arguing for.
 *
 * `id` becomes the anchor and the spine's target, so it is slug-shaped and
 * stable. `index` is the mono number in the rail — zero-padded so the column
 * stays aligned in tabular figures.
 */

export interface DocSection {
  readonly id: string;
  readonly index: string;
  /** The short form, for the section spine. */
  readonly label: string;
  readonly title: string;
  /** Paragraphs. Two, usually: what it is, then why it is built that way. */
  readonly body: readonly string[];
}

export const DEVELOPER_SECTIONS: readonly DocSection[] = [
  {
    id: 'surface',
    index: '01',
    label: 'Surface',
    title: 'The API is the product',
    body: [
      'Everything the terminal draws, it fetched over HTTP. There is no private channel between the interface and the data, and nothing is reserved for the first-party client — a client you write sees exactly what the screen sees, from the same routes, with the same shapes.',
      'The price feed is the one exception, and it is an exception of kind rather than of access: a WebSocket route carries no schema entry, so it is absent from the OpenAPI document and a generated client will not find it. Worth knowing before you go looking for it.',
    ],
  },
  {
    id: 'tools',
    index: '02',
    label: 'Tools',
    title: 'Tools, not documentation',
    body: [
      'A skill has to be consulted. A tool is already in context. That difference is why the MCP server sits next to the agent skill rather than instead of it — the skill teaches an agent that decided to look, and the server reaches the agent that never would have.',
      'Not every operation is a tool. A tool list is context every turn pays for, so each one is a question someone actually asks, named for the question rather than for the route that answers it. The server is built on the official MCP SDK.',
    ],
  },
  {
    id: 'failure',
    index: '03',
    label: 'Failure',
    title: 'Three answers a caller can tell apart',
    body: [
      'Unreachable, declined, and answered are different facts about the world, and collapsing them is how a model comes to report an outage as a market call. The client keeps them separate: an instance that is not listening, an instance that refused, and an instance that replied are three distinct outcomes with three distinct types.',
      'Each arrives as data rather than as an exception. Raising through the transport hands the model a stack trace and an invitation to retry something that will fail identically; returning a reason lets it say what went wrong and stop.',
    ],
  },
  {
    id: 'skills',
    index: '04',
    label: 'Skills',
    title: 'Two skills, one of them generated',
    body: [
      'The judgement half of a skill — which endpoint answers which question, and what makes an answer honest — is written by hand, and no generator can produce it. The mechanical half is generated from the schema the app already publishes, because hand-maintained it drifts from the API within a release.',
      'The allowlist is deliberate rather than lazy. Most operations are the interface talking to itself, and documenting those would cost an agent context without buying it a capability.',
    ],
  },
  {
    id: 'models',
    index: '05',
    label: 'Models',
    title: 'The chain is rebuilt every call',
    body: [
      'What gets configured is not a provider but a chain, and it is assembled per request and never cached — so a key you fix while the server is running is live on the next call rather than after a restart. A provider the caller names is prepended to that chain rather than substituted for it, which keeps a preference a preference instead of a single point of failure.',
      'A provider that fails goes on cooldown, and it is the next call that skips it; this one has already moved down the chain and answered. The local model tag applies only to the local adapter, because handing an Ollama tag to a hosted provider produces nothing but a confusing error.',
    ],
  },
  {
    id: 'health',
    index: '06',
    label: 'Health',
    title: 'What "healthy" is allowed to mean',
    body: [
      'The registry is passive. Nothing probes an upstream to see whether it is alive — the HTTP helpers, the exchange client, the socket feed and the database wrapper each report what they already did, so the badge reflects real traffic and spends no rate limit to produce it.',
      'A category nobody called is idle, not guessed at. A long silence is stale: shown, and never counted as a fault. Only a call that actually failed can turn one red, and losing a critical category makes the terminal wrong rather than merely thinner — which is why they are grouped by what a reader would lose instead of by hostname.',
    ],
  },
  {
    id: 'checks',
    index: '07',
    label: 'Checks',
    title: 'What has to be true before it merges',
    body: [
      'The jobs have no dependencies between them, so the wall clock is whichever one is slowest rather than the sum. Two of them check that a generated file still matches the source it was derived from.',
      'The numbers on this page are one of those files. That is why they are numbers rather than claims: when one stops being true, the build fails instead of the page quietly ageing.',
    ],
  },
  {
    id: 'start',
    index: '08',
    label: 'Start',
    title: 'Run it',
    body: [
      'Clone the repository and start both servers with the script at the root; it handles the virtualenv, the ports and the initial index. The backend answers on its own port and the terminal opens against it.',
      'The MCP server installs from its own directory and talks HTTP to a running instance, so it needs no backend changes. Both agent skills live under the skill directory and install from there or from the committed archives.',
    ],
  },
];
