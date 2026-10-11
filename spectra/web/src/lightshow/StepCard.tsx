/** One step of a Light Show set, as a collapsible card — the legacy SpotFX
 * event editor's card shape (web/src/components/cards/EditActionCard.tsx):
 * a ⠿ drag handle, a caret, the step's one-line summary while collapsed and
 * its full form while open, and copy / duplicate / delete on the row.
 *
 * Every parameter's input is rendered from the SERVED catalogue
 * (`ParamField` switches on the declared `type`), so a new action kind —
 * including the Home Assistant ones another build adds — needs no change
 * here. A "Run another set" step (type `set`) picks from the sets that would
 * not make this one call itself, opens the called set, and shows the steps
 * it will run, read-only, inside the card. */
import { useState } from 'react';
import HelpLink from '../help/HelpLink';
import Icon from '../components/Icon';
import SearchSelect, { type SearchOption } from '../components/forms/SearchSelect';
import { colorCardOptions, namedOptions, sceneOptions } from '../lib/pickerOptions';
import { useAmbientHueGroups, useGradient2dProfiles, useHaScenes, useScenes, useSpotColorSets } from '../queries';
import { CALL_KIND, callableSets, stepSummary, type SummaryLookups } from './builderOps';
import type { SortableRowProps } from './SortableList';
import type { ShowAction, ShowCatalogue, ShowKind, ShowParam, ShowSet, ShowTargets } from './types';

export interface PreviewLine { label: string; change?: string; problem?: string; via?: string[] }

export interface StepCardProps {
  action: ShowAction;
  index: number;
  kind: ShowKind | undefined;
  kinds: Map<string, ShowKind>;
  catalogue: ShowCatalogue;
  targets: ShowTargets | null;
  sets: ShowSet[];
  currentSetId: string | undefined;
  lookups: SummaryLookups;
  open: boolean;
  onToggle: () => void;
  onChange: (a: ShowAction) => void;
  onDuplicate: () => void;
  onCopy: () => void;
  onDelete: () => void;
  onOpenSet: (id: string) => void;
  previewLines?: PreviewLine[];
  row: SortableRowProps;
}

