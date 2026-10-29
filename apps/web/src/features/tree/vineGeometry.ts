/** NoteBuddy vine geometry. Pure, deterministic, DOM/React-free; world coordinates. */
export type Point = { x: number; y: number };
export type VineExclusionZone = { center: Point; radius: number } | { rect: { x: number; y: number; width: number; height: number } };
export type Cubic = [Point, Point, Point, Point];
export type VineInput = {
  id: string; start: Point; end: Point; order: number; relationIds: string[];
  /** Keep relationship leaves inside the open corridor between tree crowns. */
  leafRange?: [number, number];
  stemHitRange?: [number, number];
  /** Optional world-space departure directions from the actual notebook branches. */
  startTangent?: Point; endTangent?: Point;
  /** An optional clearance waypoint for a third tree in a triangular grove. */
  midpoint?: Point;
  /** Root beds and course controls are hard no-cross areas for the whole stem. */
  routeExclusions?: VineExclusionZone[];
};
export type RelationLeaf = {
  relationId: string; t: number; base: Point; center: Point; angle: number;
  transform: string; outline: string; vein: string; sideVeins: string[];
  petiole: string; variant: number; hit: { center: Point; minScreenSize: 44; radius: number };
};
export type VineGeometry = {
  id: string; order: number; curves: Cubic[]; centerline: string; outline: string;
  grain: string[]; tendrils: string[]; leaves: RelationLeaf[];
  hit: { centerline: string; minScreenWidth: 44; fromT: number; toT: number };
};
const p = (x: number, y: number): Point => ({ x, y });
const add = (a: Point, b: Point) => p(a.x + b.x, a.y + b.y);
const sub = (a: Point, b: Point) => p(a.x - b.x, a.y - b.y);
const mul = (a: Point, n: number) => p(a.x * n, a.y * n);
const mix = (a: Point, b: Point, n: number) => add(mul(a, 1 - n), mul(b, n));
const unit = (a: Point) => mul(a, 1 / (Math.hypot(a.x, a.y) || 1));
const norm = (a: Point) => p(-a.y, a.x);
const fmt = (n: number) => Number(n.toFixed(3));
const xy = (a: Point) => `${fmt(a.x)},${fmt(a.y)}`;
const poly = (a: Point[], close = false) => 'M' + a.map(xy).join(' L') + (close ? ' Z' : '');
export function stableHash(s: string): number {
  let h = 2166136261; for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0;
}
function at(c: Cubic, t: number): Point {
  const u = 1 - t;
  return add(add(mul(c[0], u*u*u), mul(c[1], 3*u*u*t)), add(mul(c[2], 3*u*t*t), mul(c[3], t*t*t)));
}
function tangent(c: Cubic, t: number): Point {
  const u = 1-t;
  return unit(add(add(mul(sub(c[1],c[0]),3*u*u),mul(sub(c[2],c[1]),6*u*t)),mul(sub(c[3],c[2]),3*t*t)));
}
export function vinePoint(curves: Cubic[], t: number): Point {
  const q=Math.max(0,Math.min(1,t))*curves.length,i=Math.min(curves.length-1,Math.floor(q)); return at(curves[i],q-i);
}
function direction(curves: Cubic[], t: number): Point {
  const q=Math.max(0,Math.min(1,t))*curves.length,i=Math.min(curves.length-1,Math.floor(q)); return tangent(curves[i],q-i);
}
const path = (cs: Cubic[]) => 'M'+xy(cs[0][0])+cs.map(c=>' C'+xy(c[1])+' '+xy(c[2])+' '+xy(c[3])).join('');
const LEAF = 'M0,0 C-8,-5 -18,-21 -12,-33 C-9,-41 -3,-45 2,-49 C5,-39 18,-32 14,-20 C11,-9 4,-3 0,0 Z';
const VEIN = 'M0,0 C1,-15 0,-30 2,-46';
const SIDE_VEINS = ['M1,-12 Q-5,-14 -11,-23','M1,-20 Q7,-22 12,-29','M1,-28 Q-5,-30 -9,-35','M1,-36 Q5,-37 7,-40'];

function hangingArc(a: Point, b: Point, mid: Point): Cubic[] {
  const control = sub(mul(mid, 2), mul(add(a, b), .5));
  return [[a, mix(a, control, 2 / 3), mix(b, control, 2 / 3), b]];
}

