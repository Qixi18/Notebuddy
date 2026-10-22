/**
 * NoteBuddy botanical branch geometry — no DOM, React, D3 or random state.
 * World coordinates: root=(0,0), up=-Y. Sprite is 46×69, petiole=(0,3).
 * Render paths AND hit paths from this returned geometry; never keep the old spine.
 */
export type Point = { x: number; y: number };
export type Cubic = [Point, Point, Point, Point];
export type NoteInput = { id: string; treeSlot: number; title: string; excerpt?: string };
export type BookInput = { id: string; treeSlot: number; title: string; notes: NoteInput[] };
export type TreeInput = { id: string; variant: 0 | 1 | 2; books: BookInput[] };
export type TextureSpan = { center: Point; angle: number; length: number; width: number };
export type Limb = {
  id: string; bookId: string; level: 1 | 2 | 3;
  parentId: string | null; parentT: number; curves: Cubic[];
  rootRadius: number; tipRadius: number; centerPath: string; outline: string;
  grain: string[]; textureSpans: TextureSpan[];
};
export type LeafGeometry = {
  note: NoteInput; bookId: string; twigId: string; petiole: Point;
  anchor: Point; center: Point; angle: number; variant: number;
  transform: string; hit: { cx: 0; cy: -30; rx: 26; ry: 35 };
};
export type BookGeometry = { book: BookInput; primary: Limb; limbs: Limb[]; leaves: LeafGeometry[]; hitPath: string };
export type TreeGeometry = { input: TreeInput; books: BookGeometry[]; bounds: { x: number; y: number; width: number; height: number } };
type XY = [number, number];
type Recipe = {
  /** origin + two cubic segments sharing a tangent at their join */
  axis: XY[]; forks: [number, XY, number][];
  /** fixed, nonuniform petiole sites, not alternating samples along the axis */
  leaves: [number, number, number][];
};

export const SPRITE = { width: 46, height: 69, x: -23, y: -65, petiole: { x: 0, y: 3 } };
export const TRUNK = { width: 198, height: 490, x: -99, y: -474 };
export const TRUNK_CROPS = ['20 70 440 1130', '460 70 440 1130', '892 70 362 1130'];

// Every recipe is deliberately asymmetric. Fork t, direction and reach differ.
// Profiles are authored spatial reservations, not a force layout that moves old notes.
const RECIPES: Recipe[][] = [
  [
    { axis: [[-8,-202],[-76,-237],[-72,-299],[-139,-336],[-192,-365],[-148,-427],[-194,-480]],
      forks: [[.38,[-196,-313],-.18],[.65,[-221,-400],.24],[.88,[-220,-492],-.12]],
      leaves: [[-225,-326,-62],[-157,-366,-15],[-266,-423,-42],[-187,-464,20],[-271,-528,-35],[-165,-557,9]] },
    { axis: [[13,-243],[74,-271],[103,-323],[137,-354],[171,-385],[218,-437],[215,-508]],
      forks: [[.30,[174,-301],.22],[.63,[232,-397],-.22],[.91,[232,-513],.16]],
      leaves: [[205,-308,65],[136,-365,3],[280,-408,51],[210,-460,15],[293,-534,42],[217,-585,20]] },
    { axis: [[-8,-202],[-40,-323],[-43,-386],[-14,-425],[15,-464],[58,-531],[27,-592]],
      forks: [[.43,[-44,-436],-.25],[.69,[-12,-529],.18],[.93,[32,-615],-.15]],
      leaves: [[-30,-465,-38],[30,-447,38],[-25,-572,-40],[75,-539,25],[-15,-653,-10],[84,-641,42]] }
  ],
  [
    { axis: [[-7,-206],[-66,-226],[-92,-282],[-129,-309],[-166,-336],[-168,-385],[-212,-419]],
      forks: [[.32,[-151,-286],-.24],[.63,[-201,-350],.20],[.91,[-233,-422],-.14]],
      leaves: [[-201,-292,-69],[-131,-352,-9],[-264,-369,-53],[-194,-425,6],[-285,-463,-37],[-196,-511,-5]] },
    { axis: [[14,-245],[91,-252],[125,-319],[164,-356],[203,-393],[244,-424],[265,-483]],
      forks: [[.29,[172,-281],.25],[.64,[243,-375],-.15],[.92,[277,-467],.17]],
      leaves: [[219,-289,68],[153,-353,14],[302,-386,61],[238,-451,-3],[329,-489,35],[258,-548,13]] },
    { axis: [[-7,-206],[-16,-347],[33,-380],[59,-426],[85,-472],[84,-543],[131,-589]],
      forks: [[.39,[22,-422],-.24],[.65,[81,-515],.19],[.92,[142,-596],-.12]],
      leaves: [[-30,-446,-46],[65,-452,45],[35,-556,-28],[130,-540,28],[103,-637,-8],[200,-660,30]] }
  ],
  [
    { axis: [[-10,-198],[-91,-219],[-134,-276],[-179,-303],[-224,-330],[-233,-389],[-278,-423]],
      forks: [[.27,[-144,-265],-.22],[.61,[-244,-326],.18],[.91,[-284,-410],-.20]],
      leaves: [[-192,-267,-67],[-127,-332,-10],[-306,-338,-64],[-233,-396,-12],[-344,-439,-40],[-260,-490,8]] },
    { axis: [[14,-247],[100,-262],[135,-301],[178,-323],[221,-345],[250,-390],[295,-414]],
      forks: [[.28,[172,-277],.20],[.63,[260,-335],-.18],[.92,[307,-410],.16]],
      leaves: [[214,-279,70],[162,-351,8],[321,-345,65],[264,-413,15],[364,-444,47],[304,-506,19]] },
    { axis: [[-10,-198],[-43,-319],[-61,-374],[-42,-415],[-23,-456],[-17,-523],[-51,-564]],
      forks: [[.35,[-67,-408],-.23],[.65,[-26,-493],.22],[.92,[-51,-564],-.18]],
      leaves: [[-85,-435,-42],[26,-421,57],[-81,-534,-28],[66,-513,43],[-105,-630,-18],[10,-603,34]] }
  ]
];