export default function StepCard(props: StepCardProps) {
  const { action, index, kind, open, onToggle, onChange, row } = props;
  const isCall = action.kind === CALL_KIND;
  const calledId = isCall ? (action.params.set as string | undefined) : undefined;
  const called = calledId ? props.sets.find((s) => s.id === calledId) : undefined;
  const summary = stepSummary(action, kind, props.lookups);
  const set = (name: string, value: unknown) => {
    const params = { ...action.params };
    if (value === undefined || value === '' || value === null) delete params[name];
    else params[name] = value;
    onChange({ ...action, params });
  };
  const cls = ['light-show-step', action.enabled === false ? 'off' : '', isCall ? 'call' : '',
    row.isDragging ? 'dragging' : '', open ? 'open' : ''].filter(Boolean).join(' ');
  const problems = (props.previewLines ?? []).filter((l) => l.problem);
  return (
    <li ref={row.rowRef} style={row.rowStyle} className={cls} data-step-id={action.id}>
      <div className="light-show-step-head" onClick={onToggle} role="button" aria-expanded={open} tabIndex={0}
        onKeyDown={(e) => {
          if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onToggle(); }
        }}
        aria-label={`${open ? 'Collapse' : 'Expand'} step ${index + 1}`}>
        {row.handle}
        <span className="light-show-step-num">{index + 1}</span>
        <Icon name="chevron" size={14} className={`light-show-caret${open ? ' open' : ''}`} />
        <label title="Switch this step off without deleting it" onClick={(e) => e.stopPropagation()}>
          <input type="checkbox" checked={action.enabled !== false}
            onChange={(e) => onChange({ ...action, enabled: e.target.checked })} />
          {isCall && <Icon name="callSet" size={14} />}
          <b>{kind?.label ?? action.kind}</b>
        </label>
        {!open && summary && <span className="light-show-step-summary" title={summary}>{summary}</span>}
        <span className="light-show-step-tools" onClick={(e) => e.stopPropagation()}>
          {isCall && called?.id && (
            <button type="button" className="icon-btn" title={`Open “${called.name}”`}
              aria-label={`Open ${called.name}`} onClick={() => props.onOpenSet(called.id as string)}>
              <Icon name="open" size={15} />
            </button>
          )}
          <button type="button" className="icon-btn" title="Copy this step (paste into any set)"
            aria-label="Copy step" onClick={props.onCopy}><Icon name="copy" size={15} /></button>
          <button type="button" className="icon-btn" title="Duplicate this step"
            aria-label="Duplicate step" onClick={props.onDuplicate}><Icon name="duplicate" size={15} /></button>
          <button type="button" className="icon-btn danger" title="Remove this step"
            aria-label="Remove step" onClick={props.onDelete}><Icon name="trash" size={15} /></button>
        </span>
      </div>
      {!open && problems.length > 0 && (
        <p className="light-show-problems">⚠ {problems[0].problem}{problems.length > 1 ? ` (+${problems.length - 1})` : ''}</p>
      )}
      {open && (
        <div className="light-show-step-body">
          {!kind && <p className="light-show-problems">Unknown action kind “{action.kind}”.</p>}
          {kind && <p className="muted light-show-step-help">{kind.help} <HelpLink topic={kind.help_topic} /></p>}
          {kind && (
            <div className="light-show-params">
              {kind.params.map((p) => (
                <ParamField key={p.name} p={p} value={action.params[p.name]} onChange={(v) => set(p.name, v)}
                  catalogue={props.catalogue} targets={props.targets} action={action}
                  sets={props.sets} currentSetId={props.currentSetId} />
              ))}
            </div>
          )}
          {isCall && calledId && !called && (
            <p className="light-show-problems">⚠ The set this step runs no longer exists.</p>
          )}
          {isCall && called && (
            <CalledSteps set={called} sets={props.sets} kinds={props.kinds} lookups={props.lookups}
              onOpenSet={props.onOpenSet} depth={0} />
          )}
          {(props.previewLines ?? []).map((l, i) => (
            <p key={i} className={l.problem ? 'light-show-problems' : 'light-show-preview'}>
              {l.via && l.via.length > 0 && <span className="muted">{l.via.join(' › ')}: </span>}
              {l.problem ? `⚠ ${l.problem}` : `→ ${l.change}`}
            </p>
          ))}
        </div>
      )}
    </li>
  );
}

/** The steps a "Run another set" step will run, read-only — nested calls
 * shown one level deep at a time (each is its own click to unfold). */
