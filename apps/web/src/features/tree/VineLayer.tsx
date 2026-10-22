import { memo, useEffect, useId, useMemo } from 'react';
import type { FocusEvent, PointerEvent, KeyboardEvent } from 'react';
import { buildVine, resolveVineLod, stableHash } from './vineGeometry';
import type { VineInput, RelationLeaf, VineGeometry, Point, VineExclusionZone } from './vineGeometry';

/** Layer is an SVG child. Parent owns camera transform, panel, tooltip and note routing. */
export type VineLayerProps = {
  groups: VineInput[];
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

export function VineLeafPaint({ leaf, prefix, leafAtlasHref, details = true }: {
  leaf: RelationLeaf; prefix: string; leafAtlasHref?: string; details?: boolean;
}) {
  return <g transform={leaf.transform} pointerEvents="none" aria-hidden="true">
    {leafAtlasHref
      ? <svg className="relation-leaf-texture" x={-17} y={-50} width={34} height={51}
          viewBox={`${leaf.variant * 418} 0 418 627`} preserveAspectRatio="xMidYMid meet" overflow="hidden">
          <image href={leafAtlasHref} width={1254} height={1254} />
        </svg>
      : <path className="relation-leaf-shape" d={leaf.outline} fill={`url(#${prefix}-leaf-${leaf.variant})`} />}
    <path className="relation-vein" d={leaf.vein} opacity={leafAtlasHref ? .35 : 1} />
    {details && leaf.sideVeins.map((d,i) => <path key={i} className="relation-side-vein" d={d} opacity={leafAtlasHref ? .3 : 1} />)}
  </g>;
}

export function VineStemPaint({ vine, details = true }: { vine: VineGeometry; details?: boolean }) {
  return <g pointerEvents="none" aria-hidden="true">
    <path className="vine-outline" d={vine.outline} />
    {vine.grain.map((d,i) => <path className="vine-grain" d={d} key={`grain-${i}`} />)}
    {details && vine.tendrils.map((d,i) => <path className="vine-tendril" d={d} key={`tendril-${i}`} />)}
  </g>;
}

export const VineLayer = memo(function VineLayer({
  groups, screenScale, selectedRelationId, selectedGroupId, leafAtlasHref,
  onRelation, onGroup, onPreview, relationLabel, groupLabel, groupMembers, previewId, previewItemId, onSelectedPoint, leafExclusions
}: VineLayerProps) {
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
  useEffect(() => {
    const leaf=vines.flatMap(v=>v.leaves).find(leaf=>leaf.relationId===selectedRelationId);
    if(leaf) onSelectedPoint?.(leaf.relationId,leaf.center);
  },[vines,selectedRelationId,onSelectedPoint]);
  const preview = (kind: 'relation'|'group', id: string) => (e: FocusEvent<SVGGElement> | PointerEvent<SVGGElement>) => {
    onPreview?.({kind,id,target:e.currentTarget});
  };
  const activate = (fn: () => void) => (e: KeyboardEvent<SVGGElement>) => {
    if (e.key==='Enter'||e.key===' ') { e.preventDefault();e.stopPropagation();fn(); }
  };
  return <g className="nb-vines" data-od-id="grouped-vines">
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
        <path className="vine-petiole" d={l.petiole} pointerEvents="none" />
        <VineLeafPaint leaf={l} prefix={prefix} leafAtlasHref={leafAtlasHref} details={lod.decorations} />
        <circle cx={l.center.x} cy={l.center.y} r={lod.hitRadius} fill="transparent" />
        <circle className="relation-leaf-focus" cx={l.center.x} cy={l.center.y} r={lod.hitRadius+2/screenScale} pointerEvents="none" />
        {selectedRelationId===l.relationId && <circle className="selected-dot"
          cx={l.center.x+16/screenScale} cy={l.center.y-17/screenScale} r={3.5/screenScale} pointerEvents="none" />}
      </g>)}</g>
  </g>;
});