// One notebook grows along one central leader; its smaller forks open the crown.
// Two notebooks have their own rising leaders. Neither borrows another book lane.
const SINGLE_RECIPE: Recipe = {
  axis: [[-8,-202],[-28,-260],[-14,-350],[5,-407],[24,-464],[7,-546],[30,-612]],
  forks: [[.31,[-160,-380],-.18],[.59,[150,-490],.17],[.83,[-65,-590],-.16]],
  leaves: [[-230,-385,-60],[-85,-440,-10],[226,-493,57],[94,-555,8],[-135,-638,-25],[58,-663,19]],
};
const DUAL_RECIPES: Recipe[] = [
  { axis: [[-8,-202],[-65,-245],[-65,-317],[-110,-373],[-155,-429],[-164,-510],[-142,-577]],
    forks: [[.30,[-156,-326],-.20],[.59,[-205,-440],.19],[.88,[-184,-561],-.15]],
    leaves: [[-220,-337,-65],[-97,-398,-10],[-266,-459,-48],[-134,-501,7],[-226,-602,-28],[-116,-650,14]] },
  { axis: [[12,-230],[80,-263],[97,-335],[139,-388],[181,-441],[198,-519],[169,-596]],
    forks: [[.30,[174,-330],.21],[.58,[217,-453],-.18],[.88,[196,-581],.15]],
    leaves: [[239,-342,64],[116,-407,10],[281,-468,51],[152,-524,-5],[248,-622,38],[152,-676,6]] },
];

