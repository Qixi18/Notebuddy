import { memo, useCallback, useEffect, useId, useMemo, useRef, useSyncExternalStore } from 'react';
import type { FocusEvent, PointerEvent, KeyboardEvent } from 'react';
import { buildVine, resolveVineLod, stableHash } from './vineGeometry';
import type { VineInput, RelationLeaf, VineGeometry, Point, VineExclusionZone } from './vineGeometry';
import { growthLedger, treeGrowthEnabled } from './growth/ledger';
import { useGrowthBlocked } from './growth/useGrowthPlayback';
import { playVineGrowth } from './growth/paint';
import { growthVisible } from './growth/visibility';
import { playVineFlow, type VineFlow } from './motion/vineFlow';

/** Layer is an SVG child. Parent owns camera transform, panel, tooltip and note routing. */
export type VineLayerProps = {
  groups: VineInput[];
  flowByRelation?: ReadonlyMap<string, VineFlow>;
  /** Actual CSS pixels per world unit, including all ancestor transforms. */
  screenScale: number;
  selectedRelationId?: string;
  selectedGroupId?: string;
  /** Same project asset as HomeCourseTree; omit for the standalone vector leaf. */
  leafAtlasHref?: string;
  onRelation: (relationId: string) => void;
  onGroup: (groupId: string) => void;
  relationLabel?: (relationId: string) => string;
  groupLabel?: (groupId: string) => string;
  groupMembers?: (groupId: string) => string;
  previewId?: string;
  previewItemId?: string;
  onSelectedPoint?: (relationId: string, point: Point) => void;
  leafExclusions?: VineExclusionZone[];
  onPreview?: (item: { kind: 'relation' | 'group'; id: string; target: SVGGElement } | null) => void;
};

export function VineDefinitions({ prefix }: { prefix: string }) {
  return <defs>
    {[0, 1, 2].map(i => <linearGradient key={i} id={`${prefix}-leaf-${i}`} x1="0" y1="0" x2="1" y2=".6">
      <stop stopColor={`var(--leaf-${['mid','light','dark'][i]})`} />
      <stop offset=".52" stopColor="var(--leaf-mid)" /><stop offset="1" stopColor="var(--leaf-dark)" />
    </linearGradient>)}
  </defs>;
}

export function VineLeafPaint({ leaf, prefix, leafAtlasHref, details = true, groupId }: {
  leaf: RelationLeaf; prefix: string; leafAtlasHref?: string; details?: boolean; groupId?: string;
}) {
  return <g transform={leaf.transform} pointerEvents="none" aria-hidden="true">
    <g data-growth-relation-leaf={leaf.relationId} data-growth-vine-group={groupId} data-growth-vine-t={leaf.t} data-growth-origin="0px 0px">
    {leafAtlasHref
      ? <svg className="relation-leaf-texture" x={-17} y={-50} width={34} height={51}
          viewBox={`${leaf.variant * 418} 0 418 627`} preserveAspectRatio="xMidYMid meet" overflow="hidden">
          <image href={leafAtlasHref} width={1254} height={1254} />
        </svg>
      : <path className="relation-leaf-shape" d={leaf.outline} fill={`url(#${prefix}-leaf-${leaf.variant})`} />}
    <path className="relation-vein" d={leaf.vein} opacity={leafAtlasHref ? .35 : 1} />
    {details && leaf.sideVeins.map((d,i) => <path key={i} className="relation-side-vein" d={d} opacity={leafAtlasHref ? .3 : 1} />)}
    </g></g>;
}

export function VineStemPaint({ vine, details = true }: { vine: VineGeometry; details?: boolean }) {
  return <g pointerEvents="none" aria-hidden="true"><g data-growth-vine-group={vine.id} data-growth-vine-path={vine.centerline}>
    <path className="vine-outline" d={vine.outline} />
    {vine.grain.map((d,i) => <path className="vine-grain" d={d} key={`grain-${i}`} />)}
    </g>
    {details && vine.tendrils.map((d,i) => <path className="vine-tendril" data-growth-vine-tendril="true" data-growth-vine-group={vine.id} d={d} key={`tendril-${i}`} />)}
  </g>;
}