function clearCoursePanels(input: VineInput, curves: Cubic[], mid: Point): Cubic[] {
  const contains = (q: Point, r: { x: number; y: number; width: number; height: number }, padding = 0) =>
    q.x >= r.x - padding && q.x <= r.x + r.width + padding && q.y >= r.y - padding && q.y <= r.y + r.height + padding;
  // A graft is authoritative. A mismeasured panel containing it cannot be
  // avoided without detaching that endpoint, so it is not a routing obstacle.
  const panels = (input.routeExclusions ?? []).flatMap(zone => 'rect' in zone ? [zone.rect] : [])
    .filter(r => r.width > 0 && r.height > 0 && !contains(input.start, r) && !contains(input.end, r));
  if (!panels.length) return curves;
  // Reserve tendrils and the 44px middle hit corridor down to interactive zoom.
  // Only the non-interactive graft tips taper their clearance toward the stem.
  const clearance = (t: number) => 8 + 76 * Math.min(1, t / .18, (1 - t) / .18);
  if (!Array.from({ length: 241 }, (_, i) => i / 240).some(t => panels.some(r => contains(vinePoint(curves, t), r, clearance(t))))) return curves;
  const arc = hangingArc(input.start, input.end, mid);
  let upperY = mid.y;
  for (let i = 1; i < 240; i++) {
    const t = i / 240, q = vinePoint(arc, t), padding = clearance(t);
    for (const r of panels) {
      if (q.x < r.x - padding || q.x > r.x + r.width + padding) continue;
      // A quadratic through its midpoint has y(t) = lerp(a,b,t) +
      // 4t(1-t)(mid.y - mean(a.y,b.y)). Solve the upper clearance bound;
      // x is independent of the chosen midpoint height.
      const ceiling = r.y - padding - 8 - input.order * 18;
      const limit = (input.start.y + input.end.y) / 2
        + (ceiling - ((1 - t) * input.start.y + t * input.end.y)) / (4 * t * (1 - t));
      upperY = Math.min(upperY, limit);
    }
  }
  return hangingArc(input.start, input.end, p(mid.x, upperY));
}

/** The three routes reserve separate height bands, with unequal low points. No random state. */
export function buildVine(input: VineInput): VineGeometry {
  if(!input.id || !Number.isInteger(input.order) || input.order<0 || input.order>3) throw new RangeError('A tree pair allows at most four authored lanes (0–3).');
  if(new Set(input.relationIds).size!==input.relationIds.length) throw new Error('Relation IDs must be unique within a vine.');
  if(![input.start.x,input.start.y,input.end.x,input.end.y,...(input.midpoint ? [input.midpoint.x,input.midpoint.y] : [])].every(Number.isFinite)) throw new Error('Finite endpoints required.');
  const {start:a,end:b,order}=input, dx=b.x-a.x,dy=b.y-a.y,span=Math.hypot(dx,dy);
  if(span<30) throw new RangeError('Vine endpoints need a visible separation.');
  const along=unit(sub(b,a)), n=norm(along);
  const depths=[-73,55,139,211], offsets=[.43,.58,.48,.65];
  const mid=input.midpoint ?? add(mix(a,b,offsets[order]),mul(n,depths[order]));
  const departure=unit(input.startTangent||add(along,mul(n,order===0?-.52:.4)));
  const arrival=unit(input.endTangent||add(along,mul(n,order===0?.48:-.35)));
  const reach=Math.min(105,span*.16), bridge=mul(along,Math.min(125,span*.19));
  // A clearance route is one continuous hanging arc through the reserved point.
  // Two separately steered halves created reverse hooks and a tight central bend.
  const preferred: Cubic[]=input.midpoint
    ? hangingArc(a,b,mid)
    : [[a,add(a,mul(departure,reach)),sub(mid,bridge),mid],[mid,add(mid,bridge),sub(b,mul(arrival,reach)),b]];
  const curves = clearCoursePanels(input, preferred, mid);
  const radius=(t:number)=>1.8+2.9*Math.pow(Math.abs(t-.5)*2,.8)+.3*Math.sin(t*11+order);
  const samples=Array.from({length:121},(_,i)=>{const t=i/120;return {q:vinePoint(curves,t),n:norm(direction(curves,t)),r:radius(t)}});
  const edge=(s:number)=>samples.map(v=>add(v.q,mul(v.n,s*v.r)));
  const grain=[-.4,.33].map((offset,j)=>poly(samples.filter((_,i)=>i>3&&i<116).map((v,i)=>add(v.q,mul(v.n,(offset+.07*Math.sin(i*.11+j))*v.r)))));
  const leaves=input.relationIds.map((relationId,i):RelationLeaf=>{
    // Golden-ratio slots give stable, nonuniform sites when records are appended.
    const [leafFrom,leafTo]=input.leafRange??[.2,.8];
    const t=leafFrom+(((i*.61803398875 + [.08,.31,.16,.43][order])%1))*(leafTo-leafFrom);
    const q=vinePoint(curves,t),d=direction(curves,t),normal=norm(d),side=((i+order)%3===1)?1:-1;
    const base=add(q,add(mul(normal,side*(22+(stableHash(relationId+':reach')%15))),mul(d,7)));
    const angle=Math.atan2(d.y,d.x)*180/Math.PI + (side<0?-34:151) + (stableHash(relationId+':angle')%19-9);
    const r=angle*Math.PI/180,center=add(base,p(24*Math.sin(r),-24*Math.cos(r)));
    return {relationId,t,base,center,angle,transform:`translate(${xy(base)}) rotate(${fmt(angle)})`,outline:LEAF,vein:VEIN,sideVeins:SIDE_VEINS,
      petiole:`M${xy(q)} Q${xy(add(q,mul(normal,side*14)))} ${xy(base)}`,variant:stableHash(relationId)%3,
      hit:{center,minScreenSize:44,radius:27}};
  });
  const tendrils=[.32+(order*.07),.77-(order*.04)].map((t,j)=>{
    const q=vinePoint(curves,t),d=direction(curves,t),nn=norm(d),side=j===0?-1:1;
    const pts=Array.from({length:40},(_,k)=>{const s=k/39,theta=s*Math.PI*2.25,rad=16*(1-s*.75);return add(q,add(mul(d,rad*Math.sin(theta)),mul(nn,side*(s*31+rad*(1-Math.cos(theta))))));});
    return poly(pts);
  });
  // Only the open middle segment is a stem target: never cover the tree crown.
  const [fromT,toT]=input.stemHitRange??[.19,.81];
  const hitLine=poly(Array.from({length:61},(_,i)=>vinePoint(curves,fromT+(toT-fromT)*i/60)));
  return {id:input.id,order,curves,centerline:path(curves),outline:poly([...edge(1),...edge(-1).reverse()],true),grain,tendrils,leaves,
    hit:{centerline:hitLine,minScreenWidth:44,fromT,toT}};
}