export function hashId(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  return h >>> 0;
}
function noise(id: string, salt: string): number { return hashId(id + ':' + salt) / 4294967295 * 2 - 1; }
const P = (x: number, y: number): Point => ({ x, y });
const add = (a: Point, b: Point): Point => P(a.x+b.x,a.y+b.y);
const sub = (a: Point, b: Point): Point => P(a.x-b.x,a.y-b.y);
const mul = (p: Point, n: number): Point => P(p.x*n,p.y*n);
const mix = (a: Point, b: Point, t: number): Point => add(mul(a,1-t),mul(b,t));
const unit = (p: Point): Point => mul(p,1/(Math.hypot(p.x,p.y)||1));
const normal = (p: Point): Point => P(-p.y,p.x);
const clamp = (n: number, a: number, b: number): number => Math.max(a,Math.min(b,n));
const fmt = (n: number): string => Number(n.toFixed(3)).toString();
const pair = (p: Point): string => `${fmt(p.x)},${fmt(p.y)}`;
export function rotate(p: Point, degrees: number): Point {
  const r=degrees*Math.PI/180;
  return P(p.x*Math.cos(r)-p.y*Math.sin(r),p.x*Math.sin(r)+p.y*Math.cos(r));
}
export function cubicAt(c: Cubic, t: number): Point {
  const q=1-t;
  return add(add(mul(c[0],q*q*q),mul(c[1],3*q*q*t)),add(mul(c[2],3*q*t*t),mul(c[3],t*t*t)));
}
export function cubicTangent(c: Cubic, t: number): Point {
  const q=1-t;
  return unit(add(add(mul(sub(c[1],c[0]),3*q*q),mul(sub(c[2],c[1]),6*q*t)),mul(sub(c[3],c[2]),3*t*t)));
}
export function pointAt(curves: Cubic[], t: number): Point {
  const v=clamp(t,0,1)*curves.length, i=Math.min(curves.length-1,Math.floor(v));
  return cubicAt(curves[i],v-i);
}
export function tangentAt(curves: Cubic[], t: number): Point {
  const v=clamp(t,0,1)*curves.length, i=Math.min(curves.length-1,Math.floor(v));
  return cubicTangent(curves[i],v-i);
}
export function curvePath(curves: Cubic[]): string {
  return 'M'+pair(curves[0][0])+curves.map(c=>'C'+pair(c[1])+' '+pair(c[2])+' '+pair(c[3])).join('');
}
function polyline(points: Point[], close=false): string { return 'M'+points.map(pair).join('L')+(close?'Z':''); }
export function radiusAt(limb: Pick<Limb,'rootRadius'|'tipRadius'>, t: number): number {
  return limb.tipRadius+(limb.rootRadius-limb.tipRadius)*Math.pow(1-t,1.42);
}

/** A sampled normal-offset ribbon: the thickness follows the same curved centerline. */
function paintLimb(id: string, bookId: string, level: 1|2|3, curves: Cubic[], rootRadius: number, tipRadius: number,
  parentId: string|null=null, parentT=0): Limb {
  const samples=Array.from({length:65},(_,i)=>{
    const t=i/64,p=pointAt(curves,t),n=normal(tangentAt(curves,t));
    // Small coherent edge irregularity, zero at joins/tips; never jagged random points.
    const edge=1+.035*Math.sin(t*19+hashId(id)%31)*Math.sin(Math.PI*t);
    const r=radiusAt({rootRadius,tipRadius},t)*edge;
    return {t,p,n,r};
  });
  const edge=(sign:number)=>samples.map(s=>add(s.p,mul(s.n,s.r*sign)));
  const outline=polyline([...edge(1),...edge(-1).reverse()],true);
  const grain=Array.from({length:level===1?7:level===2?4:2},(_,j)=>{
    const start=.04+(hashId(id+':grain:'+j)%13)/100;
    const end=.67+(hashId(id+':end:'+j)%23)/100;
    const offset=(j/Math.max(1,(level===1?6:level===2?3:1))-.5)*1.35;
    return polyline(Array.from({length:31},(_,k)=>{
      const t=start+(end-start)*k/30,p=pointAt(curves,t),n=normal(tangentAt(curves,t));
      const r=radiusAt({rootRadius,tipRadius},t);
      return add(p,mul(n,(offset+.09*Math.sin(t*16+j*2))*r));
    }));
  });
  // Actual texture spans turn with the tangent, clipped by the same ribbon.
  const steps=level===1?22:level===2?10:5;
  const textureSpans=Array.from({length:steps},(_,j)=>{
    const a=pointAt(curves,j/steps),b=pointAt(curves,(j+1)/steps),t=(j+.5)/steps;
    return {center:mix(a,b,.5),angle:Math.atan2(b.y-a.y,b.x-a.x)*180/Math.PI+90,
      length:Math.hypot(b.x-a.x,b.y-a.y)+7,width:radiusAt({rootRadius,tipRadius},t)*2+5};
  });
  return {id,bookId,level,parentId,parentT,curves,rootRadius,tipRadius,centerPath:curvePath(curves),outline,grain,textureSpans};
}

