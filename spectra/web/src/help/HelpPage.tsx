/** /help — searchable, nested-collapsible documentation for the whole app.
 * Content lives in helpContent.ts; this file is the rendering/search shell.
 * Search is fuzzy (typo-tolerant) via fuzzy.ts; matching auto-expands the
 * tree and shows only matching entries. `?topic=<id>` deep-links to a
 * section/entry (used by the circled-? HelpLink buttons around the app). */
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { HELP_SECTIONS, type HelpEntry, type HelpSection } from './helpContent';
import { fuzzyScore } from './fuzzy';

/* ── Search index ─────────────────────────────────────────────── */

function entryHaystack(e: HelpEntry): string {
  return [
    e.title,
    ...(e.body ?? []),
    ...(e.table ?? []).flat(),
    e.keywords ?? '',
  ].join(' ');
}

type Match = { ids: Set<string>; entryIds: Set<string> };

/** Walk the tree; collect ids of sections/entries that match the query
 * (a section matches if its own title/intro matches OR any descendant does). */
function findMatches(sections: HelpSection[], query: string): Match {
  const ids = new Set<string>();
  const entryIds = new Set<string>();
  const walk = (s: HelpSection): boolean => {
    let hit = fuzzyScore(query, `${s.title} ${s.intro ?? ''} ${s.keywords ?? ''}`) > 0;
    const selfHit = hit;
    for (const e of s.entries ?? []) {
      if (selfHit || fuzzyScore(query, entryHaystack(e)) > 0) {
        entryIds.add(e.id);
        hit = true;
      }
    }
    for (const sub of s.subsections ?? []) if (walk(sub)) hit = true;
    if (hit) ids.add(s.id);
    return hit;
  };
  sections.forEach(walk);
  return { ids, entryIds };
}

/** Ancestor chain for ?topic= deep links. */
function findPath(sections: HelpSection[], id: string): string[] | null {
  for (const s of sections) {
    if (s.id === id) return [s.id];
    if ((s.entries ?? []).some((e) => e.id === id)) return [s.id, id];
    const sub = findPath(s.subsections ?? [], id);
    if (sub) return [s.id, ...sub];
  }
  return null;
}

/* ── Text highlighting (exact-substring best effort) ──────────── */

function Highlight({ text, tokens }: { text: string; tokens: string[] }) {
  if (tokens.length === 0) return <>{text}</>;
  const pattern = tokens
    .filter((t) => t.length >= 2)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|');
  if (!pattern) return <>{text}</>;
  const parts = text.split(new RegExp(`(${pattern})`, 'gi'));
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="help-highlight">{p}</mark>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}

/** Render a table's first cell: split "Ctrl+Shift+Drag" style combos into <kbd> keys,
 * but leave filter syntax ("!", "artist:") as a single kbd chunk. */
function Keys({ text, kbd }: { text: string; kbd: boolean }) {
  if (!kbd) return <kbd>{text}</kbd>;
  // "Ctrl+Z / Cmd+Z" → alternatives separated by " / ", keys by "+"
  return (
    <>
      {text.split(' / ').map((alt, i) => (
        <Fragment key={i}>
          {i > 0 && <span style={{ color: 'var(--text-muted)' }}> or </span>}
          {alt.split('+').map((k, j) => (
            <Fragment key={j}>
              {j > 0 && <span style={{ color: 'var(--text-muted)' }}>+</span>}
              <kbd>{k}</kbd>
            </Fragment>
          ))}
        </Fragment>
      ))}
    </>
  );
}

/* ── Tree rendering ───────────────────────────────────────────── */

