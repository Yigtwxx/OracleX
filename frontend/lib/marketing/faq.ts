/**
 * The questions, and answers that do not oversell.
 *
 * Every answer here is checkable against the code it describes, and several of
 * them are deliberately unflattering: the equity universe is small, the local
 * model is the constraint, and a hosted provider means prompts leave the
 * machine. A FAQ that only answered the comfortable questions would be the
 * marketing copy this whole surface is arguing against.
 *
 * `id` becomes the anchor, so `/faq#where-does-my-data-live` opens that entry
 * directly. Slugs are stable; changing one breaks a link someone kept.
 */

export interface FaqEntry {
  readonly id: string;
  readonly question: string;
  /** Paragraphs. One is usual, two when the honest answer has a condition. */
  readonly answer: readonly string[];
}

export interface FaqGroup {
  readonly id: string;
  readonly label: string;
  readonly entries: readonly FaqEntry[];
}

export const FAQ_GROUPS: readonly FaqGroup[] = [
  {
    id: 'trust',
    label: 'Trust and limits',
    entries: [
      {
        id: 'is-this-advice',
        question: 'Is this investment advice?',
        answer: [
          'No. The terminal shows evidence and where it came from; it does not take positions, size them, or tell you to. Every conclusion it writes is meant to be argued with, which is why the rows underneath one are always reachable from it.',
        ],
      },
      {
        id: 'model-is-wrong',
        question: 'What happens when the model is wrong?',
        answer: [
          'You can see that it is. A report is built in passes: evidence is gathered and cited before anything is written, a draft is built against that evidence, and a review pass reads the draft the way a sceptic would — hunting for the claim with nothing underneath it and the number that contradicts the conclusion.',
          'That does not make it right. It makes it checkable, which is a different and more useful property: a wrong claim still points at the row it came from, so you can see exactly where the reasoning left the evidence.',
        ],
      },
      {
        id: 'why-refuse',
        question: 'Why does an analysis sometimes refuse to answer?',
        answer: [
          'Because there was not enough to say anything with. Before a verdict is written the evidence is put through a floor test — distinct sources, distinct publishers, full article bodies from desks that publish corrections, and how much primary text actually reached the prompt. Below any of those floors the endpoint answers with a refusal and names every search that came back empty.',
          'A refusal is a successful run, not an error. The facts and the market microstructure are computed without a model and are served either way, so a refusal is a page with less on it rather than a broken one.',
        ],
      },
      {
        id: 'cite-itself',
        question: 'Can the system cite itself as a source?',
        answer: [
          'No. Retrieval hits are this application remembering what it once concluded, not an independent newsroom, and they never count toward the corroboration requirement. Letting them would let the system cite its way into confidence about something no one else ever reported.',
        ],
      },
      {
        id: 'price-404',
        question: 'Why do I sometimes get an error instead of a price?',
        answer: [
          'Because the symbol could not be resolved and the API declines rather than guessing. A plausible wrong number in a trading terminal is worse than a visible failure — you act on the first and you investigate the second.',
        ],
      },
      {
        id: 'who-writes-refusal',
        question: 'Who writes the refusal text?',
        answer: [
          'Python does, from the counts themselves. A model asked to explain why it had too little to go on writes a paragraph that reads exactly like the analysis being withheld, which would hand back through the side door the thing the floor just refused.',
        ],
      },
    ],
  },
  {
    id: 'privacy',
    label: 'Data and privacy',
    entries: [
      {
        id: 'where-does-my-data-live',
        question: 'Where does my data live?',
        answer: [
          'On the machine running the instance. The vector memory is a local embedded database written to the data directory, and the caches and registries next to it are files on the same disk. Accounts and social content sit in the Supabase project you point the backend at, which is yours.',
        ],
      },
      {
        id: 'chats-third-party',
        question: 'Do my chats go to a third party?',
        answer: [
          'By default, no. The provider chain starts with a local model, and with that configuration nothing you type leaves the machine.',
          'If you configure a hosted provider — and there is a reason to, since the local model is the quality constraint — then prompts go to that provider under your own API key and their terms. That is your decision to make, and this page will not pretend the option does not change the answer.',
        ],
      },
      {
        id: 'embeddings-remote',
        question: 'Are embeddings computed remotely?',
        answer: [
          'No. The embedding models run locally, on whichever accelerator the host actually has — CUDA first, then Apple Silicon, then CPU. Nothing about retrieval requires an outbound call.',
        ],
      },
      {
        id: 'profile-public',
        question: 'How public is my profile?',
        answer: [
          'Public, on purpose, and it carries the record: the calls that worked and the ones that did not. The point of following someone here is that you are deciding on a history rather than on a follower count, and that only works if the history cannot be curated after the fact. Watchlists are shareable rather than locked to the account that made them.',
        ],
      },
      {
        id: 'who-reads-my-rows',
        question: 'Who can read my rows in the database?',
        answer: [
          'The backend connects with a service role key, which bypasses row-level security — so the database itself provides no per-user protection here and every guarantee is in the application layer.',
          'Concretely: every user-scoped endpoint takes the caller identity from the verified token and nowhere else. An identifier arriving in a path, a query or a body is untrusted and is never used to select or change rows. That single choke point is also what refuses suspended accounts, which is why it cannot be skipped on a new route.',
        ],
      },
      {
        id: 'admin-in-database',
        question: 'Is admin status stored in the database?',
        answer: [
          'No, it comes from an environment variable. The reasoning is narrow and load-bearing: a request can write the database and cannot write the environment.',
        ],
      },
    ],
  },
  {
    id: 'coverage',
    label: 'Coverage',
    entries: [
      {
        id: 'which-exchanges',
        question: 'Which exchanges does it read?',
        answer: [
          'Binance, OKX, Coinbase, Kraken, KuCoin, Bybit, Gate and Huobi for crypto, with the price route falling back across them rather than depending on any one. That fallback is not academic: the browser used to call Binance directly, which fails outright on networks where it is blocked.',
        ],
      },
      {
        id: 'which-equities',
        question: 'Which equities are covered?',
        answer: [
          'NASDAQ listings, ranked by market capitalisation and cut to the head of that list. The full screener runs to a few thousand rows and only the top of it is ever displayed.',
          'This is the honest shape of the coverage rather than an oversight: an equity board that claimed everything and resolved half of it would be worse than a small one that resolves.',
        ],
      },
      {
        id: 'symbol-missing',
        question: 'Why is my symbol not here?',
        answer: [
          'Either it is outside the covered universe, or it was written in a form that resolves somewhere else. Symbols carry their venue — crypto pairs are written as pairs, optionally with an exchange prefix, and equities are the plain ticker.',
          'That distinction is deliberate and should not be simplified away. An unprefixed ticker forced down the crypto path once read a well-known equity off a tokenised-equity market, which is exactly the kind of plausible wrong number the rest of the system is built to refuse.',
        ],
      },
      {
        id: 'prediction-geography',
        question: 'Why is there no "bets by country" view on prediction markets?',
        answer: [
          'Because that data does not exist to be shown. The exchange settles on chain and identifies a counterparty only by wallet address, so no public endpoint anywhere carries a bettor location. A map drawn from it would be invented.',
          'The map that is there instead draws layers that each say what they are — where the market resolves, where the underlying event happens, and where the venue is reachable — rather than one layer implying something nobody can know.',
        ],
      },
      {
        id: 'one-clock',
        question: 'Are crypto and equities really on one board?',
        answer: [
          'Yes, and on one colour scale and one clock. Two maps with two ranges are two pictures, and a funding flush and an equity gap read as two unrelated stories when you meet them an hour apart in different tabs.',
        ],
      },
      {
        id: 'elections-alarms',
        question: 'What about elections, alarms and per-chain data?',
        answer: [
          'All present in the terminal. The macro board carries an elections panel, the alarm engine watches conditions you define and notifies when they trigger, and the chains board tracks per-chain metrics with anomaly detection on top. They are inside the product rather than on this page because the tour above is an argument, not an inventory.',
        ],
      },
    ],
  },
];

/** Every entry, flattened — the tally counts these and the deep-link finds them here. */
export const FAQ_ENTRIES: readonly FaqEntry[] = FAQ_GROUPS.flatMap((group) => group.entries);