/** Continue the existing leader down into the redrawn stock without moving it. */
export function rootstockJoin(primary: Limb, scaleY = 1): Limb {
  const end = pointAt(primary.curves, 0);
  // Expanded preview banks scale around the leader's start. Invert that scale
  // for the stock attachment so every bank still begins at world (-8, -165).
  const start = P(-8, end.y + (-165 - end.y) / scaleY);
  const tangent = tangentAt(primary.curves, 0);
  const reach = Math.min(22, Math.hypot(end.x-start.x, end.y-start.y) * .4);
  return paintLimb(primary.id+':stock', primary.bookId, 1,
    [[start, P(start.x, start.y-24/scaleY), sub(end,mul(tangent,reach)), end]],
    22, primary.rootRadius);
}

/** The child starts at B_parent(t), with its first control along the parent's tangent. */
function fork(parent: Limb, t: number, end: Point, bend: number, id: string, level: 2|3): Limb {
  const start=pointAt(parent.curves,t),v=tangentAt(parent.curves,t),delta=sub(end,start);
  const length=Math.hypot(delta.x,delta.y),n=normal(unit(delta));
  // Bias a daughter toward its destination. A backwards parent tangent would
  // otherwise produce a hook/loop when the second leaf turns toward the light.
  const departure=unit(add(mul(v,.36),mul(unit(delta),.64)));
  const c1=add(start,mul(departure,Math.min(38,length*.32)));
  const c2=add(mix(start,end,.72),mul(n,length*bend));
  // A branch collar is never wider than its parent at the attachment.
  const rootRadius=Math.min(level===2?6.8:2.7,radiusAt(parent,t)*.77);
  return paintLimb(id,parent.bookId,level,[[start,c1,c2,end]],Math.max(.8,rootRadius),level===2?1.1:.42,parent.id,t);
}

function assertSlot(slot: number, label: string): void {
  if(!Number.isSafeInteger(slot)||slot<0) throw new RangeError(label+' requires a nonnegative persisted integer slot');
}

/**
 * Scope: three notebook lanes, six reserved Note sites per lane for the home overview.
 * A bank >0 requires a separate/expanded tree, deliberately not silent modulo aliasing.
 */
export function notebookGeometry(book: BookInput, variant: 0|1|2, crownSize: 1|2|3 = 3): BookGeometry {
  assertSlot(book.treeSlot,'book');
  if(book.treeSlot>2) throw new RangeError('Home design has lanes 0..2. Pass a persisted homeLayoutSlot; do not compact by array index.');
  if(book.treeSlot>=crownSize) throw new RangeError('A main branch must belong to one of the visible notebooks.');
  const recipe=crownSize===1?SINGLE_RECIPE:crownSize===2?DUAL_RECIPES[book.treeSlot]:RECIPES[variant][book.treeSlot], seed=book.id;
  const spread=[.86,.82,.74][variant];
  const raw=recipe.axis.map(([x,y],i)=>P(x*spread+(i===0?0:noise(seed,'axis-x-'+i)*2),y+(i===0?0:noise(seed,'axis-y-'+i)*2)));
  // Exact C1 tangent continuity across the two primary cubic segments.
  raw[4]=add(raw[3],sub(raw[3],raw[2]));
  const primary=paintLimb(book.id+':primary',book.id,1,[[raw[0],raw[1],raw[2],raw[3]],[raw[3],raw[4],raw[5],raw[6]]],15.2+noise(seed,'girth')*1.1,1.4);
  const limbs: Limb[]=[primary];
  const seconds=recipe.forks.map(([t,[x,y],bend],i)=>{
    const limb=fork(primary,t,P(x*spread+noise(seed,'fork-x-'+i)*2,y+noise(seed,'fork-y-'+i)*2),bend,book.id+':secondary:'+i,2);
    limbs.push(limb);return limb;
  });
  const seen=new Set<string>(),slots=new Set<number>();
  const leaves=book.notes.filter(note=>{
    if(seen.has(note.id)) return false;
    seen.add(note.id);assertSlot(note.treeSlot,'note');
    if(note.treeSlot>5) throw new RangeError('Six overview sites are reserved (0..5); use a persisted projection slot for other Note slots.');
    if(slots.has(note.treeSlot)) throw new Error('Duplicate physical leaf slot in '+book.id);
    slots.add(note.treeSlot);return true;
  }).map(note=>{
    const slot=note.treeSlot,[x,y,baseAngle]=recipe.leaves[slot];
    const petiole=P(x*spread+noise(note.id,'petiole-x')*2,y+noise(note.id,'petiole-y')*2);
    const angle=baseAngle+noise(note.id,'angle')*3;
    const secondary=seconds[Math.floor(slot/2)];
    const twig=fork(secondary,slot%2===0?.94:.38,petiole,slot%2===0?-.08:.10,note.id+':twig',3);
    limbs.push(twig);
    // Correct for the ROTATED local petiole. anchor+(0,3) is wrong for angled leaves.
    const anchor=sub(petiole,rotate(SPRITE.petiole,angle));
    const center=add(anchor,rotate(P(0,-30),angle));
    return {note,bookId:book.id,twigId:twig.id,petiole,anchor,center,angle,variant:hashId(note.id)%6,
      transform:`translate(${fmt(anchor.x)} ${fmt(anchor.y)}) rotate(${fmt(angle)})`,hit:{cx:0 as const,cy:-30 as const,rx:26 as const,ry:35 as const}};
  });
  return {book,primary,limbs,leaves,hitPath:limbs.filter(l=>l.level<3).map(l=>l.centerPath).join(' ')};
}

