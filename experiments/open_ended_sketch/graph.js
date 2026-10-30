/* Directed-path exploration only; no causal or physical solver. */
(function(root){
  function arcs(r){
    if(r.direction==='forward')return [[r.source,r.target]];
    if(r.direction==='backward')return [[r.target,r.source]];
    if(r.direction==='both')return [[r.source,r.target],[r.target,r.source]];
    return [];
  }
  function eligible(r){
    return r.enabled!==false && r.source!==null && r.target!==null &&
      (!r.ambiguity || r.confirmed===true) &&
      (r.origin!=='uncertain' || r.confirmed===true) &&
      (r.confidence>=.7 || r.confirmed===true);
  }
  function trace(scene,start){
    const nodes=new Map(scene.objects.map(o=>[o.id,o]));
    const reached=new Set(),blocked=new Set(),edges=new Set(),depth={};
    if(!nodes.has(start))return {nodes:[],edges:[],blocked:[],depth};
    reached.add(start);depth[start]=0;
    if(nodes.get(start).enabled===false)return {nodes:[start],edges:[],blocked:[start],depth};
    const queue=[start];
    for(let i=0;i<queue.length;i++){
      const id=queue[i];
      for(const r of scene.relations){
        if(!eligible(r))continue;
        for(const [from,to] of arcs(r)){
          if(from!==id || !nodes.has(to))continue;
          edges.add(r.id);
          if(nodes.get(to).enabled===false){blocked.add(to);continue;}
          if(!reached.has(to)){reached.add(to);depth[to]=depth[id]+1;queue.push(to);}
        }
      }
    }
    return {nodes:[...reached],edges:[...edges],blocked:[...blocked],depth};
  }
  const api={trace,eligible,arcs};root.SketchGraph=api;
  if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