function CalledSteps({ set, sets, kinds, lookups, onOpenSet, depth }: {
  set: ShowSet; sets: ShowSet[]; kinds: Map<string, ShowKind>; lookups: SummaryLookups;
  onOpenSet: (id: string) => void; depth: number;
}) {
  const [unfold, setUnfold] = useState<Set<number>>(new Set());
  if (set.actions.length === 0) return <p className="muted light-show-called">“{set.name}” has no steps yet.</p>;
  return (
    <div className="light-show-called">
      <div className="light-show-called-head muted">
        Runs these steps of <b>{set.name}</b>, here, in order:
        {set.id && (
          <button type="button" className="linklike" onClick={() => onOpenSet(set.id as string)}>open it</button>
        )}
      </div>
      <ol>
        {set.actions.map((a, i) => {
          const k = kinds.get(a.kind);
          const nested = a.kind === CALL_KIND ? sets.find((s) => s.id === a.params.set) : undefined;
          return (
            <li key={a.id ?? i} className={a.enabled === false ? 'off' : ''}>
              <b>{k?.label ?? a.kind}</b> <span className="muted">{stepSummary(a, k, lookups)}</span>
              {a.enabled === false && <span className="muted"> (switched off)</span>}
              {nested && depth < 4 && (
                <button type="button" className="linklike" onClick={() => setUnfold((u) => {
                  const n = new Set(u);
                  if (n.has(i)) n.delete(i); else n.add(i);
                  return n;
                })}>{unfold.has(i) ? 'hide' : 'show'}</button>
              )}
              {nested && unfold.has(i) && (
                <CalledSteps set={nested} sets={sets} kinds={kinds} lookups={lookups}
                  onOpenSet={onOpenSet} depth={depth + 1} />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Chips({ options, value, onChange }: {
  options: { id: string; name: string }[]; value: string[]; onChange: (v: string[]) => void;
}) {
  return (
    <span className="light-show-chips">
      {options.map((o) => {
        const on = value.includes(o.id);
        return (
          <button key={o.id} className={on ? 'active' : ''} type="button"
            onClick={() => onChange(on ? value.filter((x) => x !== o.id) : [...value, o.id])}>
            {o.name}
          </button>
        );
      })}
    </span>
  );
}

/** A long multi-pick (scenes, colour sets): the chosen ones as removable
 * chips, plus the same searchable picker to add another. */
function SearchChips({ options, value, onChange, placeholder }: {
  options: SearchOption[]; value: string[]; onChange: (v: string[]) => void; placeholder: string;
}) {
  const byId = new Map(options.map((o) => [o.value, o]));
  const rest = options.filter((o) => !value.includes(o.value));
  return (
    <span className="light-show-chips">
      {value.map((id) => (
        <button key={id} className="active" type="button" title="Remove"
          onClick={() => onChange(value.filter((x) => x !== id))}>
          {byId.get(id)?.label ?? id} ✕
        </button>
      ))}
      <SearchSelect value="" options={rest} placeholder={placeholder} allowEmpty={false} width={220}
        onChange={(v) => { if (v && !value.includes(v)) onChange([...value, v]); }} />
    </span>
  );
}

export function ParamField({ p, value, onChange, catalogue, targets, action, sets = [], currentSetId }: {
  p: ShowParam; value: unknown; onChange: (v: unknown) => void;
  catalogue: ShowCatalogue; targets: ShowTargets | null; action: ShowAction;
  sets?: ShowSet[]; currentSetId?: string;
}) {
  const scenes = useScenes().data ?? [];
  const colorSets = useSpotColorSets().data ?? [];
  const gradients = useGradient2dProfiles().data ?? {};
  const hueAreas = useAmbientHueGroups().data?.groups ?? [];
  const haScenes = useHaScenes().data;
  const pick = (options: SearchOption[], placeholder = '— choose —') => wrap(
    <SearchSelect value={String(value ?? '')} options={options} placeholder={placeholder}
      width={240} onChange={(v) => onChange(v || undefined)} />);
  const label = <span className="light-show-param-label" title={p.help}>{p.label}{p.unit ? ` (${p.unit})` : ''}</span>;
  const wrap = (input: JSX.Element) => <label className="light-show-param">{label}{input}</label>;

  switch (p.type) {
    case 'bool':
      return wrap(<input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />);
    case 'enum':
      return wrap(
        <select value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
          {(p.choices ?? []).map((c) => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
        </select>);
    case 'number':
      return wrap(<input type="number" value={value === undefined || value === null ? '' : String(value)}
        placeholder={p.default !== null && p.default !== undefined ? String(p.default) : 'default'}
        min={p.min ?? undefined} max={p.max ?? undefined}
        step={p.step ?? (p.max !== null && p.max <= 1 ? 0.05 : 1)}
        onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))} />);
    case 'color':
      return wrap(
        <span>
          <input type="color" value={typeof value === 'string' ? value : '#ffffff'}
            onChange={(e) => onChange(e.target.value)} />
          {value ? <button type="button" onClick={() => onChange(undefined)}>clear</button>
            : <span className="muted"> default</span>}
        </span>);
    case 'set': {
      // A set that (directly or indirectly) calls this one would loop — it
      // is left out of the picker; the server refuses such a save anyway.
      const options = callableSets(currentSetId, sets).map((s) => ({ value: s.id as string, label: s.name }));
      const blocked = sets.length - options.length - (currentSetId ? 1 : 0);
      return (
        <label className="light-show-param">
          {label}
          <SearchSelect value={String(value ?? '')} options={options} placeholder="— pick a set to run —"
            width={260} onChange={(v) => onChange(v || undefined)} />
          {blocked > 0 && (
            <span className="muted light-show-param-note">
              {blocked} set{blocked === 1 ? '' : 's'} not offered — {blocked === 1 ? 'it runs' : 'they run'} this one
            </span>
          )}
        </label>);
    }
    case 'scene':
      return pick(sceneOptions(scenes), '— pick scene —');
    case 'scenes':
      return wrap(<SearchChips options={sceneOptions(scenes)} placeholder="+ add a scene…"
        value={(value as string[]) ?? []} onChange={onChange} />);
    case 'color_set':
      return pick(colorCardOptions(colorSets), '— pick colour set —');
    case 'color_sets':
      return wrap(<SearchChips options={colorCardOptions(colorSets)} placeholder="+ add a colour set…"
        value={(value as string[]) ?? []} onChange={onChange} />);
    case 'gradient':
      return pick(namedOptions(Object.entries(gradients).map(([id, g]) => (
        { id, name: (g as { name?: string }).name ?? id }))), '— pick gradient —');
    case 'hue_areas':
      return wrap(<Chips options={hueAreas} value={(value as string[]) ?? []} onChange={onChange} />);
    case 'house_mode':
      return pick(namedOptions(catalogue.house_modes), '— pick house mode —');
    case 'ha_scene':
      // A free-text field, not a closed picker — he can make or rename a
      // scene in HA at any time (his own ask, 2026-10-11: "I want to be
      // able to customize the scene in HA and trigger it as part of the
      // light show"), so there is nothing SPECTRA-side to restrict this
      // to. <datalist> gives autocomplete from his live HA scenes
      // (useHaScenes) WITHOUT blocking a typed entity id the fetch
      // doesn't happen to know about yet.
      return wrap(
        <span>
          <input type="text" list="ha-scene-options"
            value={String(value ?? '')} placeholder="scene.music_mode"
            onChange={(e) => onChange(e.target.value || undefined)} />
          <datalist id="ha-scene-options">
            {(haScenes?.scenes ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </datalist>
          {haScenes && !haScenes.configured && (
            <span className="muted" title={haScenes.error ?? ''}> Home Assistant not configured — type the entity id</span>
          )}
        </span>);
    case 'target': {
      const t = (value as { kind: string; id: string | null }) ?? { kind: 'everything', id: null };
      return wrap(
        <span className="light-show-target">
          <select value={t.kind} onChange={(e) => onChange({ kind: e.target.value, id: null })}>
            <option value="everything">Everything</option>
            <option value="category">Category</option>
            <option value="fixture">Fixture</option>
          </select>
          {t.kind === 'category' && (
            <SearchSelect value={t.id ?? ''} width={200} placeholder="— pick category —"
              options={namedOptions((targets?.categories ?? []).map((c) => ({ id: c.name, name: c.name })))}
              onChange={(v) => onChange({ kind: 'category', id: v || null })} />
          )}
          {t.kind === 'fixture' && (
            <SearchSelect value={t.id ?? ''} width={220} placeholder="— pick fixture —"
              options={(targets?.fixtures ?? []).map((f) => ({
                value: f.id, label: `${f.name}${f.held_by_ambient ? ' (held by Hue Hold)' : ''}`,
                keywords: f.type,
              }))}
              onChange={(v) => onChange({ kind: 'fixture', id: v || null })} />
          )}
          {targets && !targets.live && <span className="muted"> live stack down — fixtures unknown</span>}
        </span>);
    }
    case 'room_effect':
      return pick(catalogue.room_effects.map((e) => ({
        value: e.name, label: `${e.name} (${e.kind.replace(/_/g, ' ')})`,
      })), '— pick room effect —');
    case 'overrides': {
      const props = catalogue.room_effect_schema?.properties ?? {};
      const numeric = Object.entries(props).filter(([, s]) => s.type === 'number' || s.type === 'integer');
      const cur = (value as Record<string, number>) ?? {};
      if (!action.params.effect || numeric.length === 0) return null;
      return (
        <div className="light-show-param light-show-overrides">
          {label}
          {numeric.map(([name, s]) => (
            <label key={name}>
              {name}
              <input type="number" placeholder="effect's own" value={cur[name] ?? ''}
                min={s.minimum} max={s.maximum} step={0.05}
                onChange={(e) => {
                  const next = { ...cur };
                  if (e.target.value === '') delete next[name];
                  else next[name] = Number(e.target.value);
                  onChange(next);
                }} />
            </label>
          ))}
        </div>);
    }
    default:
      return wrap(<input type="text" value={String(value ?? '')} onChange={(e) => onChange(e.target.value || undefined)} />);
  }
}