export function buildTree(input: TreeInput): TreeGeometry {
  const ids=new Set<string>(),slots=new Set<number>(),notes=new Set<string>();
  input.books.forEach(b=>{
    if(ids.has(b.id)||slots.has(b.treeSlot))throw new Error('Duplicate notebook ID or physical lane');
    ids.add(b.id);slots.add(b.treeSlot);
    b.notes.forEach(n=>{if(notes.has(n.id))throw new Error('A Note cannot appear as multiple leaves');notes.add(n.id)});
  });
  const books=input.books.map(book=>notebookGeometry(book,input.variant));
  const points=[P(-112,25),P(112,25),P(0,-484)];
  books.forEach(b=>{
    b.limbs.forEach(l=>{for(let i=0;i<=32;i++)points.push(pointAt(l.curves,i/32))});
    b.leaves.forEach(l=>[[-32,-73],[32,-73],[-32,10],[32,10]].forEach(([x,y])=>points.push(add(l.anchor,rotate(P(x,y),l.angle)))));
  });
  const x=Math.min(...points.map(p=>p.x))-18,y=Math.min(...points.map(p=>p.y))-18;
  const right=Math.max(...points.map(p=>p.x))+18,bottom=Math.max(...points.map(p=>p.y))+15;
  return {input,books,bounds:{x,y,width:right-x,height:bottom-y}};
}

/** Geometry audit, usable without a browser. No stateful collision solver. */
export function auditTree(tree: TreeGeometry) {
  const limbs=tree.books.flatMap(b=>b.limbs),map=new Map(limbs.map(l=>[l.id,l]));
  let maxJoinError=0,maxPetioleError=0,minLeafDistance=Infinity;
  limbs.forEach(l=>{if(l.parentId){const parent=map.get(l.parentId)!;const p=pointAt(parent.curves,l.parentT);const q=l.curves[0][0];maxJoinError=Math.max(maxJoinError,Math.hypot(p.x-q.x,p.y-q.y))}});
  const leaves=tree.books.flatMap(b=>b.leaves);
  leaves.forEach((leaf,i)=>{
    const p=add(leaf.anchor,rotate(SPRITE.petiole,leaf.angle)),twig=map.get(leaf.twigId)!;
    const end=pointAt(twig.curves,1);
    maxPetioleError=Math.max(maxPetioleError,Math.hypot(p.x-end.x,p.y-end.y));
    for(let j=i+1;j<leaves.length;j++)minLeafDistance=Math.min(minLeafDistance,Math.hypot(leaf.center.x-leaves[j].center.x,leaf.center.y-leaves[j].center.y));
  });
  return {leafCount:leaves.length,limbCount:limbs.length,maxJoinError,maxPetioleError,minLeafDistance};
}