function Entry({ entry, tokens }: { entry: HelpEntry; tokens: string[] }) {
  return (
    <div className="help-entry" id={`help-${entry.id}`}>
      <div className="help-entry-title">
        <Highlight text={entry.title} tokens={tokens} />
      </div>
      <div className="help-entry-body">
        {(entry.body ?? []).map((p, i) => (
          <p key={i}>
            <Highlight text={p} tokens={tokens} />
          </p>
        ))}
        {entry.table && (
          <table className="help-table">
            <tbody>
              {entry.table.map(([k, v], i) => (
                <tr key={i}>
                  <td><Keys text={k} kbd={entry.kbd ?? false} /></td>
                  <td><Highlight text={v} tokens={tokens} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Section({
  section,
  depth,
  searching,
  match,
  tokens,
  open,
  setOpen,
}: {
  section: HelpSection;
  depth: number;
  searching: boolean;
  match: Match | null;
  tokens: string[];
  open: Record<string, boolean>;
  setOpen: (id: string, v: boolean) => void;
}) {
  if (searching && match && !match.ids.has(section.id)) return null;
  // While searching, everything that matched is force-expanded.
  const isOpen = searching ? true : (open[section.id] ?? false);
  const entries = (section.entries ?? []).filter(
    (e) => !searching || !match || match.entryIds.has(e.id),
  );
  const subsections = section.subsections ?? [];
  const count = countEntries(section);
  return (
    <div className={depth === 0 ? 'help-section card' : 'help-section help-subsection'} id={`help-${section.id}`} style={depth === 0 ? { padding: 8 } : undefined}>
      <div className="help-section-header" onClick={() => setOpen(section.id, !isOpen)}>
        <span className={`caret ${isOpen ? 'open' : ''}`}>▶</span>
        <span className="help-section-title">
          <Highlight text={section.title} tokens={tokens} />
        </span>
        {!isOpen && <span className="help-section-count">{count} topic{count === 1 ? '' : 's'}</span>}
      </div>
      {isOpen && (
        <div className="help-section-body">
          {section.intro && (
            <p className="help-entry-body" style={{ marginBottom: 8 }}>
              <Highlight text={section.intro} tokens={tokens} />
            </p>
          )}
          {entries.map((e) => (
            <Entry key={e.id} entry={e} tokens={tokens} />
          ))}
          {subsections.map((sub) => (
            <Section
              key={sub.id}
              section={sub}
              depth={depth + 1}
              searching={searching}
              match={match}
              tokens={tokens}
              open={open}
              setOpen={setOpen}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function countEntries(s: HelpSection): number {
  return (s.entries?.length ?? 0) + (s.subsections ?? []).reduce((n, sub) => n + countEntries(sub), 0);
}

/* ── Page ─────────────────────────────────────────────────────── */

export default function HelpPage() {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get('q') ?? '');
  const [open, setOpenState] = useState<Record<string, boolean>>({});
  const scrolledFor = useRef<string | null>(null);

  const searching = query.trim().length > 0;
  const match = useMemo(
    () => (searching ? findMatches(HELP_SECTIONS, query) : null),
    [searching, query],
  );
  const tokens = useMemo(
    () => (searching ? query.trim().toLowerCase().split(/\s+/).filter(Boolean) : []),
    [searching, query],
  );

  const setOpen = (id: string, v: boolean) => setOpenState((o) => ({ ...o, [id]: v }));

  // ?topic=<id> deep link: expand the ancestor chain and scroll to it.
  const topic = params.get('topic');
  useEffect(() => {
    if (!topic || scrolledFor.current === topic) return;
    const path = findPath(HELP_SECTIONS, topic);
    if (!path) return;
    scrolledFor.current = topic;
    setOpenState((o) => {
      const next = { ...o };
      for (const id of path) next[id] = true;
      return next;
    });
    // Scroll after the expanded tree renders.
    requestAnimationFrame(() => {
      document.getElementById(`help-${topic}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, [topic]);

  const expandAll = (v: boolean) => {
    const next: Record<string, boolean> = {};
    const walk = (s: HelpSection) => {
      next[s.id] = v;
      (s.subsections ?? []).forEach(walk);
    };
    HELP_SECTIONS.forEach(walk);
    setOpenState(next);
  };

  const noResults = searching && match && match.ids.size === 0;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 12 }}>
        <h2 style={{ fontSize: 18 }}>Help</h2>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          Search below — typos are okay.
        </span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button onClick={() => expandAll(true)}>Expand all</button>
          <button onClick={() => expandAll(false)}>Collapse all</button>
        </span>
      </div>
      <input
        type="search"
        className="help-search"
        placeholder="Search help… (e.g. “keyboard shortcuts”, “filter syntax”, “palette”)"
        value={query}
        autoFocus
        onChange={(e) => {
          setQuery(e.target.value);
          // keep the URL shareable without spamming history
          const next = new URLSearchParams(params);
          if (e.target.value) next.set('q', e.target.value);
          else next.delete('q');
          setParams(next, { replace: true });
        }}
      />
      {noResults ? (
        <p className="empty-note">No help topics match “{query}”.</p>
      ) : (
        HELP_SECTIONS.map((s) => (
          <Section
            key={s.id}
            section={s}
            depth={0}
            searching={searching}
            match={match}
            tokens={tokens}
            open={open}
            setOpen={setOpen}
          />
        ))
      )}
    </div>
  );
}