/** Single owner per screen area. Collision thinning changes presentation only, never business records. */
export function resolveVineLod(vines: VineGeometry[], scale: number, selectedId?: string, exclusions: VineExclusionZone[] = []): {
  visible: string[]; hidden: string[]; hitRadius: number; decorations: boolean;
} {
  if(!Number.isFinite(scale)||scale<=0) throw new RangeError('Positive screen/world scale required.');
  const candidates=vines.flatMap(v=>v.leaves).sort((a,b)=>Number(b.relationId===selectedId)-Number(a.relationId===selectedId)||a.t-b.t);
  const accepted:RelationLeaf[]=[],hidden:string[]=[],hitRadius=Math.max(27,22/scale);
  for(const leaf of candidates){
    const minSeparation=2*Math.max(22,27*scale)+10;
    const clear=accepted.every(other=>Math.hypot(other.center.x-leaf.center.x,other.center.y-leaf.center.y)*scale>=minSeparation)
      &&exclusions.every(zone=>{
        if('rect' in zone){const r=zone.rect;return Math.hypot(Math.max(r.x-leaf.center.x,0,leaf.center.x-r.x-r.width),Math.max(r.y-leaf.center.y,0,leaf.center.y-r.y-r.height))>=hitRadius+4/scale;}
        return Math.hypot(zone.center.x-leaf.center.x,zone.center.y-leaf.center.y)>=zone.radius+hitRadius+4/scale;
      });
    if(clear) accepted.push(leaf);else hidden.push(leaf.relationId);
  }
  return {visible:accepted.map(l=>l.relationId),hidden,hitRadius,decorations:scale>=.48};
}

export type RelationGroupInput = { id: string; sourceNotebookId: string; targetNotebookId: string };
/** Stable notebook-pair clustering; over-cap notebook groups merge into lane 4 without dropping any ID. */
export function clusterRelations(relations: RelationGroupInput[], maxVines=4): { key: string; relationIds: string[] }[] {
  if(!Number.isInteger(maxVines)||maxVines<1||maxVines>4) throw new RangeError('maxVines must be 1–4.');
  const map=new Map<string,string[]>(),seen=new Set<string>();
  for(const r of relations){if(seen.has(r.id))continue;seen.add(r.id);const key=JSON.stringify([r.sourceNotebookId,r.targetNotebookId]);map.set(key,[...(map.get(key)||[]),r.id]);}
  const groups=[...map.entries()].sort(([a],[b])=>a.localeCompare(b)).map(([key,relationIds])=>({key,relationIds}));
  if(groups.length<=maxVines)return groups;
  return [...groups.slice(0,maxVines-1),{key:'overflow-notebook-pairs',relationIds:groups.slice(maxVines-1).flatMap(g=>g.relationIds)}];
}