export const VineLayer = memo(function VineLayer({
  groups, flowByRelation, screenScale, selectedRelationId, selectedGroupId, leafAtlasHref,
  onRelation, onGroup, onPreview, relationLabel, groupLabel, groupMembers, previewId, previewItemId, onSelectedPoint, leafExclusions
}: VineLayerProps) {
  const root = useRef<SVGGElement>(null);
  const activePlayback = useRef<(() => void) | null>(null);
  const activeFlows = useRef<{ id: string; playback: ReturnType<typeof playVineFlow> }[]>([]);
  const animatedStems = useRef(new Set<string>());
  const blocked = useGrowthBlocked();
  const ledgerVersion = useSyncExternalStore(growthLedger.subscribe, growthLedger.snapshot, () => 0);
  const growthEnabled = treeGrowthEnabled(import.meta.env.VITE_TREE_GROWTH_ENABLED);
  const prefix = `nb-vine-${useId().replace(/:/g, '')}`;
  const vines = useMemo(() => {
    const populated=groups.filter(g=>g.relationIds.length>0);
    // The host clusters each course pair to at most four lanes. One forest can
    // contain several pairs; keep their stems below every relationship leaf.
    const ids=populated.flatMap(g=>g.relationIds);
    if(new Set(ids).size!==ids.length) throw new Error('A relationship must belong to exactly one vine.');
    return populated.map(buildVine);
  }, [groups]);
  const lod = useMemo(() => resolveVineLod(vines, screenScale, selectedRelationId, leafExclusions), [vines,screenScale,selectedRelationId,leafExclusions]);
  const motionLayoutKey = useMemo(() => JSON.stringify([screenScale,
    vines.map(vine => [vine.id, vine.centerline, vine.leaves.map(leaf => [leaf.relationId, leaf.transform])]),
    flowByRelation ? [...flowByRelation] : [],
  ]), [vines, screenScale, flowByRelation]);
  const stopFlows = useCallback(() => {
    for (const flow of activeFlows.current) flow.playback.finish();
    activeFlows.current = [];
  }, []);
  const flow = useCallback((vine: VineGeometry, id: string, delay = 0, append = false) => {
    const element = root.current;
    if (!growthEnabled || blocked || !element || !growthVisible(element)) return;
    const matching = activeFlows.current.find(active => active.id === id);
    if (!append) {
      for (const active of activeFlows.current) if (active !== matching) active.playback.finish();
      activeFlows.current = matching ? [matching] : [];
    }
    if (matching) return;
    const playback = playVineFlow(element, vine, id, { ...(flowByRelation?.get(id) ?? { reverse: false }), screenScale, delay });
    const active = { id, playback };
    activeFlows.current.push(active);
    void playback.finished.then(() => { activeFlows.current = activeFlows.current.filter(candidate => candidate !== active); });
  }, [growthEnabled, blocked, flowByRelation, screenScale, stopFlows]);
  // Transient lights must never retain old coordinates after a layout/zoom change.
  useEffect(() => {
    const stop = () => { activePlayback.current?.(); stopFlows(); };
    if (blocked) stop();
    return stop;
  }, [motionLayoutKey, blocked, stopFlows]);
  useEffect(() => {
    if (!growthEnabled || !root.current || blocked || document.querySelector('[role="dialog"], .modal-backdrop')) return;
    // Consume only after a committed frame: StrictMode may cancel the first setup.
    const frame = requestAnimationFrame(() => {
      const element = root.current;
      if (!element || document.visibilityState === 'hidden' || document.querySelector('[role="dialog"], .modal-backdrop')) return;
      const pending = growthLedger.pending().filter(event => event.kind === 'relation');
      const pendingIds = new Set(pending.map(event => event.id));
      // A baseline relationship means this stem already existed before this update.
      for (const group of groups) if (group.relationIds.some(id => !pendingIds.has(id))) animatedStems.current.add(group.id);
      const visibleIds = new Set(pending.flatMap(event => {
        const leaf = [...element.querySelectorAll<SVGGElement>('[data-growth-relation-leaf]')]
          .find(candidate => candidate.dataset.growthRelationLeaf === event.id);
        const group = groups.find(group => group.relationIds.includes(event.id));
        const stem = group && [...element.querySelectorAll<SVGGElement>('[data-growth-vine-path]')]
          .find(candidate => candidate.dataset.growthVineGroup === group.id);
        return leaf && growthVisible(leaf) || stem && growthVisible(stem) ? [event.id] : [];
      }));
      if (!visibleIds.size) return;
      const stems = new Set(groups.filter(group => group.relationIds.some(id => visibleIds.has(id)) && !animatedStems.current.has(group.id)).slice(0, 2).map(group => group.id));
      const animatedIds = new Set(groups.filter(group => stems.has(group.id) || animatedStems.current.has(group.id))
        .flatMap(group => group.relationIds.filter(id => visibleIds.has(id))));
      for (const id of stems) animatedStems.current.add(id);
      activePlayback.current?.(); stopFlows();
      const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)');
      const guides = vines.filter(vine => stems.has(vine.id)).map(vine => ({ vine,
        relationId: vine.leaves.find(leaf => animatedIds.has(leaf.relationId))!.relationId,
        options: { ...(flowByRelation?.get(vine.leaves.find(leaf => animatedIds.has(leaf.relationId))!.relationId) ?? { reverse: false }), screenScale },
      }));
      const playback = reduced?.matches ? null : playVineGrowth(element, animatedIds, stems, guides);
      let cancelled = false;
      const finish = () => {
        cancelled = true;
        playback?.finish();
        element.removeEventListener('pointerdown', finish);
        element.removeEventListener('focusin', finish);
        reduced?.removeEventListener?.('change', finish);
        if (activePlayback.current === finish) activePlayback.current = null;
      };
      activePlayback.current = finish;
      element.addEventListener('pointerdown', finish, { once: true });
      element.addEventListener('focusin', finish, { once: true });
      reduced?.addEventListener?.('change', finish);
      void playback?.finished.then(() => {
        if (!cancelled) for (const vine of vines.filter(vine => !stems.has(vine.id) && vine.leaves.some(leaf => animatedIds.has(leaf.relationId))).slice(0, 2)) {
          const id = vine.leaves.find(leaf => animatedIds.has(leaf.relationId))!.relationId;
          flow(vine, id, 0, true);
        }
        finish();
      });
      if (!playback) finish();
      growthLedger.consume(pending.filter(event => event.kind === 'relation' && visibleIds.has(event.id)));
    });
    return () => cancelAnimationFrame(frame);
  }, [ledgerVersion, vines, lod, groups, growthEnabled, blocked, flow, stopFlows, flowByRelation, screenScale]);
  useEffect(() => () => activePlayback.current?.(), []);
  useEffect(() => {
    const leaf=vines.flatMap(v=>v.leaves).find(leaf=>leaf.relationId===selectedRelationId);
    if(leaf) onSelectedPoint?.(leaf.relationId,leaf.center);
  },[vines,selectedRelationId,onSelectedPoint]);
  const preview = (kind: 'relation'|'group', id: string) => (e: FocusEvent<SVGGElement> | PointerEvent<SVGGElement>) => {
    onPreview?.({kind,id,target:e.currentTarget});
    if ('pointerType' in e && e.pointerType === 'touch') return;
    // Focus capture has just finished the old native effect; replace its receipt
    // synchronously instead of waiting for the finished promise's microtask.
    if (e.type === 'focus') stopFlows();
    const vine = vines.find(vine => kind === 'group' ? vine.id === id : vine.leaves.some(leaf => leaf.relationId === id));
    if (vine) {
      activePlayback.current?.();
      flow(vine, kind === 'relation' ? id : vine.leaves[0].relationId);
    }
  };
  const activate = (fn: () => void) => (e: KeyboardEvent<SVGGElement>) => {
    if (e.key==='Enter'||e.key===' ') { e.preventDefault();e.stopPropagation();fn(); }
  };
  return <g ref={root} className="nb-vines" data-od-id="grouped-vines">
    <VineDefinitions prefix={prefix} />
    {/* All stem hit paths are below all leaf hit paths; no later stem masks a leaf. */}
    <g data-layer="stems">{vines.map(v => <g key={v.id}
      className={`vine-control kt-vine${selectedGroupId===v.id?' is-selected kt-vine-selected':''}`}
      data-vine-members={groupMembers?.(v.id)} data-vine-id={v.id} data-forest-interactive="true"
      role="button" tabIndex={0} aria-label={groupLabel?.(v.id) || `查看关联组，共 ${v.leaves.length} 条关联`}
      aria-pressed={selectedGroupId===v.id} data-od-id={`vine-${stableHash(v.id)}`}
      aria-describedby={previewItemId===v.id?previewId:undefined}
      onClick={event => { event.stopPropagation();event.currentTarget.focus();onGroup(v.id); }} onKeyDown={activate(() => onGroup(v.id))}
      onFocus={preview('group',v.id)} onPointerEnter={preview('group',v.id)}
      onBlur={() => onPreview?.(null)} onPointerLeave={() => onPreview?.(null)}>
      <title>{groupLabel?.(v.id)}</title>
      <VineStemPaint vine={v} details={lod.decorations} />
      <path className="vine-focus" d={v.centerline} />
      <path d={v.hit.centerline} fill="none" stroke="transparent" strokeWidth={44/screenScale} strokeLinecap="round" />
    </g>)}</g>
    <g data-layer="relations">{vines.flatMap(v => v.leaves).filter(l => lod.visible.includes(l.relationId)).map(l =>
      <g key={l.relationId} className={`vine-leaf${selectedRelationId===l.relationId?' is-selected':''}`}
        role="button" tabIndex={0} aria-label={relationLabel?.(l.relationId) || `查看关联 ${l.relationId}`}
        aria-pressed={selectedRelationId===l.relationId} data-relation-id={l.relationId}
        data-forest-interactive="true" aria-describedby={previewItemId===l.relationId?previewId:undefined}
        data-od-id={`relation-${stableHash(l.relationId)}`}
        onClick={event => { event.stopPropagation();event.currentTarget.focus();onRelation(l.relationId); }} onKeyDown={activate(() => onRelation(l.relationId))}
        onFocus={preview('relation',l.relationId)} onPointerEnter={preview('relation',l.relationId)}
        onBlur={() => onPreview?.(null)} onPointerLeave={() => onPreview?.(null)}>
        <title>{relationLabel?.(l.relationId)}</title>
        <path className="vine-petiole" data-growth-relation-petiole={l.relationId} data-growth-vine-group={vines.find(v => v.leaves.includes(l))?.id} d={l.petiole} pointerEvents="none" />
        <VineLeafPaint leaf={l} prefix={prefix} leafAtlasHref={leafAtlasHref} details={lod.decorations} groupId={vines.find(v => v.leaves.includes(l))?.id} />
        <circle cx={l.center.x} cy={l.center.y} r={lod.hitRadius} fill="transparent" />
        <circle className="relation-leaf-focus" cx={l.center.x} cy={l.center.y} r={lod.hitRadius+2/screenScale} pointerEvents="none" />
        {selectedRelationId===l.relationId && <circle className="selected-dot"
          cx={l.center.x+16/screenScale} cy={l.center.y-17/screenScale} r={3.5/screenScale} pointerEvents="none" />}
      </g>)}</g>
  </g>;
});
